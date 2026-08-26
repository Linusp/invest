import json
import re
from html import escape
from html.parser import HTMLParser
from typing import Any


def normalize_content(content: dict[str, Any] | str, content_format: str) -> dict:
    if content_format == "structured":
        return _normalize_structured(content)
    if not isinstance(content, str):
        raise ValueError(f"{content_format} commentary content must be a string")
    if content_format == "markdown":
        blocks = _markdown_blocks(content)
    elif content_format == "html":
        parser = _RestrictedHTMLParser()
        parser.feed(content)
        parser.close()
        blocks = parser.blocks
    else:
        raise ValueError(f"Unsupported commentary content format: {content_format}")
    return {"version": 1, "blocks": blocks}


def content_to_markdown(document: dict) -> str:
    rendered: list[str] = []
    for block in document.get("blocks", []):
        block_type = block.get("type")
        if block_type == "heading":
            rendered.append(f"{'#' * block['level']} {block['text']}")
        elif block_type == "paragraph":
            rendered.append(block["text"])
        elif block_type == "list":
            marker = "-" if block.get("style") != "number" else None
            rendered.append(
                "\n".join(
                    f"{marker or f'{index}.'} {item}"
                    for index, item in enumerate(block["items"], start=1)
                )
            )
        elif block_type == "metric":
            unit = f" {block['unit']}" if block.get("unit") else ""
            rendered.append(f"**{block['label']}**: {block['value']}{unit}")
        elif block_type == "quote":
            source = f" — {block['source']}" if block.get("source") else ""
            rendered.append(f"> {block['text']}{source}")
    return "\n\n".join(item for item in rendered if item)


def content_to_html(document: dict) -> str:
    rendered: list[str] = []
    for block in document.get("blocks", []):
        block_type = block.get("type")
        if block_type == "heading":
            level = block["level"]
            rendered.append(f"<h{level}>{escape(block['text'])}</h{level}>")
        elif block_type == "paragraph":
            rendered.append(f"<p>{escape(block['text'])}</p>")
        elif block_type == "list":
            tag = "ol" if block.get("style") == "number" else "ul"
            items = "".join(f"<li>{escape(item)}</li>" for item in block["items"])
            rendered.append(f"<{tag}>{items}</{tag}>")
        elif block_type == "metric":
            unit = f" {escape(str(block['unit']))}" if block.get("unit") else ""
            rendered.append(
                '<dl class="commentary-metric">'
                f"<dt>{escape(block['label'])}</dt>"
                f"<dd>{escape(str(block['value']))}{unit}</dd></dl>"
            )
        elif block_type == "quote":
            source = (
                f"<cite>{escape(block['source'])}</cite>"
                if block.get("source")
                else ""
            )
            rendered.append(
                f"<blockquote>{escape(block['text'])}{source}</blockquote>"
            )
    return "".join(rendered)


def _normalize_structured(content: dict[str, Any] | str) -> dict:
    if not isinstance(content, dict):
        raise ValueError("structured commentary content must be an object")
    if content.get("version") != 1 or not isinstance(content.get("blocks"), list):
        raise ValueError("structured commentary content requires version 1 and blocks")
    blocks = [_normalize_block(block) for block in content["blocks"]]
    return {"version": 1, "blocks": blocks}


def _normalize_block(block: Any) -> dict:
    if not isinstance(block, dict):
        return {"type": "paragraph", "text": str(block)}
    block_type = block.get("type")
    if block_type == "heading":
        return {
            "type": "heading",
            "level": min(6, max(1, int(block.get("level", 2)))),
            "text": str(block.get("text", "")),
        }
    if block_type == "paragraph":
        return {"type": "paragraph", "text": str(block.get("text", ""))}
    if block_type == "list":
        items = block.get("items", [])
        if not isinstance(items, list):
            items = [items]
        return {
            "type": "list",
            "style": "number" if block.get("style") == "number" else "bullet",
            "items": [str(item) for item in items],
        }
    if block_type == "metric":
        return {
            "type": "metric",
            "label": str(block.get("label", "")),
            "value": block.get("value"),
            "unit": str(block["unit"]) if block.get("unit") is not None else None,
        }
    if block_type == "quote":
        return {
            "type": "quote",
            "text": str(block.get("text", "")),
            "source": str(block["source"]) if block.get("source") else None,
        }
    return {
        "type": "paragraph",
        "text": json.dumps(block, ensure_ascii=False, default=str),
    }


def _markdown_blocks(content: str) -> list[dict]:
    blocks: list[dict] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    list_style = "bullet"

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append({"type": "paragraph", "text": "\n".join(paragraph)})
            paragraph.clear()

    def flush_list() -> None:
        if list_items:
            blocks.append({"type": "list", "style": list_style, "items": list_items[:]})
            list_items.clear()

    for raw_line in content.splitlines():
        line = raw_line.strip()
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        bullet = re.match(r"^[-*+]\s+(.+)$", line)
        numbered = re.match(r"^\d+[.)]\s+(.+)$", line)
        if heading:
            flush_paragraph()
            flush_list()
            blocks.append(
                {
                    "type": "heading",
                    "level": len(heading.group(1)),
                    "text": heading.group(2),
                }
            )
        elif bullet or numbered:
            flush_paragraph()
            next_style = "number" if numbered else "bullet"
            if list_items and next_style != list_style:
                flush_list()
            list_style = next_style
            list_items.append((bullet or numbered).group(1))
        elif not line:
            flush_paragraph()
            flush_list()
        elif line.startswith("> "):
            flush_paragraph()
            flush_list()
            blocks.append({"type": "quote", "text": line[2:]})
        else:
            flush_list()
            paragraph.append(line)
    flush_paragraph()
    flush_list()
    return blocks


class _RestrictedHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict] = []
        self._skip_depth = 0
        self._current_tag: str | None = None
        self._text: list[str] = []
        self._list_style: str | None = None
        self._list_items: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in {"ul", "ol"}:
            self._flush_text()
            self._list_style = "number" if tag == "ol" else "bullet"
            self._list_items = []
        elif tag in {"p", "blockquote", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._flush_text()
            self._current_tag = tag
            self._text = []
        elif tag == "br" and self._current_tag:
            self._text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == self._current_tag:
            text = "".join(self._text).strip()
            if tag == "li":
                if text:
                    self._list_items.append(text)
            elif tag.startswith("h"):
                self.blocks.append(
                    {"type": "heading", "level": int(tag[1]), "text": text}
                )
            elif tag == "blockquote":
                self.blocks.append({"type": "quote", "text": text})
            elif text:
                self.blocks.append({"type": "paragraph", "text": text})
            self._current_tag = None
            self._text = []
        if tag in {"ul", "ol"} and self._list_style:
            self.blocks.append(
                {
                    "type": "list",
                    "style": self._list_style,
                    "items": self._list_items[:],
                }
            )
            self._list_style = None
            self._list_items = []

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._text.append(data)

    def close(self) -> None:
        super().close()
        self._flush_text()

    def _flush_text(self) -> None:
        text = "".join(self._text).strip()
        if text:
            self.blocks.append({"type": "paragraph", "text": text})
        self._current_tag = None
        self._text = []
