"""功能：保留项目共用的绘图、趋势估计、显著性标记和描述统计工具。
输入：各工具所需的xarray/数值数据、图形参数和地图文件；输出：图形、统计量或Dataset。
主要流程：由调用者显式选择工具，完成统计或地图绘制；风旱专用计算位于wind_droughts包。
注意：原有函数实现与绘图全局设置保持不变，导入依赖cartopy、geopandas等绘图库。
"""
#%%
import numpy as np
import pandas as pd
import xarray as xr
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from matplotlib.colors import BoundaryNorm, TwoSlopeNorm
import matplotlib.cm as cm
import geopandas as gpd
import matplotlib.colors as mcolors
import seaborn as sns
from scipy import stats

plt.rcParams['font.family'] = 'Times New Roman'
plt.rcParams['font.sans-serif'] = ['Times New Roman']
# 其他全局设置
# plt.rcParams['font.size'] = 12
plt.rcParams['axes.labelsize'] = 20
# plt.rcParams['axes.titlesize'] = 16
plt.rcParams['xtick.labelsize'] = 20
plt.rcParams['ytick.labelsize'] = 20
plt.rcParams['legend.fontsize'] = 20
plt.rcParams['font.size'] = 23
plt.rcParams['axes.labelsize'] = 23
def get_p_str(p_value):
        """0.001: '\***', 0.01: '\**', 0.05: '\*', else: '无'"""
        if p_value < 0.001:
            return '***'
        elif p_value < 0.01:
            return '**' 
        elif p_value < 0.05:
            return '*'
        return ''

def china_basemap(
    shp_path: str = r"../data/中国_省.geojson",
    figsize=(10, 8),
    dpi=300,
    extent=(73, 136, 17, 54),
    edgecolor="grey",
    facecolor="none",
    linewidth=0.8,
    add_south_china_sea=True,
    south_sea_box=([0.823, 0, 0.2, 0.3]),  # (x0, y0, w, h) in ax.transAxes if anchor='axes' figsize放大不会影响子图位置
    south_sea_extent=(105, 125, 2, 25),
):  
    """
    画中国底图（省界）并可选添加南海子图。

    返回:
      fig, ax, sub_ax, gdf
        sub_ax: 南海子图 ax（若 add_south_china_sea=False 则为 None）
        gdf: 读取的省界 GeoDataFrame
    """
    fig, ax = plt.subplots(
        figsize=figsize,
        dpi=dpi,
        subplot_kw={"projection": ccrs.PlateCarree()},
    )
    gdf = gpd.read_file(shp_path)
    # 主图
    gdf.plot(
        ax=ax,
        transform=ccrs.PlateCarree(),
        edgecolor=edgecolor,
        facecolor=facecolor,
        linewidth=linewidth,
    )
    ax.set_extent(extent, crs=ccrs.PlateCarree())
    # ax.add_feature(cfeature.BORDERS, linewidth=0.5)
    gl = ax.gridlines(draw_labels=True, linewidth=0.5, alpha=1, linestyle="--")
    gl.top_labels = False
    gl.right_labels = False
    sub_ax = None
    if add_south_china_sea:
        sub_ax = ax.inset_axes(
            south_sea_box,
            transform=ax.transAxes,
            projection=ccrs.PlateCarree(),
        )

        sub_ax.set_extent(south_sea_extent, crs=ccrs.PlateCarree())
        gdf.plot(
            ax=sub_ax,
            transform=ccrs.PlateCarree(),
            edgecolor=edgecolor,
            facecolor=facecolor,
            linewidth=0.6,
        )
        # sub_ax.add_feature(cfeature.BORDERS, linewidth=0.5)
        sub_ax.gridlines(draw_labels=False, linewidth=0.3, alpha=0.5, linestyle="--")
        sub_ax.spines["geo"].set_edgecolor("black")
        sub_ax.spines["geo"].set_linewidth(0.6)
    
    return fig, ax, sub_ax, gdf

