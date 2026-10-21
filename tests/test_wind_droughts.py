"""功能：用有明确期望的人工序列验证风旱核心模块。
输入：人工风速、CF、坐标与临时文件；输出：pytest断言结果。
流程：公式边界、缺测与事件、分组阈值、空间权重、读写回归；注意：不依赖真实大数据。
"""
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from wind_droughts.wind_profile import extrapolate_wind
from wind_droughts.power_curve import wind_to_cf
from wind_droughts.spatial import regional_mean, daily_and_rolling
from wind_droughts.thresholds import build_thresholds, exclusive_daily_labels
from wind_droughts.events import identify_events
from wind_droughts.statistics import summarize_events
from wind_droughts.data_io import (read_wind, hourly_blocks, create_hourly_file,
    append_hourly, resolve_capacity)


def daily(values, start="2020-01-01"):
    """构造从给定日期开始的连续日CF。"""
    return xr.DataArray(values, dims="time", coords={"time": pd.date_range(start, periods=len(values), freq="D")})


def detect(values, merge=0, start="2020-01-01"):
    """用固定0.2阈值识别人工CF。"""
    cf = daily(values, start)
    return identify_events(cf, xr.full_like(cf, .2), "fixed", "fixed", merge)


def test_power_law():
    """10m到100m的倍率为10**(1/7)，缺测保持缺测。"""
    result = extrapolate_wind(daily([10., np.nan]))
    assert result[0] == pytest.approx(10 * 10**(1/7))
    assert np.isnan(result[1])
    assert extrapolate_wind(daily([10.]), 10, 10)[0] == 10


@pytest.mark.parametrize("args", [(0,100,.1), (10,-1,.1), (10,100,np.nan), (10,100,-.1), (10,100,2)])
def test_bad_profile(args):
    """非正高度、无效指数必须明确报错。"""
    with pytest.raises(ValueError):
        extrapolate_wind(daily([1.]), *args)


def test_dynamic_unimplemented():
    """动态ERA5接口不可假装运行。"""
    with pytest.raises(NotImplementedError, match="ERA5"):
        extrapolate_wind(daily([1.]), method="dynamic_era5")


def test_curve_boundaries_range_and_cause():
    """切入为0、额定为1、切出为0，负值及NaN/无穷为缺测。"""
    p = wind_to_cf(daily([0., 2.9, 3., 6., 12., 24.99, 25., 26., np.nan, -1., np.inf]))
    np.testing.assert_allclose(p.cf.values[:8], [0,0,0,(6**3-3**3)/(12**3-3**3),1,1,0,0])
    assert np.isnan(p.cf.values[8:]).all()
    assert p.cause.values.tolist() == [1,1,0,0,0,0,2,2,-1,-1,-1]
    assert ((p.cf.dropna("time") >= 0) & (p.cf.dropna("time") <= 1)).all()


def test_discrete_curve():
    """离散功率曲线线性插值，并在切出强制停机。"""
    p = wind_to_cf(daily([3., 7.5, 12., 25., np.nan]), discrete_curve=[(3,0),(12,2000),(25,2000)])
    np.testing.assert_allclose(p.cf, [0,.5,1,0,np.nan], equal_nan=True)
    with pytest.raises(ValueError):
        wind_to_cf(daily([1.]), cut_in=12)


def test_continuous_events_and_equality():
    """等于阈值不算低值；末个低值日就是结束日。"""
    e = detect([.1,.1,.2,.05])
    assert e.duration_days.tolist() == [2,1]
    assert e.low_cf_days.tolist() == [2,1]
    assert e.iloc[0].end == pd.Timestamp("2020-01-02")
    assert e.iloc[0].cumulative_cf_deficit == pytest.approx(.2)


def test_recovery_merge():
    """恢复一天默认拆为两场，允许合并时跨度3天而低CF为2天。"""
    assert len(detect([.1,.3,.1])) == 2
    e = detect([.1,.3,.1], merge=1)
    assert len(e) == 1
    assert e.iloc[0].duration_days == 3
    assert e.iloc[0].low_cf_days == 2
    assert e.iloc[0].valid_observations == 3
    assert e.iloc[0].cumulative_cf_deficit == pytest.approx(.2)


