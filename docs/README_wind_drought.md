# 风旱分析程序

## 当前默认：固定阈值逐小时站点LPW

`ANALYSIS_MODE="hourly_lpw"`为当前口径。每个站点在 `CF<0.1`、`CF<0.05`、`CF<0.02` 三个情景下分别识别严格连续至少4小时的低风电事件。恢复1小时、缺测1小时、缺时间标签，以及默认排除的切出停机小时都会中断事件，不进行短暂恢复合并。

时长等级互斥：LPW1为[4,8)小时，LPW2为[8,12)小时，LPW3为[12,24)小时，LPW4为[24,∞)小时。4个连续小时记录00、01、02、03构成4小时事件；`end`是最后一个低CF时间标签03，另存 `end_exclusive=04` 表示右开端点。跨年事件只有一个ID，次数归开始年，LPW小时数按实际年份分配。研究边界事件保留并标记，真实时长可能更长。

运行前激活正确的Conda环境，或使用 `conda run --no-capture-output -n main_env python`；绘图库需要该环境的本地DLL。完整计算：

```powershell
conda run --no-capture-output -n main_env python code/run_wind_drought.py --skip-quality
```

复用已保存且参数匹配的站点小时CF，可避免重复计算外推与CF：

```powershell
conda run --no-capture-output -n main_env python code/run_wind_drought.py --hourly-cf outputs/wind_drought/run_20261021_183538_454692/netcdf/hourly_cf.nc --skip-quality
```

该历史路径仅适用于已有此本地结果的机器；克隆仓库后先从原始风速完整运行。缓存复用会核对高度、幂律指数、机型参数与CF结构，并记录源文件路径、大小、修改时间及属性。阈值和事件输入均为站点小时CF，日/七日CF不参与本次识别。

每次在 `outputs/lpw/run_*/` 创建新目录：

| 输出 | 含义 |
| --- | --- |
| `tables/events_CF010.csv.gz` | CF<0.1全部≥4小时事件，gzip压缩CSV |
| `tables/events_CF005.csv.gz` | CF<0.05全部≥4小时事件 |
| `tables/events_CF002.csv.gz` | CF<0.02全部≥4小时事件 |
| `tables/station_frequency.csv` | 每站×阈值×等级的次数、时长、CF强度及有效小时诊断 |
| `tables/station_annual_statistics.csv` | 每站每年各等级事件开始次数，及当年低CF/LPW小时 |
| `tables/lpw_summary.csv` | 同阈值各等级的站点次数汇总及空间均值；不是去重的区域同步事件数 |
| `netcdf/lpw_station_frequency.nc` | 可直接用于空间分析的站点×阈值×等级频次与坐标 |
| `netcdf/thresholds.nc` | 三个固定CF阈值及小时识别口径 |
| `figures/frequency_*.png` | 三阈值×ALL/四等级，共15张频次地图 |
| `manifest.json` | 事件数、时间范围、边界规则、图件清单、共享色标和完成状态 |
| `cf_source.json`、`configuration.json` | 源CF信息及本次配置快照 |

事件表按站点逐块追加，站内按时间排序。`pd.read_csv(path)`可直接读取 `.csv.gz`，不必手工解压。`duration_hours`和`valid_observations`相等；`lpw_class`是时长等级；`cumulative_cf_deficit=sum(阈值-CF)`单位为CF·小时，未计算电量。`missing_hours=0`表示事件内部不允许缺测；`missing_before/after`按分析中不可用小时标记，也包括被剔除的切出停机；另记录事件内切出小时及研究边界标记。

频次表中的 `event_count` 是全研究期次数；`mean_events_per_calendar_year` 是次数除研究期覆盖的日历年数（不完整年也计一年）；`events_per_valid_year` 是次数除 `valid_hours/(365.2425×24)`，用于有效观测时长标准化。它们均不是低CF时间占比，后者另存 `low_cf_fraction`。`low_cf_hours`包含不足4小时的短低值段，`lpw_hours`仅包含合格事件。完全无有效观测的站点次数记NaN，有观测但没有事件记0。`ALL`为该阈值内四等级之和；不同阈值的次数不能相加。

默认地图绘制 `event_count`；可配置为 `events_per_valid_year`。地图通过 `utils.plot_scat_map` 绘制离散站点，不进行空间插值；同一等级在三个CF阈值下共用离散色标，不同等级可用不同范围。南海子图复用本地省界，不下载Natural Earth文件。原始data和生成outputs仍全部忽略，不上传GitHub。

