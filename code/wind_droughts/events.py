"""功能：识别逐小时站点LPW，并保留原日尺度连续事件识别。
输入：单站小时CF、固定阈值及分级边界，或旧日CF与逐日阈值；输出：事件表。
流程：划分严格连续低值段、筛选时长、计算强度及等级；注意：小时LPW不合并恢复，缺测必断开。
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


def classify_lpw_duration(hours, lower_bounds=(4, 8, 12, 24), labels=("LPW1", "LPW2", "LPW3", "LPW4")):
    """按左闭右开区间赋予互斥等级；末档无上限，小于最低时长返回空字符串。"""
    bounds = np.asarray(lower_bounds, dtype=float)
    if (bounds.ndim != 1 or not len(bounds) or len(bounds) != len(labels)
            or not np.isfinite(bounds).all() or (bounds < 1).any()
            or (np.diff(bounds) <= 0).any() or len(set(labels)) != len(labels)
            or any(not isinstance(label, str) or not label or label == "ALL" for label in labels)):
        raise ValueError("LPW时长下界须为递增正数，标签须唯一且不能为ALL")
    values = np.asarray(hours)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("事件时长须为有限非负数")
    codes = np.searchsorted(bounds, values, side="right") - 1
    return np.where(codes >= 0, np.asarray(labels, dtype=object)[np.maximum(codes, 0)], "")


def hourly_lpw_masks(cf, threshold, cause=None, exclude_cut_out=True):
    """校验单站小时序列并返回时间、有效及严格低CF掩码；缺时标签不自动插值。"""
    if cf.dims != ("time",):
        raise ValueError("小时事件输入须为单站一维time序列")
    # pandas/xarray可能使用us或ns分辨率；统一到ns再比较整数时间差。
    index = pd.DatetimeIndex(cf.time.values).as_unit("ns")
    if (index.empty or index.hasnans or index.has_duplicates or not index.is_monotonic_increasing
            or not (index == index.floor("h")).all()):
        raise ValueError("小时输入须非空、整点、有序且无重复")
    if not np.isfinite(threshold) or not 0 < threshold <= 1:
        raise ValueError("小时固定CF阈值须在(0,1]")
    values = cf.values
    if ((values[np.isfinite(values)] < 0) | (values[np.isfinite(values)] > 1)).any():
        raise ValueError("有效CF须在[0,1]")
    valid = np.isfinite(values)
    if cause is not None:
        if cause.dims != cf.dims or not cause.time.equals(cf.time):
            raise ValueError("成因码须与小时CF完全对齐")
        if not np.isin(cause.values, [-1, 0, 1, 2]).all():
            raise ValueError("发现未知成因码")
        valid &= cause.values != -1
        if exclude_cut_out:
            valid &= cause.values != 2
    # 与原数组同精度比较，恰好等于阈值的观测不算低CF。
    return index, valid, valid & (values < threshold)


def identify_hourly_lpw(cf, threshold, level, *, cause=None, exclude_cut_out=True, min_hours=4,
                        lower_bounds=(4, 8, 12, 24), labels=("LPW1", "LPW2", "LPW3", "LPW4"),
                        station_id="regional"):
    """识别连续达到min_hours的LPW（默认4小时）；每标签代表1小时，结束为末个低CF标签。"""
    classify_lpw_duration([], lower_bounds, labels)
    if not isinstance(min_hours, int) or min_hours < 1 or lower_bounds[0] != min_hours:
        raise ValueError("最小时数须为正整数且等于首档分级下界")
    index, valid, low = hourly_lpw_masks(cf, threshold, cause, exclude_cut_out)
    # 相邻低值记录若缺了时间标签，也必须分成两场，不能跨缺小时连接。
    gaps = np.diff(index.asi8) != pd.Timedelta(hours=1).value
    starts = np.flatnonzero(low & (~np.r_[False, low[:-1]] | np.r_[False, gaps]))
    ends = np.flatnonzero(low & (~np.r_[low[1:], False] | np.r_[gaps, False]))
    durations = ends - starts + 1
    keep = durations >= min_hours
    # 前缀和和分段最小值避免逐场切片，适用于数百万场事件。
    prefix = np.r_[0., np.cumsum(np.where(valid, cf.values, 0.), dtype=np.float64)]
    minima = np.minimum.reduceat(np.where(low, cf.values, np.inf), starts) if len(starts) else np.array([])
    starts, ends, durations, minima = starts[keep], ends[keep], durations[keep], minima[keep]
    total_cf = prefix[ends + 1] - prefix[starts]
    cut_out = np.zeros(len(index), dtype=int) if cause is None else (cause.values == 2).astype(int)
    cut_prefix = np.r_[0, np.cumsum(cut_out)]
    cut_hours = cut_prefix[ends+1]-cut_prefix[starts]
    preceding = np.maximum(starts - 1, 0)
    following = np.minimum(ends + 1, len(index) - 1)
    grade = classify_lpw_duration(durations, lower_bounds, labels)
    return pd.DataFrame(dict(
        event_id=[f"{level}_{station_id}_{n:06d}" for n in range(1, len(starts)+1)],
        station_id=str(station_id), threshold_level=level, cf_threshold=threshold,
        start=index[starts], end=index[ends], end_exclusive=index[ends]+pd.Timedelta(hours=1),
        duration_hours=durations, valid_observations=durations, lpw_class=grade,
        mean_cf=total_cf / durations, min_cf=minima,
        cumulative_cf_deficit=np.maximum(threshold * durations - total_cf, 0.),
        missing_hours=np.zeros(len(starts), dtype=int), cut_out_hours=cut_hours,
        missing_before=(starts > 0) & (~valid[preceding] | (index.asi8[starts]-index.asi8[preceding] != pd.Timedelta(hours=1).value)),
        missing_after=(ends < len(index)-1) & (~valid[following] | (index.asi8[following]-index.asi8[ends] != pd.Timedelta(hours=1).value)),
        left_boundary=starts == 0, right_boundary=ends == len(index)-1))
