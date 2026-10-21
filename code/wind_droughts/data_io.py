"""功能：读取校验风速、分块持久化CF并保存研究结果。
输入：NetCDF、名称映射与输出目录；输出：统一坐标的DataArray、质检JSON和NetCDF/CSV。
流程：检查结构及时间、逐块读取、保存；注意：仅补NaN时间标签，绝不插值或静默去重。
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr
import netCDF4


def configure_netcdf_cache(size_mb=256):
    """在打开源文件前配置NetCDF原生块缓存，减少大原生块的重复解压。"""
    if not isinstance(size_mb, int) or size_mb < 1:
        raise ValueError("NetCDF缓存MB须为正整数")
    netCDF4.set_chunk_cache(size=size_mb * 1024**2, nelems=1009, preemption=.75)


def read_wind(ds, variable="wind", selection=None, coordinate_map=None, assumed_units="m s-1",
              study_start=None, study_end=None):
    """明确取出风速变量，统一名称并校验时间/单位；返回尚未加载全部数值的风速数组。"""
    selected = ds.sel(selection or {})
    if variable not in selected.data_vars:
        raise ValueError(f"风速变量{variable!r}不存在；现有变量{list(selected.data_vars)}")
    wind = selected[variable]
    mapping = coordinate_map or {}
    wind = wind.rename({k: v for k, v in mapping.items() if k in wind.dims or k in wind.coords if k != v})
    if "time" not in wind.dims:
        raise ValueError("需映射时间维到time")
    times = pd.DatetimeIndex(wind.time.values)
    if times.empty or times.hasnans or times.has_duplicates or not times.is_monotonic_increasing:
        raise ValueError("时间为空、无效、重复或未排序；请明确修复源数据后重试")
    if not (times == times.floor("h")).all():
        raise ValueError("时间戳须对齐整点小时")
    units = wind.attrs.get("units", assumed_units)
    if units is None or units.strip().lower() not in {"m s-1", "m/s", "m s**-1", "m s^-1"}:
        raise ValueError(f"不支持或未声明风速单位：{units}；请转换到m/s")
    wind = wind.sel(time=slice(study_start, study_end)).transpose("time", ...)
    if wind.time.size == 0:
        raise ValueError("研究期内无观测")
    wind.attrs = {**wind.attrs, "units": "m s-1", "units_source": "file" if "units" in selected[variable].attrs else "config_assumption"}
    return wind


def hourly_blocks(wind, block_hours=744, study_start=None, study_end=None):
    """按完整预期小时轴迭代小块；缺小时只置NaN，内存不随整个研究期增长。"""
    if not isinstance(block_hours, int) or block_hours < 1:
        raise ValueError("分块小时数必须为正整数")
    start = pd.Timestamp(study_start) if study_start is not None else pd.Timestamp(wind.time.values[0])
    end = pd.Timestamp(study_end) if study_end is not None else pd.Timestamp(wind.time.values[-1])
    if start != start.floor("h") or end != end.floor("h") or end < start:
        raise ValueError("研究起止须为递增整点小时")
    times = pd.date_range(start, end, freq="h")
    for offset in range(0, len(times), block_hours):
        target = times[offset:offset+block_hours]
        # 先切片再加载，避免reindex触发全量数组读取。
        block = wind.sel(time=slice(target[0], target[-1])).load().reindex(time=target)
        yield offset, block


def inspect_data(ds, wind, block_hours=744, high_limit=50.):
    """扫描实际结构、时间步长和全量缺测异常计数，返回可序列化检查报告。"""
    times = pd.DatetimeIndex(wind.time.values)
    report = dict(dataset_type=type(ds).__name__, selected_type=type(ds.sel(var="ws")).__name__ if "var" in ds.coords and "ws" in ds['var'].values else "not_applicable",
        dimensions=dict(ds.sizes), global_attrs=dict(ds.attrs),
        variables={k: dict(dimensions=list(v.dims), shape=list(v.shape), dtype=str(v.dtype), attrs=dict(v.attrs)) for k,v in ds.variables.items()},
        time_start=str(times[0]), time_end=str(times[-1]), sorted=times.is_monotonic_increasing,
        duplicate_timestamps=int(times.duplicated().sum()),
        time_steps={str(k): int(v) for k,v in pd.Series(times[1:]-times[:-1]).value_counts().items()},
        missing_timestamp_hours=len(pd.date_range(times[0], times[-1], freq="h").difference(times)),
        units=wind.attrs["units"], units_source=wind.attrs["units_source"],
        nan=0, infinite=0, negative=0, anomalous_high=0, minimum=None, maximum=None)
    for _, block in hourly_blocks(wind, block_hours):
        v = block.values
        report['nan'] += int(np.isnan(v).sum())
        report['infinite'] += int(np.isinf(v).sum())
        report['negative'] += int((v < 0).sum())
        report['anomalous_high'] += int((np.isfinite(v) & (v > high_limit)).sum())
        finite = v[np.isfinite(v)]
        if finite.size:
            report['minimum'] = float(finite.min()) if report['minimum'] is None else min(report['minimum'], float(finite.min()))
            report['maximum'] = float(finite.max()) if report['maximum'] is None else max(report['maximum'], float(finite.max()))
    return report


def create_hourly_file(path, template, metadata, chunk_hours=744):
    """创建可追加的逐小时CF文件，保留站点/网格坐标；返回已打开的netCDF4句柄。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    coords = template.isel(time=slice(0, 0)).coords
    xr.Dataset(coords=coords, attrs=metadata).to_netcdf(path, engine="netcdf4", unlimited_dims=["time"],
        encoding={"time": {"dtype": "float64", "units": "hours since 1970-01-01 00:00:00", "calendar": "proleptic_gregorian"}})
    handle = netCDF4.Dataset(path, "a")
    chunks = tuple(min(chunk_hours, max(1, template.sizes[d])) if d == "time" else
                   min(128, template.sizes[d]) for d in template.dims)
    handle.createVariable("cf", "f4", template.dims, zlib=True, complevel=2, fill_value=np.nan, chunksizes=chunks)
    handle.createVariable("cause", "i1", template.dims, zlib=True, complevel=2, chunksizes=chunks)
    handle.variables['cf'].units = "1"
    handle.variables['cause'].codes = "-1=missing_or_invalid;0=operating;1=below_cut_in;2=cut_out"
    return handle


