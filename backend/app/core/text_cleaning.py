"""Strip Markdown noise (images, broken/truncated links, headers) from Firecrawl/Tavily
content so it never leaks into the LLM prompt or the rendered answer — the source of the
embedded photos, ``](url#)`` fragments and ``### header ###`` garbage seen in answers.

Preserves legitimate prose, bold, and bullet lists (the UI renders Markdown)."""

from __future__ import annotations

import re

_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_IMAGE_TRUNCATED = re.compile(r"!\[[^\]]*\]?\(?[^\s)]*\)?")
_LINK = re.compile(r"\[([^\]]+)\]\((?:https?://|/|mailto:)[^)]*\)")
_LINK_LEFTOVER = re.compile(r"\]\((?:https?://|/|mailto:)?[^)\s]*\)?")
# bare [text] -> text, but PRESERVE citation markers like [1], [2]
_BARE_BRACKET = re.compile(r"(?<!!)\[(?!\d+\])([^\]\n]{1,200})\]")
_HEADER_LINE = re.compile(r"(?m)^\s{0,3}#{1,6}\s*")
_HASHES = re.compile(r"#{2,}")
# Raw URLs leak into answers (e.g. a news link beside a dean name). Citations use [n];
# strip raw URLs but keep the official WhatsApp admin channel.
_RAW_URL = re.compile(r"https?://(?!api\.whatsapp\.com|wa\.me)\S+")
_MULTISPACE = re.compile(r"[ \t]{2,}")
_MULTINEWLINE = re.compile(r"\n{3,}")


def clean_markdown_text(text: str | None) -> str:
    if not text:
        return ""
    out = text
    out = _IMAGE.sub("", out)  # ![alt](url) images
    out = _IMAGE_TRUNCATED.sub("", out)  # truncated ![](htt
    out = _LINK.sub(r"\1", out)  # [text](url) -> text
    out = _LINK_LEFTOVER.sub("", out)  # leftover ](url) fragments
    out = _BARE_BRACKET.sub(r"\1", out)  # bare [text] -> text
    out = _HEADER_LINE.sub("", out)  # leading ### header
    out = _HASHES.sub("", out)  # inline ### / ##
    out = _RAW_URL.sub("", out)  # strip leftover raw URLs (citations use [n])
    out = _MULTISPACE.sub(" ", out)
    out = _MULTINEWLINE.sub("\n\n", out)
    # tidy stray leading punctuation left by removed markup
    out = re.sub(r"(?m)^[ \t]*[)\]]+[ \t]*", "", out)
    return out.strip()