def plot_scat_map(ds_ti, levels=None,colors=None,cmap='viridis',norm=None,
                  extent=None,save_path=None,figsize=(10, 10),
                  title=None,text = None,cbar_label=None,orient='horizontal',
                cbar_pad = 0.05, cbar_shrink=0.8,cbar_tick_labels=None,cbar_label_pos=[1.05, -0.4],
                add_south_china_sea=True,south_sea_anchor='axes', south_sea_box=[0.85, -0.01, 0.15, 0.3]
                  ):  
    """
    绘制风速散点分布图（增强版）
    
    参数:
    -----
    ...
    cbar_label : str
        色标标签。
    cbar_tick_labels : dict or tuple or None
        自定义色标刻度。dict 形式为 {tick: label}，
        tuple 形式为 (ticks, labels)。默认为 None。
    figsize : tuple
        图形大小。
    add_south_china_sea : bool
        是否添加南海子图。
    """
    # 提取经纬度和数据
    lons = ds_ti.longitude.values
    lats = ds_ti.latitude.values
    data_values = ds_ti.values
    
    # 过滤掉缺失值
    valid_mask = ~np.isnan(data_values)
    lons_valid = lons[valid_mask]
    lats_valid = lats[valid_mask]
    data_valid = data_values[valid_mask]
    
    print(f"有效数据点数: {len(data_valid)}")
    print(f"数据范围: {data_valid.min():.2f} - {data_valid.max():.2f}")
    
    # 创建图形
    fig = plt.figure(figsize=figsize)
    ax = plt.axes(projection=ccrs.PlateCarree())
    
    # 设置地图范围
    if extent is None:
        extent = [lons_valid.min()-2, lons_valid.max()+2, 
                  lats_valid.min()-1, lats_valid.max()+1]
    ax.set_extent(extent, crs=ccrs.PlateCarree())
    
    # 读取并绘制shapefile
    shp_path = r"../data/中国_省.geojson"
    gdf = gpd.read_file(shp_path)
    gdf.boundary.plot(ax=ax, transform=ccrs.PlateCarree(), 
                      edgecolor='black', linewidth=0.7)
    
    # 添加经纬度网格
    gl = ax.gridlines(draw_labels=True, linewidth=0.5, alpha=0.5, linestyle='--')
    gl.top_labels = False
    gl.right_labels = False
    
    # --- 色标和归一化逻辑 ---
    if levels is not None and colors is not None:
        print("使用离散色标 (BoundaryNorm)")
        cmap_obj = mcolors.ListedColormap(colors)
        norm_obj = BoundaryNorm(levels, ncolors=len(colors), clip=True)
    else:
        print(f"使用连续色标 '{cmap}'")
        cmap_obj = cmap
        norm_obj = norm
    
    # 绘制散点图
    scatter = ax.scatter(lons_valid, lats_valid, c=data_valid, 
                         cmap=cmap_obj, norm=norm_obj, s=20, alpha=1,
                         edgecolors='none', transform=ccrs.PlateCarree())
    
    # 添加色标
    cbar = plt.colorbar(scatter, ax=ax, orientation=orient, 
                        pad=cbar_pad, shrink=cbar_shrink,)
    # 将色标标签放到色标右侧
    cbar.set_label('')
    cbar.ax.text(*cbar_label_pos, cbar_label, transform=cbar.ax.transAxes,va='top', ha='left')
    if cbar_tick_labels is not None:
        if isinstance(cbar_tick_labels, dict):
            ticks = list(cbar_tick_labels.keys())
            labels = list(cbar_tick_labels.values())
            cbar.set_ticks(ticks)
            cbar.set_ticklabels(labels)
        elif isinstance(cbar_tick_labels, tuple) and len(cbar_tick_labels) == 2:
            ticks, labels = cbar_tick_labels
            cbar.set_ticks(ticks)
            cbar.set_ticklabels(labels)
    # 添加标题
    if title:
        ax.set_title(title, fontweight='bold', pad=20)
    if text:
        ax.text(0.02, 0.95, text, transform=ax.transAxes)
    plt.tight_layout()
    
    # 添加南海子图
    if add_south_china_sea:
        south_sea_anchor == 'axes'# 使用主轴归一化坐标，相对主图稳定，不受 tight_layout / figsize 影响
        sub_ax = ax.inset_axes(south_sea_box, transform=ax.transAxes,
                                   projection=ccrs.PlateCarree())
        sub_ax.set_extent([105, 125, 2, 25], crs=ccrs.PlateCarree())
        gdf.boundary.plot(ax=sub_ax, transform=ccrs.PlateCarree(),
                          edgecolor='grey', linewidth=0.5)
        south_china_sea_mask = (
            (lons_valid >= 105) & (lons_valid <= 125) &
            (lats_valid >= 2) & (lats_valid <= 25)
        )
        lons_scs = lons_valid[south_china_sea_mask]
        lats_scs = lats_valid[south_china_sea_mask]
        data_scs = data_valid[south_china_sea_mask]
        if len(lons_scs) > 0:
            sub_ax.scatter(lons_scs, lats_scs, c=data_scs,
                           cmap=cmap_obj, norm=norm_obj, s=10, alpha=1,
                           edgecolors='none', transform=ccrs.PlateCarree())
        sub_ax.add_feature(cfeature.BORDERS, linewidth=0.5)
        sub_ax.gridlines(draw_labels=False, linewidth=0.3, alpha=0.5, linestyle='--')
        sub_ax.spines['geo'].set_edgecolor('black')
        sub_ax.spines['geo'].set_linewidth(0.6)    
    if save_path is not None:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"图形已保存至: {save_path}")
    
    return fig, ax

