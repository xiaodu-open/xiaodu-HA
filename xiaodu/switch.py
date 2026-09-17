"""XiaoDu switch entities."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import REQUEST_TURN_OFF, REQUEST_TURN_ON
from .coordinator import XiaoDuCoordinator
from .entity import XiaoDuEntity
from .mapping import primary_platform


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """随设备发现增量创建开关实体。"""
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    def add_new() -> None:
        devices = [
            device
            for device in coordinator.data.values()
            if device.device_id not in known and primary_platform(device) == "switch"
        ]
        if devices:
            async_add_entities(
                XiaoDuSwitch(coordinator, device.device_id) for device in devices
            )
            known.update(device.device_id for device in devices)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class XiaoDuSwitch(XiaoDuEntity, SwitchEntity):
    """小度开关 / 插座 / 音箱等只支持开关的设备。"""

    def __init__(self, coordinator: XiaoDuCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id, "switch")
        if self.device.device_types & {"SOCKET", "OUTLET", "PLUG", "PLUGIN"}:
            self._attr_device_class = SwitchDeviceClass.OUTLET

    @property
    def is_on(self) -> bool | None:
        return self.pending_power_state

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_control(REQUEST_TURN_ON, pending_state=("power_state", True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_control(
            REQUEST_TURN_OFF, pending_state=("power_state", False)
        )
