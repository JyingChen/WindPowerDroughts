"""功能：空间余弦加权和日/七日时间聚合。
输入：逐小时CF及纬度；输出：区域小时、日平均和辅助滚动CF。
流程：逐时有效权重归一化，再按日有效小时筛选；注意：站点权重并非装机权重。
"""
import numpy as np
import xarray as xr


def regional_mean(cf):
    """按cos(纬度)聚合所有非time维；缺测点不参与权重分母，全部缺测返回NaN。"""
    dims = [d for d in cf.dims if d != "time"]
    if not dims:
        return cf.rename("regional_cf")
    if "lat" not in cf.coords:
        raise ValueError("空间聚合需要纬度坐标，请配置COORDINATE_MAP")
    lat = cf.lat
    if not np.isfinite(lat.values).all() or (np.abs(lat.values) > 90).any():
        raise ValueError("纬度必须有限且位于[-90,90]")
    # 广播到空间维；海量时间维由xarray隐式广播，不复制整块权重。
    weights = np.cos(np.deg2rad(lat)).where(np.abs(lat) < 90, 0.)
    valid_weights = weights.where(np.isfinite(cf), 0.)
    numerator = (cf.where(np.isfinite(cf), 0.) * weights).sum(dims)
    denominator = valid_weights.sum(dims)
    return (numerator / denominator.where(denominator > 0)).rename("regional_cf")


def daily_and_rolling(hourly, min_hours=18, rolling=True):
    """计算日平均及后向七日平均；七日窗口必须七天全有效，不补缺失小时。"""
    if not isinstance(min_hours, int) or not 1 <= min_hours <= 24:
        raise ValueError("每天最少有效小时数须为1到24的整数")
    count = hourly.resample(time="1D").count().rename("valid_hours")
    daily = hourly.resample(time="1D").mean(skipna=True).where(count >= min_hours).rename("daily_cf")
    result = xr.Dataset({"daily_cf": daily, "valid_hours": count})
    if rolling:
        result["rolling7_cf"] = daily.rolling(time=7, min_periods=7).mean()
        result.rolling7_cf.attrs["meaning"] = "trailing 7 complete valid days; auxiliary unless selected as event input"
    return result
