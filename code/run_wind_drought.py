"""功能：唯一正式入口，组织逐小时风速到CF及站点LPW，也可运行旧日尺度分析。
输入：config.py及原始NetCDF；输出：分次运行的NetCDF、CSV、检查与配置JSON。
流程：校验/原质量检查、分块外推与CF、按模式调用小时LPW或日尺度识别。
注意：小时LPW使用固定阈值与互斥时长等级；旧日模式保持原规则，质量检查仍可单独运行。
"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import argparse
import sys
import pandas as pd
import xarray as xr

import config
from quality_control.data_quality import QualityConfig, run_quality_check
from wind_droughts.data_io import (read_wind, inspect_data, hourly_blocks, create_hourly_file,
    append_hourly, save_json, save_tables, resolve_capacity, configure_netcdf_cache)
from wind_droughts.wind_profile import extrapolate_wind
from wind_droughts.power_curve import wind_to_cf
from wind_droughts.spatial import regional_mean, daily_and_rolling
from wind_droughts.thresholds import build_thresholds, exclusive_daily_labels
from wind_droughts.events import identify_events
from wind_droughts.statistics import summarize_events
from wind_droughts.lpw_analysis import run_hourly_lpw, replot_hourly_lpw


def run_legacy_quality():
    """保留原阶段0质量检查功能与输出路径；严重时间轴问题时返回2。"""
    root = Path(__file__).resolve().parent
    data_path = (root / config.DATA_PATH).resolve()
    output_dir = (root / config.OUTPUT_DIR).resolve()
    with xr.open_dataset(data_path, engine="netcdf4") as ds:
        report = run_quality_check(
            ds, output_dir, variable=config.WIND_VARIABLE,
            selection=config.WIND_SELECTOR, time_dim=config.TIME_DIM,
            station_dim=config.STATION_DIM, study_start=config.STUDY_START,
            study_end=config.STUDY_END,
            config=QualityConfig(config.MIN_STATION_VALID_RATE,
                                 config.MIN_DAILY_VALID_HOURS,
                                 config.MIN_ANNUAL_VALID_RATE,
                                 config.ANOMALOUS_HIGH_WIND_SPEED,
                                 config.STATION_CHUNK_SIZE))
    s = report["summary"]
    print(f"质量报告已输出至: {output_dir}")
    print(f"位置数: {len(s)}; 研究期预期小时数: {report['expected_hours']}")
    print(f"站点最低有效率不达标: {(~s['meets_min_station_rate']).sum()}")
    print(f"缺测段总数: {len(report['missing_runs'])}")
    if report["time_issues"]:
        print("正式计算已停止：存在严重时间轴问题。")
        for issue in report["time_issues"]:
            print(f"- {issue}")
        return 2
    print("阶段0质量检查完成。")
    return 0


def main(argv=None):
    """解析命令行并依次调度计算模块；每次新建结果目录，避免覆盖已有结果。"""
    parser = argparse.ArgumentParser(description="逐小时风速→CF→风旱事件分析")
    parser.add_argument("--quality-only", action="store_true", help="仅运行原阶段0质量检查")
    parser.add_argument("--quality-html", action="store_true", help="从已有质量CSV生成HTML报告")
    parser.add_argument("--inspect-only", action="store_true", help="仅扫描结构和数据质量")
    parser.add_argument("--skip-quality", action="store_true", help="跳过原质量CSV重算，仍执行新读取层校验")
    parser.add_argument("--analysis-mode", choices=["hourly_lpw", "daily"], default=None,
                        help="覆盖config.ANALYSIS_MODE；daily保留旧日尺度分析")
    parser.add_argument("--hourly-cf", type=Path, help="复用明确指定的站点小时CF文件，校验机型与高度后识别LPW")
    parser.add_argument("--skip-maps", action="store_true", help="只计算小时LPW统计，跳过地图")
    parser.add_argument("--plot-lpw-run", type=Path, help="从已有LPW结果目录重绘地图，不重新识别事件")
    args = parser.parse_args(argv)
    if args.quality_html:
        from quality_control.generate_quality_html import main as generate_quality_html
        generate_quality_html()
        return 0
    if args.quality_only:
        return run_legacy_quality()
    if args.plot_lpw_run:
        if args.hourly_cf or args.inspect_only or args.skip_maps:
            parser.error("--plot-lpw-run不能与--hourly-cf、--inspect-only、--skip-maps同时使用")
        replot_hourly_lpw(args.plot_lpw_run, config)
        return 0
    mode = args.analysis_mode or config.ANALYSIS_MODE
    if mode not in {"daily", "hourly_lpw"}:
        raise ValueError("ANALYSIS_MODE只支持hourly_lpw或daily")
    if args.hourly_cf and (mode != "hourly_lpw" or args.inspect_only):
        parser.error("--hourly-cf仅适用于hourly_lpw分析，不能与--inspect-only同时使用")
    root = Path(__file__).resolve().parent
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("run_%Y%m%d_%H%M%S_%f")
    base_dir = config.LPW_OUTPUT_DIR if mode == "hourly_lpw" else config.ANALYSIS_OUTPUT_DIR
    out = (root / base_dir / stamp).resolve()
    out.mkdir(parents=True)
    nc_dir, csv_dir = out / "netcdf", out / "tables"
    nc_dir.mkdir()
    csv_dir.mkdir()
    settings = {k: v for k, v in vars(config).items() if k.isupper()}
    save_json(out / "configuration.json", settings)
    if args.hourly_cf:
        run_hourly_lpw(args.hourly_cf, out, config, plot_maps=config.LPW_PLOT_MAPS and not args.skip_maps)
        return 0
    capacity = None
    if mode == "daily":
        if config.EVENT_INPUT not in ("daily", "rolling7"):
            raise ValueError("EVENT_INPUT只支持daily或rolling7")
        if config.EVENT_INPUT == "rolling7" and not config.COMPUTE_ROLLING_7D:
            raise ValueError("rolling7识别需开启七日滚动计算")
        capacity = resolve_capacity(config.INSTALLED_CAPACITY_KW, config.RATED_POWER_KW, config.TURBINE_COUNT)
        if capacity is not None and config.EVENT_INPUT != "daily":
            raise ValueError("电量仅支持日CF分析；七日滚动含重叠窗口")
    configure_netcdf_cache(config.NETCDF_CHUNK_CACHE_MB)
    with xr.open_dataset((root / config.DATA_PATH).resolve(), engine="netcdf4") as ds:
        wind = read_wind(ds, config.WIND_VARIABLE, config.WIND_SELECTOR, config.COORDINATE_MAP,
                         config.WIND_UNITS, config.STUDY_START, config.STUDY_END)
        report = inspect_data(ds, wind, config.HOURLY_BLOCK_HOURS, config.ANOMALOUS_HIGH_WIND_SPEED)
        save_json(out / "data_inspection.json", report)
        print(f"已检查：{dict(wind.sizes)}；{report['time_start']} 至 {report['time_end']}；单位来源={report['units_source']}", flush=True)
        if args.inspect_only:
            print(f"检查结果：{out}", flush=True)
            return 0
        if config.RUN_LEGACY_QUALITY and not args.skip_quality:
            status = run_legacy_quality()
            if status:
                return status
        metadata = dict(event_input="station_hourly_cf" if mode == "hourly_lpw" else config.EVENT_INPUT,
            source_height_m=config.SOURCE_HEIGHT_M,
            hub_height_m=config.HUB_HEIGHT_M, shear_alpha=config.SHEAR_ALPHA,
            wind_units_source=report['units_source'], exclude_cut_out_from_analysis=int(config.EXCLUDE_CUT_OUT),
            spatial_weight="cos(latitude); station sampling weights, not installed capacity weights",
            assumptions="source wind units and measurement height from config when absent in source; generic turbine",
            configuration_json="../configuration.json")
        handle = create_hourly_file(nc_dir / "hourly_cf.nc", wind, metadata, config.HOURLY_BLOCK_HOURS)
        regional = []
        try:
            for offset, block in hourly_blocks(wind, config.HOURLY_BLOCK_HOURS, config.STUDY_START, config.STUDY_END):
                hub = extrapolate_wind(block, config.SOURCE_HEIGHT_M, config.HUB_HEIGHT_M,
                                       config.SHEAR_ALPHA, config.PROFILE_METHOD)
                products = wind_to_cf(hub, config.CUT_IN_MS, config.RATED_SPEED_MS,
                                      config.CUT_OUT_MS, config.RATED_POWER_KW, config.DISCRETE_POWER_CURVE)
                append_hourly(handle, products, offset)
                analysis_cf = products.cf.where(products.cause != 2) if config.EXCLUDE_CUT_OUT else products.cf
                regional.append(xr.Dataset({"regional_cf": regional_mean(analysis_cf),
                    "regional_cf_including_cut_out": regional_mean(products.cf),
                    "cut_out_weight_fraction": regional_mean((products.cause == 2).astype(float).where(products.cause != -1))}))
                if offset % 22320 == 0:
                    print(f"CF分块处理：{block.time.values[-1]}", flush=True)
        finally:
            handle.close()
    hourly = xr.concat(regional, dim="time")
    hourly.attrs.update(metadata)
    hourly.to_netcdf(nc_dir / "regional_hourly_cf.nc", engine="netcdf4")
    daily = daily_and_rolling(hourly.regional_cf, config.MIN_DAILY_VALID_HOURS, config.COMPUTE_ROLLING_7D)
    daily.attrs.update(metadata)
    daily.attrs['min_daily_valid_hours'] = config.MIN_DAILY_VALID_HOURS
    daily.to_netcdf(nc_dir / "daily_cf.nc", engine="netcdf4")
    if mode == "hourly_lpw":
        run_hourly_lpw(nc_dir / "hourly_cf.nc", out, config, plot_maps=config.LPW_PLOT_MAPS and not args.skip_maps)
        return 0
    series = daily.daily_cf if config.EVENT_INPUT == "daily" else daily.rolling7_cf
    limits = build_thresholds(series, config.THRESHOLD_TYPE, config.PERCENTILE_LEVELS,
        config.PERCENTILE_MODE, config.FIXED_CF_THRESHOLD, config.BASELINE_START, config.BASELINE_END)
    limits.attrs.update(metadata)
    if all(key in limits for key in ("P20", "P10", "P5")):
        limits["exclusive_daily_band"] = exclusive_daily_labels(series, limits)
    limits.to_netcdf(nc_dir / "thresholds.nc", engine="netcdf4")
    summaries, periods, all_events, selected_events = [], [], [], []
    for level in (config.PERCENTILE_LEVELS if config.THRESHOLD_TYPE == "percentile" else ["fixed"]):
        events = identify_events(series, limits[level], level, config.THRESHOLD_TYPE,
            config.MERGE_RECOVERY_DAYS, daily.valid_hours if config.EVENT_INPUT == "daily" else None, capacity)
        selected, summary, period = summarize_events(series, limits[level], events, level, config.MIN_EVENT_LOW_DAYS)
        save_tables(csv_dir, {f"events_all_{level}": events, f"events_selected_{level}": selected})
        summaries.append(summary)
        periods.append(period)
        all_events.append(events)
        selected_events.append(selected)
        print(f"{level}：全部事件{len(events)}，筛选事件{len(selected)}，低CF日数{summary.iloc[0].low_cf_days}", flush=True)
    period = pd.concat(periods, ignore_index=True)
    save_tables(csv_dir, {"scenario_summary": pd.concat(summaries, ignore_index=True),
        "events_all": pd.concat(all_events, ignore_index=True), "events_selected": pd.concat(selected_events, ignore_index=True),
        "annual_statistics": period.loc[period.grouping == "year"],
        "monthly_statistics": period.loc[period.grouping == "month"],
        "seasonal_statistics": period.loc[period.grouping == "season"]})
    print(f"分析完成：{out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
