"""功能：保留阶段0逐小时风速质量检查。
输入：风速Dataset、变量选择和研究期；输出：站点、缺测段和年度完整率CSV。
流程：检查时间轴、对齐研究期、统计各位置缺测与异常；注意：值数组会全量载入内存，不插值。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr


@dataclass
class QualityConfig:
    """配置质量检查的有效率、日有效小时数、异常值与分块参数。"""
    min_station_valid_rate: float = 0.90
    min_daily_valid_hours: int = 18
    min_annual_valid_rate: float = 0.90
    anomalous_high_wind_speed: float = 50.0
    station_chunk_size: int = 128


def _positions(ds, station_dim):
    if station_dim in ds.dims:
        n = ds.sizes[station_dim]
        ids = ds.coords.get("station_id", ds.coords[station_dim]).values
        lat = ds.coords.get("latitude", xr.DataArray(np.full(n, np.nan), dims=station_dim)).values
        lon = ds.coords.get("longitude", xr.DataArray(np.full(n, np.nan), dims=station_dim)).values
        return [(str(ids[i]), i, float(lat[i]), float(lon[i])) for i in range(n)]
    if "lat" in ds.dims and "lon" in ds.dims:
        out = []
        for i, lat in enumerate(ds.lat.values):
            for j, lon in enumerate(ds.lon.values):
                out.append((f"{lat:g}_{lon:g}", (i, j), float(lat), float(lon)))
        return out
    raise ValueError("未识别站点/网格维度；需要 station，或 lat 和 lon。")


def _get_values(ds, selector, time_dim, station_dim, index):
    da = ds[selector["variable"]]
    for dim, value in selector.get("selection", {}).items():
        da = da.sel({dim: value})
    da = da.transpose(time_dim, ...)
    if station_dim in da.dims:
        return np.asarray(da.isel({station_dim: index}).values, dtype=float)
    lat_i, lon_i = index
    return np.asarray(da.isel(lat=lat_i, lon=lon_i).values, dtype=float)


def _runs(mask, expected, raw_missing):
    padded = np.r_[False, mask, False]
    starts = np.flatnonzero(~padded[:-1] & padded[1:])
    ends = np.flatnonzero(padded[:-1] & ~padded[1:]) - 1
    rows = []
    for s, e in zip(starts, ends):
        segment = raw_missing[s:e + 1]
        rows.append({"start": expected[s], "end": expected[e], "hours": int(e - s + 1),
                     "missing_timestamp_hours": int(np.count_nonzero(segment == "timestamp_missing")),
                     "nan_hours": int(np.count_nonzero(segment == "nan")),
                     "source": ";".join(sorted(set(segment.tolist())))})
    return rows


def run_quality_check(ds: xr.Dataset, output_dir, *, variable="wind", selection=None,
                      time_dim="time", station_dim="station", study_start=None,
                      study_end=None, config=None):
    """输出原有质量报告；重复或异常时间轴以time_issues记录，不自动修复。"""
    cfg = config or QualityConfig()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    selection = selection or {}
    raw_time = pd.DatetimeIndex(pd.to_datetime(ds[time_dim].values))
    time_issues = []
    if raw_time.has_duplicates:
        time_issues.append(f"时间戳重复 {int(raw_time.duplicated().sum())} 个")
    if not raw_time.is_monotonic_increasing:
        time_issues.append("时间戳不是严格递增")
    if len(raw_time) > 1:
        diffs = raw_time[1:] - raw_time[:-1]
        if not np.all(diffs == pd.Timedelta(hours=1)):
            time_issues.append("原始时间戳不是严格逐小时")
    start = pd.Timestamp(study_start) if study_start is not None else raw_time.min()
    end = pd.Timestamp(study_end) if study_end is not None else raw_time.max()
    expected = pd.date_range(start, end, freq="h")
    missing_ts = expected.difference(raw_time)
    if len(missing_ts):
        time_issues.append(f"预期时间轴缺失 {len(missing_ts)} 小时")
    if time_issues:
        print("严重时间轴问题：" + "；".join(time_issues))
    selector = {"variable": variable, "selection": selection}
    positions = _positions(ds, station_dim)
    da = ds[variable]
    for dim, value in selection.items():
        da = da.sel({dim: value})
    # 单值辅助维（如仅含ws的var）可明确压缩，保留time和空间维。
    extra = [d for d in da.dims if d not in {time_dim, station_dim, "lat", "lon"}]
    if any(da.sizes[d] != 1 for d in extra):
        raise ValueError("存在未选择的多值辅助维，请显式指定selection")
    if extra:
        da = da.squeeze(extra)
    if station_dim in da.dims:
        values_all = np.asarray(da.transpose(time_dim, station_dim).values, dtype=float)
    else:
        values_all = np.asarray(da.transpose(time_dim, "lat", "lon").values, dtype=float)
    summary, missing_rows, annual_rows = [], [], []
    expected_raw_indices = None
    if raw_time.is_unique and raw_time.is_monotonic_increasing:
        raw_index = pd.Series(np.arange(len(raw_time)), index=raw_time)
        expected_raw_indices = raw_index.reindex(expected)
    for pos_id, index, lat, lon in positions:
        vals = values_all[:, index] if station_dim in ds.dims else values_all[:, index[0], index[1]]
        # Duplicate timestamps make a station-level hourly mapping ambiguous.
        if raw_time.has_duplicates or not raw_time.is_monotonic_increasing:
            aligned = np.full(len(expected), np.nan)
            raw_missing = np.full(len(expected), "timestamp_missing", dtype=object)
        else:
            aligned = np.full(len(expected), np.nan)
            present = expected_raw_indices.notna().to_numpy()
            aligned[present] = vals[expected_raw_indices[present].astype(int)]
            raw_missing = np.where(present, np.where(np.isnan(aligned), "nan", "valid"), "timestamp_missing")
        valid = np.isfinite(aligned)
        missing = ~valid
        runs = _runs(missing, expected, raw_missing)
        for r in runs:
            missing_rows.append({"position": pos_id, "latitude": lat, "longitude": lon, **r})
        years = pd.DatetimeIndex(expected).year
        for year in np.unique(years):
            m = years == year
            annual_rows.append({"position": pos_id, "latitude": lat, "longitude": lon,
                                "year": int(year), "expected_hours": int(m.sum()),
                                "valid_hours": int(valid[m].sum()),
                                "valid_rate": float(valid[m].mean()),
                                "meets_min_annual_rate": bool(valid[m].mean() >= cfg.min_annual_valid_rate)})
        daily = pd.Series(valid, index=expected).resample("D").sum()
        invalid_days = int((daily < cfg.min_daily_valid_hours).sum())
        longest_valid = max((len(x) for x in np.split(np.flatnonzero(valid), np.where(np.diff(np.flatnonzero(valid)) != 1)[0] + 1)), default=0)
        summary.append({"position": pos_id, "latitude": lat, "longitude": lon,
                        "expected_hours": len(expected), "valid_hours": int(valid.sum()),
                        "missing_hours": int(missing.sum()), "missing_rate": float(missing.mean()),
                        "raw_missing_timestamp_hours": int(np.count_nonzero(raw_missing == "timestamp_missing")),
                        "nan_hours": int(np.count_nonzero(raw_missing == "nan")),
                        "longest_valid_hours": int(longest_valid),
                        "missing_runs": len(runs), "longest_missing_hours": max((r["hours"] for r in runs), default=0),
                        "missing_1h": sum(r["hours"] == 1 for r in runs),
                        "missing_2_6h": sum(2 <= r["hours"] <= 6 for r in runs),
                        "missing_7_24h": sum(7 <= r["hours"] <= 24 for r in runs),
                        "missing_over_24h": sum(r["hours"] > 24 for r in runs),
                        "invalid_days": invalid_days,
                        "negative_wind_hours": int(np.isfinite(aligned).sum() and (aligned < 0).sum()),
                        "nonfinite_wind_hours": int((~np.isfinite(aligned)).sum()),
                        "anomalous_high_wind_hours": int((np.isfinite(aligned) & (aligned > cfg.anomalous_high_wind_speed)).sum()),
                        "meets_min_station_rate": bool(valid.mean() >= cfg.min_station_valid_rate)})
    pd.DataFrame(summary).to_csv(output_dir / "data_quality_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(missing_rows).to_csv(output_dir / "missing_runs.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(annual_rows).to_csv(output_dir / "annual_completeness.csv", index=False, encoding="utf-8-sig")
    report = {"time_issues": time_issues, "expected_start": str(start), "expected_end": str(end),
              "expected_hours": len(expected), "positions": len(positions),
              "summary": pd.DataFrame(summary), "missing_runs": pd.DataFrame(missing_rows),
              "annual": pd.DataFrame(annual_rows)}
    return report
