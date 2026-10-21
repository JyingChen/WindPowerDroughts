"""功能：生成固定、全年或分月历史百分位阈值及互斥逐日标签。
输入：唯一识别时间尺度的区域CF和基准期；输出：与日期对齐的情景阈值。
流程：筛选历史有效值、分位数估计、逐日映射；注意：CF严格小于阈值才算低CF。
"""
import numpy as np
import pandas as pd
import xarray as xr


def build_thresholds(cf, kind="percentile", levels=None, mode="annual", fixed=.1,
                     baseline_start=None, baseline_end=None):
    """在选定CF尺度上计算阈值；分月缺少历史样本时该月阈值为NaN。"""
    if cf.dims != ("time",):
        raise ValueError("阈值输入须为一维time序列")
    if kind not in ("fixed", "percentile") or mode not in ("annual", "monthly"):
        raise ValueError("未知阈值类型或历史分组方式")
    if kind == "fixed":
        if not np.isfinite(fixed) or not 0 <= fixed <= 1:
            raise ValueError("固定CF阈值须在[0,1]")
        return xr.Dataset({"fixed": xr.full_like(cf, fixed, dtype=float)},
                          attrs={"threshold_type": "fixed", "comparison": "cf < threshold"})
    levels = {"P20": 20, "P10": 10, "P5": 5} if levels is None else levels
    if not levels or any(not np.isfinite(p) or not 0 < p < 100 for p in levels.values()):
        raise ValueError("百分位须在(0,100)")
    history = cf.sel(time=slice(baseline_start, baseline_end))
    if not np.isfinite(history.values).any():
        raise ValueError("基准期无有效CF，无法计算百分位阈值")
    result = {}
    for label, percentile in levels.items():
        values = np.full(cf.size, np.nan)
        groups = range(1, 13) if mode == "monthly" else [None]
        for month in groups:
            sample = history.values if month is None else history.values[history.time.dt.month.values == month]
            sample = sample[np.isfinite(sample)]
            mask = np.ones(cf.size, dtype=bool) if month is None else cf.time.dt.month.values == month
            if len(sample):
                values[mask] = np.percentile(sample, percentile, method="linear")
        result[label] = xr.DataArray(values, dims="time", coords={"time": cf.time},
                                     attrs={"percentile": percentile, "units": "1"})
    return xr.Dataset(result, attrs={"threshold_type": "percentile", "mode": mode,
                       "baseline_start": str(pd.Timestamp(history.time.values[0])),
                       "baseline_end": str(pd.Timestamp(history.time.values[-1])),
                       "comparison": "cf < threshold; equal values are not low CF"})


def exclusive_daily_labels(cf, thresholds):
    """返回互斥逐日阈值区间码0/1/2/3；缺测为-1，仅作辅助描述，不用于事件分级。"""
    for key in ("P20", "P10", "P5"):
        if key not in thresholds:
            raise ValueError("区间标签需要P20/P10/P5")
    valid = np.isfinite(cf)
    label = xr.zeros_like(cf, dtype="int8")
    for code, key in enumerate(("P20", "P10", "P5"), 1):
        valid = valid & np.isfinite(thresholds[key])
        label = xr.where(cf < thresholds[key], code, label)
    label = label.where(valid, -1).astype("int8").rename("exclusive_daily_band")
    label.attrs["codes"] = "-1=missing;0=>=P20;1=[P10,P20);2=[P5,P10);3=<P5; auxiliary only"
    return label
