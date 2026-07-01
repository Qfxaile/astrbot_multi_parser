import re

import httpx

from ..models import BaseParser, ParseContext, ParseResult


class DouyinParser(BaseParser):
    name = "douyin"
    PATTERN = r"https://(?:v\.douyin\.com|www\.douyin\.com|vm\.tiktok\.com|www\.tiktok\.com)/[^\s]+"

    async def match(self, context: ParseContext) -> bool:
        return bool(re.search(self.PATTERN, context.combined_text))

    async def parse(self, context: ParseContext) -> ParseResult:
        match = re.search(self.PATTERN, context.combined_text)
        if not match:
            return ParseResult(platform=self.name, error="未找到抖音链接。")

        info = await self._fetch_info(match.group(0))
        if info.get("error"):
            return ParseResult(platform=self.name, error=f"解析失败: {info['msg']}")

        note_type = info.get("type", "")
        extra_lines = []
        video_url = ""
        image_urls = []
        cover_urls = []
        if note_type == "图集":
            image_urls = [url for url in info.get("cover", []) if url]
        else:
            cover = info.get("cover", "")
            if cover:
                cover_urls.append(cover)
            if note_type == "视频":
                video_url = info.get("video_url", "")
                if not video_url:
                    extra_lines.append("无法获取视频直链。")

        return ParseResult(
            platform=self.name,
            title=info.get("title", "未知标题"),
            author=info.get("author_name", "未知作者"),
            cover_urls=cover_urls,
            image_urls=image_urls,
            video_url=video_url,
            extra_lines=extra_lines,
        )

    async def _fetch_info(self, url: str) -> dict:
        api_url = str(self.config.get("douyin_api_url", "")).rstrip("/")
        async with httpx.AsyncClient(timeout=int(self.config.get("request_timeout_seconds", 30))) as client:
            response = await client.get(f"{api_url}/?url={url}")
        data = response.json()
        if data.get("code") != 0:
            return {"error": "解析失败", "msg": data.get("msg", "未知错误") + "\n被字节做局了。"}

        video_data = data.get("data", {})
        item = video_data.get("item", {})
        note_type = video_data.get("jx", {}).get("type", "")
        author = video_data.get("author", {})
        return {
            "title": item.get("title", "未知标题"),
            "cover": item.get("images", []) if note_type == "图集" else item.get("cover_gif", ""),
            "author_name": author.get("name", "未知作者"),
            "video_url": item.get("ury", ""),
            "type": note_type,
        }
