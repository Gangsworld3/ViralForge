from __future__ import annotations

from typing import Any

from agents.base import BaseAgent, PipelineState
from video_engine.brain import VideoBrain
from video_engine.engine import VideoEngine


class VideoAgent(BaseAgent):
    name = "video"

    def __init__(self, config, router, memory, healer, logger=None):
        super().__init__(config, router, memory, healer, logger=logger)
        self.engine = VideoEngine(config, memory, logger=logger)
        self.brain = VideoBrain(config, router, memory, logger=logger)

    def run(self, state: PipelineState) -> dict[str, Any]:
        def _execute() -> dict[str, Any]:
            plan = self.brain.plan_video(
                topic=state.topic,
                script=state.script,
                trend_items=state.trend_items,
                research_text=state.research_text,
                analytics_hint=state.analytics,
            )
            score_report = self.brain.score_plan(plan, state.topic, state.script, state.trend_items)
            regenerated = False
            if score_report["score"] < 72:
                revised_plan = self.brain.revise_plan(plan, state.topic, state.script, state.trend_items, score_report)
                revised_score = self.brain.score_plan(revised_plan, state.topic, state.script, state.trend_items)
                if revised_score["score"] >= score_report["score"]:
                    plan = revised_plan
                    score_report = revised_score
                    regenerated = True
            state.video_plan = plan
            video = self.engine.build_video(
                topic=state.topic,
                script=state.script,
                trend_items=state.trend_items,
                plan=plan,
            )
            artifact_score = self.brain.score_render_artifact(video["video_path"], plan)
            if artifact_score["score"] < 70 and not regenerated:
                revised_plan = self.brain.revise_plan(plan, state.topic, state.script, state.trend_items, artifact_score)
                revised_score = self.brain.score_plan(revised_plan, state.topic, state.script, state.trend_items)
                if revised_score["score"] >= score_report["score"]:
                    plan = revised_plan
                    score_report = revised_score
                    state.video_plan = plan
                    video = self.engine.build_video(
                        topic=state.topic,
                        script=state.script,
                        trend_items=state.trend_items,
                        plan=plan,
                    )
                    artifact_score = self.brain.score_render_artifact(video["video_path"], plan)
                    regenerated = True
            if regenerated:
                video["regenerated"] = True
            video["plan"] = plan
            video["plan_score"] = score_report
            video["artifact_score"] = artifact_score
            state.video_path = video["video_path"]
            state.subtitle_path = video["subtitle_path"]
            return video

        return self.healer.safe_execute(self.name, _execute, retries=1)
