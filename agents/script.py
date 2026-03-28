from __future__ import annotations

from typing import Any

from agents.base import BaseAgent, PipelineState
from analytics.retention import RetentionOptimizer
from analytics.viral_scoring import ViralScorer


class ScriptAgent(BaseAgent):
    name = "script"

    def __init__(self, config, router, memory, healer, logger=None):
        super().__init__(config, router, memory, healer, logger=logger)
        self.scorer = ViralScorer(memory=memory, logger=logger)
        self.retention = RetentionOptimizer(memory=memory, logger=logger)

    def _score(self, text: str) -> int:
        score = 35
        lowered = text.lower()
        hook_tokens = ["hey", "you won't believe", "stop scrolling", "here's", "watch this"]
        score += 12 if any(token in lowered for token in hook_tokens) else 0
        score += 12 if "why it works" in lowered else 0
        score += min(20, len(text.split()) // 25)
        score += 8 if "call to action" in lowered or "comment" in lowered else 0
        score += 8 if "curious" in lowered or "shocking" in lowered or "unexpected" in lowered else 0
        return min(100, score)

    def _target_word_count(self) -> int:
        target_seconds = float(getattr(self.config, "video_target_duration_seconds", 60))
        wpm = max(1, int(getattr(self.config, "video_speech_wpm", 165)))
        return max(90, int(target_seconds * wpm / 60.0))

    def _critique(self, draft: str) -> str:
        prompt = (
            "Critique this short-form script for virality, clarity, and human tone. "
            "Return one short revision only, no bullet points.\n\n"
            f"{draft}"
        )
        return self.router.generate_text(prompt, task_type="optimize")

    def run(self, state: PipelineState) -> dict[str, Any]:
        def _execute() -> dict[str, Any]:
            target_words = self._target_word_count()
            prompt = (
                f"Create a short-form viral script about: {state.topic}.\n"
                f"Use these trend signals:\n{state.research_text}\n\n"
                f"Keep it conversational and human. Start with a strong hook, include one emotional trigger, "
                f"one practical insight, and a clear CTA. Tone: influencer, not corporate.\n"
                f"Target length: about {target_words} words so the voiceover lands near {getattr(self.config, 'video_target_duration_seconds', 60)} seconds.\n"
                f"Structure: hook, trend context, 3 value beats, CTA."
            )
            draft = self.router.generate_text(prompt, task_type="script")
            breakdown = self.scorer.score(draft, state.research_text)
            score = breakdown.total
            critique = self._critique(draft)
            if score < 78 or len(draft.split()) < int(target_words * 0.8):
                revised_prompt = (
                    "Rewrite this script to be more viral and concise, without sounding robotic.\n\n"
                    f"Expand it toward about {target_words} words if it is too short.\n"
                    f"Draft:\n{draft}\n\nFeedback:\n{critique}"
                )
                revised = self.router.generate_text(revised_prompt, task_type="script")
            else:
                revised = draft
            retention = self.retention.analyze(revised)
            word_count = len(revised.split())
            ideal_words = self._target_word_count()
            length_penalty = abs(word_count - ideal_words) // 10
            score = max(0, min(100, score - length_penalty))
            state.script = revised
            self.memory.save_memory("script", revised, {"topic": state.topic, "score": score})
            return {
                "status": "ok",
                "summary": f"Generated script scored {score}/100",
                "score": score,
                "word_count": word_count,
                "target_word_count": ideal_words,
                "score_breakdown": breakdown.__dict__,
                "retention": retention.__dict__,
                "script": revised,
            }

        return self.healer.safe_execute(self.name, _execute, retries=1)
