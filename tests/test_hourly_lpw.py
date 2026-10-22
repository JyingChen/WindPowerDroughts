"""功能：验证固定CF阈值逐小时LPW、互斥等级、频次和流式结果。
输入：明确构造的小时CF、成因码与临时NetCDF；输出：pytest断言和小型测试产物。
流程：检查4/8/12/24边界、缺测/切出、跨年、独立阈值、缓存校验及地图接口。
注意：测试不依赖真实大数据或网络地图下载，旧日尺度测试继续运行。
"""
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
import xarray as xr
import config
from wind_droughts.events import classify_lpw_duration, identify_hourly_lpw
from wind_droughts.statistics import summarize_hourly_lpw
from wind_droughts.data_io import validate_hourly_cf
from wind_droughts.lpw_analysis import run_hourly_lpw,replot_hourly_lpw
from wind_droughts.plotting import frequency_map_levels, plot_lpw_frequency_maps


def hours(values, start="2020-01-01"):
    """构造连续整点小时CF。"""
    return xr.DataArray(np.asarray(values, dtype=float), dims="time",
                        coords={"time": pd.date_range(start, periods=len(values), freq="h")})


@pytest.mark.parametrize("duration,expected", [(3,""),(4,"LPW1"),(7,"LPW1"),(8,"LPW2"),
    (11,"LPW2"),(12,"LPW3"),(23,"LPW3"),(24,"LPW4"),(100,"LPW4")])
def test_duration_classes_exclusive(duration, expected):
    """4、8、12、24小时边界各自只属于一档，不重叠。"""
    assert classify_lpw_duration([duration]).tolist() == [expected]


def test_hour_count_not_timestamp_difference():
    """00到03四个小时记录构成4小时LPW，右开端点为04点。"""
    e = identify_hourly_lpw(hours([.01]*4), .1, "CF010")
    assert len(e)==1 and e.iloc[0].duration_hours==4
    assert e.iloc[0].end == pd.Timestamp("2020-01-01 03:00")
    assert e.iloc[0].end_exclusive == pd.Timestamp("2020-01-01 04:00")
    assert e.iloc[0].cumulative_cf_deficit == pytest.approx(.36)
    assert e.iloc[0].left_boundary and e.iloc[0].right_boundary
    assert identify_hourly_lpw(hours([.01]*3),.1,"CF010").empty


def test_independent_fixed_thresholds_and_strict_comparison():
    """三个固定CF情景独立；等于阈值的恢复小时打断事件。"""
    cf=hours([.08]*4+[.1]+[.04]*8+[.1]+[.01]*12)
    assert identify_hourly_lpw(cf,.1,"CF010").duration_hours.tolist()==[4,8,12]
    assert identify_hourly_lpw(cf,.05,"CF005").duration_hours.tolist()==[8,12]
    assert identify_hourly_lpw(cf,.02,"CF002").duration_hours.tolist()==[12]


@pytest.mark.parametrize('dtype',['float32','float64'])
def test_equal_threshold_for_saved_cf_precision(dtype):
    """实际缓存为float32；两种精度下等于0.02的小时都不算低CF。"""
    cf=hours([.02]*4+[.01]*4).astype(dtype)
    events=identify_hourly_lpw(cf,.02,'CF002')
    assert len(events)==1 and events.iloc[0].duration_hours==4
    assert events.iloc[0].start==pd.Timestamp('2020-01-01 04:00')


def test_one_hour_recovery_and_missing_split():
    """一个恢复小时、一个NaN小时或一个缺时间标签都必须拆为两场。"""
    for gap in (.1, np.nan):
        e=identify_hourly_lpw(hours([.01]*4+[gap]+[.01]*4),.1,"CF010")
        assert e.duration_hours.tolist()==[4,4]
        if np.isnan(gap):
            assert e.iloc[0].missing_after and e.iloc[1].missing_before
    cf=hours([.01]*9).isel(time=[0,1,2,3,5,6,7,8])
    e=identify_hourly_lpw(cf,.1,"CF010")
    assert e.duration_hours.tolist()==[4,4]
    assert e.iloc[0].missing_after


