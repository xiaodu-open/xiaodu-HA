"""XiaoDu cover entities（窗帘 / 卷帘 / 百叶 / 开窗器）。

MCP 的窗帘能力：
- 开 / 关 → TurnOnRequest / TurnOffRequest
- 开合比例 → TurnOnRequest + degree(1-100)
- 百叶角度 → SetAngleRequest + angle
MCP 没有 PauseRequest，因此不支持「停止」。
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    COVER_DEVICE_CLASSES,
    REQUEST_SET_ANGLE,
    REQUEST_TURN_OFF,
    REQUEST_TURN_ON,
)
from .coordinator import XiaoDuCoordinator
from .entity import XiaoDuEntity, power_state
from .mapping import primary_platform


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """随设备发现增量创建窗帘实体。"""
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    def add_new() -> None:
        devices = [
            device
            for device in coordinator.data.values()
            if device.device_id not in known and primary_platform(device) == "cover"
        ]
        if devices:
            async_add_entities(
                XiaoDuCover(coordinator, device.device_id) for device in devices
            )
            known.update(device.device_id for device in devices)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class XiaoDuCover(XiaoDuEntity, CoverEntity):
    """小度窗帘类设备。"""

    def __init__(self, coordinator: XiaoDuCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "cover")
        for device_type in sorted(self.device.device_types):
            if device_type in COVER_DEVICE_CLASSES:
                self._attr_device_class = CoverDeviceClass(
                    COVER_DEVICE_CLASSES[device_type]
                )
                break

    @property
    def _has_position(self) -> bool:
        return self.device.property("degree") is not None and self.device.supports(
            "turnOnPercent", "turnOn"
        )

    @property
    def _has_tilt(self) -> bool:
        return self.device.property("angle") is not None and self.device.supports(
            "setAngle"
        )

    @property
    def supported_features(self) -> CoverEntityFeature:
        features = CoverEntityFeature(0)
        if self.device.supports("turnOn"):
            features |= CoverEntityFeature.OPEN
        if self.device.supports("turnOff"):
            features |= CoverEntityFeature.CLOSE
        if self._has_position:
            features |= CoverEntityFeature.SET_POSITION
        if self._has_tilt:
            features |= CoverEntityFeature.SET_TILT_POSITION
        return features

    @property
    def current_cover_position(self) -> int | None:
        """degree 即开合比例（0=全关，100=全开）。"""
        if not self._has_position:
            return None
        try:
            degree = int(float(self.device.property("degree")))
        except (TypeError, ValueError):
            return None
        return max(0, min(100, self.pending_state("position", degree)))

    @property
    def current_cover_tilt_position(self) -> int | None:
        if not self._has_tilt:
            return None
        try:
            angle = int(float(self.device.property("angle")))
        except (TypeError, ValueError):
            return None
        return max(0, min(100, self.pending_state("tilt", angle)))

    @property
    def is_closed(self) -> bool | None:
        """以 degree 为准；云端本身就是按 degree>0 反推 turnOnState 的。"""
        position = self.current_cover_position
        if position is not None:
            return position == 0
        state = self.pending_state("power_state", power_state(self.device))
        if state is None:
            return None
        return not state

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._async_control(
            REQUEST_TURN_ON,
            pending_state=("position", 100) if self._has_position else None,
        )

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._async_control(
            REQUEST_TURN_OFF,
            pending_state=("position", 0) if self._has_position else None,
        )

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """设置开合比例。

        degree 槽位下限是 1，position=0 语义上就是全关，改发 TurnOffRequest。
        """
        position = kwargs.get(ATTR_POSITION)
        if position is None:
            raise HomeAssistantError("需要指定开合比例")
        position = max(0, min(100, int(position)))
        if position == 0:
            await self.async_close_cover()
            return
        await self._async_control(
            REQUEST_TURN_ON,
            pending_state=("position", position),
            degree=position,
        )

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        angle = kwargs.get(ATTR_TILT_POSITION)
        if angle is None:
            raise HomeAssistantError("需要指定角度")
        angle = max(0, min(100, int(angle)))
        await self._async_control(
            REQUEST_SET_ANGLE,
            pending_state=("tilt", angle),
            angle=angle,
        )
