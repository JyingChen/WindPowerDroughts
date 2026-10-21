# 风旱分析项目

原始 `data/` 和本地生成的 `outputs/` 不随Git仓库上传。克隆后需自行创建 `data/`，放入 `wind_data_trimmed.nc`；数据结构和参数假设见下方分析文档。

```text
code/                         源码
├─ run_wind_drought.py         唯一正式执行入口
├─ config.py                   路径与可调参数
├─ utils.py                    保留的共用工具
├─ quality_control/            独立的质量控制模块
│  ├─ data_quality.py          原始风速质量检查
│  └─ generate_quality_html.py 质量HTML报告
└─ wind_droughts/              风速外推、CF、阈值、事件与统计
tests/                        pytest测试与测试配置
docs/                         运行说明与研究口径
data/                         原始数据
outputs/                      分析结果和质量报告
requirements-wind-drought.txt 依赖清单
```

在项目根目录运行：

```powershell
$windPython = 'C:/Users/35237/.conda/envs/main_env/python.exe'
& $windPython code/run_wind_drought.py --skip-quality
& $windPython -m pytest tests -q -p no:cacheprovider
```

不带参数会先执行原阶段0质量检查。`--quality-only`仅运行质量检查，`--quality-html`从已有质量CSV生成HTML报告，`--inspect-only`仅检查原始数据。

详细说明见 [风旱分析文档](docs/README_wind_drought.md)。源码迁移未改变分析公式、参数、原始数据或已有结果。历史运行报告中的旧测试路径代表当时的执行记录，新测试命令以上述命令为准。
