"""封装小红书 Web 登录请求所需的本地签名。"""

import time
from collections.abc import Mapping
from typing import Any, Protocol


class RedBookRequestSigner(Protocol):
    """声明登录适配器使用的最小签名能力。"""

    def sign(
        self,
        method: str,
        uri: str,
        a1_value: str,
        payload: Mapping[str, object],
    ) -> dict[str, str]:
        """返回请求签名头，不生成或持久化设备标识。"""


class XhshowRequestSigner:
    """使用 ``xhshow`` 生成小红书 Web 请求签名。"""

    def __init__(self) -> None:
        # 延迟导入使解析器模块本身不依赖签名库初始化；AstrBot 安装插件依赖后
        # 才会在管理员实际发起小红书登录时加载密码学实现。
        from xhshow import Xhshow

        self._client: Any = Xhshow()

    def sign(
        self,
        method: str,
        uri: str,
        a1_value: str,
        payload: Mapping[str, object],
    ) -> dict[str, str]:
        """使用官方响应设置的 ``a1`` 生成 ``X-S`` 和统一时间戳。"""
        timestamp = time.time()
        method = method.upper()
        if method not in {"GET", "POST"}:
            raise ValueError("unsupported signed request method")
        # XYW 签名只使用请求内容、官方 a1 与时间戳；不调用库中的设备 ID、
        # Web ID 或指纹生成能力。
        x_s = self._client.sign_xyw(
            method=method,
            uri=uri,
            a1_value=a1_value,
            payload=dict(payload),
            timestamp=timestamp,
        )
        return {
            "X-S": str(x_s),
            "X-T": str(self._client.get_x_t(timestamp)),
        }
