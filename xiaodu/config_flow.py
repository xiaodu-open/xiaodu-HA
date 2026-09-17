"""Config flow for the XiaoDu integration (OAuth2 authorization code)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_entry_oauth2_flow

from .const import DOMAIN
from .oauth import XiaoDuProxyOAuth2Implementation


class OAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """通过百度 OAuth2 授权码流程配置 XiaoDu。"""

    DOMAIN = DOMAIN

    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(__name__)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """确保 OAuth2 实现已注册后再进入标准授权流程。

        首次通过 UI 添加集成时，async_setup 可能尚未被调用
        （domain 未写入 configuration.yaml 且无 config entry），
        因此在此处兜底注册中转 OAuth2 实现，避免 missing_configuration。
        """
        config_entry_oauth2_flow.async_register_implementation(
            self.hass,
            DOMAIN,
            XiaoDuProxyOAuth2Implementation(self.hass),
        )
        return await super().async_step_user(user_input)

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> FlowResult:
        """OAuth 成功后创建配置条目。"""
        return self.async_create_entry(title="XiaoDu", data=data)

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """token 失效时触发重新授权。"""
        return await self.async_step_user()