def append_hourly(handle, products, offset):
    """将一块CF及成因写入已打开文件；时间以文件CF编码转换，保留原坐标。"""
    n = products.sizes['time']
    time = handle.variables['time']
    dates = pd.DatetimeIndex(products.time.values).to_pydatetime()
    time[offset:offset+n] = netCDF4.date2num(dates, units=time.units, calendar=getattr(time, 'calendar', 'standard'))
    for key in ('cf', 'cause'):
        handle.variables[key][offset:offset+n] = products[key].values
        handle.variables[key].setncatts(products[key].attrs)


def save_json(path, value):
    """以UTF-8保存可追溯配置或检查结果；支持路径和numpy标量的文本表示。"""
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def save_tables(output_dir, tables):
    """将名称到DataFrame的映射保存为带UTF-8 BOM的CSV，空表也保留列名。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in tables.items():
        frame.to_csv(output_dir / f"{name}.csv", index=False, encoding="utf-8-sig")


def resolve_capacity(installed_capacity_kw=None, rated_power_kw=None, turbine_count=None):
    """仅用明确装机或额定功率乘明确机组数解析区域容量；未给出则不计算电量。"""
    if installed_capacity_kw is not None:
        if not np.isfinite(installed_capacity_kw) or installed_capacity_kw <= 0:
            raise ValueError("装机容量须为有限正数")
        return installed_capacity_kw
    if turbine_count is None:
        return None
    if not isinstance(turbine_count, int) or turbine_count < 1 or rated_power_kw is None or not np.isfinite(rated_power_kw) or rated_power_kw <= 0:
        raise ValueError("机组数量须为正整数且额定功率须为有限正数")
    return rated_power_kw * turbine_count
