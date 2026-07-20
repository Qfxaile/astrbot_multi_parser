from collections.abc import Mapping

import httpx

from .contracts import ParseContext, ParseResult
from .http import request_timeout
from .media import ImageMaterializer


class BaseParser:
    """平台解析器的稳定契约。"""

    name = "base"
    image_host_suffixes: tuple[str, ...] = ()

    def __init__(self, config: Mapping[str, object]):
        self.config = config

    @property
    def request_timeout(self) -> float:
        return request_timeout(self.config)

    async def match(self, context: ParseContext) -> bool:
        raise NotImplementedError

    async def parse(self, context: ParseContext) -> ParseResult:
        raise NotImplementedError

    async def materialize_images(
        self,
        result: ParseResult,
        client: httpx.AsyncClient,
        referer: str,
    ) -> ParseResult:
        materializer = ImageMaterializer(self.config, self.image_host_suffixes)
        return await materializer.materialize(result, client, referer)
