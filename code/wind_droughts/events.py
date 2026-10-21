"""功能：在单一阈值情景内识别连续低CF事件。
输入：日CF、逐日阈值和允许恢复天数；输出：保持跨年event_id的事件表。
流程：找低值日、检查间隙、构建事件；注意：缺测必断开，持续天数不用于等级分类。
"""
import numpy as np
import pandas as pd

EVENT_COLUMNS = ["event_id", "start", "end", "duration_days", "valid_observations",
                 "low_cf_days", "recovery_days", "mean_cf", "min_cf", "threshold_type",
                 "threshold_level", "final_level", "cumulative_cf_deficit", "missing_days",
                 "incomplete_source_days", "missing_source_hours", "missing_before", "missing_after",
                 "left_boundary", "right_boundary"]


def identify_events(cf, threshold, level, threshold_type="percentile", merge_recovery_days=0,
                    valid_hours=None, installed_capacity_kw=None):
    """逐日识别所有≥1低CF日事件；结尾为末个低值日，恢复天计入跨度但不计低CF日数。"""
    if not isinstance(merge_recovery_days, int) or merge_recovery_days < 0:
        raise ValueError("恢复合并参数须为非负整数")
    if cf.dims != ("time",) or threshold.dims != ("time",):
        raise ValueError("事件输入须为一维time序列")
    if not cf.time.equals(threshold.time):
        raise ValueError("CF与阈值时间坐标必须完全一致")
    index = pd.DatetimeIndex(cf.time.values)
    if index.empty or index.has_duplicates or not index.is_monotonic_increasing or not (index == index.normalize()).all():
        raise ValueError("输入须非空、按日零点排序且无重复")
    full = pd.date_range(index[0], index[-1], freq="D")
    series = pd.Series(cf.values, index=index).reindex(full)
    limits = pd.Series(threshold.values, index=index).reindex(full)
    values, bounds = series.to_numpy(), limits.to_numpy()
    valid = np.isfinite(values) & np.isfinite(bounds)
    low = valid & (values < bounds)
    positions = np.flatnonzero(low)
    groups = []
    for pos in positions:
        if groups:
            previous = groups[-1][-1]
            # 缺测日无论多短都禁止合并；只允许有限值的短暂恢复。
            if pos - previous - 1 <= merge_recovery_days and valid[previous:pos + 1].all():
                groups[-1].append(pos)
                continue
        groups.append([pos])
    hours = None
    if valid_hours is not None:
        if not valid_hours.time.equals(cf.time):
            raise ValueError("有效小时数须与CF对齐")
        hours = pd.Series(valid_hours.values, index=index).reindex(full).to_numpy()
    if installed_capacity_kw is not None and (not np.isfinite(installed_capacity_kw) or installed_capacity_kw <= 0):
        raise ValueError("装机容量须为有限正数")
    if installed_capacity_kw is not None and hours is None:
        raise ValueError("电量估计仅支持带有效小时数的日CF，不支持七日滚动CF")
    rows = []
    for number, group in enumerate(groups, 1):
        start, end = group[0], group[-1]
        span = slice(start, end + 1)
        segment = values[span]
        # 累计缺口为sum(max(阈值-CF,0))，单位CF·日；恢复日贡献0。
        deficit = np.maximum(bounds[span] - segment, 0.)
        row = dict(event_id=f"{level}_{number:06d}", start=full[start], end=full[end],
                   duration_days=end-start+1, valid_observations=len(segment), low_cf_days=len(group),
                   recovery_days=len(segment)-len(group), mean_cf=float(segment.mean()),
                   min_cf=float(segment.min()), threshold_type=threshold_type,
                   threshold_level=level, final_level=level, cumulative_cf_deficit=float(deficit.sum()),
                   missing_days=0, incomplete_source_days=int((hours[span] < 24).sum()) if hours is not None else np.nan,
                   missing_source_hours=int((24-hours[span]).sum()) if hours is not None else np.nan,
                   missing_before=bool(start > 0 and not valid[start-1]),
                   missing_after=bool(end < len(full)-1 and not valid[end+1]),
                   left_boundary=start == 0, right_boundary=end == len(full)-1)
        if installed_capacity_kw is not None:
            # 使用日平均及该日有效小时作等效估计；非实际损失电量，不外推缺测小时。
            row["threshold_deficit_energy_kwh_estimate"] = float((deficit * hours[span]).sum() * installed_capacity_kw)
            row["full_output_gap_energy_kwh"] = float(((1-segment) * hours[span]).sum() * installed_capacity_kw)
        rows.append(row)
    columns = EVENT_COLUMNS + (["threshold_deficit_energy_kwh_estimate", "full_output_gap_energy_kwh"]
                               if installed_capacity_kw is not None else [])
    return pd.DataFrame(rows, columns=columns)
