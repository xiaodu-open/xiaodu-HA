"""百度小度 smarthome MCP 接口的异步客户端。

鉴权采用 OAuth access_token，以请求头 `Cookie: AUTHORIZATION=Bearer {token}` 携带。
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from ..const import (
    CONTROL_NAMESPACE,
    MCP_URL,
    METHOD_DEVICECONTROL,
    METHOD_DEVICELIST,
    METHOD_SCENELIST,
    METHOD_TRIGGERSCENE,
    REQUEST_TIMEOUT,
    REQUEST_TRIGGER_SCENE,
)
from ..models import IotDevice, SceneItem
from .exceptions import (
    XiaoDuAuthError,
    XiaoDuConnectionError,
    XiaoDuProtocolError,
)
from .parser import parse_iot_devices, parse_scenes

_LOGGER = logging.getLogger(__name__)

TokenProvider = Callable[[], Awaitable[str]]

# HTTP 200 但业务侧未登录时的关键字
_AUTH_ERROR_MARKERS = (
    "not login",
    "token decode",
    "invalid token",
    "token expired",
    "unauthorized",
)


class XiaoDuIotClient:
    """封装 DEVICELIST 与 DEVICECONTROL。"""

    def __init__(self, session: ClientSession, token_provider: TokenProvider) -> None:
        self._session = session
        # 异步回调，每次请求前返回最新有效的 access_token
        # （由 OAuth2Session 负责过期自动刷新）
        self._token_provider = token_provider

    async def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        token = await self._token_provider()
        headers = {
            "Content-Type": "application/json",
            "Cookie": f"AUTHORIZATION=Bearer {token}",
        }
        try:
            async with self._session.post(
                MCP_URL,
                json=payload,
                headers=headers,
                timeout=ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                if response.status in (401, 403):
                    raise XiaoDuAuthError(f"鉴权失败：http {response.status}")
                response.raise_for_status()
                result = await response.json(content_type=None)
        except XiaoDuAuthError:
            raise
        except (ClientError, TimeoutError) as err:
            raise XiaoDuConnectionError(f"无法访问小度 MCP：{err}") from err
        if not isinstance(result, dict):
            raise XiaoDuProtocolError("小度 MCP 返回了非对象响应")
        if self._is_auth_error(result):
            raise XiaoDuAuthError("小度 MCP 鉴权失败（未登录或 token 失效）")
        return result

    @staticmethod
    def _is_auth_error(result: dict[str, Any]) -> bool:
        """同时识别 HTTP 错误与 HTTP 200 的业务鉴权错误。"""
        if result.get("status") in (2, "2"):
            return True
        message = str(result.get("msg") or result.get("message") or "").lower()
        return any(marker in message for marker in _AUTH_ERROR_MARKERS)

    async def async_get_devices(self) -> dict[str, IotDevice]:
        """拉取并归一化全部设备。"""
        response = await self._request({"method": METHOD_DEVICELIST, "params": {}})
        return parse_iot_devices(response)

    async def async_get_scenes(self) -> dict[str, SceneItem]:
        """拉取并归一化全部场景。"""
        response = await self._request({"method": METHOD_SCENELIST, "params": {}})
        return parse_scenes(response)

    async def async_trigger_scene(self, scene_name: str) -> None:
        """按名称触发场景（服务端会触发所有同名场景）。"""
        response = await self._request(
            {
                "method": METHOD_TRIGGERSCENE,
                "protocal": {
                    "header": {
                        "namespace": CONTROL_NAMESPACE,
                        "name": REQUEST_TRIGGER_SCENE,
                        "payloadVersion": 1,
                    },
                    "payload": {"sceneName": scene_name},
                },
            }
        )
        self._raise_for_operation_error(response, METHOD_TRIGGERSCENE)

    async def async_control(
        self, device: IotDevice, request_name: str, **values: Any
    ) -> None:
        """下发一条控制指令。

        设备以 deviceName + roomName + floorName 三元组定位，缺一不可，
        否则同名设备会控错。
        """
        payload = {
            "deviceName": device.name,
            "roomName": device.room_name or "",
            "floorName": device.floor_name or "默认楼层",
            **values,
        }
        _LOGGER.debug(
            "control device=%s (id=%s) action=%s values=%s",
            device.name,
            device.device_id,
            request_name,
            values,
        )
        response = await self._request(
            {
                "method": METHOD_DEVICECONTROL,
                "protocal": {
                    "header": {
                        "namespace": CONTROL_NAMESPACE,
                        "name": request_name,
                        "payloadVersion": 1,
                    },
                    "payload": payload,
                },
            }
        )
        self._raise_for_operation_error(response, request_name)

    @staticmethod
    def _raise_for_operation_error(
        response: dict[str, Any], operation: str
    ) -> None:
        status = response.get("status")
        if status not in (None, 0, "0"):
            details = next(
                (
                    str(response[key])[:240]
                    for key in ("msg", "message", "error", "errorMessage")
                    if response.get(key) not in (None, "")
                ),
                "上游未返回错误信息",
            )
            raise XiaoDuProtocolError(f"{operation} 失败：status={status} {details}")
