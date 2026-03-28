from __future__ import annotations

from typing import Any

from agents.base import BaseAgent, PipelineState
from analytics.retention import RetentionOptimizer
from analytics.viral_scoring import ViralScorer


class OptimizationAgent(BaseAgent):
    name = "optimize"

    def __init__(self, config, router, memory, healer, logger=None):
        super().__init__(config, router, memory, healer, logger=logger)
        self.scorer = ViralScorer(memory=memory, logger=logger)
        self.retention = RetentionOptimizer(memory=memory, logger=logger)

    def _variation(self, state: PipelineState, variant: int) -> str:
        return self.router.generate_text(
            f"Write variation {variant} of the caption for this script. Keep it energetic and short.\n\n{state.script}",
            task_type="optimize",
        )

    def _llm_rank(self, variations: list[dict[str, Any]], topic: str) -> str:
        prompt = (
            f"Rank these short-form caption variations for topic '{topic}'. "
            f"Pick the most viral one and explain why in one short paragraph.\n\n"
            + "\n".join(f"{item['variant']}: {item['text']}" for item in variations)
        )
        return self.router.generate_text(prompt, task_type="optimize")

    def run(self, state: PipelineState) -> dict[str, Any]:
        def _execute() -> dict[str, Any]:
            variations = [self._variation(state, index) for index in range(1, 6)]
            scores = []
            for index, text in enumerate(variations, 1):
                breakdown = self.scorer.score(text, state.research_text)
                retention = self.retention.analyze(text)
                score = min(100, breakdown.total + len(retention.pacing_notes) * 2)
                scores.append(
                    {
                        "variant": index,
                        "score": score,
                        "text": text,
                        "breakdown": breakdown.__dict__,
                        "retention": retention.__dict__,
                    }
                )
            best = max(scores, key=lambda item: item["score"])
            llm_rank = self._llm_rank(scores[:3], state.topic)
            state.caption = best["text"]
            state.hashtags = ["#viral", "#shorts", "#ai", f"#{state.topic.replace(' ', '').lower()}"]
            self.memory.save_memory("optimization", str(scores), {"topic": state.topic, "best": best["variant"]})
            self.memory.save_memory("ab_test_summary", llm_rank, {"topic": state.topic, "best": best["variant"]})
            return {
                "status": "ok",
                "summary": f"Selected variation {best['variant']} with score {best['score']}/100",
                "best": best,
                "variations": scores,
                "hashtags": state.hashtags,
                "caption": state.caption,
                "llm_rank": llm_rank,
            }

        return self.healer.safe_execute(self.name, _execute, retries=1)
