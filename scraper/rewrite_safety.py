"""Checks that generated copy is not reproducing source wording."""

from __future__ import annotations

import html
import re

TAG_RE = re.compile(r"<[^>]+>")
WORD_RE = re.compile(r"[a-z0-9£%'-]+", re.IGNORECASE)


def words(value: str) -> list[str]:
    text = html.unescape(str(value or ""))
    text = TAG_RE.sub(" ", text)
    return [word.lower() for word in WORD_RE.findall(text)]


def ngrams(tokens: list[str], size: int) -> set[tuple[str, ...]]:
    if size <= 0 or len(tokens) < size:
        return set()
    return {
        tuple(tokens[index:index + size])
        for index in range(len(tokens) - size + 1)
    }


def excessive_source_overlap(
    output_text: str,
    source_text: str,
    *,
    long_phrase_size: int = 10,
    short_phrase_size: int = 5,
    max_short_ratio: float = 0.20,
) -> bool:
    output_words = words(output_text)
    source_words = words(source_text)

    if len(output_words) < 12 or len(source_words) < 12:
        return False

    if ngrams(output_words, long_phrase_size) & ngrams(
        source_words, long_phrase_size
    ):
        return True

    output_short = ngrams(output_words, short_phrase_size)
    source_short = ngrams(source_words, short_phrase_size)
    if not output_short:
        return False

    shared = output_short & source_short
    ratio = len(shared) / len(output_short)
    return len(shared) >= 3 and ratio > max_short_ratio