当前配色为0次灰色，其余七档蓝—青—绿—黄—橙—红；累计次数的[0,1)档只包含0。每个等级按三个阈值合并后的频次分位点附近设置易读整数边界，避免频次集中于少数等距色段。这里仅调整绘图分箱，不改变CF阈值或事件定义。`LPW_MAP_LEVELS`可按等级指定边界字典，也可为所有等级共用列表或None（自动等距）；`LPW_MAP_COLORS`配置正频次色阶，`LPW_MAP_ZERO_COLOR`配置0次颜色。当前固定边界单位是累计次数，若切换有效年频次，应将边界设为None或使用匹配单位的新边界。

仅重绘已有结果：

```powershell
conda run --no-capture-output -n main_env python code/run_wind_drought.py --plot-lpw-run outputs/lpw/run_20261021_203640_703000
```

重绘会更新PNG、`plot_configuration.json`和manifest中的绘图信息，保留原科学计算配置和所有事件、频次统计文件。

## 保留的旧模式：区域日CF

以下为 `--analysis-mode daily` 的原日尺度配置和输出说明，P20/P10/P5及日持续时间不用于当前小时LPW。

唯一正式入口是 `code/run_wind_drought.py`。`code/` 顶层仅保留入口、配置和共用工具；质量检查与HTML报告独立放在 `code/quality_control/`，风旱专用计算位于 `code/wind_droughts/`，两个包分别承担质量控制与分析职责。原 `utils.py` 仅补充中文说明，函数实现保留，质量输出继续使用 `OUTPUT_DIR=../outputs/quality`。新计算不导入绘图工具，避免要求 cartopy/geopandas 等无关依赖。`examples/TEST.py` 保留交互探索用途，测试集中于 `tests/`，依赖清单位于项目根目录。

## 环境与运行

本机可用环境：`C:/Users/35237/.conda/envs/main_env/python.exe`。默认 `python` 指向不含 xarray 的 base 环境，需选择正确解释器。依赖见 `requirements-wind-drought.txt`；计算不需要 dask。

在项目根目录的 PowerShell 中执行：

```powershell
$windPython = 'C:/Users/35237/.conda/envs/main_env/python.exe'
& $windPython -m pytest tests -q -p no:cacheprovider
& $windPython code/run_wind_drought.py --inspect-only
& $windPython code/run_wind_drought.py --skip-quality
& $windPython code/run_wind_drought.py --quality-html
```

不带选项会重新运行原阶段0质量检查后继续分析。`--quality-only` 保留原来的仅质量检查流程。`--skip-quality` 保留旧报告、不重算旧CSV，仍重新执行新读取层校验和全量异常扫描。Windows受限令牌下测试使用工作区内独立UUID目录，避免pytest默认0700目录权限问题；小型测试文件保留在 `outputs/test_artifacts/`。

## 数据与配置

实际源文件是站点数据：`wind(time=175320, station=1619, var=2)`，`var=['ws','wd']`。`ds.sel(var='ws')` 是Dataset，显式选择 `['wind']` 才是风速DataArray。时间为2005-01-01 00:00至2024-12-31 23:00。全量扫描：无缺小时、重复时间、NaN、无穷或负风速；范围0–50。变量和坐标均无属性，无法从文件验证单位、测量高度、时区及原始数据的填补历史。

配置中的 m/s 和10m高度是显式假设；程序不声称从源文件中获得这些信息。时间按源时间标签的日界划分，不擅自解释为UTC或北京时间。幂律默认10m→100m、alpha=1/7；指数允许[0,1]。动态ERA5方法仅预留接口，调用时明确报尚未实现。

`COORDINATE_MAP` 按“源名称→统一名称”设置，时间统一为 `time`，纬度为 `lat`，经度为 `lon`；站点维名可保留。`WIND_VARIABLE`、`WIND_SELECTOR` 明确指定风速。时间重复、未排序、非整点会报错，不排序或去重；缺小时补NaN标签，不插值。负风速与非有限值在计算CF时视为缺测；高于异常阈值只报告、不自动删除。原质量检查将缺小时也视为严重时间问题；如需对有缺小时的数据继续分析，使用 `--skip-quality`，新计算层会严格保留缺测。

默认机型仅是简化研究参数：切入3、额定12、切出25 m/s，额定功率2000 kW。`v<切入` 为0，`切入≤v<额定` 按 `(v³-切入³)/(额定³-切入³)`，`额定≤v<切出` 为1，`v≥切出` 为0。离散曲线支持配置 `(m/s,kW)` 点列，线性插值，需覆盖切入至切出。两种曲线均强制切出停机并保留缺测。

## 识别与统计口径

