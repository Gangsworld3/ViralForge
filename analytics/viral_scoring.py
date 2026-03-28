from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from utils.text import extract_keywords, split_sentences, split_words


@dataclass
class ViralScoreBreakdown:
    total: int
    hook: int
    emotion: int
    trend_alignment: int
    curiosity: int
    structure: int
    retention: int
    cta: int


class ViralScorer:
    def __init__(self, memory=None, logger=None):
        self.memory = memory
        self.logger = logger

    def _score_hook(self, text: str) -> int:
        lowered = text.lower()
        score = 0
        if lowered.startswith(("hey", "stop", "listen", "wait", "watch")):
            score += 22
        if any(marker in lowered for marker in ["you won't believe", "here's", "this is why", "real reason", "secret"]):
            score += 18
        if "?" in text[:80]:
            score += 10
        return min(30, score)

    def _score_emotion(self, text: str) -> int:
        lowered = text.lower()
        markers = ["insane", "wild", "crazy", "shocking", "money", "easy", "fast", "fear", "win", "lose"]
        score = sum(4 for marker in markers if marker in lowered)
        return min(20, score)

    def _score_trend_alignment(self, text: str, trend_context: str) -> int:
        text_tokens = set(extract_keywords(text, limit=16))
        trend_tokens = set(extract_keywords(trend_context, limit=16))
        overlap = len(text_tokens.intersection(trend_tokens))
        return min(20, overlap * 4)

    def _score_curiosity(self, text: str) -> int:
        lowered = text.lower()
        score = 0
        if "because" in lowered:
            score += 5
        if any(marker in lowered for marker in ["secret", "unexpected", "counterintuitive", "mistake", "hack"]):
            score += 8
        if any(word in lowered for word in ["why", "how", "what happens"]):
            score += 6
        return min(15, score)

    def _score_structure(self, text: str) -> int:
        words = split_words(text)
        sentences = split_sentences(text)
        score = 0
        if 50 <= len(words) <= 220:
            score += 8
        elif len(words) < 50:
            score += 4
        if len(sentences) >= 3:
            score += 6
        if len(sentences) <= 6:
            score += 4
        return min(15, score)

    def _score_retention(self, text: str) -> int:
        lowered = text.lower()
        score = 0
        if any(token in lowered for token in ["first", "next", "then", "finally", "step"]):
            score += 6
        if "comment" in lowered or "save this" in lowered:
            score += 4
        if "part 2" in lowered or "follow" in lowered:
            score += 3
        return min(10, score)

    def _score_cta(self, text: str) -> int:
        lowered = text.lower()
        score = 0
        if any(token in lowered for token in ["comment", "follow", "link in bio", "save", "share"]):
            score += 10
        return min(10, score)

    def score(self, text: str, trend_context: str = "") -> ViralScoreBreakdown:
        hook = self._score_hook(text)
        emotion = self._score_emotion(text)
        trend_alignment = self._score_trend_alignment(text, trend_context)
        curiosity = self._score_curiosity(text)
        structure = self._score_structure(text)
        retention = self._score_retention(text)
        cta = self._score_cta(text)
        total = min(100, hook + emotion + trend_alignment + curiosity + structure + retention + cta)
        return ViralScoreBreakdown(
            total=total,
            hook=hook,
            emotion=emotion,
            trend_alignment=trend_alignment,
            curiosity=curiosity,
            structure=structure,
            retention=retention,
            cta=cta,
        )

    def explain(self, breakdown: ViralScoreBreakdown) -> str:
        return (
            f"hook={breakdown.hook}, emotion={breakdown.emotion}, trend={breakdown.trend_alignment}, "
            f"curiosity={breakdown.curiosity}, structure={breakdown.structure}, "
            f"retention={breakdown.retention}, cta={breakdown.cta}, total={breakdown.total}"
        )

