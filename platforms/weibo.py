import re

from ..models import BaseParser, ParseContext, ParseResult


class WeiboParser(BaseParser):
    """微博解析器骨架，具体内容解析在平台任务中实现。"""

    name = "weibo"

    async def match(self, context: ParseContext) -> bool:
        return bool(re.search(r"https?://(?:www\.)?weibo\.com/", context.combined_text))

    async def parse(self, context: ParseContext) -> ParseResult:
        return ParseResult(platform=self.name, error="微博解析器尚未完成。")
