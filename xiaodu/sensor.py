"""XiaoDu 只读属性传感器。"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    CONCENTRATION_MILLIGRAMS_PER_CUBIC_METER,
    PERCENTAGE,
    UnitOfMass,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import XiaoDuCoordinator
from .entity import XiaoDuEntity
from .mapping import sensor_properties

SENSOR_SPECS: dict[str, tuple[SensorDeviceClass | None, str | None]] = {
    "temperature": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    "humidity": (SensorDeviceClass.HUMIDITY, PERCENTAGE),
    "targetHumidity": (SensorDeviceClass.HUMIDITY, PERCENTAGE),
    "pm2.5": (SensorDeviceClass.PM25, CONCENTRATION_MICROGRAMS_PER_CUBIC_METER),
    "pm10": (SensorDeviceClass.PM10, CONCENTRATION_MICROGRAMS_PER_CUBIC_METER),
    "hcho": (None, CONCENTRATION_MILLIGRAMS_PER_CUBIC_METER),
    "tovc": (None, CONCENTRATION_MILLIGRAMS_PER_CUBIC_METER),
    "airPressure": (SensorDeviceClass.ATMOSPHERIC_PRESSURE, UnitOfPressure.HPA),
    "electricityCapacityPercentage": (SensorDeviceClass.BATTERY, PERCENTAGE),
    "electricityCapacity": (SensorDeviceClass.BATTERY, PERCENTAGE),
    "deviceState": (SensorDeviceClass.ENUM, None),
    "weight": (SensorDeviceClass.WEIGHT, UnitOfMass.KILOGRAMS),
    "impedance": (None, "Ω"),
    "bmi": (None, None),
    "bodyFatPercentage": (None, PERCENTAGE),
    "bodyWaterPercentage": (None, PERCENTAGE),
    "muscleMass": (SensorDeviceClass.WEIGHT, UnitOfMass.KILOGRAMS),
}
# 属性名可能含点（pm2.5），translation_key 与 unique_id 后缀必须是合法标识
SENSOR_TRANSLATION_KEYS = {
    "temperature": "temperature",
    "humidity": "humidity",
    "targetHumidity": "target_humidity",
    "pm2.5": "pm25",
    "pm10": "pm10",
    "hcho": "hcho",
    "tovc": "tvoc",
    "airPressure": "air_pressure",
    "electricityCapacityPercentage": "battery",
    "electricityCapacity": "battery",
    "deviceState": "device_state",
    "weight": "weight",
    "impedance": "impedance",
    "bmi": "bmi",
    "bodyFatPercentage": "body_fat",
    "bodyWaterPercentage": "body_water",
    "muscleMass": "muscle_mass",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """随设备发现增量创建传感器实体。"""
    coordinator = entry.runtime_data.coordinator
    known: set[tuple[str, str]] = set()

    def add_new() -> None:
        entities: list[XiaoDuSensor] = []
        for device in coordinator.data.values():
            for property_name in sensor_properties(device):
                key = (device.device_id, property_name)
                if key in known:
                    continue
                device_class, unit = SENSOR_SPECS[property_name]
                entities.append(
                    XiaoDuSensor(
                        coordinator,
                        device.device_id,
                        property_name,
                        device_class,
                        unit,
                    )
                )
                known.add(key)
        if entities:
            async_add_entities(entities)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class XiaoDuSensor(XiaoDuEntity, SensorEntity):
    """把一个归一化属性暴露为 HA 传感器。

    实体名由 `translation_key` 决定（温度 / 湿度 / PM2.5 ...），因此不参与子设备聚合改名。
    已知限制：若同一个复合父设备下有多个子设备各带同名属性，合并后友好名会撞车
    （都是「父设备名 温度」）。当前接口数据里不存在这种设备，真出现再处理。
    """

    _attr_state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT
    _keep_translated_name = True

    def __init__(
        self,
        coordinator: XiaoDuCoordinator,
        device_id: str,
        property_name: str,
        device_class: SensorDeviceClass | None,
        native_unit: str | None,
    ) -> None:
        super().__init__(coordinator, device_id, property_name.replace(".", "_"))
        self.property_name = property_name
        self._attr_translation_key = SENSOR_TRANSLATION_KEYS[property_name]
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = native_unit
        if device_class == SensorDeviceClass.ENUM:
            self._attr_state_class = None

    @property
    def native_value(self) -> Any:
        value = self.device.property(self.property_name)
        if self._attr_device_class == SensorDeviceClass.ENUM:
            return str(value) if value is not None else None
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @property
    def options(self) -> list[str] | None:
        if self._attr_device_class != SensorDeviceClass.ENUM:
            return None
        detail = self.device.options(self.property_name)
        values = detail.get("range")
        if isinstance(values, (list, dict)):
            return [str(value) for value in values]
        current = self.device.property(self.property_name)
        return [str(current)] if current is not None else []
