"""功能：按情景汇总事件并统计年度、月份、季节发生规律。
输入：识别CF、阈值、完整事件表和统一N日筛选；输出：概览与分期CSV用表。
流程：先筛事件，再按实际日期分配低CF日；注意：跨年事件次数按开始年计一次。
"""
import numpy as np
import pandas as pd


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
