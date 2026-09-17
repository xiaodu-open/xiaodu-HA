"""XiaoDu climate entities."""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ATTR_TEMPERATURE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    OFF_VALUES,
    REQUEST_SET_FAN_SPEED,
    REQUEST_SET_MODE,
    REQUEST_SET_TEMPERATURE,
    REQUEST_TURN_OFF,
    REQUEST_TURN_ON,
)
from .coordinator import XiaoDuCoordinator
from .entity import XiaoDuEntity
from .mapping import (
    FAN_MODES,
    fan_mode_to_speed,
    primary_platform,
    speed_to_fan_mode,
    temperature_range,
)

MODE_TO_HVAC = {
    "制冷": HVACMode.COOL,
    "制热": HVACMode.HEAT,
    "除湿": HVACMode.DRY,
    "送风": HVACMode.FAN_ONLY,
    "自动": HVACMode.AUTO,
}
HVAC_TO_MODE = {value: key for key, value in MODE_TO_HVAC.items()}
EXPOSED_HVAC_MODES = (
    HVACMode.OFF,
    HVACMode.COOL,
    HVACMode.HEAT,
    HVACMode.FAN_ONLY,
    HVACMode.DRY,
    HVACMode.AUTO,
)
# 地暖 / 热水器 / 浴霸只会加热，没有制冷概念
HEAT_ONLY_TYPES = frozenset({"FLOOR_HEATER", "WATER_HEATER", "HEATER", "YUBA"})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """随设备发现增量创建空调实体。"""
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    def add_new() -> None:
        devices = [
            device
            for device in coordinator.data.values()
            if device.device_id not in known and primary_platform(device) == "climate"
        ]
        if devices:
            async_add_entities(
                XiaoDuClimate(coordinator, device.device_id) for device in devices
            )
            known.update(device.device_id for device in devices)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class XiaoDuClimate(XiaoDuEntity, ClimateEntity):
    """小度空调、地暖、热水器、浴霸等带温度调节的设备。"""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1.0

    def __init__(self, coordinator: XiaoDuCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "climate")
        minimum, maximum = temperature_range(self.device)
        self._attr_min_temp = minimum
        self._attr_max_temp = maximum

    @property
    def _is_heat_only(self) -> bool:
        return bool(self.device.device_types & HEAT_ONLY_TYPES)

    @property
    def supported_features(self) -> ClimateEntityFeature:
        features = ClimateEntityFeature(0)
        if self.device.supports("setTemperature"):
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        if self.device.supports("setFanSpeed") and self.fan_modes:
            features |= ClimateEntityFeature.FAN_MODE
        if self.device.supports("turnOn"):
            features |= ClimateEntityFeature.TURN_ON
        if self.device.supports("turnOff"):
            features |= ClimateEntityFeature.TURN_OFF
        return features

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """不支持 setMode 时只暴露「关」与当前模式，避免出现控不了的选项。"""
        if self._is_heat_only:
            return [HVACMode.OFF, HVACMode.HEAT]
        if self.device.supports("setMode"):
            return list(EXPOSED_HVAC_MODES)
        current = MODE_TO_HVAC.get(str(self.device.property("mode")))
        return [HVACMode.OFF, current or HVACMode.COOL]

    @property
    def hvac_mode(self) -> HVACMode | None:
        state = str(self.device.property("turnOnState") or "").upper()
        if state in OFF_VALUES:
            actual = HVACMode.OFF
        elif self._is_heat_only:
            actual = HVACMode.HEAT
        else:
            actual = MODE_TO_HVAC.get(str(self.device.property("mode")), HVACMode.AUTO)
        return self.pending_state("hvac_mode", actual)

    @property
    def target_temperature(self) -> float | None:
        value = self.device.property("temperature", "targetTemperature")
        try:
            actual = float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
        return self.pending_state("target_temperature", actual)

    @property
    def fan_modes(self) -> list[str] | None:
        if not self.device.supports("setFanSpeed"):
            return None
        return list(FAN_MODES)

    @property
    def fan_mode(self) -> str | None:
        actual = speed_to_fan_mode(
            self.device.property("fanSpeed"), self.device.options("fanSpeed")
        )
        return self.pending_state("fan_mode", actual)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes = super().extra_state_attributes
        attributes["xiaodu_fan_speed"] = self.device.property("fanSpeed")
        attributes["xiaodu_mode"] = self.device.property("mode")
        attributes["xiaodu_fan_speed_options"] = self.device.options("fanSpeed").get(
            "levelRange", {}
        )
        attributes["xiaodu_fan_speed_range"] = self.device.options("fanSpeed").get(
            "range", {}
        )
        return attributes

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            raise HomeAssistantError("需要指定目标温度")
        await self._async_control(
            REQUEST_SET_TEMPERATURE,
            pending_state=("target_temperature", float(temperature)),
            temperature=temperature,
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if not self.fan_modes or fan_mode not in self.fan_modes:
            raise HomeAssistantError(f"不支持的风速档位：{fan_mode}")
        speed = fan_mode_to_speed(fan_mode, self.device.options("fanSpeed"))
        if speed is None:
            raise HomeAssistantError(f"不支持的风速档位：{fan_mode}")
        await self._async_control(
            REQUEST_SET_FAN_SPEED,
            pending_state=("fan_mode", fan_mode),
            speed=speed,
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._async_control(
                REQUEST_TURN_OFF, pending_state=("hvac_mode", HVACMode.OFF)
            )
            return
        if self._is_heat_only:
            # 地暖/热水器只有开与关，HEAT 即开机
            await self._async_control(
                REQUEST_TURN_ON, pending_state=("hvac_mode", HVACMode.HEAT)
            )
            return
        current = MODE_TO_HVAC.get(str(self.device.property("mode")), HVACMode.AUTO)
        if hvac_mode == current:
            # 模式没变，只需开机
            await self._async_control(
                REQUEST_TURN_ON, pending_state=("hvac_mode", current)
            )
            return
        mode = HVAC_TO_MODE.get(hvac_mode)
        if mode is None:
            raise HomeAssistantError(f"不支持的空调模式：{hvac_mode}")
        await self._async_control(
            REQUEST_SET_MODE,
            pending_state=("hvac_mode", hvac_mode),
            mode=mode,
        )

    async def async_turn_on(self) -> None:
        await self._async_control(REQUEST_TURN_ON)

    async def async_turn_off(self) -> None:
        await self._async_control(
            REQUEST_TURN_OFF, pending_state=("hvac_mode", HVACMode.OFF)
        )