def calculate_station_trends(ds, method='monthly', time_dim='time'):
    """
    计算全部每个站点的趋势（支持年平均和月平均）请先算好ds_month或ds_yearly再用函数计算
    
    参数:
    -----
    ds : xarray.DataArray
        风速数据，包含时间和站点维度
    var_name : str
        变量名，默认 'ws'
    method : str
        'yearly' - 使用年平均数据计算趋势
        'monthly' - 使用月平均数据计算趋势
    time_dim : str
        时间维度名称，默认 'time'
    
    返回:
    -----
    xarray.Dataset 包含趋势分析结果
    """
    print(f"开始计算站点趋势分析（方法: {method}）...")
    # ds chunk
    ds = ds.chunk({'station': 500})
    if method == 'yearly':
        time_scale = 1  # 年
        time_unit = 'year'
        ds_resampled = ds.resample(time='YS').mean().load()
    elif method == 'monthly':
        time_scale = 12  # 月转年
        time_unit = 'month'
        ds_resampled = ds.resample(time='MS').mean().load()
    else:
        raise ValueError("method must be 'yearly' or 'monthly'")
    
    print(f"数据维度: {ds_resampled.shape}")
    print(f"时间范围: {ds_resampled.time[0].values} 到 {ds_resampled.time[-1].values}")
    print(f"时间点数: {len(ds_resampled.time)} 个{time_unit}")
    
    # 2. 转换时间为数值（年份单位）
    if method == 'yearly':
        time_numeric = np.arange(len(ds_resampled.time))  # 0, 1, 2, ..., 19
    else:  # monthly
        # 将月份转换为年份（0, 1/12, 2/12, ..., 239/12）
        time_numeric = np.arange(len(ds_resampled.time)) / time_scale
    
    n_time_points = len(time_numeric)
    n_years = time_numeric[-1] - time_numeric[0] + (1 if method == 'yearly' else 1/12)
    n_stations = len(ds_resampled.station)
    
    # 3. 初始化结果数组
    results = {
        'trend': np.full(n_stations, np.nan),           # 趋势斜率 (m/s/decade)
        'p_value': np.full(n_stations, np.nan),         # p值
        'r_value': np.full(n_stations, np.nan),         # 相关系数
        'std_err': np.full(n_stations, np.nan),         # 标准误差
        'ci_lower': np.full(n_stations, np.nan),        # 95%置信区间下限
        'ci_upper': np.full(n_stations, np.nan),        # 95%置信区间上限
        'intercept': np.full(n_stations, np.nan),       # 截距
        'total_change': np.full(n_stations, np.nan),    # 总变化量
        'pct_change': np.full(n_stations, np.nan),      # 百分比变化
        'n_valid': np.full(n_stations, np.nan)          # 有效数据点数
    }
    
    # 4. 逐站点计算趋势
    print(f"\n正在处理 {n_stations} 个站点...")
    
    for i in range(n_stations):
        # 获取该站点的数据
        y = ds_resampled.isel(station=i).values
        
        # 检查有效数据
        valid_mask = ~np.isnan(y)
        n_valid = valid_mask.sum()
        
        # !设置最小数据点要求
        # min_points = 10 if method == 'yearly' else 120  # 年平均至少10年，月平均至少10年(120个月)
        
        # if n_valid < min_points:
        #     continue
        
        x = time_numeric[valid_mask]
        y_valid = y[valid_mask]
        
        # 执行线性回归
        slope, intercept, r_value, p_value, std_err = stats.linregress(x, y_valid)
        
        # 计算95%置信区间
        t_val = stats.t.ppf(0.975, n_valid - 2)  # t分布临界值
        ci_half_width = t_val * std_err
        
        # 计算总变化量和百分比变化
        total_change = slope * n_years  # 整个时期的总变化
        initial_value = intercept
        pct_change = (total_change / initial_value * 100) if initial_value != 0 else np.nan
        
        # 保存结果
        results['trend'][i] = slope*10  # 转换为每十年变化
        results['p_value'][i] = p_value
        results['r_value'][i] = r_value
        results['std_err'][i] = std_err
        results['ci_lower'][i] = slope*10 - ci_half_width
        results['ci_upper'][i] = slope*10 + ci_half_width
        results['intercept'][i] = intercept
        results['total_change'][i] = total_change
        results['pct_change'][i] = pct_change
        results['n_valid'][i] = n_valid
        
        # 进度显示
        if (i + 1) % 200 == 0:
            print(f"  已完成 {i + 1}/{n_stations} 个站点")
    
    # 5. 创建结果Dataset
    result_ds = xr.Dataset({
        'trend': (['station'], results['trend']),
        'p_value': (['station'], results['p_value']),
        'r_value': (['station'], results['r_value']),
        'std_err': (['station'], results['std_err']),
        'ci_lower': (['station'], results['ci_lower']),
        'ci_upper': (['station'], results['ci_upper']),
        'intercept': (['station'], results['intercept']),
        'total_change': (['station'], results['total_change']),
        'pct_change': (['station'], results['pct_change']),
        'n_valid': (['station'], results['n_valid'])
    }, coords={
        'station': ds_resampled.station,
        'latitude': ds_resampled.latitude,
        'longitude': ds_resampled.longitude
    })
    
    # 6. 添加元数据
    result_ds.attrs['description'] = f'Wind speed trend analysis based on {method} mean data'
    result_ds.attrs['time_period'] = f"{ds_resampled.time[0].values} to {ds_resampled.time[-1].values}"
    result_ds.attrs['n_time_points'] = n_time_points
    result_ds.attrs['n_years'] = float(n_years)
    result_ds.attrs['method'] = method
    
    # 添加变量属性
    result_ds['trend'].attrs['units'] = 'm/s per 10year'
    result_ds['trend'].attrs['long_name'] = f'Wind speed linear trend ({method})'
    result_ds['total_change'].attrs['units'] = 'm/s'
    result_ds['total_change'].attrs['long_name'] = f'Total change over {n_years:.1f} years'
    result_ds['pct_change'].attrs['units'] = '%'
    result_ds['pct_change'].attrs['long_name'] = 'Percentage change'
    result_ds['n_valid'].attrs['long_name'] = f'Number of valid {time_unit} data points'
    
    # 7. 打印统计摘要
    print("\n" + "="*60)
    print(f"趋势分析完成！（方法: {method}）")
    print("="*60)
    
    trends = results['trend']
    p_values = results['p_value']
    
    print(f"总站点数: {n_stations}")
    print(f"有效站点数: {(~np.isnan(trends)).sum()}")
    print(f"时间跨度: {n_years:.1f} 年")
    print(f"数据点数: {n_time_points} 个{time_unit}")
    
    print(f"\n显著性分析 (p < 0.05):")
    print(f"  显著增加趋势: {((p_values < 0.05) & (trends > 0)).sum()} 个站点")
    print(f"  显著减少趋势: {((p_values < 0.05) & (trends < 0)).sum()} 个站点")
    print(f"  不显著变化: {((p_values >= 0.05) & (~np.isnan(p_values))).sum()} 个站点")
    
    print(f"\n趋势统计:")
    print(f"  平均趋势: {np.nanmean(trends):.4f} m/s/decade")
    print(f"  趋势中位数: {np.nanmedian(trends):.4f} m/s/decade")
    print(f"  趋势标准差: {np.nanstd(trends):.4f} m/s/decade")
    print(f"  最大增加: {np.nanmax(trends):.4f} m/s/decade")
    print(f"  最大减少: {np.nanmin(trends):.4f} m/s/decade")
    
    print(f"\n{n_years:.1f}年累积变化:")
    total_changes = results['total_change']
    print(f"  平均累积变化: {np.nanmean(total_changes):.3f} m/s")
    print(f"  最大累积增加: {np.nanmax(total_changes):.3f} m/s")
    print(f"  最大累积减少: {np.nanmin(total_changes):.3f} m/s")
    
    print(f"\n百分比变化:")
    pct_changes = results['pct_change']
    print(f"  平均百分比变化: {np.nanmean(pct_changes):.2f}%")
    print(f"  最大百分比增加: {np.nanmax(pct_changes):.2f}%")
    print(f"  最大百分比减少: {np.nanmin(pct_changes):.2f}%")
    
    return result_ds