def test_cut_out_breaks_default_and_is_flagged_if_included():
    """切出0CF默认中断低风速事件；显式纳入时保留切出小时计数。"""
    cf=hours([.01]*4+[0.]+[.01]*4)
    cause=xr.zeros_like(cf,dtype="int8")
    cause[4]=2
    e=identify_hourly_lpw(cf,.1,"CF010",cause=cause)
    assert e.duration_hours.tolist()==[4,4]
    e=identify_hourly_lpw(cf,.1,"CF010",cause=cause,exclude_cut_out=False)
    assert e.duration_hours.tolist()==[9] and e.iloc[0].cut_out_hours==1


def test_cross_year_single_event_and_hours_allocated():
    """跨年4小时只计一场；开始次数归开始年、小时数按实际年分配。"""
    cf=hours([.01]*4,"2020-12-31 22:00")
    e=identify_hourly_lpw(cf,.1,"CF010",station_id="S1")
    info=dict(station=1,station_id="S1",latitude=30.,longitude=120.)
    f,a=summarize_hourly_lpw(cf,.1,e,"CF010",info)
    assert len(e)==1 and e.event_id.is_unique
    assert a.ALL_event_starts.tolist()==[1,0]
    assert a.lpw_hours.tolist()==[2,2]
    assert f.loc[f.lpw_class=="ALL","event_count"].item()==1
    assert f.loc[f.lpw_class!="ALL","event_count"].sum()==1


def test_invalid_hour_axis_and_cf_rejected():
    """重复、未排序、非整点及越界CF均不能进入小时事件识别。"""
    cf=hours([.01]*4)
    for bad in (cf.isel(time=[0,0,1,2]), cf.isel(time=[3,2,1,0]),
                cf.assign_coords(time=cf.time+pd.Timedelta(minutes=30)), hours([1.1]*4)):
        with pytest.raises(ValueError):
            identify_hourly_lpw(bad,.1,"CF010")


def test_streaming_station_analysis_and_cache_validation(tmp_path):
    """两站人工NetCDF验证三级阈值、四个时长档、缺测站NaN和逐站CSV.gz。"""
    values=[]
    for duration in [4,8,12,24]:
        values.extend([.5]+[.01]*duration)
    values.append(.5)
    values=np.column_stack([values,np.full(len(values),np.nan)])
    times=pd.date_range("2020-01-01",periods=len(values),freq="h")
    source=xr.Dataset({'cf':(('time','station'),values),
        'cause':(('time','station'),np.where(np.isfinite(values),0,-1).astype('int8'))},
        coords={'time':times,'station':[1,2],'station_id':('station',['A','B']),
                'lat':('station',[30.,40.]),'lon':('station',[110.,120.])},
        attrs=dict(source_height_m=config.SOURCE_HEIGHT_M,hub_height_m=config.HUB_HEIGHT_M,shear_alpha=config.SHEAR_ALPHA))
    source.cf.attrs=dict(units='1',cut_in_ms=config.CUT_IN_MS,rated_speed_ms=config.RATED_SPEED_MS,
        cut_out_ms=config.CUT_OUT_MS,rated_power_kw=config.RATED_POWER_KW,curve='cubic')
    path=tmp_path/'source.nc'; source.to_netcdf(path,engine='netcdf4')
    settings=SimpleNamespace(**{k:v for k,v in vars(config).items() if k.isupper()})
    settings.LPW_STATION_BLOCK_SIZE=1
    manifest=run_hourly_lpw(path,tmp_path/'result',settings,plot_maps=False)
    assert manifest['status']=='complete'
    assert manifest['threshold_event_counts']=={'CF010':4,'CF005':4,'CF002':4}
    f=pd.read_csv(tmp_path/'result/tables/station_frequency.csv')
    assert f.loc[f.station==2,'event_count'].isna().all()
    a=f.loc[(f.station==1)&(f.threshold_level=='CF010')].set_index('lpw_class')
    assert a.loc['ALL','event_count']==4
    assert a.loc[['LPW1','LPW2','LPW3','LPW4'],'event_count'].tolist()==[1,1,1,1]
    e=pd.read_csv(tmp_path/'result/tables/events_CF010.csv.gz')
    assert e.duration_hours.tolist()==[4,8,12,24] and e.event_id.is_unique
    with xr.open_dataset(tmp_path/'result/netcdf/lpw_station_frequency.nc') as saved:
        assert saved.event_count.sel(threshold_level='CF010',lpw_class='ALL',station=1)==4
        assert saved.cf_threshold.sel(threshold_level='CF010')==.1
    with pytest.raises(ValueError,match='不匹配'):
        validate_hourly_cf(source,{'hub_height_m':999.})


