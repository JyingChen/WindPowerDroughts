"""功能：唯一正式入口，组织逐小时风速到CF再到独立阈值情景事件的流程。
输入：config.py及原始NetCDF；输出：分次运行的NetCDF、CSV、检查与配置JSON。
流程：校验/原质量检查、分块外推与CF、聚合、阈值、识别、统计。
注意：不插值、不按持续时间分级；默认机型为假设，质量检查可单独运行。
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
    args = parser.parse_args(argv)
    if args.quality_html:
        from quality_control.generate_quality_html import main as generate_quality_html
        generate_quality_html()
        return 0
    if args.quality_only:
        return run_legacy_quality()
    root = Path(__file__).resolve().parent
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("run_%Y%m%d_%H%M%S_%f")
    out = (root / config.ANALYSIS_OUTPUT_DIR / stamp).resolve()
    out.mkdir(parents=True)
    nc_dir, csv_dir = out / "netcdf", out / "tables"
    nc_dir.mkdir()
    csv_dir.mkdir()
    settings = {k: v for k, v in vars(config).items() if k.isupper()}
    save_json(out / "configuration.json", settings)
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
        metadata = dict(event_input=config.EVENT_INPUT, source_height_m=config.SOURCE_HEIGHT_M,
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
    series = daily.daily_cf if config.EVENT_INPUT == "daily" else daily.rolling7_cf
    limits = build_thresholds(series, config.THRESHOLD_TYPE, config.PERCENTILE_LEVELS,
        config.PERCENTILE_MODE, config.FIXED_CF_THRESHOLD, config.BASELINE_START, config.BASELINE_END)
    daily.attrs.update(metadata)
    daily.attrs['min_daily_valid_hours'] = config.MIN_DAILY_VALID_HOURS
    daily.to_netcdf(nc_dir / "daily_cf.nc", engine="netcdf4")
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
