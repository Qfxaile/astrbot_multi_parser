from dataclasses import dataclass, field

from astrbot.api.message_components import Image, Plain, Video


@dataclass
class ParseContext:
    text: str
    json_urls: list[str] = field(default_factory=list)
    json_previews: list[str] = field(default_factory=list)

    @property
    def combined_text(self) -> str:
        return "\n".join([self.text, *self.json_urls]).strip()


@dataclass
class ParseResult:
    platform: str
    title: str = ""
    author: str = ""
    description: str = ""
    cover_urls: list[str] = field(default_factory=list)
    image_urls: list[str] = field(default_factory=list)
    video_url: str = ""
    error: str = ""
    extra_lines: list[str] = field(default_factory=list)

    def info_chain(self, include_video_url: bool = False) -> list:
        chain: list = []
        for image_url in [*self.cover_urls, *self.image_urls]:
            if image_url:
                chain.append(Image.fromURL(image_url))

        lines = []
        if self.title:
            lines.append(self.title)
        if self.author:
            lines.append(f"作者: {self.author}")
        if self.description:
            lines.append(f"简介:\n{self.description}")
        lines.extend(self.extra_lines)
        if self.error:
            lines.append(self.error)
        if self.video_url and include_video_url:
            lines.append(f"视频链接: {self.video_url}")

        if lines:
            chain.append(Plain("\n".join(lines)))
        return chain

    def video_chain(self) -> list:
        return [Video.fromURL(self.video_url)] if self.video_url else []


class BaseParser:
    name = "base"

    def __init__(self, config):
        self.config = config

    async def match(self, context: ParseContext) -> bool:
        raise NotImplementedError

    async def parse(self, context: ParseContext) -> ParseResult:
        raise NotImplementedError
