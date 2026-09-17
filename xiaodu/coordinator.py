"""DataUpdateCoordinator for the XiaoDu integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import XiaoDuApiError, XiaoDuAuthError, XiaoDuIotClient
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, SCENE_SCAN_INTERVAL
from .mapping import device_control_key
from .models import IotDevice, SceneItem

_LOGGER = logging.getLogger(__name__)


class XiaoDuCoordinator(DataUpdateCoordinator[dict[str, IotDevice]]):
    """周期性从云端拉取设备快照。"""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: XiaoDuIotClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client
        self.entry = entry

    async def _async_update_data(self) -> dict[str, IotDevice]:
        try:
            return await self.client.async_get_devices()
        except XiaoDuAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except XiaoDuApiError as err:
            raise UpdateFailed(str(err)) from err

    def is_name_ambiguous(self, device: IotDevice) -> bool:
        """判断「名称 + 房间 + 楼层」是否对应多个设备。

        小度 DEVICECONTROL 只能按名称与位置定位设备，命中多个时下发会控错，
        因此调用方应直接拒绝。
        """
        target = device_control_key(device)
        return (
            sum(
                device_control_key(current) == target and not current.is_composite_parent
                for current in self.data.values()
            )
            > 1
        )


class XiaoDuSceneCoordinator(DataUpdateCoordinator[dict[str, SceneItem]]):
    """周期性拉取场景列表。

    与设备 coordinator 独立：场景列表拉取失败不应让设备实体变不可用，反之亦然。
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: XiaoDuIotClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_scene",
            update_interval=SCENE_SCAN_INTERVAL,
        )
        self.client = client
        self.entry = entry

    async def _async_update_data(self) -> dict[str, SceneItem]:
        try:
            return await self.client.async_get_scenes()
        except XiaoDuAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except XiaoDuApiError as err:
            raise UpdateFailed(str(err)) from err


class XiaoDuRuntimeData:
    """挂在 ConfigEntry 上的运行时对象。"""

    def __init__(
        self,
        client: XiaoDuIotClient,
        coordinator: XiaoDuCoordinator,
        scene_coordinator: XiaoDuSceneCoordinator,
    ) -> None:
        self.client = client
        self.coordinator = coordinator
        self.scene_coordinator = scene_coordinator


type XiaoDuConfigEntry = ConfigEntry[XiaoDuRuntimeData]
