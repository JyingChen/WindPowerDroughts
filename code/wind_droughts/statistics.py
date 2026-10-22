"""功能：统计逐小时站点LPW频次及原日尺度事件规律。
输入：CF、阈值、事件表与时长等级；输出：站点分级频次、年度统计或原日尺度汇总。
流程：互斥分类计数、按实际日期分配低值小时；注意：跨年事件次数按开始年计一次。
"""
import numpy as np
import pandas as pd
from .events import hourly_lpw_masks


def summarize_events(cf, threshold, events, level, min_low_days=1):
    """返回筛选事件、情景摘要和分期统计；N按低CF日数筛选，不改变情景或event_id。"""
    if not isinstance(min_low_days, int) or min_low_days < 1:
        raise ValueError("N必须为正整数")
    selected = events.loc[events.low_cf_days >= min_low_days].copy()
    times = pd.DatetimeIndex(cf.time.values)
    valid = np.isfinite(cf.values) & np.isfinite(threshold.values)
    low = valid & (cf.values < threshold.values)
    retained = np.zeros(len(times), dtype=bool)
    for row in selected.itertuples():
        retained |= (times >= row.start) & (times <= row.end)
    kept_low = low & retained
    summary = pd.DataFrame([dict(threshold_level=level, min_low_days=min_low_days,
        valid_days=int(valid.sum()), missing_or_no_threshold_days=int((~valid).sum()),
        low_cf_days=int(low.sum()), low_cf_fraction=float(low.sum()/valid.sum()) if valid.any() else np.nan,
        selected_event_low_cf_days=int(kept_low.sum()), all_event_count=len(events), event_count=len(selected),
        mean_duration_days=selected.duration_days.mean(), max_duration_days=selected.duration_days.max(),
        mean_event_cf=selected.mean_cf.mean(), min_event_cf=selected.min_cf.min(),
        cumulative_cf_deficit=selected.cumulative_cf_deficit.sum())])
    seasons = np.array(["DJF", "DJF", "MAM", "MAM", "MAM", "JJA", "JJA", "JJA", "SON", "SON", "SON", "DJF"])
    rows = []
    for grouping, keys in (("year", times.year.astype(str)),
                           ("month", times.strftime("%Y-%m")),
                           ("season", seasons[times.month-1])):
        starts = pd.DatetimeIndex(selected.start)
        start_keys = (starts.year.astype(str) if grouping == "year" else starts.strftime("%Y-%m")
                      if grouping == "month" else seasons[starts.month-1])
        for key in sorted(set(keys)):
            mask = keys == key
            n = int(valid[mask].sum())
            event_group = selected.loc[start_keys == key]
            rows.append(dict(threshold_level=level, grouping=grouping, period=key, valid_days=n,
                low_cf_days=int(low[mask].sum()), low_cf_fraction=float(low[mask].sum()/n) if n else np.nan,
                selected_event_low_cf_days=int(kept_low[mask].sum()), event_starts=len(event_group),
                mean_duration_days=event_group.duration_days.mean(), max_duration_days=event_group.duration_days.max(),
                mean_event_cf=event_group.mean_cf.mean(), min_event_cf=event_group.min_cf.min(),
                cumulative_cf_deficit=float(np.maximum(threshold.values[mask]-cf.values[mask], 0)[kept_low[mask]].sum())))
    return selected, summary, pd.DataFrame(rows)


def summarize_hourly_lpw(cf, threshold, events, level, station_info, *, cause=None,
                         exclude_cut_out=True, labels=("LPW1", "LPW2", "LPW3", "LPW4")):
    """统计单站各等级累计次数及有效年频次；年度事件归开始年，LPW小时按实际年份分配。"""
    index, valid, low = hourly_lpw_masks(cf, threshold, cause, exclude_cut_out)
    years = np.arange(index[0].year, index[-1].year+1)
    year_codes = index.year.to_numpy() - years[0]
    valid_count = int(valid.sum())
    expected_hours = int((index[-1]-index[0])/pd.Timedelta(hours=1))+1
    valid_years = valid_count / (365.2425 * 24)
    # 仅用已达LPW最小时长的事件标记小时；不足4小时低CF仍单独计入low_cf_hours。
    delta = np.zeros(len(index)+1, dtype=np.int32)
    if not events.empty:
        start_positions = index.get_indexer(events.start)
        end_positions = index.get_indexer(events.end)
        if (start_positions < 0).any() or (end_positions < 0).any():
            raise ValueError("事件时间不在CF时间轴内")
        np.add.at(delta, start_positions, 1)
        np.add.at(delta, end_positions+1, -1)
    retained = np.cumsum(delta[:-1]) > 0
    shared = dict(**station_info, threshold_level=level, cf_threshold=threshold,
        expected_hours=expected_hours, valid_hours=valid_count,
        missing_timestamp_hours=expected_hours-len(index),
        source_missing_hours=int((~np.isfinite(cf.values) | (cause.values == -1)).sum()) if cause is not None else int((~np.isfinite(cf.values)).sum()),
        excluded_cut_out_hours=int((cause.values == 2).sum()) if cause is not None and exclude_cut_out else 0,
        valid_fraction=valid_count/expected_hours, low_cf_hours=int(low.sum()),
        low_cf_fraction=float(low.sum()/valid_count) if valid_count else np.nan,
        calendar_years=len(years), valid_equivalent_years=valid_years)
    frequency = []
    for grade in ("ALL", *labels):
        group = events if grade == "ALL" else events.loc[events.lpw_class == grade]
        count = len(group)
        frequency.append(dict(**shared, lpw_class=grade,
            event_count=count if valid_count else np.nan,
            mean_events_per_calendar_year=count/len(years) if valid_count else np.nan,
            events_per_valid_year=count/valid_years if valid_years else np.nan,
            lpw_hours=int(group.duration_hours.sum()),
            mean_duration_hours=group.duration_hours.mean(), max_duration_hours=group.duration_hours.max(),
            mean_event_cf=group.mean_cf.mean(), min_event_cf=group.min_cf.min(),
            cumulative_cf_deficit=group.cumulative_cf_deficit.sum(),
            boundary_event_count=int((group.left_boundary | group.right_boundary).sum())))
    start_codes = pd.DatetimeIndex(events.start).year.to_numpy()-years[0]
    annual_valid = np.bincount(year_codes, weights=valid, minlength=len(years)).astype(int)
    annual_low = np.bincount(year_codes, weights=low, minlength=len(years)).astype(int)
    annual_lpw = np.bincount(year_codes, weights=retained, minlength=len(years)).astype(int)
    counts = {grade: np.bincount(start_codes if grade == "ALL" else start_codes[events.lpw_class.values == grade],
                                minlength=len(years)) for grade in ("ALL", *labels)}
    annual = []
    for i, year in enumerate(years):
        left = max(index[0], pd.Timestamp(year=int(year), month=1, day=1))
        right = min(index[-1], pd.Timestamp(year=int(year), month=12, day=31, hour=23))
        expected_year = int((right-left)/pd.Timedelta(hours=1))+1
        annual.append(dict(**station_info, threshold_level=level, cf_threshold=threshold, year=int(year),
            expected_hours=expected_year, valid_hours=annual_valid[i],
            low_cf_hours=annual_low[i], lpw_hours=annual_lpw[i],
            valid_fraction=annual_valid[i]/expected_year,
            **{f"{grade}_event_starts": int(counts[grade][i]) if annual_valid[i] else np.nan
               for grade in ("ALL", *labels)}))
    return pd.DataFrame(frequency), pd.DataFrame(annual)
