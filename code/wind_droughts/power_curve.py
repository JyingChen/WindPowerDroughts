"""功能：按简化三次方或离散机型曲线计算CF和停机成因。
输入：轮毂风速和机型参数；输出：含CF、成因码的Dataset。
流程：参数校验、分段计算、缺测屏蔽；注意：切出边界即停机，额定功率单位kW。
"""
import numpy as np
import xarray as xr


def wind_to_cf(wind, cut_in=3., rated_speed=12., cut_out=25., rated_power_kw=2000.,
               discrete_curve=None):
    """转换CF；v<切入为0，切入≤v<额定为爬坡，额定≤v<切出为1，v≥切出为0。"""
    if not all(np.isfinite(v) for v in (cut_in, rated_speed, cut_out, rated_power_kw)):
        raise ValueError("机型参数必须有限")
    if not 0 <= cut_in < rated_speed < cut_out or rated_power_kw <= 0:
        raise ValueError("需0≤切入<额定<切出，额定功率>0")
    valid = np.isfinite(wind) & (wind >= 0)
    if discrete_curve is None:
        # 切入处CF=0，额定处CF=1；三次方风速比例归一化。
        ramp = (wind**3 - cut_in**3) / (rated_speed**3 - cut_in**3)
        cf = xr.where(wind < cut_in, 0., xr.where(wind < rated_speed, ramp, 1.))
    else:
        curve = np.asarray(discrete_curve, dtype=float)
        if (curve.ndim != 2 or curve.shape[1] != 2 or len(curve) < 2
                or not np.isfinite(curve).all() or not (np.diff(curve[:, 0]) > 0).all()
                or (curve[:, 1] < 0).any() or (curve[:, 1] > rated_power_kw).any()
                or curve[0, 0] > cut_in or curve[-1, 0] < cut_out):
            raise ValueError("离散曲线需递增风速、合法功率，并覆盖切入至切出")
        cf = xr.apply_ufunc(np.interp, wind, kwargs={"xp": curve[:, 0],
                            "fp": curve[:, 1] / rated_power_kw})
        cf = xr.where(wind < cut_in, 0., cf)
    cf = xr.where(wind >= cut_out, 0., cf).clip(0, 1).where(valid).rename("cf")
    # 成因码0=一般运行，1=低于切入，2=切出停机，-1=无效/缺测。
    cause = xr.where(~valid, -1, xr.where(wind >= cut_out, 2,
                     xr.where(wind < cut_in, 1, 0))).astype("int8").rename("cause")
    cf.attrs = dict(units="1", cut_in_ms=cut_in, rated_speed_ms=rated_speed,
                    cut_out_ms=cut_out, rated_power_kw=rated_power_kw,
                    curve="discrete" if discrete_curve is not None else "cubic")
    cause.attrs["codes"] = "-1=missing_or_invalid;0=operating;1=below_cut_in;2=cut_out"
    return xr.Dataset({"cf": cf, "cause": cause})