def test_frequency_levels_and_shared_map_interface(tmp_path,monkeypatch):
    """地图复用utils接口并传入站点坐标；同一时长等级跨阈值使用相同离散边界。"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import utils
    calls=[]
    def fake_map(data,**kwargs):
        """记录绘图输入，用小画布验证输出文件。"""
        assert data.latitude.dims==('station',) and data.longitude.dims==('station',)
        calls.append(kwargs)
        return plt.subplots(figsize=(2,2))
    monkeypatch.setattr(utils,'plot_scat_map',fake_map)
    rows=[]
    for level,threshold,counts in [('CF010',.1,[0,20]),('CF005',.05,[1,5])]:
        for station,count in enumerate(counts):
            rows.append(dict(station=station,latitude=30.+station,longitude=110.+station,
                threshold_level=level,cf_threshold=threshold,lpw_class='LPW1',event_count=count))
    boundary=tmp_path/'boundary.geojson'; boundary.write_text('{}')
    files,scales=plot_lpw_frequency_maps(pd.DataFrame(rows),tmp_path/'maps',boundary_path=boundary,
        labels=('LPW1',),lower_bounds=(4,),dpi=30,
        fixed_levels={'LPW1':[0,1,5,10,21]},colors=['blue','green','red'],zero_color='#d9d9d9')
    assert len(files)==2 and all(Path(f).is_file() for f in files)
    np.testing.assert_equal(calls[0]['levels'],calls[1]['levels'])
    assert scales['LPW1']['levels'][-1]>=20
    assert scales['LPW1']['zero_bin'] is True
    assert scales['LPW1']['colors']==['#d9d9d9','#0000ff','#008000','#ff0000']
    with pytest.raises(ValueError):
        frequency_map_levels([0,20],fixed=[0,5,10])


def test_scatter_map_mixed_boundary_does_not_add_fake_stations(tmp_path):
    """混合面/线底图只能绘制边界线，不能把线端点误画为站点。"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import PathCollection
    import geopandas as gpd
    from shapely.geometry import Polygon,LineString
    from utils import plot_scat_map
    boundary=tmp_path/'mixed.geojson'
    gpd.GeoDataFrame(geometry=[Polygon([(100,20),(110,20),(110,30),(100,30)]),
                              LineString([(101,21),(109,29)])],crs='EPSG:4326').to_file(boundary,driver='GeoJSON')
    values=xr.DataArray([1.,2.],dims='station',coords={'latitude':('station',[24.,26.]),
                                                      'longitude':('station',[104.,106.])})
    fig,ax=plot_scat_map(values,shp_path=boundary,add_south_china_sea=False,
                         extent=(99,111,19,31),figsize=(4,4),cbar_label='Events')
    scatters=[c for c in ax.collections if isinstance(c,PathCollection)]
    assert len(scatters)==1 and len(scatters[0].get_offsets())==2
    fig.savefig(tmp_path/'map.png',dpi=40)
    plt.close(fig)


def test_replot_preserves_scientific_tables(tmp_path,monkeypatch):
    """重绘只读取科学统计表，更新图件及绘图配置，不能重新识别或修改事件统计。"""
    import json
    from wind_droughts import lpw_analysis
    table_dir=tmp_path/'tables';table_dir.mkdir()
    path=table_dir/'station_frequency.csv';path.write_text('station,event_count\n1,5\n')
    previous=path.read_bytes()
    manifest={'analysis_mode':'hourly_lpw','class_labels':json.dumps(['LPW1','LPW2','LPW3','LPW4']),
        'class_lower_hours':json.dumps([4,8,12,24]),'time_start':'2020-01-01','time_end':'2020-12-31',
        'threshold_event_counts':{'CF010':5},'status':'complete'}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    captured=[]
    def fake_maps(frame,output_dir,**kwargs):
        """记录重绘参数，避免在重绘流程测试中重复实际制图。"""
        captured.append(kwargs)
        return ['example.png'],{'LPW1':{'levels':[0,1,10]}}
    monkeypatch.setattr(lpw_analysis,'plot_lpw_frequency_maps',fake_maps)
    result=replot_hourly_lpw(tmp_path,config)
    assert path.read_bytes()==previous
    assert result['threshold_event_counts']=={'CF010':5}
    assert captured[0]['fixed_levels']==config.LPW_MAP_LEVELS
    assert (tmp_path/'plot_configuration.json').is_file()