def get_norm_twoslope(values, method='symmetric', percentile=95):
    """
    获取最优的colormap归一化设置
    
    参数:
    -----
    values : array
        数据值
    method : str
        'symmetric' - 对称范围，适合趋势数据
        'percentile' - 基于百分位数，适合有异常值的数据
        'quantile' - 基于分位数，更稳健
        'adaptive' - 自适应方法
    percentile : float
        百分位数阈值（用于 percentile 方法）
    
    返回:
    -----
    norm : TwoSlopeNorm
        归一化对象
    """
    valid_values = values[~np.isnan(values)]
    
    if method == 'symmetric':
        # 方法1: 对称范围（推荐用于趋势）
        vmax = max(abs(np.nanmin(values)), abs(np.nanmax(values)))
        norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)
        
    elif method == 'percentile':
        # 方法2: 基于百分位数（去除异常值影响）
        lower = np.nanpercentile(valid_values, 100-percentile)
        upper = np.nanpercentile(valid_values, percentile)
        vmax = max(abs(lower), abs(upper))
        norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)
        
    elif method == 'quantile':
        # 方法3: 基于四分位数（更稳健）
        q1 = np.nanpercentile(valid_values, 25)
        q3 = np.nanpercentile(valid_values, 75)
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        vmax = max(abs(lower), abs(upper))
        norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)
        
    elif method == 'adaptive':
        # 方法4: 自适应方法（考虑数据分布）
        mean_abs = np.nanmean(np.abs(valid_values))
        std_abs = np.nanstd(np.abs(valid_values))
        vmax = mean_abs + 2 * std_abs  # 包含95%的数据
        norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)
        
    elif method == 'manual':
        # 方法5: 手动设置（针对特定数据范围）
        # 例如：趋势通常在 ±0.05 m/s/year 范围内
        vmax = 0.05
        norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)
    
    else:
        raise ValueError(f"Unknown method: {method}")
    
    print(f"Norm 设置 ({method}):")
    print(f"  vmin: {-vmax:.4f}")
    print(f"  vcenter: 0")
    print(f"  vmax: {vmax:.4f}")
    
    return norm


