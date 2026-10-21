"""功能：保留阶段0质量检查回归测试。
输入：人工小时序列；输出：pytest断言结果。
流程：测试闰日、缺小时、NaN和重复时间；注意：0m/s是有效观测，不是缺测。
"""
import numpy as np
import pandas as pd
import xarray as xr

from quality_control.data_quality import QualityConfig, run_quality_check


def make_ds(times, values):
    """构造含一个站点和ws辅助维的人工风速Dataset。"""
    return xr.Dataset({"wind": (("time", "station", "var"), np.asarray(values, dtype=float)[:, None, None])},
                      coords={"time": times, "station": [1], "station_id": ("station", ["S1"]),
                              "latitude": ("station", [30.]), "longitude": ("station", [120.]), "var": ["ws"]})


def test_leap_year_and_missing_sources(tmp_path):
    """闰日缺小时和NaN可分别统计，并合为同一个连续缺测段。"""
    times = pd.date_range("2020-02-28 23:00", periods=5, freq="h").delete(2)
    ds = make_ds(times, [1, 2, np.nan, 4])
    r = run_quality_check(ds, tmp_path, selection={"var": "ws"}, study_start="2020-02-28 23:00", study_end="2020-02-29 03:00")
    assert r["expected_hours"] == 5
    assert r["summary"].iloc[0].raw_missing_timestamp_hours == 1
    assert r["summary"].iloc[0].nan_hours == 1
    assert len(r["missing_runs"]) == 1
    assert r["missing_runs"].iloc[0].hours == 2


def test_zero_is_valid_and_duplicate_is_reported(tmp_path):
    """重复时间必须报告，不能静默修复后算作有效小时。"""
    times = pd.to_datetime(["2021-01-01 00:00", "2021-01-01 00:00", "2021-01-01 01:00"])
    r = run_quality_check(make_ds(times, [0, 2, 3]), tmp_path)
    assert r["summary"].iloc[0].valid_hours == 0
    assert r["time_issues"]


def test_moved_html_report_resolves_config_paths(tmp_path, monkeypatch):
    """报告模块迁移后仍按config所在目录解析路径，且不依赖启动目录。"""
    import config
    from quality_control.generate_quality_html import main as generate_html

    source_dir = tmp_path / "code"
    data_dir = tmp_path / "data"
    source_dir.mkdir()
    data_dir.mkdir()
    ds = make_ds(pd.date_range("2020-01-01", periods=3, freq="h"), [0., 2., 3.])
    ds.to_netcdf(data_dir / "wind.nc", engine="netcdf4")
    run_quality_check(ds, tmp_path / "quality", selection={"var": "ws"})
    monkeypatch.setattr(config, "__file__", str(source_dir / "config.py"))
    monkeypatch.setattr(config, "DATA_PATH", "../data/wind.nc")
    monkeypatch.setattr(config, "OUTPUT_DIR", "../quality")
    monkeypatch.chdir(data_dir)
    generate_html()
    html = (tmp_path / "quality" / "wind_data_quality_report.html").read_text(encoding="utf-8")
    assert "风速数据质量检查可视化报告" in html
    assert (tmp_path / "quality" / "abnormal_runs.csv").exists()


def test_html_report_available_from_single_entry(monkeypatch):
    """唯一主入口的HTML选项调用保留的报告功能，不启动CF全量计算。"""
    import run_wind_drought
    from quality_control import generate_quality_html

    calls = []
    monkeypatch.setattr(generate_quality_html, "main", lambda: calls.append("html"))
    assert run_wind_drought.main(["--quality-html"]) == 0
    assert calls == ["html"]
