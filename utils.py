import json
import re

from astrbot.api.event import AstrMessageEvent

from .models import ParseContext


def extract_context(event: AstrMessageEvent) -> ParseContext:
    raw = getattr(event.message_obj, "raw_message", None)
    if isinstance(raw, dict):
        raw_message = raw.get("message", [])
    else:
        raw_message = getattr(raw, "message", []) if raw else []

    text_parts = [event.message_str]
    json_urls: list[str] = []
    json_previews: list[str] = []

    for segment in raw_message:
        if isinstance(segment, dict):
            segment_type = segment.get("type")
            data = segment.get("data", {})
        else:
            segment_type = getattr(segment, "type", "")
            data = getattr(segment, "data", {})

        if segment_type == "text":
            text = data.get("text", "") if isinstance(data, dict) else getattr(data, "text", "")
            text_parts.append(str(text))
        elif segment_type == "json":
            json_data = data.get("data", "") if isinstance(data, dict) else getattr(data, "data", "")
            url, preview = extract_json_url_and_preview(str(json_data))
            if url:
                json_urls.append(url)
            if preview:
                json_previews.append(preview)

    return ParseContext(
        text="\n".join(part for part in text_parts if part).strip(),
        json_urls=json_urls,
        json_previews=json_previews,
    )


def extract_json_url_and_preview(data: str) -> tuple[str, str]:
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return "", ""
    url = (
        payload.get("meta", {}).get("detail_1", {}).get("qqdocurl", "")
        or payload.get("meta", {}).get("news", {}).get("jumpUrl", "")
    )
    preview = payload.get("meta", {}).get("news", {}).get("preview", "")
    return str(url or ""), str(preview or "")


def replace_links(text: str, replacement: str = "[链接请自己进入详情页看]") -> str:
    return re.sub(r"(http[s]?://\S+|www\.\S+)", replacement, text).strip()
