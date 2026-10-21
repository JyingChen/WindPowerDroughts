"""功能：保留原阶段0质量HTML报告生成器。
输入：原始风速NetCDF、质量CSV和config配置；输出：可浏览的HTML质量报告。
流程：读取位置与质量统计、构建表格和图表、写出HTML；注意：不参与CF或事件计算。
"""
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr

import config
from .data_quality import _positions


def _table(df, columns=None, max_rows=30):
    if df is None or df.empty:
        return '<p class="ok">无记录</p>'
    if columns:
        df = df[[c for c in columns if c in df.columns]]
    return df.head(max_rows).to_html(index=False, classes="data", border=0)


def main():
    """读取原有质量结果并生成HTML报告，路径继续采用config.OUTPUT_DIR。"""
    # 配置中的相对路径始终以code目录为基准，不随模块迁移或工作目录改变。
    root = Path(config.__file__).resolve().parent
    out = (root / config.OUTPUT_DIR).resolve(); out.mkdir(parents=True, exist_ok=True)
    with xr.open_dataset((root / config.DATA_PATH).resolve(), engine="netcdf4") as ds:
        da = ds[config.WIND_VARIABLE].sel(config.WIND_SELECTOR).transpose(config.TIME_DIM, config.STATION_DIM)
        times = pd.DatetimeIndex(pd.to_datetime(ds[config.TIME_DIM].values))
        positions = _positions(ds, config.STATION_DIM)

    summary = pd.read_csv(out / "data_quality_summary.csv")
    annual = pd.read_csv(out / "annual_completeness.csv")
    expected = pd.date_range(times.min(), times.max(), freq="h")
    abnormal_rows = []
    for block_start in range(0, len(positions), config.STATION_CHUNK_SIZE):
        block = np.asarray(da.isel({config.STATION_DIM: slice(block_start, block_start + config.STATION_CHUNK_SIZE)}).values, dtype=float)
        for local_k, (pos_id, _, lat, lon) in enumerate(positions[block_start:block_start + config.STATION_CHUNK_SIZE]):
            v = block[:, local_k]
            bad = (~np.isfinite(v)) | (v < 0) | (v > config.ANOMALOUS_HIGH_WIND_SPEED)
            # Runs are based on the raw sequence; timestamps are included in the table.
            p = np.r_[False, bad, False]
            starts = np.flatnonzero(~p[:-1] & p[1:]); ends = np.flatnonzero(p[:-1] & ~p[1:]) - 1
            for s, e in zip(starts, ends):
                seg = v[s:e+1]
                abnormal_rows.append({"position": pos_id, "latitude": lat, "longitude": lon,
                    "start": times[s], "end": times[e], "hours": int(e-s+1),
                    "nan_hours": int(np.isnan(seg).sum()), "negative_hours": int((seg < 0).sum()),
                    "high_wind_hours": int((seg > config.ANOMALOUS_HIGH_WIND_SPEED).sum()),
                    "nonfinite_hours": int((~np.isfinite(seg)).sum())})
    abnormal = pd.DataFrame(abnormal_rows)
    abnormal.to_csv(out / "abnormal_runs.csv", index=False, encoding="utf-8-sig")
    missing_path = out / "missing_runs.csv"
    missing = pd.read_csv(missing_path) if missing_path.exists() and missing_path.stat().st_size > 30 else pd.DataFrame()

    annual_chart = "".join(f'<div class="barrow"><span>{int(y)}</span><i style="width:{100*r:.1f}%"></i><b>{r:.2%}</b></div>' for y, r in annual.groupby("year").valid_rate.mean().items())
    rate_chart = "".join(f'<div class="barrow"><span>{x:.0%}</span><i style="width:{n/max(1,len(summary))*100:.1f}%"></i><b>{n}</b></div>' for x, n in summary["missing_rate"].round(3).value_counts().sort_index().items())

    worst = summary.sort_values(["missing_rate", "invalid_days"], ascending=False)
    long_missing = missing.sort_values("hours", ascending=False) if not missing.empty else missing
    long_abnormal = abnormal.sort_values("hours", ascending=False) if not abnormal.empty else abnormal
    controls = f"最低站点有效率={config.MIN_STATION_VALID_RATE:.0%}；每日最低有效小时数={config.MIN_DAILY_VALID_HOURS}；最低年度有效率={config.MIN_ANNUAL_VALID_RATE:.0%}；异常高风速阈值={config.ANOMALOUS_HIGH_WIND_SPEED:g} m/s。"
    status = "通过：未发现连续缺测或连续异常风速段。" if missing.empty and abnormal.empty else "发现问题：请查看连续问题明细。"
    html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>风速数据质量报告</title>
    <style>body{{font-family:Arial,"Microsoft YaHei",sans-serif;max-width:1400px;margin:30px auto;color:#243447}}h1{{color:#123b5d}}h2{{border-bottom:2px solid #d9e7f2;padding-bottom:6px}}.card{{background:#f5f9fc;padding:14px 18px;margin:12px 0;border-left:5px solid #3984a8}}.ok{{color:#16834b;font-weight:bold}}.warn{{color:#b44b00;font-weight:bold}}.data{{border-collapse:collapse;width:100%;font-size:13px}}.data th,.data td{{border:1px solid #d5dde5;padding:5px;text-align:right}}.data th{{background:#e8f1f7}}.chart{{max-width:850px;background:#fafafa;padding:8px 15px}}.barrow{{display:flex;align-items:center;gap:8px;margin:4px 0}}.barrow span{{width:70px;text-align:right;font-size:12px}}.barrow i{{display:inline-block;height:16px;background:#3984a8;min-width:1px}}.barrow b{{font-size:12px}}</style></head><body>
    <h1>风速数据质量检查可视化报告</h1><div class="card"><b>研究期：</b>{times.min()} 至 {times.max()}；<b>位置数：</b>{len(summary)}；<b>预期小时数：</b>{len(expected)}<br><span class="{'ok' if missing.empty and abnormal.empty else 'warn'}">{status}</span></div>
    <p>{controls}</p><h2>1. 连续缺测与连续异常</h2><p>连续问题按原始时间序列逐小时识别；跨月、跨年不截断。</p>
    <h3>连续缺测段（最长优先）</h3>{_table(long_missing, ['position','start','end','hours','missing_timestamp_hours','nan_hours','source'])}
    <h3>连续异常风速段（最长优先）</h3>{_table(long_abnormal, ['position','start','end','hours','nan_hours','negative_hours','high_wind_hours','nonfinite_hours'])}
    <h2>2. 完整率概览</h2><h3>年度平均有效率</h3><div class="chart">{annual_chart}</div><h3>站点缺测率分布</h3><div class="chart">{rate_chart}</div>
    <h2>3. 质量摘要</h2><p>缺测率最高及每日有效小时不足的站点：</p>{_table(worst, ['position','latitude','longitude','missing_rate','missing_runs','longest_missing_hours','invalid_days','meets_min_station_rate'])}
    <h2>4. 年度有效率</h2>{_table(annual.sort_values(['year','valid_rate']), ['position','year','expected_hours','valid_hours','valid_rate','meets_min_annual_rate'])}
    <h2>5. 文件与说明</h2><p>原始数据：{config.DATA_PATH}。阶段0 CSV 报告位于：{out}。0 m/s 被视为有效风速；NaN、负值和超过阈值的风速不会被静默删除。</p></body></html>'''
    path = out / "wind_data_quality_report.html"; path.write_text(html, encoding="utf-8")
    print(f"HTML报告已生成: {path}"); print(f"连续缺测段: {len(missing)}; 连续异常段: {len(abnormal)}")


