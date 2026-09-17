"""XiaoDu scene entities。

场景通过 SCENELIST 拉取、TRIGGERSCENE 按名称触发。
服务端会触发所有同名场景（McpTrait::triggerScene），这是既有行为。
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import XiaoDuSceneCoordinator
from .models import SceneItem


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """随场景发现增量创建场景实体。"""
    coordinator = entry.runtime_data.scene_coordinator
    known: set[str] = set()

    def add_new() -> None:
        if not coordinator.data:
            return
        scenes = [
            scene
            for scene in coordinator.data.values()
            if scene.scene_id not in known
        ]
        if scenes:
            async_add_entities(
                XiaoDuScene(coordinator, scene.scene_id) for scene in scenes
            )
            known.update(scene.scene_id for scene in scenes)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class XiaoDuScene(CoordinatorEntity[XiaoDuSceneCoordinator], Scene):
    """一个小度场景。

    场景不是设备，不挂 device_info：挂到设备上会让实体 ID 带上设备名前缀
    （scene.小度场景_回家），也会在设备列表里多出一个假设备。
    """

    _attr_has_entity_name = False

    def __init__(self, coordinator: XiaoDuSceneCoordinator, scene_id: str) -> None:
        super().__init__(coordinator, context=scene_id)
        self._scene_id = scene_id
        self._last_scene = coordinator.data[scene_id]
        self._attr_unique_id = f"scene_{scene_id}"

    @property
    def scene(self) -> SceneItem:
        current = self.coordinator.data.get(self._scene_id)
        if current is not None:
            self._last_scene = current
        return self._last_scene

    @property
    def name(self) -> str:
        return self.scene.name

    @property
    def available(self) -> bool:
        return super().available and self._scene_id in self.coordinator.data

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes: dict[str, Any] = {
            "xiaodu_scene_id": self.scene.scene_id,
            "xiaodu_third_party": self.scene.is_third_party,
        }
        if self.scene.scene_type:
            attributes["xiaodu_scene_type"] = self.scene.scene_type
        if self.scene.room_name:
            attributes["xiaodu_room"] = self.scene.room_name
        if self.scene.floor_name:
            attributes["xiaodu_floor"] = self.scene.floor_name
        return attributes

    async def async_activate(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_trigger_scene(self.scene.name)
