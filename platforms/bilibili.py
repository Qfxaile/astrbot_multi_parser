import re

import httpx

from ..models import BaseParser, ParseContext, ParseResult
from ..utils import replace_links


class BilibiliParser(BaseParser):
    name = "bilibili"
    SHORT_PATTERN = r"https?://(?:bili2233\.cn|b23\.tv)/[a-zA-Z0-9]+"
    ID_PATTERN = r"(BV[0-9A-Za-z]{10}|av\d+)"

    async def match(self, context: ParseContext) -> bool:
        text = context.combined_text
        return bool(re.search(self.ID_PATTERN, text) or re.search(self.SHORT_PATTERN, text))

    async def parse(self, context: ParseContext) -> ParseResult:
        text = context.combined_text
        match = re.search(self.ID_PATTERN, text)
        video_id = match.group(0) if match else await self._extract_id_from_short_url(text)
        if not video_id:
            return ParseResult(platform=self.name, error="未找到 B站 视频 ID。")

        info = await self._get_video_info(video_id)
        if info.get("error"):
            return ParseResult(platform=self.name, error=info["error"])

        play_url = await self._get_play_url(str(info["cid"]), video_id)
        extra_lines = [] if play_url else ["无法获取视频直链。"]

        return ParseResult(
            platform=self.name,
            title=info.get("title", "未知标题"),
            author=info.get("author", "未知作者"),
            description=replace_links(info.get("desc", "")),
            cover_urls=[info.get("pic", "")],
            video_url=play_url,
            extra_lines=extra_lines,
        )

    async def _extract_id_from_short_url(self, text: str) -> str:
        match = re.search(self.SHORT_PATTERN, text)
        if not match:
            return ""
        headers = self._headers("https://www.bilibili.com")
        async with httpx.AsyncClient(timeout=int(self.config.get("request_timeout_seconds", 30))) as client:
            response = await client.get(match.group(0), headers=headers, follow_redirects=True)
        final_url = str(response.url)
        id_match = re.search(self.ID_PATTERN, final_url)
        return id_match.group(0) if id_match else ""

    @staticmethod
    def _id_type(video_id: str) -> str:
        return "bvid" if video_id.startswith("BV") else "aid" if video_id.startswith("av") else "unknown"

    async def _get_video_info(self, video_id: str) -> dict:
        id_type = self._id_type(video_id)
        if id_type == "bvid":
            api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={video_id}"
        elif id_type == "aid":
            api_url = f"https://api.bilibili.com/x/web-interface/view?aid={video_id[2:]}"
        else:
            return {"error": "未知ID类型"}

        async with httpx.AsyncClient(timeout=int(self.config.get("request_timeout_seconds", 30))) as client:
            data = (await client.get(api_url, headers=self._headers("https://www.bilibili.com"))).json()
        if data.get("code") != 0:
            return {"error": f"获取视频信息失败: {data.get('message')}"}

        video_data = data["data"]
        return {
            "title": video_data.get("title", "未知标题"),
            "pic": video_data.get("pic", ""),
            "author": video_data.get("owner", {}).get("name", "未知作者"),
            "desc": video_data.get("desc", ""),
            "cid": video_data.get("cid"),
        }

    async def _get_play_url(self, cid: str, video_id: str) -> str:
        id_type = self._id_type(video_id)
        if id_type == "bvid":
            api_url = f"https://api.bilibili.com/x/player/playurl?bvid={video_id}&cid={cid}&qn=16&type=mp4&platform=html5"
        elif id_type == "aid":
            api_url = f"https://api.bilibili.com/x/player/playurl?avid={video_id[2:]}&cid={cid}&qn=16&type=mp4&platform=html5"
        else:
            return ""

        async with httpx.AsyncClient(timeout=int(self.config.get("request_timeout_seconds", 30))) as client:
            data = (await client.get(api_url, headers=self._headers("https://www.bilibili.com"))).json()
        return data.get("data", {}).get("durl", [{}])[0].get("url", "") if data.get("code") == 0 else ""

    @staticmethod
    def _headers(referer: str) -> dict:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:102.0) Gecko/20100101 Firefox/102.0",
            "Referer": referer,
        }