def test_missing_always_interrupts():
    """即使允许恢复三天，缺测也必须拆分。"""
    e = detect([.1,np.nan,.1], merge=3)
    assert len(e) == 2
    assert e.iloc[0].missing_after and e.iloc[1].missing_before
    assert (e.missing_days == 0).all()
    cf = daily([.1,.1,.1]).isel(time=[0,2])
    assert len(identify_events(cf, xr.full_like(cf,.2), "P20", merge_recovery_days=3)) == 2


def test_cross_year_single_id():
    """跨年事件保留一个ID，年度低值日分配到各自年份，次数记开始年。"""
    cf = daily([.1,.1,.1], "2020-12-31")
    th = xr.full_like(cf,.2)
    e = identify_events(cf, th, "P20")
    assert len(e) == 1 and e.iloc[0].duration_days == 3
    _, summary, periods = summarize_events(cf, th, e, "P20")
    annual = periods[periods.grouping == "year"]
    assert annual.event_starts.tolist() == [1,0]
    assert annual.low_cf_days.tolist() == [1,2]
    assert summary.iloc[0].event_count == 1


def test_exclusive_labels_and_independent_scenarios():
    """辅助标签互斥；P5低值可同时属于三个独立情景，最终等级只记录情景名。"""
    cf = daily([.25,.15,.075,.025,np.nan])
    limits = xr.Dataset({k:xr.full_like(cf,v) for k,v in {"P20":.2,"P10":.1,"P5":.05}.items()})
    assert exclusive_daily_labels(cf,limits).values.tolist() == [0,1,2,3,-1]
    for label in limits:
        events = identify_events(cf,limits[label],label)
        assert len(events) == 1
        assert events.iloc[0].final_level == label
    assert [identify_events(cf, limits[k], k).iloc[0].low_cf_days for k in limits] == [3,2,1]


def test_monthly_threshold_cross_boundary():
    """分月阈值在跨月时切换，连续低值跨月仍是一场事件。"""
    cf = daily([.2,.1,.3,.4], "2020-01-30")
    t = build_thresholds(cf, levels={"P50":50}, mode="monthly")["P50"]
    np.testing.assert_allclose(t, [.15,.15,.35,.35])
    e = identify_events(cf,t,"P50")
    assert len(e) == 1 and e.iloc[0].duration_days == 2
    assert e.iloc[0].cumulative_cf_deficit == pytest.approx(.1)


def test_baseline_and_fixed():
    """百分位仅用基准期，固定阈值保持常数。"""
    cf = daily([0.,.1,.2,.9])
    t = build_thresholds(cf, levels={"P50":50}, baseline_end="2020-01-03")
    np.testing.assert_allclose(t.P50, .1)
    np.testing.assert_allclose(build_thresholds(cf,kind="fixed",fixed=.3)['fixed'], .3)
    with pytest.raises(ValueError):
        build_thresholds(daily([np.nan]))


def test_region_weights_missing_and_all_missing():
    """纬度0/60度权重为1/0.5；缺测后分母重新归一化。"""
    cf = xr.DataArray([[0,1],[np.nan,1],[np.nan,np.nan]], dims=("time","station"),
        coords={"time":pd.date_range("2020-01-01",periods=3,freq="h"),"lat":("station",[0,60])})
    np.testing.assert_allclose(regional_mean(cf), [1/3,1,np.nan], equal_nan=True)


def test_cut_out_exclusion_renormalizes():
    """剔除切出停机后重新归一化，全部切出不伪装成低风速风旱。"""
    wind = xr.DataArray([[25.,12.],[25.,26.]], dims=("time","station"),
        coords={"time":pd.date_range("2020-01-01", periods=2, freq="h"), "lat":("station",[0.,60.])})
    p = wind_to_cf(wind)
    np.testing.assert_allclose(regional_mean(p.cf),[1/3,0])
    np.testing.assert_allclose(regional_mean(p.cf.where(p.cause != 2)),[1,np.nan],equal_nan=True)


