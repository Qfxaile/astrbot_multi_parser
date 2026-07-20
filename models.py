"""兼容导出模块。

新代码应从 ``core`` 子包按职责导入；保留本模块以兼容现有平台和第三方调用。
"""

from .core.contracts import OrderedContent, ParseContext, ParseResult
from .core.parser import BaseParser

__all__ = ["BaseParser", "OrderedContent", "ParseContext", "ParseResult"]
