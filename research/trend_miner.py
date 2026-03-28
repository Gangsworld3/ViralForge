from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from utils.text import extract_keywords, split_sentences


@dataclass
class TrendFinding:
    title: str
    source: str
    description: str
    hook: str
    score: int
    keywords: list[str] = field(default_factory=list)


class TrendMiner:
    def __init__(self, memory=None, logger=None):
        self.memory = memory
        self.logger = logger

    def score_trend(self, title: str, description: str, topic: str) -> int:
        text = f"{title} {description}".lower()
        score = 35
        for token in extract_keywords(topic, limit=6):
            if token in text:
                score += 10
        if any(marker in text for marker in ["viral", "trending", "growth", "creator", "money", "ai", "hack"]):
            score += 12
        if any(marker in text for marker in ["today", "now", "breaking", "new", "latest"]):
            score += 8
        if len(text.split()) < 30:
            score += 5
        return min(100, score)

    def hook_from_trend(self, title: str, description: str) -> str:
        sentences = split_sentences(description or title)
        if sentences:
            return sentences[0][:120]
        return title[:120]

    def mine(self, topic: str, items: list[dict[str, Any]]) -> list[TrendFinding]:
        findings: list[TrendFinding] = []
        for item in items:
            title = item.get("title", "")
            description = item.get("description", "")
            source = item.get("source", "unknown")
            score = self.score_trend(title, description, topic)
            findings.append(
                TrendFinding(
                    title=title,
                    source=source,
                    description=description,
                    hook=self.hook_from_trend(title, description),
                    score=score,
                    keywords=extract_keywords(f"{title} {description}", limit=8),
                )
            )
        findings.sort(key=lambda item: item.score, reverse=True)
        return findings