def compare_trends(trend_yearly, trend_monthly, save_path=None):
    """
    对比年平均和月平均的趋势结果
    """
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    
    # 1. 趋势值对比散点图
    ax1 = axes[0, 0]
    valid = (~np.isnan(trend_yearly.trend.values)) & (~np.isnan(trend_monthly.trend.values))
    ax1.scatter(trend_yearly.trend.values[valid], 
               trend_monthly.trend.values[valid],
               alpha=0.5, s=30, c='steelblue')
    
    # 添加1:1线
    lim = max(abs(trend_yearly.trend.values[valid]).max(), 
             abs(trend_monthly.trend.values[valid]).max())
    ax1.plot([-lim, lim], [-lim, lim], 'r--', linewidth=2, label='1:1 line')
    
    # 计算相关系数
    from scipy.stats import pearsonr
    corr, p_val = pearsonr(trend_yearly.trend.values[valid], 
                          trend_monthly.trend.values[valid])
    
    ax1.set_xlabel('Yearly Trend (m/s/year)', fontweight='bold')
    ax1.set_ylabel('Monthly Trend (m/s/year)', fontweight='bold')
    ax1.set_title(f'Trend Comparison\nCorrelation: {corr:.3f} (p={p_val:.2e})', 
                 fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend()
    
    # 2. 显著性对比
    ax2 = axes[0, 1]
    categories = ['Sig. Increase\n(Yearly)', 'Sig. Increase\n(Monthly)',
                 'Sig. Decrease\n(Yearly)', 'Sig. Decrease\n(Monthly)',
                 'Not Sig.\n(Yearly)', 'Not Sig.\n(Monthly)']
    
    yearly_sig_inc = ((trend_yearly.p_value < 0.05) & (trend_yearly.trend > 0)).sum().values
    monthly_sig_inc = ((trend_monthly.p_value < 0.05) & (trend_monthly.trend > 0)).sum().values
    yearly_sig_dec = ((trend_yearly.p_value < 0.05) & (trend_yearly.trend < 0)).sum().values
    monthly_sig_dec = ((trend_monthly.p_value < 0.05) & (trend_monthly.trend < 0)).sum().values
    yearly_not_sig = (trend_yearly.p_value >= 0.05).sum().values
    monthly_not_sig = (trend_monthly.p_value >= 0.05).sum().values
    
    counts = [yearly_sig_inc, monthly_sig_inc, 
             yearly_sig_dec, monthly_sig_dec,
             yearly_not_sig, monthly_not_sig]
    
    colors = ['#FF6B6B', '#FF8E8E', '#4ECDC4', '#6FD9D0', '#FFD93D', '#FFE066']
    bars = ax2.bar(range(len(categories)), counts, color=colors, alpha=0.8, edgecolor='black')
    
    ax2.set_xticks(range(len(categories)))
    ax2.set_xticklabels(categories, rotation=0, ha='center', fontsize=10)
    ax2.set_ylabel('Number of Stations', fontweight='bold')
    ax2.set_title('Significance Comparison', fontweight='bold')
    ax2.grid(True, alpha=0.3, axis='y')
    
    # 添加数值标签
    for bar in bars:
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                f'{int(height)}',
                ha='center', va='bottom', fontweight='bold')
    
    # 3. 趋势分布直方图对比
    ax3 = axes[1, 0]
    ax3.hist(trend_yearly.trend.values[~np.isnan(trend_yearly.trend.values)],
            bins=50, alpha=0.5, label='Yearly', color='steelblue', edgecolor='black')
    ax3.hist(trend_monthly.trend.values[~np.isnan(trend_monthly.trend.values)],
            bins=50, alpha=0.5, label='Monthly', color='coral', edgecolor='black')
    
    ax3.set_xlabel('Trend (m/s/year)', fontweight='bold')
    ax3.set_ylabel('Frequency', fontweight='bold')
    ax3.set_title('Trend Distribution Comparison', fontweight='bold')
    ax3.legend()
    ax3.grid(True, alpha=0.3, axis='y')
    
    # 4. 统计摘要表格
    ax4 = axes[1, 1]
    ax4.axis('off')
    
    stats_data = [
        ['Metric', 'Yearly', 'Monthly'],
        ['Mean Trend', f'{np.nanmean(trend_yearly.trend.values):.4f}', 
         f'{np.nanmean(trend_monthly.trend.values):.4f}'],
        ['Median Trend', f'{np.nanmedian(trend_yearly.trend.values):.4f}', 
         f'{np.nanmedian(trend_monthly.trend.values):.4f}'],
        ['Std Dev', f'{np.nanstd(trend_yearly.trend.values):.4f}', 
         f'{np.nanstd(trend_monthly.trend.values):.4f}'],
        ['Sig. Increase', f'{yearly_sig_inc}', f'{monthly_sig_inc}'],
        ['Sig. Decrease', f'{yearly_sig_dec}', f'{monthly_sig_dec}'],
        ['Not Significant', f'{yearly_not_sig}', f'{monthly_not_sig}'],
        ['Correlation', f'{corr:.3f}', f'p={p_val:.2e}']
    ]
    
    table = ax4.table(cellText=stats_data, cellLoc='center', loc='center',
                     colWidths=[0.4, 0.3, 0.3])
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 2)
    
    # 设置表头样式
    for i in range(3):
        table[(0, i)].set_facecolor('#4ECDC4')
        table[(0, i)].set_text_props(weight='bold', color='white')
    
    # 设置交替行颜色
    for i in range(1, len(stats_data)):
        for j in range(3):
            if i % 2 == 0:
                table[(i, j)].set_facecolor('#F0F0F0')
    
    ax4.set_title('Statistical Summary', fontweight='bold', pad=20, fontsize=14)
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"对比图已保存至: {save_path}")
    
    return fig, axes

