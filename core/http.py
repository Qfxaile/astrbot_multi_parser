from collections.abc import Mapping, Sequence

from httpx import Cookies


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


def request_timeout(
    config: Mapping[str, object],
    *,
    key: str = "request_timeout_seconds",
    default: float = 30.0,
) -> float:
    """从配置读取 httpx 超时秒数。"""
    return float(config.get(key, default))
