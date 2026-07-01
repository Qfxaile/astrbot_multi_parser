import re

import httpx

from ..models import BaseParser, ParseContext, ParseResult


class RedBookParser(BaseParser):
    name = "redbook"
    PATTERN = r"https?://(?:www\.xiaohongshu\.com/(?:explore|discovery/item)/[^/?\s]+|xhslink\.com(?:/[^/?\s]+)+)(?:\?[^\s#]*)?"

    async def match(self, context: ParseContext) -> bool:
        return bool(re.search(self.PATTERN, context.combined_text))

    async def parse(self, context: ParseContext) -> ParseResult:
        match = re.search(self.PATTERN, context.combined_text)
        if not match:
            return ParseResult(platform=self.name, error="未找到小红书链接。")

        info = await self._fetch_info(match.group(0))
        if info.get("error"):
            return ParseResult(platform=self.name, error=f"解析失败: {info['msg']}")

        note_type = info.get("note_type", "")
        media_urls = [url for url in info.get("media_urls", []) if url]
        image_urls = media_urls if note_type == "图文" else []
        cover_urls = [] if note_type == "图文" else [url for url in context.json_previews if url][:1]
        video_url = media_urls[0] if note_type != "图文" and media_urls else ""
        extra_lines = []
        if note_type != "图文" and not video_url:
            extra_lines.append("无法获取视频直链。")

        return ParseResult(
            platform=self.name,
            title=info.get("title", "无标题"),
            author=info.get("author", "未知作者"),
            description=info.get("description", ""),
            cover_urls=cover_urls,
            image_urls=image_urls,
            video_url=video_url,
            extra_lines=extra_lines,
        )

    async def _fetch_info(self, url: str) -> dict:
        api_url = str(self.config.get("redbook_api_url", "")).strip()
        async with httpx.AsyncClient(timeout=int(self.config.get("request_timeout_seconds", 30))) as client:
            response = await client.post(api_url, json={"url": url}, headers={"Content-Type": "application/json"})
        if response.status_code != 200:
            return {"error": "API请求失败", "msg": f"HTTP {response.status_code}"}

        data = response.json()
        if data.get("message") != "获取小红书作品数据成功":
            return {"error": "解析失败", "msg": data.get("message", "未知错误")}

        note = data.get("data", {})
        return {
            "note_type": note.get("作品类型", "未知"),
            "title": note.get("作品标题", "无标题"),
            "description": note.get("作品描述", ""),
            "author": note.get("作者昵称", "未知作者"),
            "media_urls": note.get("下载地址", []),
        }
