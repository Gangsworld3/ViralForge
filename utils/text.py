from __future__ import annotations

import re
from hashlib import sha1
from typing import Iterable


WORD_RE = re.compile(r"[A-Za-z0-9']+|[\u0600-\u06FF]+")


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or sha1(value.encode("utf-8")).hexdigest()[:10]


def split_words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def extract_keywords(text: str, limit: int = 8) -> list[str]:
    tokens = [token.lower() for token in split_words(text) if len(token) > 3]
    seen: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
    return seen[:limit]


def is_rtl(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06FF" for ch in text)


def chunk_words(words: Iterable[str], chunk_size: int = 5) -> list[list[str]]:
    words = list(words)
    return [words[i : i + chunk_size] for i in range(0, len(words), chunk_size)]
