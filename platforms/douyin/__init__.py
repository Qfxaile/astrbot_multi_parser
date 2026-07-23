"""导出抖音解析器与登录适配器。"""

from .login import DouyinLoginProvider
from .parser import DouyinParser

__all__ = ["DouyinLoginProvider", "DouyinParser"]
