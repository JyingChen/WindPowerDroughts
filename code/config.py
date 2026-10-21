"""功能：集中管理质量检查和风旱分析参数。
输入：用户修改的路径、机型和研究口径；输出：供各模块读取的常量。
流程：保留原质量检查配置，再声明风旱配置；注意：默认机型、单位和高度均为研究假设。
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
EVENT_INPUT = "daily"  # daily 或 rolling7；一次运行只选一种
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
