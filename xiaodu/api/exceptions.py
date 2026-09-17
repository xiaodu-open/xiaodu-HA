"""XiaoDu API 异常体系。"""
from __future__ import annotations


class XiaoDuApiError(Exception):
    """通用 / 业务错误。"""


class XiaoDuAuthError(XiaoDuApiError):
    """鉴权失败（access_token 无效或过期）。"""


class XiaoDuConnectionError(XiaoDuApiError):
    """网络连接错误或超时。"""


class XiaoDuProtocolError(XiaoDuApiError):
    """返回结构不符合预期，或业务 status 非 0。"""
