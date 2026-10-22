"""功能：集中管理质量检查和风旱分析参数。
输入：用户修改的路径、机型和研究口径；输出：供各模块读取的常量。
流程：声明质量检查、CF、小时LPW及旧日尺度配置；注意：默认机型、单位和高度均为研究假设。
"""

DATA_PATH = "../data/wind_data_trimmed.nc"
OUTPUT_DIR = "../outputs/quality"
TIME_DIM = "time"
STATION_DIM = "station"
WIND_VARIABLE = "wind"
WIND_SELECTOR = {"var": "ws"}
WIND_UNITS = "m s-1"

# Leave these as None to use the actual first/last timestamp in the file.
# Set both explicitly when the scientific study period is prescribed.
STUDY_START = None
STUDY_END = None

MIN_STATION_VALID_RATE = 0.90
MIN_DAILY_VALID_HOURS = 18
MIN_ANNUAL_VALID_RATE = 0.90
ANOMALOUS_HIGH_WIND_SPEED = 50.0
STATION_CHUNK_SIZE = 128

# 保留 OUTPUT_DIR 给原有质量检查和 HTML 报告使用。
ANALYSIS_OUTPUT_DIR = "../outputs/wind_drought"
ANALYSIS_MODE = "hourly_lpw"  # hourly_lpw为当前口径；daily保留原区域日CF分析
LPW_OUTPUT_DIR = "../outputs/lpw"
LPW_CF_THRESHOLDS = {"CF010": 0.1, "CF005": 0.05, "CF002": 0.02}
LPW_MIN_HOURS = 4
LPW_CLASS_LOWER_HOURS = (4, 8, 12, 24)
LPW_CLASS_LABELS = ("LPW1", "LPW2", "LPW3", "LPW4")
LPW_STATION_BLOCK_SIZE = 32  # 按站点块读取完整时间轴，事件不被块边界截断
LPW_PLOT_MAPS = True
LPW_MAP_METRIC = "event_count"  # 或events_per_valid_year：按有效小时折算年的频次
# 按三阈值合并后的各等级频次分布设置边界；0单独一档，其余边界靠近分位点并取整。
# 可改为None自动等距分级，或提供所有等级共用的边界列表。
# 以下边界单位为累计次数；切换有效年频次指标时，应设None或改用相应的年频次边界。
LPW_MAP_LEVELS = {
    "ALL": (0, 1, 2000, 3500, 5000, 6250, 7000, 8000, 11000),
    "LPW1": (0, 1, 200, 500, 1000, 1600, 2200, 2800, 5700),
    "LPW2": (0, 1, 100, 250, 500, 850, 1150, 1450, 2500),
    "LPW3": (0, 1, 500, 1000, 1800, 2500, 3000, 3800, 5800),
    "LPW4": (0, 1, 700, 1050, 1400, 1600, 1750, 1850, 2100),
}
LPW_MAP_CMAP = "turbo"  # LPW_MAP_COLORS=None时的备选色图
LPW_MAP_COLORS = ("#2166ac", "#1f9ac6", "#1a9850", "#d4df23", "#fdae31", "#f46d43", "#a50026")
LPW_MAP_ZERO_COLOR = "#d9d9d9"  # [0,1)档只包含0次，单独使用灰色
LPW_MAP_EXTENT = (73, 136, 17, 54)
LPW_MAP_FIGSIZE = (10, 8)
LPW_MAP_DPI = 180
LPW_MAP_ADD_SOUTH_CHINA_SEA = True
LPW_MAP_PATH = "../data/中国_省.geojson"
RUN_LEGACY_QUALITY = True
COORDINATE_MAP = {"time": "time", "latitude": "lat", "longitude": "lon"}
SOURCE_HEIGHT_M = 10.0
HUB_HEIGHT_M = 100.0
SHEAR_ALPHA = 1 / 7
PROFILE_METHOD = "power_law"  # dynamic_era5 目前明确抛出 NotImplementedError
CUT_IN_MS = 3.0
RATED_SPEED_MS = 12.0
CUT_OUT_MS = 25.0
RATED_POWER_KW = 2000.0
DISCRETE_POWER_CURVE = None  # 可设为 [(风速m/s, 功率kW), ...]；须覆盖切入至切出
EXCLUDE_CUT_OUT = True  # 只从分析用CF剔除；原始逐小时CF与成因仍保存
HOURLY_BLOCK_HOURS = 744
NETCDF_CHUNK_CACHE_MB = 256  # 源文件原生块较大；避免相邻计算块反复解压同一数据
COMPUTE_ROLLING_7D = True
EVENT_INPUT = "daily"  # 以下阈值和日数参数仅用于ANALYSIS_MODE=daily
THRESHOLD_TYPE = "percentile"  # percentile 或 fixed
PERCENTILE_MODE = "annual"  # annual 为全年统一，monthly 为分月历史分位数
PERCENTILE_LEVELS = {"P20": 20, "P10": 10, "P5": 5}
FIXED_CF_THRESHOLD = 0.1
BASELINE_START = None  # None 使用完整研究期；始末日期均包含
BASELINE_END = None
MERGE_RECOVERY_DAYS = 0
MIN_EVENT_LOW_DAYS = 1  # 统计筛选；三个情景使用相同N，所有事件仍另表保存
INSTALLED_CAPACITY_KW = None  # 区域装机；不由站点数推算
TURBINE_COUNT = None  # 仅明确给出此项时才可用额定功率推算装机
