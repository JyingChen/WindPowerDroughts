# 风旱分析项目

当前默认分析为逐站逐小时低风电事件（LPW）：分别使用 `CF<0.1`、`CF<0.05`、`CF<0.02`，严格连续至少4小时。

| 时长等级 | 持续时间 |
| --- | --- |
| LPW1 | 4≤时长<8小时 |
| LPW2 | 8≤时长<12小时 |
| LPW3 | 12≤时长<24小时 |
| LPW4 | 时长≥24小时 |

三个CF阈值分别统计；每个阈值内等级互斥。使用 `utils.plot_scat_map` 绘制各站点累计次数的离散色标地图，同等级跨阈值使用一致色标。

地图采用灰色单独表示0次，其余使用蓝—青—绿—黄—橙—红离散配色；各等级边界依据合并三个阈值后的频次分布设置并取整，详见config中的 `LPW_MAP_LEVELS`。更改色标后可用 `--plot-lpw-run 结果目录` 只重绘地图，无需重算事件。

原始 `data/` 和本地生成的 `outputs/` 不随Git仓库上传；其他目录中的NetCDF、GRIB、HDF5、Zarr、NumPy数组等二进制数据和计算结果也被忽略。克隆后需自行创建 `data/`，放入 `wind_data_trimmed.nc`；数据结构和参数假设见下方分析文档。

```text
code/                         源码
├─ run_wind_drought.py         唯一正式执行入口
├─ config.py                   路径与可调参数
├─ utils.py                    保留的共用工具
├─ quality_control/            独立的质量控制模块
│  ├─ data_quality.py          原始风速质量检查
│  └─ generate_quality_html.py 质量HTML报告
└─ wind_droughts/              风速外推、CF、小时LPW、统计与绘图
tests/                        pytest测试与测试配置
docs/                         运行说明与研究口径
data/                         原始数据
outputs/                      分析结果和质量报告
requirements-wind-drought.txt 依赖清单
```

在项目根目录运行：

```powershell
conda run --no-capture-output -n main_env python code/run_wind_drought.py --skip-quality
conda run --no-capture-output -n main_env python -m pytest tests -q -p no:cacheprovider
```

应激活包含绘图依赖的Conda环境，避免直接调用解释器时混用其他环境的本地DLL。不带参数会先执行原阶段0质量检查。`--quality-only`仅运行质量检查，`--quality-html`从已有质量CSV生成HTML报告，`--inspect-only`仅检查原始数据。

可用 `--hourly-cf 文件路径` 复用已有 `hourly_cf.nc`，程序会核对机型、高度与指数，避免重算CF；`--skip-maps`仅计算LPW统计。新结果位于 `outputs/lpw/run_*/`，事件表为 `.csv.gz`，地图位于 `figures/`。`--analysis-mode daily`保留旧区域日CF方法，输出仍位于 `outputs/wind_drought/`。

详细说明见 [风旱分析文档](docs/README_wind_drought.md)。源码迁移未改变分析公式、参数、原始数据或已有结果。历史运行报告中的旧测试路径代表当时的执行记录，新测试命令以上述命令为准。
