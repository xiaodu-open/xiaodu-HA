"""Base entity for the XiaoDu integration."""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from time import monotonic
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    ON_VALUES,
    POWER_STATE_PENDING_TIMEOUT,
    POWER_STATE_REFRESH_DELAYS,
)
from .coordinator import XiaoDuCoordinator
from .mapping import resolve_pending_power_state
from .models import IotDevice

_LOGGER = logging.getLogger(__name__)

# HA 请求名 -> 上游 supportActions 中的动作名
_REQUEST_ACTIONS = {
    "TurnOnRequest": "turnOn",
    "TurnOffRequest": "turnOff",
    "SetBrightnessPercentageRequest": "setBrightnessPercentage",
    "SetColorTemperatureRequest": "setColorTemperature",
    "SetTemperatureRequest": "setTemperature",
    "SetModeRequest": "setMode",
    "SetFanSpeedRequest": "setFanSpeed",
    "SetAngleRequest": "setAngle",
}


def request_action(request_name: str) -> str:
    """把 HA 请求名转换为上游动作名。"""
    return _REQUEST_ACTIONS.get(request_name, request_name)


def power_state(device: IotDevice) -> bool | None:
    """从设备属性中解析开关状态。"""
    value = device.property("turnOnState", "powerState", "power")
    if value is None:
        return None
    return str(value).upper() in ON_VALUES


class XiaoDuEntity(CoordinatorEntity[XiaoDuCoordinator]):
    """XiaoDu 实体基类。"""

    _attr_has_entity_name = True
    # 子类置 True 表示实体名由 translation_key 决定，不参与子设备聚合改名（见 sensor.py）
    _keep_translated_name = False

    def __init__(
        self, coordinator: XiaoDuCoordinator, device_id: str, suffix: str
    ) -> None:
        super().__init__(coordinator, context=device_id)
        self._device_id = device_id
        self._last_device = coordinator.data[device_id]
        self._attr_unique_id = f"{device_id}_{suffix}"
        # HA 只在实体首次注册时读一次 device_info，必须在这里就把归属定下来
        parent = self._parent
        self._attr_device_info = self._make_device_info(parent or self._last_device)
        if self._keep_translated_name:
            self._attr_name = None
        elif parent is not None:
            # 多路开关等复合设备：三个子实体挂在同一设备下，
            # 实体名必须用子设备自己的名字（左键/中键/右键），否则会同名
            self._attr_name = self._last_device.name
        else:
            self._attr_name = None
        self._pending_states: dict[str, tuple[Any, float]] = {}
        self._pending_refresh_attempt = 0
        self._pending_refresh_cancel: Callable[[], None] | None = None

    @property
    def _parent(self) -> IotDevice | None:
        """返回复合父设备；无父设备或父设备不在快照里时返回 None。"""
        parent_id = self._last_device.parent_device_id
        if not parent_id:
            return None
        return self.coordinator.data.get(parent_id)

    @property
    def device(self) -> IotDevice:
        """返回当前设备快照；设备临时消失时沿用上一次快照。"""
        current = self.coordinator.data.get(self._device_id)
        if current is not None:
            self._last_device = current
        return self._last_device

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._device_id in self.coordinator.data
            and self.device.available
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes: dict[str, Any] = {
            "xiaodu_device_types": sorted(self.device.device_types),
            "xiaodu_supported_actions": sorted(self.device.raw_capabilities),
            "xiaodu_properties": self.device.properties,
            "xiaodu_property_options": self.device.property_options,
        }
        if self.device.description:
            attributes["xiaodu_description"] = self.device.description
        if self.device.status:
            attributes["xiaodu_status"] = self.device.status
        if self.device.floor_name:
            attributes["xiaodu_floor"] = self.device.floor_name
        if self.device.parent_device_id:
            attributes["xiaodu_parent_device_id"] = self.device.parent_device_id
        return attributes

    @staticmethod
    def _make_device_info(owner: IotDevice) -> DeviceInfo:
        """owner 为实体归属的设备：有复合父设备时是父设备，否则是自身。"""
        return DeviceInfo(
            identifiers={(DOMAIN, owner.device_id)},
            name=owner.name,
            manufacturer="Baidu XiaoDu",
            model=owner.description or ", ".join(sorted(owner.device_types)),
            suggested_area=owner.room_name,
        )

    @property
    def pending_power_state(self) -> bool | None:
        """在云端状态追上之前，先返回刚刚下发的开关状态。"""
        return self.pending_state("power_state", power_state(self.device))

    def pending_state(self, key: str, actual: Any) -> Any:
        """返回乐观值，直到云端值追上或超时。"""
        pending = self._pending_states.get(key)
        if pending is None:
            return actual
        displayed, complete = resolve_pending_power_state(
            pending[0],
            pending[1],
            actual,
            monotonic(),
            POWER_STATE_PENDING_TIMEOUT.total_seconds(),
        )
        if complete:
            self._clear_pending_state(key)
        return displayed

    async def _async_control(
        self,
        request_name: str,
        *,
        pending_state: tuple[str, Any] | None = None,
        **values: Any,
    ) -> None:
        """校验后下发控制指令，并驱动乐观状态与补刷。"""
        if self.coordinator.is_name_ambiguous(self.device):
            raise HomeAssistantError(
                f"小度设备名称与位置重复，无法准确定位：{self.device.name}"
            )
        if not self.device.supports(request_action(request_name)):
            raise HomeAssistantError(f"{self.device.name} 不支持 {request_name}")

        await self.coordinator.client.async_control(
            self.device, request_name, **values
        )

        if pending_state is not None:
            self._set_pending_state(*pending_state)
            self.async_write_ha_state()
        try:
            await self.coordinator.async_request_refresh()
        except Exception as err:  # noqa: BLE001 - 刷新失败不应让控制调用失败
            _LOGGER.debug("小度状态即时刷新失败：%s", err)
        if pending_state is not None and self._pending_states:
            self._schedule_pending_refresh()

    def _set_pending_state(self, key: str, value: Any) -> None:
        self._pending_states[key] = (value, monotonic())
        self._pending_refresh_attempt = 0

    def _clear_pending_state(self, key: str | None = None) -> None:
        if key is None:
            self._pending_states.clear()
        else:
            self._pending_states.pop(key, None)
        self._pending_refresh_attempt = 0
        if not self._pending_states and self._pending_refresh_cancel is not None:
            self._pending_refresh_cancel()
            self._pending_refresh_cancel = None

    def _schedule_pending_refresh(self) -> None:
        """按 2/5/10/13 秒递进补刷，直到乐观状态结算。"""
        if self._pending_refresh_cancel is not None:
            self._pending_refresh_cancel()
        if not self._pending_states:
            return
        delay = POWER_STATE_REFRESH_DELAYS[
            min(self._pending_refresh_attempt, len(POWER_STATE_REFRESH_DELAYS) - 1)
        ]
        self._pending_refresh_attempt += 1
        self._pending_refresh_cancel = async_call_later(
            self.hass, timedelta(seconds=delay), self._async_pending_refresh
        )

    async def _async_pending_refresh(self, _now: datetime) -> None:
        self._pending_refresh_cancel = None
        if not self._pending_states:
            return
        try:
            await self.coordinator.async_request_refresh()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("小度状态延迟刷新失败：%s", err)
        if self._pending_states:
            self._schedule_pending_refresh()
        else:
            self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """实体移除时取消未完成的延迟刷新。"""
        self._clear_pending_state()
        await super().async_will_remove_from_hass()
