"""功能：组织逐站逐小时LPW识别、频次统计、结果流式保存和地图生成。
输入：有成因码的站点小时CF文件与config参数；输出：压缩CSV事件表、频次CSV/NetCDF及地图。
流程：校验CF来源、按站点块读取完整时间轴、逐阈值识别统计、调用绘图模块。
注意：三个阈值独立，缺测与剔除的切出必断开；事件表逐站追加，避免百万事件同时占内存。
"""
from contextlib import ExitStack
from pathlib import Path
import gzip
import json
import numpy as np
import pandas as pd
import xarray as xr
from .data_io import configure_netcdf_cache, validate_hourly_cf, save_json, save_tables, save_lpw_frequency
from .events import classify_lpw_duration, identify_hourly_lpw
from .statistics import summarize_hourly_lpw
from .plotting import plot_lpw_frequency_maps


def run_hourly_lpw(source_path, output_dir, settings, *, plot_maps=True):
    """从明确指定的小时CF源识别全部站点LPW，保留跨年事件并流式写出事件CSV.gz。"""
    source_path, output_dir = Path(source_path).resolve(), Path(output_dir).resolve()
    table_dir, nc_dir = output_dir / "tables", output_dir / "netcdf"
    table_dir.mkdir(parents=True, exist_ok=True)
    nc_dir.mkdir(parents=True, exist_ok=True)
    thresholds = settings.LPW_CF_THRESHOLDS
    labels, bounds = settings.LPW_CLASS_LABELS, settings.LPW_CLASS_LOWER_HOURS
    classify_lpw_duration([], bounds, labels)
    if not thresholds or any(not np.isfinite(v) or not 0 < v <= 1 for v in thresholds.values()):
        raise ValueError("LPW各固定阈值须在(0,1]")
    if any(not isinstance(k, str) or not k or not k.replace('_','').isalnum() for k in thresholds):
        raise ValueError("阈值情景名仅允许字母、数字和下划线")
    if not isinstance(settings.LPW_STATION_BLOCK_SIZE, int) or settings.LPW_STATION_BLOCK_SIZE < 1:
        raise ValueError("LPW站点分块大小须为正整数")
    if settings.LPW_MIN_HOURS != bounds[0]:
        raise ValueError("LPW最小时数须等于第一档下界")
    if settings.PROFILE_METHOD != "power_law":
        raise NotImplementedError("当前LPW缓存复用只支持已实现的幂律CF来源")
    configure_netcdf_cache(settings.NETCDF_CHUNK_CACHE_MB)
    expected_model = dict(source_height_m=settings.SOURCE_HEIGHT_M, hub_height_m=settings.HUB_HEIGHT_M,
        shear_alpha=settings.SHEAR_ALPHA, cut_in_ms=settings.CUT_IN_MS, rated_speed_ms=settings.RATED_SPEED_MS,
        cut_out_ms=settings.CUT_OUT_MS, rated_power_kw=settings.RATED_POWER_KW,
        curve="cubic" if settings.DISCRETE_POWER_CURVE is None else "discrete")
    if settings.DISCRETE_POWER_CURVE is not None:
        source_config_path = source_path.parent.parent / "configuration.json"
        if not source_config_path.is_file():
            raise ValueError("离散曲线缓存必须附带原configuration.json以核对曲线点")
        previous = json.loads(source_config_path.read_text(encoding="utf-8"))
        if previous.get("DISCRETE_POWER_CURVE") != json.loads(json.dumps(settings.DISCRETE_POWER_CURVE)):
            raise ValueError("缓存CF的离散机型曲线与当前配置不同，请重算")
    configuration = {k: v for k,v in vars(settings).items() if k.isupper()}
    save_json(output_dir / "configuration.json", configuration)
    frequency_frames, annual_frames = [], []
    event_counts = {level: 0 for level in thresholds}
    with xr.open_dataset(source_path, engine="netcdf4") as raw:
        validate_hourly_cf(raw, expected_model)
        ds = raw.sel(time=slice(settings.STUDY_START, settings.STUDY_END))
        times = validate_hourly_cf(ds)
        metadata = dict(analysis_mode="hourly_lpw", event_input="station_hourly_cf",
            source_cf_file=str(source_path), time_start=str(times[0]), time_end=str(times[-1]),
            comparison="cf < threshold; equal values are not low",
            event_definition=f"strictly continuous low CF for >= {settings.LPW_MIN_HOURS} observed hours",
            duration_definition="number of hourly bins; end is last low timestamp; end_exclusive=end+1h",
            class_lower_hours=json.dumps(list(bounds)), class_labels=json.dumps(list(labels)),
            exclude_cut_out=int(settings.EXCLUDE_CUT_OUT), frequency_default=settings.LPW_MAP_METRIC,
            cross_year_rule="one event ID; event count assigned to start year; LPW hours by actual year",
            boundary_rule="include observed boundary events; true duration may be longer; boundary flags retained",
            deficit_units="CF hour; not energy")
        source_info = dict(path=str(source_path), bytes=source_path.stat().st_size,
            modified_ns=source_path.stat().st_mtime_ns, dimensions=dict(ds.sizes), attrs=dict(raw.attrs),
            cf_attrs=dict(raw.cf.attrs), expected_model=expected_model)
        save_json(output_dir / "cf_source.json", source_info)
        with ExitStack() as stack:
            streams = {level: stack.enter_context(gzip.open(table_dir / f"events_{level}.csv.gz", "wt",
                        encoding="utf-8-sig", newline="", compresslevel=1)) for level in thresholds}
            written = {level: False for level in thresholds}
            size = settings.LPW_STATION_BLOCK_SIZE
            for offset in range(0, ds.sizes['station'], size):
                block = ds[['cf','cause']].isel(station=slice(offset, offset+size)).load()
                for j in range(block.sizes['station']):
                    station = block.isel(station=j)
                    station_id = str(station.station_id.item()) if 'station_id' in station.coords else str(station.station.item())
                    info = dict(station=station.station.item(), station_id=station_id,
                                latitude=float(station.lat), longitude=float(station.lon))
                    for level, threshold in thresholds.items():
                        events = identify_hourly_lpw(station.cf, threshold, level, cause=station.cause,
                            exclude_cut_out=settings.EXCLUDE_CUT_OUT, min_hours=settings.LPW_MIN_HOURS,
                            lower_bounds=bounds, labels=labels, station_id=station_id)
                        frequency, annual = summarize_hourly_lpw(station.cf, threshold, events, level, info,
                            cause=station.cause, exclude_cut_out=settings.EXCLUDE_CUT_OUT, labels=labels)
                        events = events.assign(**info)
                        events.to_csv(streams[level], index=False, header=not written[level],
                            date_format="%Y-%m-%d %H:%M:%S", float_format="%.10g")
                        written[level] = True
                        event_counts[level] += len(events)
                        frequency_frames.append(frequency)
                        annual_frames.append(annual)
                print(f"LPW站点进度：{min(offset+size,ds.sizes['station'])}/{ds.sizes['station']}；累计事件 {event_counts}", flush=True)
        frequency = pd.concat(frequency_frames, ignore_index=True)
        annual = pd.concat(annual_frames, ignore_index=True)
        # 每个阈值内四个等级互斥，其次数之和必须等于ALL；不跨阈值相加。
        check = frequency.pivot(index=['threshold_level','station'], columns='lpw_class', values='event_count')
        np.testing.assert_allclose(check[list(labels)].sum(axis=1, min_count=1), check['ALL'], equal_nan=True)
        summary = frequency.groupby(['threshold_level','cf_threshold','lpw_class'], sort=False).agg(
            station_event_count=('event_count', lambda x: x.sum(min_count=1)),
            mean_station_event_count=('event_count','mean'), median_station_event_count=('event_count','median'),
            min_station_event_count=('event_count','min'), max_station_event_count=('event_count','max'),
            valid_stations=('event_count','count'), lpw_station_hours=('lpw_hours','sum')).reset_index()
        save_tables(table_dir, {'station_frequency': frequency, 'station_annual_statistics': annual,
                                'lpw_summary': summary})
        compact = save_lpw_frequency(frequency, nc_dir / 'lpw_station_frequency.nc', metadata)
        compact.close()
        limits = xr.Dataset({'cf_threshold': ('threshold_level', list(thresholds.values()))},
                            coords={'threshold_level': list(thresholds)}, attrs=metadata)
        limits.cf_threshold.attrs['units'] = '1'
        limits.to_netcdf(nc_dir / 'thresholds.nc', engine='netcdf4')
    manifest = dict(**metadata, station_count=int(ds.sizes['station']), threshold_event_counts=event_counts,
                    event_tables='tables/events_<threshold_level>.csv.gz; grouped by station, chronological within station',
                    summary_count_meaning='station-events across all stations; not unique regional synchronous events',
                    source=source_info, plots=[], plot_scales={}, status='statistics_complete')
    save_json(output_dir / 'manifest.json', manifest)
    if plot_maps:
        source_root = Path(settings.__file__).resolve().parent
        files, scales = plot_lpw_frequency_maps(frequency, output_dir / 'figures',
            boundary_path=(source_root / settings.LPW_MAP_PATH).resolve(), labels=labels, lower_bounds=bounds,
            metric=settings.LPW_MAP_METRIC, fixed_levels=settings.LPW_MAP_LEVELS, cmap=settings.LPW_MAP_CMAP,
            colors=settings.LPW_MAP_COLORS, zero_color=settings.LPW_MAP_ZERO_COLOR,
            extent=settings.LPW_MAP_EXTENT, figsize=settings.LPW_MAP_FIGSIZE, dpi=settings.LPW_MAP_DPI,
            add_south_china_sea=settings.LPW_MAP_ADD_SOUTH_CHINA_SEA,
            period=f"{times[0]:%Y-%m-%d} to {times[-1]:%Y-%m-%d}")
        manifest.update(plots=files, plot_scales=scales)
    manifest['status'] = 'complete'
    save_json(output_dir / 'manifest.json', manifest)
    print(f"逐小时站点LPW完成：{output_dir}", flush=True)
    return manifest


