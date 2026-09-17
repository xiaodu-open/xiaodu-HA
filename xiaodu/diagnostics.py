"""XiaoDu 诊断信息（不含凭据、设备 ID 与设备名）。"""
from __future__ import annotations

from collections import Counter
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DEFAULT_SCAN_INTERVAL
from .coordinator import XiaoDuRuntimeData
from .mapping import entity_counts


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry[XiaoDuRuntimeData]
) -> dict[str, Any]:
    """返回聚合后的设备统计信息。"""
    coordinator = entry.runtime_data.coordinator
    scene_coordinator = entry.runtime_data.scene_coordinator
    devices = list(coordinator.data.values())
    type_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    available = 0
    for device in devices:
        type_counts.update(device.device_types)
        action_counts.update(device.raw_capabilities)
        available += int(device.available)
    return {
        "device_count": len(devices),
        "available_count": available,
        "composite_parent_count": sum(
            device.is_composite_parent for device in devices
        ),
        "device_type_counts": dict(type_counts),
        "action_counts": dict(action_counts),
        "entity_counts": entity_counts(devices),
        "scene_count": len(scene_coordinator.data or {}),
        "third_party_scene_count": sum(
            scene.is_third_party for scene in (scene_coordinator.data or {}).values()
        ),
        "scene_last_update_success": scene_coordinator.last_update_success,
        "last_update_success": coordinator.last_update_success,
        "update_interval_seconds": int(DEFAULT_SCAN_INTERVAL.total_seconds()),
    }
