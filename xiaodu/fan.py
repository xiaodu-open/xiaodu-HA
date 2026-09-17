"""XiaoDu fan entities（电风扇 / 塔扇）。

风速走 preset_mode（低/中/高）而不是 percentage：上游 fanSpeed 是离散档位，
不同设备的档位数不同，用百分比会造成来回取整漂移。
工作模式（mode）不混进 preset_mode，仅在实体属性里可见。
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import REQUEST_SET_FAN_SPEED, REQUEST_TURN_OFF, REQUEST_TURN_ON
from .coordinator import XiaoDuCoordinator
from .entity import XiaoDuEntity
from .mapping import FAN_MODES, fan_mode_to_speed, primary_platform, speed_to_fan_mode


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """随设备发现增量创建风扇实体。"""
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    def add_new() -> None:
        devices = [
            device
            for device in coordinator.data.values()
            if device.device_id not in known and primary_platform(device) == "fan"
        ]
        if devices:
            async_add_entities(
                XiaoDuFan(coordinator, device.device_id) for device in devices
            )
            known.update(device.device_id for device in devices)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class XiaoDuFan(XiaoDuEntity, FanEntity):
    """小度风扇类设备。"""

    def __init__(self, coordinator: XiaoDuCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "fan")

    @property
    def supported_features(self) -> FanEntityFeature:
        features = FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
        if self.device.supports("setFanSpeed"):
            features |= FanEntityFeature.PRESET_MODE
        return features

    @property
    def is_on(self) -> bool | None:
        return self.pending_power_state

    @property
    def preset_modes(self) -> list[str] | None:
        if not self.device.supports("setFanSpeed"):
            return None
        return list(FAN_MODES)

    @property
    def preset_mode(self) -> str | None:
        actual = speed_to_fan_mode(
            self.device.property("fanSpeed", "windSpeed", "speed"),
            self.device.options("fanSpeed"),
        )
        return self.pending_state("preset_mode", actual)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes = super().extra_state_attributes
        attributes["xiaodu_fan_speed"] = self.device.property(
            "fanSpeed", "windSpeed", "speed"
        )
        attributes["xiaodu_mode"] = self.device.property("mode")
        return attributes

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        if preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
            return
        await self._async_control(REQUEST_TURN_ON, pending_state=("power_state", True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_control(
            REQUEST_TURN_OFF, pending_state=("power_state", False)
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if not self.preset_modes or preset_mode not in self.preset_modes:
            raise HomeAssistantError(f"不支持的风速档位：{preset_mode}")
        speed = fan_mode_to_speed(preset_mode, self.device.options("fanSpeed"))
        if speed is None:
            raise HomeAssistantError(f"不支持的风速档位：{preset_mode}")
        await self._async_control(
            REQUEST_SET_FAN_SPEED,
            pending_state=("preset_mode", preset_mode),
            speed=speed,
        )