#todo 写成class类，包含中国底图函数、子图函数、散点图函数、显著/非显著散点函数、趋势计算函数、色标调制函数（根据describe信息）
def plot_trend_spatial(trend_ds, var='trend', significance_level=0.05,
                       save_path=None, title=None, figsize=(13, 11),
                       cb_levels=None, colors=None,alpha=0.9,
                       norm_method='percentile',
                       vmin=None, vmax=None,
                       txt_fz=20, cbar_pad=0.04, cbar_shrink=0.5,
                       add_south_china_sea=True,
                       south_sea_anchor='axes',
                       south_sea_box=[0.85, -0.01, 0.15, 0.3],#axes方法
                    south_sea_pos=[0.682, 0.137, 0.12, 0.4]) :# figure坐标方法: 
    """
    绘制趋势空间分布图（改进版）
    ---------
    norm_method : str
        归一化方法: 'symmetric', 'percentile', 'quantile', 'adaptive', 'manual'
    vmin, vmax : float or None
        手动设置colormap范围，如果提供则忽略 norm_method
    """
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    import matplotlib.colors as mcolors
    from matplotlib.colors import TwoSlopeNorm, BoundaryNorm
    from matplotlib.lines import Line2D
    fig, ax = plt.subplots(figsize=figsize, subplot_kw={'projection': ccrs.PlateCarree()})

    # 获取数据
    lons = trend_ds.longitude.values
    lats = trend_ds.latitude.values
    values = trend_ds[var].values
    p_values = trend_ds.p_value.values

    ax.set_extent([lons.min()-2, lons.max()+2, lats.min()-1, lats.max()+1], crs=ccrs.PlateCarree())

    # 区分显著和不显著
    significant = p_values < significance_level

    # 设置 cmap / norm
    if cb_levels is not None and colors is not None:
        print("使用离散色标 (BoundaryNorm)")
        cmap = mcolors.ListedColormap(colors)
        norm = BoundaryNorm(cb_levels, ncolors=len(colors), clip=True)
    else:
        print('使用连续色标')
        cmap = 'RdBu_r'
        if vmin is not None and vmax is not None:
            norm = TwoSlopeNorm(vmin=vmin, vcenter=0, vmax=vmax)
            print(f"使用手动设置: vmin={vmin}, vmax={vmax}")
        else:
            norm = get_norm_twoslope(values, method=norm_method)

    # --- 提取成统一散点绘制函数：主图/子图共用 ---
    def _scatter_points(target_ax, mask=None, s_nosig=30, s_sig=30, lw=0.5,
                        edgecolor='None',alpha=alpha):
        """
        mask: None 表示全量；否则为布尔数组，True 的点会被绘制
        返回： (sc_not_sig, sc_sig)
        """
        if mask is None:
            mask = np.ones_like(values, dtype=bool)

        # 同时过滤 NaN，避免无意义点
        valid = mask & (~np.isnan(values)) & (~np.isnan(lons)) & (~np.isnan(lats)) & (~np.isnan(p_values))
        sig_m = valid & significant
        nosig_m = valid & (~significant)

        sc1 = target_ax.scatter(
            lons[nosig_m], lats[nosig_m],
            c=values[nosig_m], cmap=cmap, norm=norm,
            s=s_nosig, alpha=alpha, marker='o',
            linewidths=lw, edgecolors=edgecolor,
            transform=ccrs.PlateCarree(),
            label='Not significant'
        )
        sc2 = target_ax.scatter(
            lons[sig_m], lats[sig_m],
            c=values[sig_m], cmap=cmap, norm=norm,
            s=s_sig, alpha=alpha, marker='^',
            linewidths=lw, edgecolors=edgecolor,
            transform=ccrs.PlateCarree(),
            label=f'Significant (p<{significance_level})'
        )
        return sc1, sc2



    # 添加地图要素
    shp_path = r'../data/中国_省.geojson'
    gdf = gpd.read_file(shp_path)
    gdf.plot(ax=ax, transform=ccrs.PlateCarree(), edgecolor='grey', facecolor='none', linewidth=0.8)
    
    # 主图散点（全域）
    scatter1, scatter2 = _scatter_points(ax, mask=None,)
    
    # 网格
    gl = ax.gridlines(draw_labels=True, linewidth=0.5, alpha=0.5, linestyle='--')
    gl.top_labels = False
    gl.right_labels = False

    # colorbar（保持用 scatter2）
    cbar = plt.colorbar(scatter2, ax=ax, orientation='vertical',
                        pad=cbar_pad, shrink=cbar_shrink, extend='both')
    if var == 'trend':
        cbar.set_label(r'Wind Speed Trend (m s$^{-1}$ dec$^{-1}$)', fontweight='bold')
    elif var == 'total_change':
        cbar.set_label('Total Change (m/s)', fontweight='bold')
    elif var == 'pct_change':
        cbar.set_label('Percentage Change (%)', fontweight='bold')

    if title:
        ax.set_title(title, fontweight='bold', pad=20)

    legend_handles = [
        Line2D([0], [0], marker='o', linestyle='None',
           markerfacecolor='none', markeredgecolor='black', markeredgewidth=1.2,
           markersize=11, label='Not significant'),
        Line2D([0], [0], marker='^', linestyle='None',
           markerfacecolor='none', markeredgecolor='black', markeredgewidth=1.2,
           markersize=11, label=f'Significant (p<{significance_level})')
            ]
    ax.legend(handles=legend_handles, loc='lower left', framealpha=0.9, frameon=False)

    # 统计文字
    sig_count = significant.sum()
    total_count = (~np.isnan(values)).sum()
    stats_text = (
        f'Significant: {sig_count}/{total_count} ({sig_count/total_count*100:.1f}%)  '
        f'Sig increase: {((p_values < significance_level) & (values > 0)).sum()}/{(values>0).sum()}\n'
        f'Mean trend: {np.nanmean(values):.3f} m/s /10a      '
        f'Sig decrease: {((p_values < significance_level) & (values < 0)).sum()}/{(values<0).sum()}'
    )
    ax.text(0.02, 0.98, stats_text, transform=ax.transAxes,
            verticalalignment='top', fontsize=txt_fz)

    plt.tight_layout()

    # 南海子图（与主图完全同逻辑：同 cmap/norm、同显著性 marker）
    if add_south_china_sea:
        if south_sea_anchor == 'axes':
            sub_ax = ax.inset_axes(south_sea_box, transform=ax.transAxes, projection=ccrs.PlateCarree())
        else:
            sub_ax = fig.add_axes(south_sea_pos, projection=ccrs.PlateCarree())

        sub_ax.set_extent([105, 125, 2, 25], crs=ccrs.PlateCarree())
        gdf.plot(ax=sub_ax, transform=ccrs.PlateCarree(), edgecolor='grey', facecolor='none', linewidth=1.5)

        south_china_sea_mask = (
            (lons >= 105) & (lons <= 125) &
            (lats >= 2) & (lats <= 25)
        )

        # 子图散点（只画 mask 区域，样式完全一致，但点更小一点）
        _scatter_points(sub_ax, mask=south_china_sea_mask, s_nosig=18, s_sig=22, lw=0.35)

        sub_ax.add_feature(cfeature.BORDERS, linewidth=0.5)
        sub_ax.gridlines(draw_labels=False, linewidth=0.3, alpha=0.5, linestyle='--')
        sub_ax.spines['geo'].set_edgecolor('black')
        sub_ax.spines['geo'].set_linewidth(0.6)

    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"图形已保存至: {save_path}")

    return fig, ax 