def replot_hourly_lpw(output_dir, settings):
    """从已完成的频次CSV重绘地图，只更新绘图配置和manifest，不重算或覆盖事件统计。"""
    output_dir = Path(output_dir).resolve()
    manifest_path = output_dir / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('analysis_mode') != 'hourly_lpw':
        raise ValueError("重绘仅接受小时LPW结果目录")
    frequency = pd.read_csv(output_dir / 'tables' / 'station_frequency.csv')
    labels = json.loads(manifest['class_labels'])
    bounds = json.loads(manifest['class_lower_hours'])
    root = Path(settings.__file__).resolve().parent
    files, scales = plot_lpw_frequency_maps(frequency, output_dir / 'figures',
        boundary_path=(root / settings.LPW_MAP_PATH).resolve(), labels=labels, lower_bounds=bounds,
        metric=settings.LPW_MAP_METRIC, fixed_levels=settings.LPW_MAP_LEVELS, cmap=settings.LPW_MAP_CMAP,
        colors=settings.LPW_MAP_COLORS, zero_color=settings.LPW_MAP_ZERO_COLOR,
        extent=settings.LPW_MAP_EXTENT, figsize=settings.LPW_MAP_FIGSIZE, dpi=settings.LPW_MAP_DPI,
        add_south_china_sea=settings.LPW_MAP_ADD_SOUTH_CHINA_SEA,
        period=f"{pd.Timestamp(manifest['time_start']):%Y-%m-%d} to {pd.Timestamp(manifest['time_end']):%Y-%m-%d}")
    plot_settings = {k:v for k,v in vars(settings).items() if k.startswith('LPW_MAP_')}
    manifest.update(plots=files, plot_scales=scales, plot_configuration=plot_settings, status='complete')
    save_json(output_dir / 'plot_configuration.json', plot_settings)
    save_json(manifest_path, manifest)
    print(f"LPW地图已重绘，事件和频次统计保持原值：{output_dir}", flush=True)
    return manifest
