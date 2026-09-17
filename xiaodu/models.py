"""XiaoDu 设备的归一化数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class IotDevice:
    """一个归一化后的小度 appliance。"""

    device_id: str
    name: str
    room_name: str | None
    floor_name: str | None
    device_types: frozenset[str]
    description: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    property_options: dict[str, dict[str, Any]] = field(default_factory=dict)
    raw_capabilities: frozenset[str] = field(default_factory=frozenset)
    available: bool = True
    status: str | None = None
    parent_device_id: str | None = None
    is_composite_parent: bool = False

    def property(self, *names: str) -> Any:
        """返回首个存在的属性值（用于兼容上游多种字段名）。"""
        for name in names:
            if name in self.properties:
                return self.properties[name]
        return None

    def supports(self, *actions: str) -> bool:
        """判断上游 supportActions 是否包含其中任一动作。"""
        supported = {str(action).lower() for action in self.raw_capabilities}
        return any(str(action).lower() in supported for action in actions)

    def options(self, property_name: str) -> dict[str, Any]:
        """返回某属性的 detail / 取值范围元数据。"""
        return self.property_options.get(property_name, {})


@dataclass(frozen=True, slots=True)
class SceneItem:
    """一个归一化后的小度场景。

    TRIGGERSCENE 按名称触发（服务端会触发所有同名场景），因此 name 是控制主键，
    scene_id 只用于生成稳定的实体标识。
    """

    scene_id: str
    name: str
    scene_type: str | None = None
    room_name: str | None = None
    floor_name: str | None = None
    is_third_party: bool = False