def test_empty_events_and_missing_month_baseline():
    """没有事件时仍输出有效空表；历史无样本月份阈值缺测。"""
    cf = daily([.3,.4], "2020-01-31")
    th = build_thresholds(cf, levels={"P20":20}, mode="monthly", baseline_end="2020-01-31").P20
    assert th[0] == .3 and np.isnan(th[1])
    events = identify_events(cf,th,"P20")
    selected, summary, periods = summarize_events(cf,th,events,"P20")
    assert selected.empty and summary.iloc[0].event_count == 0
    assert summary.iloc[0].valid_days == 1
    assert periods.event_starts.sum() == 0


def test_grid_weights():
    """经纬度网格可广播纬度权重。"""
    cf = xr.DataArray([[[0.,0.],[1.,1.]]],dims=("time","lat","lon"),
        coords={"time":[pd.Timestamp("2020-01-01")],"lat":[0.,60.],"lon":[100.,101.]})
    assert regional_mean(cf)[0] == pytest.approx(1/3)


def test_daily_minimum_and_rolling():
    """每天18小时有效才保留；含缺测日的七日窗口无效。"""
    times = pd.date_range("2020-01-01",periods=8*24,freq="h")
    values = np.ones(len(times))*.2
    values[:7] = np.nan
    values[24:30] = np.nan
    ds = daily_and_rolling(xr.DataArray(values,dims="time",coords={"time":times}),18)
    assert np.isnan(ds.daily_cf[0]) and ds.daily_cf[1] == pytest.approx(.2)
    assert np.isnan(ds.rolling7_cf[6]) and ds.rolling7_cf[7] == pytest.approx(.2)


def test_common_minimum_filter_and_energy():
    """N只筛统计事件；未提供装机不产电量，提供时区分两类缺口。"""
    cf = daily([.1,.1,.3,.1]); th=xr.full_like(cf,.2)
    hours=xr.full_like(cf,24.)
    events=identify_events(cf,th,"P20",valid_hours=hours,installed_capacity_kw=1000.)
    assert events.iloc[0].threshold_deficit_energy_kwh_estimate == pytest.approx(4800)
    assert events.iloc[0].full_output_gap_energy_kwh == pytest.approx(43200)
    selected, summary, _=summarize_events(cf,th,events,"P20",2)
    assert len(selected)==1 and summary.iloc[0].low_cf_days==3
    assert not any("kwh" in c for c in detect([.1]).columns)
    assert resolve_capacity(None,2000,None) is None
    assert resolve_capacity(None,2000,3)==6000


def test_read_mapping_missing_hours_and_roundtrip(tmp_path):
    """自定义维名映射、缺小时NaN、小时编码和CF成因均可往返保存。"""
    ds=xr.Dataset({"speed":(("date","site","kind"),np.array([1.,3.])[:,None,None])},
        coords={"date":pd.to_datetime(["2020-01-01 00:00","2020-01-01 02:00"]),
                "site":[1],"kind":["ws"],"latitude":("site",[30.])})
    wind=read_wind(ds,"speed",{"kind":"ws"},{"date":"time","latitude":"lat"})
    blocks=list(hourly_blocks(wind,2))
    assert np.isnan(blocks[0][1].values[1,0])
    path=tmp_path/"cf.nc"
    handle=create_hourly_file(path,wind,{"test":"yes"})
    try:
        for offset,block in blocks:
            append_hourly(handle,wind_to_cf(block),offset)
    finally:
        handle.close()
    with xr.open_dataset(path) as saved:
        assert saved.time.size==3
        assert saved.time.values[1]==np.datetime64("2020-01-01T01:00:00")
        assert saved.cause.values[:,0].tolist()==[1,-1,0]
        assert np.isnan(saved.cf.values[1,0])
    with pytest.raises(ValueError):
        read_wind(ds.isel(date=[1,0]),"speed",{"kind":"ws"},{"date":"time"})
    with pytest.raises(ValueError):
        read_wind(ds.isel(date=[0,0]),"speed",{"kind":"ws"},{"date":"time"})
