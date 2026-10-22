"""功能：复用utils.plot_scat_map绘制站点LPW分级频次离散色标地图。
输入：站点频次表、边界文件和绘图参数；输出：各阈值各等级PNG及色标说明。
流程：为同等级三个阈值选择共同分级、构造带经纬度DataArray、调用共用绘图工具。
注意：累计次数与有效年频次可选，默认累计次数；有效数据为零次数时也绘制，缺测不当作零。
"""
from pathlib import Path
import numpy as np
import xarray as xr


def frequency_map_levels(values, fixed=None, integer=True):
    """生成覆盖全部数据的递增离散边界；固定边界不足以覆盖数据时明确报错。"""
    from matplotlib.ticker import MaxNLocator
    values = np.asarray(values, dtype=float)
    finite = values[np.isfinite(values)]
    if not finite.size or (finite < 0).any():
        raise ValueError("频次色标需要非负有效值")
    if fixed is None:
        levels = MaxNLocator(nbins=6, integer=integer).tick_values(0., max(float(finite.max()), 1.))
        levels = levels[levels >= 0]
    else:
        levels = np.asarray(fixed, dtype=float)
    if (levels.ndim != 1 or len(levels) < 2 or not np.isfinite(levels).all()
            or (np.diff(levels) <= 0).any() or levels[0] > finite.min() or levels[-1] < finite.max()):
        raise ValueError("离散色标边界须递增且覆盖全部频次")
    return levels


def plot_lpw_frequency_maps(frequency, output_dir, *, boundary_path, labels, lower_bounds,
                            metric="event_count", fixed_levels=None, cmap="turbo", colors=None,
                            zero_color="#d9d9d9", extent=None,
                            figsize=(10, 8), dpi=180, add_south_china_sea=True, period=""):
    """绘制分级频次；边界可按等级配置，0次可独立用灰色，同等级跨阈值保持同色同界。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import is_color_like, to_hex
    from utils import plot_scat_map
    if metric not in {"event_count", "events_per_valid_year"}:
        raise ValueError("地图指标只能为event_count或events_per_valid_year")
    if not Path(boundary_path).is_file():
        raise FileNotFoundError(f"缺少本地地图边界文件：{boundary_path}")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    files, scale_info = [], {}
    ranges = {"ALL": f">={lower_bounds[0]} h"}
    for i, label in enumerate(labels):
        ranges[label] = (f"{lower_bounds[i]}-<{lower_bounds[i+1]} h" if i+1 < len(labels) else f">={lower_bounds[i]} h")
    for grade in ("ALL", *labels):
        group = frequency.loc[frequency.lpw_class == grade]
        if not np.isfinite(group[metric]).any():
            continue
        requested = fixed_levels.get(grade) if isinstance(fixed_levels, dict) else fixed_levels
        levels = frequency_map_levels(group[metric], requested, integer=metric == "event_count")
        zero_bin = metric == "event_count" and levels[0] == 0 and levels[1] == 1
        positive_bins = len(levels)-1-int(zero_bin)
        if colors is not None:
            if not len(colors) or any(not is_color_like(c) for c in colors):
                raise ValueError("离散颜色列表含无效颜色")
            palette = np.asarray(colors, dtype=object)
            positive_colors = palette[np.rint(np.linspace(0,len(palette)-1,positive_bins)).astype(int)].tolist()
        else:
            positive_colors = list(plt.get_cmap(cmap)(np.linspace(.08,.92,positive_bins)))
        bin_colors = ([zero_color] if zero_bin else []) + positive_colors
        if not is_color_like(zero_color):
            raise ValueError("0次颜色无效")
        scale_info[grade] = {"metric": metric, "levels": levels.tolist(),
            "colors": [to_hex(c) for c in bin_colors], "zero_bin": bool(zero_bin),
            "intervals": [f"[{levels[i]:g}, {levels[i+1]:g})" for i in range(len(levels)-1)],
            "shared_across_thresholds": True}
        for level, rows in group.groupby("threshold_level", sort=False):
            if not np.isfinite(rows[metric]).any():
                continue
            values = xr.DataArray(rows[metric].to_numpy(dtype=float), dims="station",
                coords={"station": rows.station.values, "latitude": ("station", rows.latitude.values),
                        "longitude": ("station", rows.longitude.values)})
            filename = output_dir / f"frequency_{level}_{grade}_{metric}.png"
            threshold = float(rows.cf_threshold.iloc[0])
            title = f"CF < {threshold:.2f} | {grade} ({ranges[grade]})\n{period}"
            ticks = {float(x): f"{x:g}" for x in levels}
            fig, _ = plot_scat_map(values, levels=levels, colors=bin_colors, extent=extent,
                figsize=figsize, title=title, cbar_label="Events" if metric == "event_count" else "Events / valid year",
                text="Grey: 0 events" if zero_bin else None,
                cbar_tick_labels=ticks, save_path=None, shp_path=boundary_path, dpi=dpi,
                add_south_china_sea=add_south_china_sea, add_country_borders=False)
            # 原工具的南海子图在tight_layout后生成；保存整张fig可保留子图。
            fig.savefig(filename, dpi=dpi, bbox_inches="tight")
            plt.close(fig)
            files.append(str(filename))
    return files, scale_info
