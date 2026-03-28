from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from utils.text import split_sentences, split_words


@dataclass
class RetentionPlan:
    opening_hook: str
    pacing_notes: list[str]
    chapter_markers: list[str]
    predicted_dropoff_points: list[int]
    rewrite_notes: str


class RetentionOptimizer:
    def __init__(self, memory=None, logger=None):
        self.memory = memory
        self.logger = logger

    def analyze(self, script: str, analytics: dict[str, Any] | None = None) -> RetentionPlan:
        sentences = split_sentences(script)
        words = split_words(script)
        opening_hook = sentences[0] if sentences else script[:120]
        pacing_notes = []
        if len(words) > 180:
            pacing_notes.append("Trim long explanations to keep the first half under 30 seconds.")
        if len(sentences) > 6:
            pacing_notes.append("Split the midsection with pattern interrupts every 2-3 sentences.")
        if "because" not in script.lower():
            pacing_notes.append("Add a fast justification line after the hook.")
        if "?" not in opening_hook:
            pacing_notes.append("Turn the hook into a question or tease to lift curiosity.")
        chapter_markers = [sentence[:40] for sentence in sentences[:4]]
        predicted_dropoff_points = [min(len(words), p) for p in (20, 45, 80, 120) if len(words) > p]
        rewrite_notes = " ".join(pacing_notes) if pacing_notes else "Hook is clear; keep the delivery tight and conversational."
        return RetentionPlan(
            opening_hook=opening_hook,
            pacing_notes=pacing_notes,
            chapter_markers=chapter_markers,
            predicted_dropoff_points=predicted_dropoff_points,
            rewrite_notes=rewrite_notes,
        )

