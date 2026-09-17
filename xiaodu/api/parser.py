"""把小度 DEVICELIST 原始响应解析为稳定的 IotDevice 模型。"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Any

from ..const import UNREACHABLE_VALUES
from ..models import IotDevice, SceneItem
from .exceptions import XiaoDuProtocolError


def _lookup(data: Mapping[str, Any], *names: str) -> Any:
    """按字段名查找，兼容上游大小写不一致。"""
    lowered = {str(key).lower(): value for key, value in data.items()}
    for name in names:
        if name in data:
            return data[name]
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _stable_fallback(*parts: object) -> str:
    """为缺少 applianceId 的设备生成稳定 ID（重启后不变）。"""
    text = "\x1f".join(str(part or "").strip().lower() for part in parts)
    return hashlib.sha256(text.encode()).hexdigest()[:24]


def stable_fallback_id(*parts: object) -> str:
    """对外暴露稳定回退 ID 的生成方式。"""
    return _stable_fallback(*parts)


def _flatten_appliances(
    appliances: Iterable[Any], parent_id: str | None = None
) -> Iterable[tuple[Mapping[str, Any], str | None]]:
    """展开父设备与 subAppliances，同时保留父子关系。"""
    for item in appliances:
        if not isinstance(item, Mapping):
            continue
        raw_id = _lookup(item, "applianceId", "deviceId", "id", "uuid", "num")
        item_id = str(raw_id) if raw_id else None
        yield item, parent_id
        children = item.get("subAppliances")
        if isinstance(children, list):
            yield from _flatten_appliances(children, item_id)


def _property_value(value: Any) -> Any:
    if isinstance(value, Mapping) and "value" in value:
        return value["value"]
    return value


def _property_detail(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    detail = value.get("detail")
    if isinstance(detail, Mapping):
        return dict(detail)
    return {}


def _collect_attributes(
    item: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """归集 attributes（dict / list 两种形态）与 stateSetting。"""
    properties: dict[str, Any] = {}
    property_options: dict[str, dict[str, Any]] = {}

    attributes = item.get("attributes")
    if isinstance(attributes, Mapping):
        pairs = list(attributes.items())
    elif isinstance(attributes, list):
        pairs = [
            (attribute["name"], attribute)
            for attribute in attributes
            if isinstance(attribute, Mapping) and attribute.get("name")
        ]
    else:
        pairs = []
    for key, attribute in pairs:
        property_name = str(key)
        properties[property_name] = _property_value(attribute)
        if detail := _property_detail(attribute):
            property_options[property_name] = detail

    state_setting = item.get("stateSetting")
    if isinstance(state_setting, Mapping):
        for key, setting in state_setting.items():
            property_name = str(key)
            properties.setdefault(property_name, _property_value(setting))
            if detail := _property_detail(setting):
                property_options.setdefault(property_name, detail)
            value_range = (
                setting.get("valueRangeMap") if isinstance(setting, Mapping) else None
            )
            if isinstance(value_range, Mapping):
                property_options.setdefault(property_name, {})["valueRangeMap"] = dict(
                    value_range
                )

    return properties, property_options


def parse_iot_devices(raw: Any) -> dict[str, IotDevice]:
    """解析 DEVICELIST 响应，返回 {device_id: IotDevice}。"""
    if not isinstance(raw, Mapping):
        raise XiaoDuProtocolError("DEVICELIST 响应不是对象")
    status = raw.get("status")
    if status not in (None, 0, "0"):
        raise XiaoDuProtocolError(f"DEVICELIST 失败：status={status}")
    data = raw.get("data", raw)
    appliances = data.get("appliances") if isinstance(data, Mapping) else None
    if not isinstance(appliances, list):
        raise XiaoDuProtocolError("DEVICELIST 缺少 appliances 列表")

    devices: dict[str, IotDevice] = {}
    for item, parent_id in _flatten_appliances(appliances):
        name = str(_lookup(item, "friendlyName", "deviceName", "name") or "")
        if not name:
            # DEVICECONTROL 以 deviceName 定位设备，无名设备无法控制
            continue

        raw_id = _lookup(item, "applianceId", "deviceId", "id", "uuid", "num")

        types = _lookup(item, "applianceTypes", "deviceTypes", "type") or []
        if isinstance(types, str):
            types = [types]
        normalized_types = frozenset(str(value).upper() for value in types)

        properties, property_options = _collect_attributes(item)

        actions = _lookup(item, "supportActions", "actions") or []
        if isinstance(actions, str):
            actions = [actions]

        children = item.get("subAppliances")
        is_composite_parent = isinstance(children, list) and bool(children)

        # 采用「不可用白名单取反」：connectivity 缺失时视为在线，避免整屋误判离线
        connectivity = str(properties.get("connectivity") or "").upper()
        available = connectivity not in UNREACHABLE_VALUES

        device_id = str(
            raw_id
            or _stable_fallback(
                parent_id,
                _lookup(item, "floorName"),
                _lookup(item, "roomName"),
                name,
                *sorted(normalized_types),
            )
        )
        if device_id in devices:
            continue

        devices[device_id] = IotDevice(
            device_id=device_id,
            name=name,
            room_name=str(_lookup(item, "roomName") or "") or None,
            floor_name=str(_lookup(item, "floorName") or "") or None,
            device_types=normalized_types,
            description=str(_lookup(item, "friendlyDescription") or "") or None,
            properties=properties,
            property_options=property_options,
            raw_capabilities=frozenset(str(action) for action in actions),
            available=available,
            status=str(item.get("status") or "") or None,
            parent_device_id=parent_id,
            is_composite_parent=is_composite_parent,
        )
    return devices


def parse_scenes(raw: Any) -> dict[str, SceneItem]:
    """解析 SCENELIST 响应，返回 {scene_id: SceneItem}。

    只取 myScenes 与 thirdPartyScenes；recommendScenes 是「推荐但用户未创建」的模板，
    按名称触发会失败，因此不生成实体。
    """
    if not isinstance(raw, Mapping):
        raise XiaoDuProtocolError("SCENELIST 响应不是对象")
    status = raw.get("status")
    if status not in (None, 0, "0"):
        raise XiaoDuProtocolError(f"SCENELIST 失败：status={status}")
    data = raw.get("data", raw)
    if not isinstance(data, Mapping):
        raise XiaoDuProtocolError("SCENELIST 缺少 data")
    if "myScenes" not in data and "thirdPartyScenes" not in data:
        # 两个键都没有说明结构变了，宁可报错也不要静默上报「零场景」
        raise XiaoDuProtocolError("SCENELIST 缺少 myScenes / thirdPartyScenes")

    scenes: dict[str, SceneItem] = {}
    for key, is_third_party in (("myScenes", False), ("thirdPartyScenes", True)):
        items = data.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            name = str(_lookup(item, "name", "sceneName") or "")
            if not name:
                continue
            # isSet 为 0 表示场景只是推荐模板、用户并未真正创建
            is_set = _lookup(item, "isSet")
            if is_set is not None and str(is_set).lower() in ("0", "false"):
                continue
            raw_id = _lookup(item, "sceneId", "scenesId", "id")
            scene_id = str(raw_id or _stable_fallback(key, name))
            if scene_id in scenes:
                continue
            scenes[scene_id] = SceneItem(
                scene_id=scene_id,
                name=name,
                scene_type=str(_lookup(item, "type") or "") or None,
                room_name=str(_lookup(item, "groupName", "roomName") or "") or None,
                floor_name=str(_lookup(item, "floorName") or "") or None,
                is_third_party=is_third_party,
            )
    return scenes