def plot_seasonal_pdf(ds_spring, ds_summer, ds_autumn, ds_winter, 
                      save_path=None, title=None,xlabel='Wind Speed (m/s)',
                      figsize=(12, 8)):
    """
    绘制四个季节的风速概率密度函数
    
    参数:
    -----
    ds_spring, ds_summer, ds_autumn, ds_winter : xarray.DataArray
        四个季节的风速数据
    save_path : str or None
        保存路径
    figsize : tuple
        图形大小
    """
    # 提取有效数据
    spring_data = ds_spring.values[~np.isnan(ds_spring.values)]
    summer_data = ds_summer.values[~np.isnan(ds_summer.values)]
    autumn_data = ds_autumn.values[~np.isnan(ds_autumn.values)]
    winter_data = ds_winter.values[~np.isnan(ds_winter.values)]
    
    # 创建图形
    fig, ax = plt.subplots(figsize=figsize)
    
    # 定义季节颜色和标签
    # seasons = {
    #     'Spring': (spring_data, '#00C957', '2005-2009'),#'Spring (Mar-May)'),
    #     'Summer': (summer_data, '#FF6B6B', '2010-2014'),#'Summer (Jun-Aug)'),
    #     'Autumn': (autumn_data, '#F18900', '2015-2019'),#'Autumn (Sep-Nov)'),
    #     'Winter': (winter_data, '#4ECDC4', '2020-2024')#'Winter (Dec-Feb)')
    # }
    seasons = {
        'Spring': (spring_data, '#00C957', 'Spring (Mar-May)'),
        'Summer': (summer_data, '#FF6B6B', 'Summer (Jun-Aug)'),
        'Autumn': (autumn_data, '#F18900', 'Autumn (Sep-Nov)'),
        'Winter': (winter_data, '#4ECDC4', 'Winter (Dec-Feb)')
    }
    # 绘制每个季节的PDF
    for season_name, (data, color, label) in seasons.items():
        # 使用KDE绘制概率密度
        kde = stats.gaussian_kde(data)
        x_range = np.linspace(data.min(), data.max(), 200)
        density = kde(x_range)
        
        ax.plot(x_range, density, label=label, color=color, linewidth=2.5, alpha=0.8)
        ax.fill_between(x_range, density, alpha=0.2, color=color)
        
        # 打印统计信息
        print(f"{season_name}:")
        print(f"  Mean: {data.mean():.2f} m/s")
        print(f"  Std: {data.std():.2f} m/s")
        print(f"  Median: {np.median(data):.2f} m/s")
        print(f"  Min: {data.min():.2f} m/s")
        print(f"  Max: {data.max():.2f} m/s\n")
    
    # 设置图形属性
    # 设置图形全局属性
    
    ax.set_xlabel(xlabel, fontweight='bold')
    ax.set_ylabel('Probability Density', fontweight='bold')
    if title:
        ax.set_title(title,  fontweight='bold', pad=20)
    ax.legend(loc='upper right', framealpha=0.9)
    ax.grid(True, alpha=0.3, linestyle='--')
    # ax.tick_params(labelsize=12)
    
    # 设置背景
    ax.set_facecolor('#F8F9FA')
    fig.patch.set_facecolor('white')
    
    plt.tight_layout()
    
    # 保存图形
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"图形已保存至: {save_path}")
    
    return fig, ax

