"""Markdown syntax parser backend built on markdown-it-py."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from markdown_it import MarkdownIt

from ..source.loader import ScenarioSource


class MarkdownBlockKind(StrEnum):
    HEADING = "heading"
    FENCE = "fence"
    CODE_BLOCK = "code_block"
    PARAGRAPH = "paragraph"
    BULLET_LIST = "bullet_list"
    ORDERED_LIST = "ordered_list"
    LIST_ITEM = "list_item"
    BLOCKQUOTE = "blockquote"
    THEMATIC_BREAK = "thematic_break"
    HTML_BLOCK = "html_block"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class LineSpan:
    """One-based source line range for a parsed markdown block."""

    line_start: int
    line_end: int


@dataclass(frozen=True, slots=True)
class MarkdownBlock:
    """Library-neutral markdown block used by scenario parsing code."""

    kind: MarkdownBlockKind
    content: str = ""
    line_span: LineSpan | None = None
    heading_level: int | None = None
    fence_info: str = ""
    markup: str = ""
    nesting_level: int = 0


@dataclass(frozen=True, slots=True)
class MarkdownTokenDocument:
    """Normalized markdown token document produced by a backend adapter."""

    source_path: Path
    blocks: tuple[MarkdownBlock, ...]

    def blocks_by_kind(self, kind: MarkdownBlockKind) -> tuple[MarkdownBlock, ...]:
        return tuple(block for block in self.blocks if block.kind == kind)

    @property
    def headings(self) -> tuple[MarkdownBlock, ...]:
        return self.blocks_by_kind(MarkdownBlockKind.HEADING)


class MarkdownBackend(Protocol):
    def parse(self, source: ScenarioSource) -> MarkdownTokenDocument:
        """Parse raw markdown source into a library-neutral token document."""


class MarkdownItBackend:
    """Adapter that hides markdown-it-py token objects behind local IR."""

    def __init__(self) -> None:
        self._parser = MarkdownIt("commonmark")

    def parse(self, source: ScenarioSource) -> MarkdownTokenDocument:
        tokens = self._parser.parse(source.text)
        blocks: list[MarkdownBlock] = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token.type == "heading_open":
                inline_content, next_index = _next_inline_content(tokens, index)
                blocks.append(
                    MarkdownBlock(
                        kind=MarkdownBlockKind.HEADING,
                        content=inline_content,
                        line_span=_line_span(token.map),
                        heading_level=_heading_level(token.tag),
                        markup=token.markup,
                        nesting_level=token.level,
                    )
                )
                index = next_index
                continue

            if token.type == "paragraph_open":
                inline_content, next_index = _next_inline_content(tokens, index)
                blocks.append(
                    MarkdownBlock(
                        kind=MarkdownBlockKind.PARAGRAPH,
                        content=inline_content,
                        line_span=_line_span(token.map),
                        markup=token.markup,
                        nesting_level=token.level,
                    )
                )
                index = next_index
                continue

            block = _standalone_block(token)
            if block is not None:
                blocks.append(block)
            index += 1

        return MarkdownTokenDocument(source_path=source.path, blocks=tuple(blocks))


def _standalone_block(token) -> MarkdownBlock | None:
    if token.type == "fence":
        return MarkdownBlock(
            kind=MarkdownBlockKind.FENCE,
            content=token.content,
            line_span=_line_span(token.map),
            fence_info=token.info.strip(),
            markup=token.markup,
            nesting_level=token.level,
        )
    if token.type == "code_block":
        return MarkdownBlock(
            kind=MarkdownBlockKind.CODE_BLOCK,
            content=token.content,
            line_span=_line_span(token.map),
            markup=token.markup,
            nesting_level=token.level,
        )
    if token.type == "bullet_list_open":
        return _container_block(MarkdownBlockKind.BULLET_LIST, token)
    if token.type == "ordered_list_open":
        return _container_block(MarkdownBlockKind.ORDERED_LIST, token)
    if token.type == "list_item_open":
        return _container_block(MarkdownBlockKind.LIST_ITEM, token)
    if token.type == "blockquote_open":
        return _container_block(MarkdownBlockKind.BLOCKQUOTE, token)
    if token.type == "hr":
        return _container_block(MarkdownBlockKind.THEMATIC_BREAK, token)
    if token.type == "html_block":
        return MarkdownBlock(
            kind=MarkdownBlockKind.HTML_BLOCK,
            content=token.content,
            line_span=_line_span(token.map),
            markup=token.markup,
            nesting_level=token.level,
        )
    return None


def _container_block(kind: MarkdownBlockKind, token) -> MarkdownBlock:
    return MarkdownBlock(
        kind=kind,
        line_span=_line_span(token.map),
        markup=token.markup,
        nesting_level=token.level,
    )


def _next_inline_content(tokens, open_token_index: int) -> tuple[str, int]:
    index = open_token_index + 1
    while index < len(tokens):
        token = tokens[index]
        if token.type == "inline":
            return token.content, index + 1
        if token.nesting == -1:
            return "", index + 1
        index += 1
    return "", index


def _line_span(raw_map: list[int] | None) -> LineSpan | None:
    if raw_map is None or len(raw_map) < 2:
        return None
    return LineSpan(line_start=raw_map[0] + 1, line_end=raw_map[1])


def _heading_level(tag: str) -> int | None:
    if len(tag) == 2 and tag.startswith("h") and tag[1].isdigit():
        return int(tag[1])
    return None
