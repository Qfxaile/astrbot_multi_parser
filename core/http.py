"""提供 HTTP 配置、Cookie 构造和鉴权失败识别能力。"""

from collections.abc import Collection, Mapping, Sequence

from httpx import Cookies, Response

AUTH_FAILURE_STATUS_CODES = frozenset({401, 403})


class CookieAccessError(ValueError):
    """表示平台明确拒绝当前匿名会话或 Cookie 会话。"""

    def __init__(self, platform: str, *, configured: bool):
        self.platform = platform
        self.configured = configured
        if configured:
            message = (
                f"{platform}内容获取失败，配置的 Cookies 可能已失效，请更新后重试。"
            )
        else:
            message = (
                f"{platform}内容获取失败，可能需要配置 Cookies，"
                "请在插件配置中填写后重试。"
            )
        super().__init__(message)


def parse_cookie_header(value: object) -> list[tuple[str, str]]:
    """解析简单 Cookie 请求头，忽略无名称或无等号的片段。"""
    pairs: list[tuple[str, str]] = []
    for segment in str(value or "").split(";"):
        if "=" not in segment:
            continue
        name, content = segment.strip().split("=", 1)
        if name:
            pairs.append((name, content))
    return pairs


def build_cookies(value: object, domains: Sequence[str]) -> Cookies:
    """把 Cookie 字符串中的每个键值限定到指定域。"""
    cookies = Cookies()
    for name, content in parse_cookie_header(value):
        for domain in domains:
            cookies.set(name, content, domain=domain, path="/")
    return cookies


def build_cookie_access_error(platform: str, cookie_value: object) -> CookieAccessError:
    """按 Cookie 是否已配置生成不包含敏感凭据的访问失败异常。"""
    return CookieAccessError(
        platform,
        configured=bool(parse_cookie_header(cookie_value)),
    )


def raise_for_cookie_access(
    response: Response,
    *,
    platform: str,
    cookie_value: object,
    status_codes: Collection[int] = AUTH_FAILURE_STATUS_CODES,
) -> None:
    """在响应明确表示鉴权或访问被拒绝时抛出 Cookie 提示异常。

    默认状态只包含语义稳定的鉴权拒绝；额外风控状态由平台解析器显式声明。
    本函数只判断调用方确认过的平台状态码，不读取响应正文，也不会在异常中
    保留 Cookie。调用方仍需随后调用 ``response.raise_for_status()`` 处理其他错误。
    """
    if response.status_code in status_codes:
        raise build_cookie_access_error(platform, cookie_value)


def request_timeout(
    config: Mapping[str, object],
    *,
    key: str = "request_timeout_seconds",
    default: float = 30.0,
) -> float:
    """从配置读取 httpx 超时秒数。"""
    return float(config.get(key, default))
