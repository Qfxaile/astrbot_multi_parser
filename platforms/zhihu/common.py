import html
import re
from urllib.parse import urljoin, urlsplit, urlunsplit


def normalize_text(value: str, *, keep_newlines: bool = False) -> str:
    """解码实体并规范化知乎正文中的空白。"""
    if not value:
        return ""
    text = html.unescape(value)
    text = text.replace("\xa0", " ").replace("\u3000", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    if keep_newlines:
        text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
    else:
        text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_media_url(value: str, page_url: str | None = None) -> str:
    """将媒体候选规范化为不含凭据的 HTTP(S) URL。"""
    if not value:
        return ""
    normalized = html.unescape(str(value)).strip().strip("\"'")
    normalized = normalized.replace("\\u002F", "/").replace("\\/", "/")
    if not normalized or normalized.startswith(("data:", "blob:", "javascript:")):
        return ""
    if normalized.startswith("//"):
        normalized = f"https:{normalized}"
    elif page_url and not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", normalized):
        normalized = urljoin(page_url, normalized)
    try:
        parsed = urlsplit(normalized)
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 80, 443}
    ):
        return ""
    return urlunsplit(parsed)


def media_key(url: str) -> str:
    normalized = normalize_media_url(url)
    if not normalized:
        return ""
    parsed = urlsplit(normalized)
    scheme = "https" if parsed.scheme == "http" else parsed.scheme
    path = parsed.path.lower()
    strip_query = bool(
        re.search(r"\.(?:jpg|jpeg|png|webp|gif|avif|mp4|m3u8|mov)(?:$|/)", path)
        or (parsed.hostname or "").endswith("zhimg.com")
        or (parsed.hostname or "") == "video.zhihu.com"
    )
    return urlunsplit(
        parsed._replace(
            scheme=scheme,
            query="" if strip_query else parsed.query,
            fragment="",
        )
    )


def merge_unique_urls(*groups: list[str]) -> list[str]:
    merged = []
    seen = set()
    for group in groups:
        for url in group:
            key = media_key(url)
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(url)
    return merged


def format_count(value: object) -> str:
    try:
        number = int(float(str(value)))
    except (TypeError, ValueError):
        return normalize_text(str(value or ""))
    if abs(number) >= 100_000_000:
        text = f"{number / 100_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{text}亿"
    if abs(number) >= 10_000:
        text = f"{number / 10_000:.1f}".rstrip("0").rstrip(".")
        return f"{text}万"
    return str(number)
