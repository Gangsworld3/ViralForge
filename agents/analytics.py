from __future__ import annotations

from typing import Any

from agents.base import BaseAgent, PipelineState
from analytics.analytics import AnalyticsEngine, MetricRecord
from analytics.retention import RetentionOptimizer
from analytics.viral_scoring import ViralScorer


class AnalyticsAgent(BaseAgent):
    name = "analytics"

    def __init__(self, config, router, memory, healer, logger=None):
        super().__init__(config, router, memory, healer, logger=logger)
        self.engine = AnalyticsEngine(config, memory, logger=logger)
        self.scorer = ViralScorer(memory=memory, logger=logger)
        self.retention = RetentionOptimizer(memory=memory, logger=logger)

    def run(self, state: PipelineState) -> dict[str, Any]:
        def _execute() -> dict[str, Any]:
            base_views = 700 + len(state.topic) * 35 + len(state.script.split()) * 2
            likes = max(40, len(state.script.split()) // 2)
            comments = max(8, len(state.trend_items) * 2)
            shares = max(5, len(state.hashtags))
            record = MetricRecord(
                content_id=state.topic.replace(" ", "-").lower(),
                platform="aggregate",
                views=base_views,
                likes=likes,
                comments=comments,
                shares=shares,
                watch_time_seconds=float(base_views) * 0.45,
                revenue=0.0,
                metadata={"topic": state.topic},
            )
            summary = self.engine.ingest(record)
            overall = self.engine.summarize()
            winners = self.engine.winning_patterns()
            score_breakdown = self.scorer.score(state.script or state.caption, state.research_text)
            retention = self.retention.analyze(state.script or state.caption, overall)
            improvement_prompt = (
                f"Based on these winning content IDs and analytics, give one practical improvement for the next short-form video.\n"
                f"Winners: {winners}\nMetrics: {overall}"
            )
            improvement_note = self.router.generate_text(improvement_prompt, task_type="analytics")
            state.analytics = {**summary, **overall}
            state.analytics["winning_patterns"] = winners
            state.analytics["improvement_note"] = improvement_note
            state.analytics["predicted_score"] = score_breakdown.total
            state.analytics["score_breakdown"] = score_breakdown.__dict__
            state.analytics["retention"] = retention.__dict__
            return {
                "status": "ok",
                "summary": f"Engagement score {summary['engagement_score']}",
                "metrics": state.analytics,
                "improvement_note": improvement_note,
                "score_breakdown": score_breakdown.__dict__,
                "retention": retention.__dict__,
            }

        return self.healer.safe_execute(self.name, _execute, retries=1)
