"""Heading-aware chunking: ~450 tokens, 60 overlap, never crossing a page boundary."""
import hashlib
from dataclasses import dataclass

from app.services.parser import ParsedDoc

TARGET_WORDS = 340   # ~450 tokens
OVERLAP_WORDS = 45   # ~60 tokens
MIN_WORDS = 6


@dataclass
class ChunkOut:
    page: int | None
    section: str | None
    text: str
    ocr: bool
    text_hash: str


def _mk(page, section, words, ocr) -> ChunkOut | None:
    text = " ".join(words).strip()
    if len(words) < MIN_WORDS:
        return None
    return ChunkOut(page, section, text, ocr, hashlib.sha256(text.encode()).hexdigest())


def chunk(doc: ParsedDoc) -> list[ChunkOut]:
    out: list[ChunkOut] = []
    section: str | None = None
    for p in doc.pages:
        words: list[str] = []
        chunk_section = section

        def flush(keep_overlap: bool):
            nonlocal words, chunk_section
            c = _mk(p.page, chunk_section, words, p.ocr)
            if c:
                out.append(c)
            words = words[-OVERLAP_WORDS:] if keep_overlap and c else []
            chunk_section = section

        for b in p.blocks:
            if b.heading:
                if words:
                    flush(keep_overlap=False)
                section = b.text
                chunk_section = section
                words = [b.text]  # keep the heading in the chunk text for retrieval
                continue
            w = b.text.split()
            while w:
                room = TARGET_WORDS - len(words)
                if room <= 0:
                    flush(keep_overlap=True)
                elif len(w) <= room:
                    words.extend(w)
                    w = []
                elif len(words) >= 60 and len(w) <= TARGET_WORDS:
                    flush(keep_overlap=True)  # keep the block whole in the next chunk
                else:
                    words.extend(w[:room])
                    w = w[room:]
                    flush(keep_overlap=True)
        if words:
            flush(keep_overlap=False)
    return out
