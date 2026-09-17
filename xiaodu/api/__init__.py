"""XiaoDu API 层：HTTP 会话、客户端与异常。"""
from __future__ import annotations

import aiohttp
from aiohttp import ClientSession

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .exceptions import (
    XiaoDuApiError,
    XiaoDuAuthError,
    XiaoDuConnectionError,
    XiaoDuProtocolError,
)
from .iot import XiaoDuIotClient
from .parser import parse_iot_devices, parse_scenes, stable_fallback_id

__all__ = [
    "XiaoDuApiError",
    "XiaoDuAuthError",
    "XiaoDuConnectionError",
    "XiaoDuIotClient",
    "XiaoDuProtocolError",
    "async_new_session",
    "parse_iot_devices",
    "parse_scenes",
    "stable_fallback_id",
]


def async_new_session(hass: HomeAssistant) -> ClientSession:
    """创建禁用 cookie jar 的会话。

    小度要求鉴权头为 `Cookie: AUTHORIZATION=Bearer <token>`，其值含空格。
    共享会话启用了 cookie jar，一旦 jar 中存在该域名 cookie，aiohttp 会用
    http.cookies.SimpleCookie 重新序列化 Cookie 头，值在空格处被截断为
    `AUTHORIZATION=Bearer`，token 丢失，服务端返回 status=2 "not login"。
    使用 DummyCookieJar 后，手动设置的 Cookie 头会原样发送（与 curl 一致）。
    """
    return async_create_clientsession(hass, cookie_jar=aiohttp.DummyCookieJar())
