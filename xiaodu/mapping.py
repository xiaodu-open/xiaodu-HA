"""纯映射规则：平台选择、传感器筛选、色温/风速换算、乐观状态结算。

本模块不依赖 Home Assistant，便于单独推理与测试。
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .const import (
    AMBIENT_SENSOR_TYPES,
    CLIMATE_TYPES,
    COLOR_TEMP_MAX_KELVIN,
    COLOR_TEMP_MIN_KELVIN,
    CONDITIONAL_CLIMATE_TYPES,
    COVER_TYPES,
    FAN_TYPES,
    INPUT_ONLY_TYPES,
    LIGHT_TYPES,
    SWITCH_TYPES,
)
from .models import IotDevice

# 可作为只读传感器暴露的属性 -> 门槛品类（None 表示有值即建实体）
SENSOR_PROPERTY_TYPES: dict[str, frozenset[str] | None] = {
    "temperature": AMBIENT_SENSOR_TYPES,
    "humidity": AMBIENT_SENSOR_TYPES,
    "targetHumidity": None,
    "pm2.5": None,
    "pm10": None,
    "hcho": None,
    "tovc": None,
    "airPressure": None,
    "electricityCapacityPercentage": None,
    "electricityCapacity": None,
    "deviceState": None,
    "weight": frozenset({"BODY_FAT_SCALE", "WEIGHT_SCALE"}),
    "impedance": frozenset({"BODY_FAT_SCALE"}),
    "bmi": frozenset({"BODY_FAT_SCALE"}),
    "bodyFatPercentage": frozenset({"BODY_FAT_SCALE"}),
    "bodyWaterPercentage": frozenset({"BODY_FAT_SCALE"}),
    "muscleMass": frozenset({"BODY_FAT_SCALE"}),
}
SENSOR_PROPERTIES = tuple(SENSOR_PROPERTY_TYPES)

FAN_MODES = ("low", "medium", "high")

# 空调温度兜底区间（设备未上报 valueRangeMap 时使用）
DEFAULT_MIN_TEMP = 16.0
DEFAULT_MAX_TEMP = 30.0


def resolve_pending_power_state(
    pending: Any,
    created_at: float | None,
    actual: Any,
    now: float,
    timeout: float,
) -> tuple[Any, bool]:
    """返回 (对外显示的值, 该乐观状态是否已结算)。"""
    if pending is None or created_at is None:
        return actual, True
    if actual == pending or now - created_at >= timeout:
        return actual, True
    return pending, False


def device_control_key(device: IotDevice) -> tuple[str, str, str]:
    """返回用于重名歧义判断的「名称 + 位置」键。"""
    return (
        device.name.strip(),
        (device.room_name or "").strip(),
        (device.floor_name or "").strip(),
    )


def color_temp_pct_to_kelvin(value: Any) -> int | None:
    """上报的 0-100 色温百分比 -> 开尔文。"""
    try:
        percentage = float(value)
    except (TypeError, ValueError):
        return None
    percentage = max(0.0, min(100.0, percentage))
    span = COLOR_TEMP_MAX_KELVIN - COLOR_TEMP_MIN_KELVIN
    return round(COLOR_TEMP_MIN_KELVIN + span * percentage / 100)


def color_temp_kelvin_to_pct(kelvin: Any) -> int | None:
    """开尔文 -> 下发用的 0-100 色温百分比。"""
    try:
        value = float(kelvin)
    except (TypeError, ValueError):
        return None
    span = COLOR_TEMP_MAX_KELVIN - COLOR_TEMP_MIN_KELVIN
    percentage = (value - COLOR_TEMP_MIN_KELVIN) * 100 / span
    return max(0, min(100, round(percentage)))


def _numeric_range(options: Mapping[str, Any], *keys: str) -> tuple[int, int] | None:
    """从属性选项里取 {min, max} 区间。"""
    for key in keys:
        value_range = options.get(key)
        if not isinstance(value_range, Mapping):
            continue
        try:
            minimum = int(value_range["min"])
            maximum = int(value_range["max"])
        except (KeyError, TypeError, ValueError):
            continue
        if minimum <= maximum:
            return minimum, maximum
    return None


def temperature_range(device: IotDevice) -> tuple[float, float]:
    """返回目标温度区间。

    空调固定 16-30℃：小度侧的语音/LLM 协议就是按这个区间约束的
    （`models/service/conf/Prompt.php` 的 SetTemperature schema），
    而设备上报的 `valueRangeMap` 往往是传感器量程（见过 0-60），直接用会得到无意义的滑块。
    地暖 / 热水器这类温区差异大的品类才采用设备上报的区间。
    """
    if device.device_types & CLIMATE_TYPES:
        return DEFAULT_MIN_TEMP, DEFAULT_MAX_TEMP
    for property_name in ("temperature", "targetTemperature"):
        found = _numeric_range(
            device.options(property_name), "valueRangeMap", "range", "levelRange"
        )
        if found is not None:
            return float(found[0]), float(found[1])
    return DEFAULT_MIN_TEMP, DEFAULT_MAX_TEMP


def fan_mode_to_speed(mode: str, options: Mapping[str, Any]) -> str | None:
    """把 HA 的三档风速转换为上游可接受的取值。"""
    if mode not in FAN_MODES:
        return None
    speed_range = _numeric_range(options, "range", "valueRangeMap")
    if speed_range is not None:
        minimum, maximum = speed_range
        if mode == "low":
            value = minimum
        elif mode == "high":
            value = maximum
        else:
            value = round((minimum + maximum) / 2)
        return str(value)
    aliases = {"low": "low", "medium": "middle", "high": "high"}
    return aliases[mode]


def speed_to_fan_mode(value: Any, options: Mapping[str, Any]) -> str | None:
    """把上游风速取值折算到最近的 HA 档位。"""
    if value is None:
        return None
    speed_range = _numeric_range(options, "range", "valueRangeMap")
    if speed_range is not None:
        try:
            current = int(value)
        except (TypeError, ValueError):
            return None
        minimum, maximum = speed_range
        targets = {
            "low": minimum,
            "medium": round((minimum + maximum) / 2),
            "high": maximum,
        }
        return min(targets, key=lambda mode: abs(targets[mode] - current))
    aliases = {"low": "low", "middle": "medium", "medium": "medium", "high": "high"}
    return aliases.get(str(value).lower())


def primary_platform(device: IotDevice) -> str | None:
    """为设备选定唯一的控制平台。

    优先级：light > cover > climate > fan > switch。
    地暖/热水器/浴霸等只有声明 setTemperature 才归 climate，否则退回 switch。
    """
    if device.is_composite_parent:
        return None
    types = device.device_types
    if types & INPUT_ONLY_TYPES:
        return None
    if types & LIGHT_TYPES:
        return "light"
    if types & COVER_TYPES:
        return "cover"
    if types & CLIMATE_TYPES:
        return "climate"
    if types & CONDITIONAL_CLIMATE_TYPES:
        return "climate" if device.supports("setTemperature") else "switch"
    if types & FAN_TYPES:
        return "fan"
    if types & SWITCH_TYPES:
        return "switch"
    return None


def sensor_properties(device: IotDevice) -> list[str]:
    """返回应生成只读传感器实体的属性名。"""
    if device.is_composite_parent:
        return []
    result: list[str] = []
    for property_name, required_types in SENSOR_PROPERTY_TYPES.items():
        if device.property(property_name) is None:
            continue
        if required_types is not None and not (device.device_types & required_types):
            # 例：空调的 temperature 是目标温度，不是环境读数
            continue
        result.append(property_name)
    return result


def entity_counts(devices: Iterable[IotDevice]) -> dict[str, int]:
    """统计一次快照会产生的各平台实体数量。"""
    counts = {"light": 0, "cover": 0, "climate": 0, "fan": 0, "switch": 0, "sensor": 0}
    for device in devices:
        if device.is_composite_parent:
            continue
        platform = primary_platform(device)
        if platform:
            counts[platform] += 1
        counts["sensor"] += len(sensor_properties(device))
    return counts
