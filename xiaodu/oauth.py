"""XiaoDu 的 OAuth2 实现：授权与 token 交换全部走中转服务。

集成侧不持有任何 OAuth 凭据——`client_id`、`client_secret`、`scope` 都由中转服务在
服务端注入，因此这里既不发送也不保存它们。

token 请求（换取与刷新）完全交给基类 `LocalOAuth2Implementation._token_request`：
它会把 4xx 映射成 `OAuth2TokenRequestReauthError`、网络与 5xx 映射成
`OAuth2TokenRequestTransientError`，coordinator 依赖这两类异常区分「需要重新授权」与
「稍后重试」。自行覆写该方法会退化成裸 `ClientResponseError`，刷新失败将被当成普通
网络错误无限重试，永远弹不出重新授权提示。
"""
from __future__ import annotations

from yarl import URL

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow

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
        """复用基类生成授权 URL（含签名 state），仅剔除其中空的 client_id。

        授权地址由浏览器直接访问百度，带上空的 client_id 会被拒；
        而 token 请求中的 client_id 上游会忽略，故无需为此覆写 _token_request。
        """
        url = URL(await super().async_generate_authorize_url(flow_id))
        query = {k: v for k, v in url.query.items() if k != "client_id"}
        return str(url.with_query(query))
