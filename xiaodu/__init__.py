"""The XiaoDu integration."""
from __future__ import annotations

import logging

from aiohttp import ClientError, ClientResponseError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .api import XiaoDuIotClient, async_new_session
from .const import DOMAIN, PLATFORMS
from .coordinator import (
    XiaoDuCoordinator,
    XiaoDuRuntimeData,
    XiaoDuSceneCoordinator,
)
from .mapping import primary_platform, sensor_properties
from .oauth import XiaoDuProxyOAuth2Implementation

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """注册走中转服务的 OAuth2 实现。"""
    config_entry_oauth2_flow.async_register_implementation(
        hass,
        DOMAIN,
        XiaoDuProxyOAuth2Implementation(hass),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """从 Config Entry 初始化 XiaoDu 集成。"""
    if entry.data.get("auth_implementation") != DOMAIN:
        # 2.0.0 之前的条目由内置 client_secret 直连百度换出，token 无法经中转刷新
        raise ConfigEntryAuthFailed("需要重新授权（授权方式已升级为中转服务）")

    implementation = (
        await config_entry_oauth2_flow.async_get_config_entry_implementation(
            hass, entry
        )
    )
    oauth_session = config_entry_oauth2_flow.OAuth2Session(
        hass, entry, implementation
    )
    try:
        await oauth_session.async_ensure_token_valid()
    except ClientResponseError as err:
        # 中转服务对 refresh_token 失效返回 400
        if err.status in (400, 401, 403):
            raise ConfigEntryAuthFailed("授权已失效，请重新授权") from err
        raise ConfigEntryNotReady(f"中转服务异常：{err}") from err
    except ClientError as err:
        raise ConfigEntryNotReady(f"无法连接中转服务：{err}") from err

    async def _async_token() -> str:
        await oauth_session.async_ensure_token_valid()
        return oauth_session.token["access_token"]

    api_session = async_new_session(hass)
    client = XiaoDuIotClient(api_session, _async_token)
    coordinator = XiaoDuCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    scene_coordinator = XiaoDuSceneCoordinator(hass, entry, client)
    # 场景拉取失败不应阻塞设备接入，因此不用 async_config_entry_first_refresh
    await scene_coordinator.async_refresh()

    _migrate_entity_unique_ids(hass, entry, set(coordinator.data))
    _remove_stale_platform_entities(hass, entry, coordinator)

    entry.runtime_data = XiaoDuRuntimeData(client, coordinator, scene_coordinator)

    registry = dr.async_get(hass)

    def register_devices() -> None:
        """把设备写入设备注册表，使无实体的设备也能在 UI 中出现。

        复合父设备（多路开关面板）本身不产生控制实体，但必须注册：
        它的子设备实体会挂到它下面，实现一张卡片操作多路。
        反之，已归入父设备的子设备不再单独注册。
        """
        for device in coordinator.data.values():
            if device.parent_device_id in coordinator.data:
                continue
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, device.device_id)},
                manufacturer="Baidu XiaoDu",
                model=device.description or ", ".join(sorted(device.device_types)),
                name=device.name,
                suggested_area=device.room_name,
            )

    register_devices()
    entry.async_on_unload(coordinator.async_add_listener(register_devices))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # 必须在平台加载之后：此时子设备实体已按新的 device_info 重新绑定到父设备，
    # 旧的子设备记录变成空设备，删除它不会连带删掉实体（否则实体 ID 会重新生成）
    _remove_merged_child_devices(hass, entry, coordinator)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载 Config Entry。

    会话由 async_create_clientsession 创建，HA 会自行回收，无需手动关闭。
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _migrate_entity_unique_ids(
    hass: HomeAssistant, entry: ConfigEntry, device_ids: set[str]
) -> None:
    """迁移 3.0.0 之前的实体标识。

    - 旧版 unique_id 就是 device_id，新版为 `{device_id}_{platform}`；
      不迁移会让历史统计数据与自动化全部指向孤儿实体。
    - 旧版的 media_player 实体（播放控制从未真正生效）已随平台移除，直接清理。
    """
    registry = er.async_get(hass)
    existing = {
        entity.unique_id
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.domain == "media_player":
            registry.async_remove(entity.entity_id)
            continue
        if entity.unique_id not in device_ids:
            continue
        new_unique_id = f"{entity.unique_id}_{entity.domain}"
        if new_unique_id in existing:
            continue
        _LOGGER.debug(
            "迁移实体 %s 的 unique_id：%s -> %s",
            entity.entity_id,
            entity.unique_id,
            new_unique_id,
        )
        registry.async_update_entity(entity.entity_id, new_unique_id=new_unique_id)
        existing.add(new_unique_id)


def _remove_stale_platform_entities(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: XiaoDuCoordinator
) -> None:
    """清理因品类归类变化而失效的旧实体。

    3.1.0 起窗帘、风扇从 switch 独立出去，地暖/热水器按能力在 climate 与 switch 之间移动。
    旧实体的 unique_id 后缀与新平台不符时会永久 unavailable，直接删除。
    """
    registry = er.async_get(hass)
    expected: set[str] = set()
    for device in coordinator.data.values():
        platform = primary_platform(device)
        if platform:
            expected.add(f"{device.device_id}_{platform}")
        for property_name in sensor_properties(device):
            expected.add(f"{device.device_id}_{property_name.replace('.', '_')}")

    known_device_ids = set(coordinator.data)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.domain == "scene":
            continue
        unique_id = entity.unique_id
        device_id, _, _suffix = unique_id.rpartition("_")
        if device_id not in known_device_ids:
            # 设备已解绑或标识变化，交给 HA 常规的孤儿实体机制处理
            continue
        if unique_id not in expected:
            _LOGGER.debug("移除失效实体 %s（unique_id=%s）", entity.entity_id, unique_id)
            registry.async_remove(entity.entity_id)


def _remove_merged_child_devices(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: XiaoDuCoordinator
) -> None:
    """删除已并入复合父设备的子设备记录。

    3.2.0 起多路开关的每一路不再是独立设备，实体统一挂到面板设备下。
    旧的子设备记录会变成没有实体的空设备，HA 不会自己清理。
    """
    registry = dr.async_get(hass)
    entities = er.async_get(hass)
    merged_ids = {
        device.device_id
        for device in coordinator.data.values()
        if device.parent_device_id in coordinator.data
    }
    if not merged_ids:
        return
    for device_entry in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if not any(
            domain == DOMAIN and identifier in merged_ids
            for domain, identifier in device_entry.identifiers
        ):
            continue
        if er.async_entries_for_device(entities, device_entry.id, True):
            # 仍有实体挂在上面，删除会连带删实体，交给下次启动
            _LOGGER.debug("子设备 %s 仍有实体，暂不删除", device_entry.name)
            continue
        _LOGGER.debug("移除已合并的空子设备记录 %s", device_entry.name)
        registry.async_remove_device(device_entry.id)