- 原始逐小时CF始终保存。`cause=-1/0/1/2` 分别表示缺测或无效、一般运行、低于切入、切出停机。`EXCLUDE_CUT_OUT=True` 时只从分析用空间平均中剔除切出网格，剩余有效权重重新归一化。区域小时文件另存含切出的CF及切出权重比例。
- 空间平均按 `cos(纬度)` 加权。站点资料表示采样位置权重，不能视为装机权重或严格面积代表权重；网格资料使用相同纬度加权。所有点无效时为NaN。
- 先求区域小时CF，再求日平均；默认每日至少18个有效区域小时。记录日有效小时数；缺测日不补值。七日指标为后向、七天完整有效的日CF平均。`EVENT_INPUT` 在 daily/rolling7 中单选，阈值与事件始终用同一序列。
- 默认用完整研究期日CF计算全年统一P20/P10/P5，采用线性分位数估计。可设置基准期、分月阈值或固定CF阈值。严格 `CF<阈值` 才算低CF，等于阈值不算；分月阈值逐日映射，事件可跨月。
- 三个百分位是独立、嵌套的阈值情景，分别识别、保存和统计，不能相加。`threshold_level` 与 `final_level` 均为情景名称，没有持续时间严重程度分类。`exclusive_daily_band` 是附加互斥区间码（非事件等级）：0为≥P20，1为[P10,P20)，2为[P5,P10)，3为<P5，-1为缺测。
- 默认记录所有含≥1个低CF日的事件。`MERGE_RECOVERY_DAYS=0` 表示严格连续；设为1可合并一天有效恢复，但缺测日始终中断。事件结束为最后一个低CF日，不包含尾部恢复天。`duration_days` 为首末低值日的日历跨度，`low_cf_days` 为低值日数，`valid_observations` 含合并恢复日。平均CF及最低CF按完整事件跨度计算。
- `MIN_EVENT_LOW_DAYS=N` 只筛选统计事件（低CF日数≥N），三个情景使用相同N；完整事件表仍保留。低CF总日数与占比始终基于所有有效判定日，另列筛选事件内低CF日数。
- 累计CF缺口为 `sum(max(阈值-CF,0))`，单位CF·日；恢复日贡献0。`missing_days=0` 是事件内部不允许缺测的结果，同时记录缺测邻接、研究边界、源数据不满24小时天数和源缺小时数。边界事件可能尚未完整结束，不自动删除。
- 跨年事件只有一个ID。年度/月度次数用开始日期归属，低CF日数和累计CF缺口按实际日期分配；持续时间、事件CF统计按开始期归属完整事件。季节统计汇总全部年份的DJF/MAM/JJA/SON，不另构建跨年季节事件。

## 输出

每次在 `ANALYSIS_OUTPUT_DIR/run_日期_时间_微秒/` 新建目录，避免覆盖既有分析结果：

| 文件 | 内容 |
| --- | --- |
| `configuration.json` | 所有可调参数快照 |
| `data_inspection.json` | 原始结构、属性、时间步长和全量异常扫描 |
| `netcdf/hourly_cf.nc` | 原始站点/网格逐小时CF及成因 |
| `netcdf/regional_hourly_cf.nc` | 分析用CF、含切出CF、切出加权比例 |
| `netcdf/daily_cf.nc` | 日CF、日有效小时、可选七日CF |
| `netcdf/thresholds.nc` | 每个情景的逐日阈值及辅助互斥标签 |
| `tables/events_all_情景.csv` | 全部事件 |
| `tables/events_selected_情景.csv` | 统一N筛选后的事件 |
| `tables/events_all.csv` / `events_selected.csv` | 按情景拼接，含threshold_level |
| `tables/scenario_summary.csv` | 各情景低CF日数、比例、次数、持续时间及CF统计 |
| `tables/annual_statistics.csv` | 年度低CF日数、事件开始次数及强度统计 |
| `tables/monthly_statistics.csv` | 逐年逐月统计 |
| `tables/seasonal_statistics.csv` | 全研究期季节统计 |

没有区域装机容量或明确机组数时，不输出电量。额定功率本身不代表区域装机，站点数也不作为机组数。显式给出容量后，仅日CF模式可输出 `threshold_deficit_energy_kwh_estimate`（日平均相对风旱阈值的缺口×有效小时×容量）与 `full_output_gap_energy_kwh`（相对满发的差额×有效小时×容量）。前者为日平均口径的等效估计，后者为满发参照差；两者均不称为实际损失电量，缺测小时不外推。站点CF乘区域容量还隐含站点加权CF代表机群的假设，需要研究者确认。

后续需确认：源风速单位、参考高度和时间日界，具体机型曲线，区域代表性及装机分布，基准期、分月/全年口径、日有效小时门槛与统一N。ERA5动态风切变还需多高度逐小时数据和实际计算实现。