def plot_seasonal_boxplot(ds_spring, ds_summer, ds_autumn, ds_winter,
                          save_path=None, title=None, ylabel='Wind Speed (m/s)',
                          figsize=(10, 8), ylim=None, showfliers=True):
    """
    绘制四个季节的风速箱线图
    
    参数:
    -----
    ylim : tuple or None
        y轴范围，例如 (0, 6) 限制显示范围
    showfliers : bool
        是否显示异常值点，False 可以隐藏异常值
    """
    # 准备数据
    data_list = []
    labels = []
    
    for season_name, ds_season in [('Spring', ds_spring), ('Summer', ds_summer), 
                                    ('Autumn', ds_autumn), ('Winter', ds_winter)]:
        season_data = ds_season.values[~np.isnan(ds_season.values)]
        data_list.append(season_data)
        labels.append(season_name)
    
    # 创建图形
    fig, ax = plt.subplots(figsize=figsize)
    
    # 绘制箱线图
    bp = ax.boxplot(data_list, labels=labels, patch_artist=True,
                    boxprops=dict(facecolor='lightblue', alpha=0.7),
                    medianprops=dict(color='red', linewidth=2),
                    whiskerprops=dict(linewidth=1.5),
                    capprops=dict(linewidth=1.5),
                    showfliers=showfliers)  # 控制是否显示异常值
    
    # 设置颜色
    colors = ['#00C957', '#FF6B6B', '#F18900', '#4ECDC4']
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)
    
    ax.set_ylabel(ylabel, fontweight='bold')
    if title:
        ax.set_title(title, fontweight='bold', pad=20)
    ax.grid(True, alpha=0.3, axis='y', linestyle='--')
    
    # 设置y轴范围
    if ylim is not None:
        ax.set_ylim(ylim)
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"箱线图已保存至: {save_path}")
    
    return fig, ax

def describe(da:xr.DataArray, pcts:list=[10,25,50,75,80,90,95]):
    """将输入展平，返回pandas描述统计；百分位参数以0至100数值传入，NaN由pandas忽略。"""
    # np.ravel 配合 np.asarray 可以将 xarray, pd.Series, pd.DataFrame, list 或 2D 列向量/行向量全部展平为 1D
    arr = np.ravel(np.asarray(da))
    s = pd.Series(arr)
    # pandas 的 percentiles 接收一维列表或数组
    desc = s.describe(percentiles=np.array(pcts)/100)
    return desc
