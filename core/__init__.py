"""插件核心领域契约与基础服务。"""

from .contracts import OrderedContent, ParseContext, ParseResult
from .parser import BaseParser

__all__ = ["BaseParser", "OrderedContent", "ParseContext", "ParseResult"]
