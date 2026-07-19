import re

from ..models import BaseParser, ParseContext, ParseResult


class ZhihuParser(BaseParser):
    """知乎解析器骨架，具体内容解析在平台任务中实现。"""

    name = "zhihu"

    async def match(self, context: ParseContext) -> bool:
        return bool(re.search(r"https?://(?:www\.|zhuanlan\.)?zhihu\.com/", context.combined_text))

    async def parse(self, context: ParseContext) -> ParseResult:
        return ParseResult(platform=self.name, error="知乎解析器尚未完成。")
