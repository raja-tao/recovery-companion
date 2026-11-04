"""Heading-aware chunking. Each chunk keeps its section path for citations."""
from __future__ import annotations

import re
from dataclasses import dataclass

from rag.text import approx_tokens

_HEADING = re.compile(r"^(#{1,4})\s+(.*)$")


@dataclass
class Chunk:
    index: int
    section: str
    content: str
    token_count: int


def chunk_markdown(text: str, title: str, max_words: int = 160, overlap_paragraphs: int = 1) -> list[Chunk]:
    sections: list[tuple[str, list[str]]] = []
    path: list[str] = []
    current: list[str] = []
    current_section = title

    def flush():
        body = "\n".join(current).strip()
        if body:
            sections.append((current_section, [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]))

    for line in (text or "").splitlines():
        m = _HEADING.match(line.strip())
        if m:
            flush()
            current = []
            level, heading = len(m.group(1)), m.group(2).strip()
            if level == 1:
                path = []
                current_section = heading if heading != title else title
                continue
            path = path[: level - 2] + [heading]
            current_section = " > ".join(path)
        else:
            current.append(line)
    flush()

    chunks: list[Chunk] = []
    for section, paragraphs in sections:
        buf: list[str] = []
        words = 0
        for para in paragraphs:
            pw = len(para.split())
            if buf and words + pw > max_words:
                content = "\n\n".join(buf)
                chunks.append(Chunk(len(chunks), section, content, approx_tokens(content)))
                buf = buf[-overlap_paragraphs:] if overlap_paragraphs else []
                words = sum(len(p.split()) for p in buf)
            buf.append(para)
            words += pw
        if buf:
            content = "\n\n".join(buf)
            chunks.append(Chunk(len(chunks), section, content, approx_tokens(content)))
    return chunks
