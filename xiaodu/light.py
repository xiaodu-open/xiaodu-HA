"""XiaoDu light entities."""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    COLOR_TEMP_MAX_KELVIN,
    COLOR_TEMP_MIN_KELVIN,
    REQUEST_SET_BRIGHTNESS,
    REQUEST_SET_COLOR_TEMPERATURE,
    REQUEST_TURN_OFF,
    REQUEST_TURN_ON,
)
from .coordinator import XiaoDuCoordinator
from .entity import XiaoDuEntity
from .mapping import (
    color_temp_kelvin_to_pct,
    color_temp_pct_to_kelvin,
    primary_platform,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """随设备发现增量创建灯实体。"""
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    def add_new() -> None:
        devices = [
            device
            for device in coordinator.data.values()
            if device.device_id not in known and primary_platform(device) == "light"
        ]
        if devices:
            async_add_entities(
                XiaoDuLight(coordinator, device.device_id) for device in devices
            )
            known.update(device.device_id for device in devices)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class XiaoDuLight(XiaoDuEntity, LightEntity):
    """小度灯类设备。

    MCP 没有 SetColorRequest，因此彩灯（RGB/RGBW/RGBCW）也只暴露亮度与色温。
    """

    _attr_min_color_temp_kelvin = COLOR_TEMP_MIN_KELVIN
    _attr_max_color_temp_kelvin = COLOR_TEMP_MAX_KELVIN

    def __init__(self, coordinator: XiaoDuCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "light")

    @property
    def is_on(self) -> bool | None:
        return self.pending_power_state

    @property
    def _has_brightness(self) -> bool:
        return self.device.property("brightness") is not None and self.device.supports(
            "setBrightnessPercentage"
        )

    @property
    def _has_color_temp(self) -> bool:
        return self.device.property(
            "colorTemperatureInKelvin"
        ) is not None and self.device.supports("setColorTemperature")

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """HA 约定 COLOR_TEMP 已隐含亮度调节，故有色温时只报 COLOR_TEMP。"""
        if self._has_color_temp:
            return {ColorMode.COLOR_TEMP}
        if self._has_brightness:
            return {ColorMode.BRIGHTNESS}
        return {ColorMode.ONOFF}

    @property
    def color_mode(self) -> ColorMode:
        return next(iter(self.supported_color_modes))

    @property
    def brightness(self) -> int | None:
        """上游 brightness 为 0-100 百分比，HA 需要 0-255。"""
        if not self._has_brightness:
            return None
        try:
            percentage = float(self.device.property("brightness"))
        except (TypeError, ValueError):
            return None
        return round(max(0.0, min(100.0, percentage)) * 255 / 100)

    @property
    def color_temp_kelvin(self) -> int | None:
        """上游 colorTemperatureInKelvin 实际是 0-100 百分比，需换算成开尔文。"""
        if not self._has_color_temp:
            return None
        actual = color_temp_pct_to_kelvin(
            self.device.property("colorTemperatureInKelvin")
        )
        return self.pending_state("color_temp", actual)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """开灯 / 调亮度 / 调色温。

        MCP 一条指令只能带一个属性，同时指定色温与亮度时拆成两条下发。
        """
        sent = False
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            if not self._has_color_temp:
                raise HomeAssistantError("该小度灯设备不支持色温调节")
            percentage = color_temp_kelvin_to_pct(kwargs[ATTR_COLOR_TEMP_KELVIN])
            if percentage is None:
                raise HomeAssistantError("色温取值无效")
            await self._async_control(
                REQUEST_SET_COLOR_TEMPERATURE,
                pending_state=("color_temp", kwargs[ATTR_COLOR_TEMP_KELVIN]),
                colorTemperatureValue=percentage,
            )
            sent = True

        if ATTR_BRIGHTNESS in kwargs:
            if not self._has_brightness:
                raise HomeAssistantError("该小度灯设备不支持亮度调节")
            brightness = round(float(kwargs[ATTR_BRIGHTNESS]) * 100 / 255)
            await self._async_control(
                REQUEST_SET_BRIGHTNESS,
                pending_state=("power_state", True),
                bright=max(0, min(100, brightness)),
            )
            sent = True

        if not sent:
            await self._async_control(
                REQUEST_TURN_ON, pending_state=("power_state", True)
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_control(
            REQUEST_TURN_OFF, pending_state=("power_state", False)
        )
