"""导出微信平台解析器与登录适配器。"""

from .login import WeChatLoginProvider
from .parser import WeChatParser

__all__ = ["WeChatLoginProvider", "WeChatParser"]
