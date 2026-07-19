import re

from ..models import BaseParser, ParseContext, ParseResult


class XiaoheiheParser(BaseParser):
    """小黑盒解析器骨架，具体内容解析在平台任务中实现。"""

    name = "xiaoheihe"

    async def match(self, context: ParseContext) -> bool:
        return bool(re.search(r"https?://(?:www\.)?xiaoheihe\.cn/", context.combined_text))

    async def parse(self, context: ParseContext) -> ParseResult:
        return ParseResult(platform=self.name, error="小黑盒解析器尚未完成。")
