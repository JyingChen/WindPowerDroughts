"""功能：将参考高度风速外推到轮毂高度。
输入：风速DataArray及高度、指数；输出：同形状轮毂风速。
流程：校验参数后应用幂律；注意：缺测保留，ERA5动态接口尚未实现。
"""
import numpy as np


def extrapolate_wind(wind, source_height=10., target_height=100., alpha=1/7,
                     method="power_law", era5=None):
    """按幂律外推风速；高度须正且有限，指数须有限且位于[0,1]。"""
    if method == "dynamic_era5":
        raise NotImplementedError("动态风切变需ERA5多高度逐小时数据、对齐及质控；当前尚未实现。")
    if method != "power_law":
        raise ValueError("未知高度外推方法")
    if not all(np.isfinite(v) for v in (source_height, target_height, alpha)):
        raise ValueError("高度和指数必须为有限数")
    if min(source_height, target_height) <= 0 or not 0 <= alpha <= 1:
        raise ValueError("高度必须>0，alpha须在[0,1]")
    # V(z)=V(z0)*(z/z0)**alpha；无效风速维持缺测，不做插值。
    result = wind.where(np.isfinite(wind) & (wind >= 0)) * (target_height / source_height)**alpha
    result.attrs = dict(units="m s-1", source_height_m=source_height,
                        hub_height_m=target_height, shear_alpha=alpha, method=method)
    return result.rename("hub_wind_speed")
