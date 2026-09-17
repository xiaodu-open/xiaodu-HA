"""XiaoDu 的 OAuth2 实现：授权与 token 交换全部走中转服务。

集成侧不持有任何 OAuth 凭据——`client_id`、`client_secret`、`scope` 都由中转服务在
服务端注入，因此这里既不发送也不保存它们。
"""
from __future__ import annotations

from yarl import URL

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, PROXY_AUTHORIZE, PROXY_TOKEN


class XiaoDuProxyOAuth2Implementation(
    config_entry_oauth2_flow.LocalOAuth2Implementation
):
    """通过中转服务完成百度授权码流程。"""

    def __init__(self, hass: HomeAssistant) -> None:
        # client_id / client_secret 传空串：两者均由中转服务注入
        super().__init__(hass, DOMAIN, "", "", PROXY_AUTHORIZE, PROXY_TOKEN)

    @property
    def name(self) -> str:
        return "小度账号"

    async def async_generate_authorize_url(self, flow_id: str) -> str:
        """复用基类生成授权 URL（含签名 state），仅剔除其中空的 client_id。"""
        url = URL(await super().async_generate_authorize_url(flow_id))
        query = {k: v for k, v in url.query.items() if k != "client_id"}
        return str(url.with_query(query))

    async def _token_request(self, data: dict) -> dict:
        """向中转服务请求 token，请求体只含 grant 相关字段。"""
        data.pop("client_id", None)
        session = async_get_clientsession(self.hass)
        resp = await session.post(self.token_url, data=data)
        resp.raise_for_status()
        return await resp.json(content_type=None)
