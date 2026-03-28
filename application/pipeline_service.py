from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.analytics import AnalyticsAgent
from agents.base import PipelineState
from agents.monetization import MonetizationAgent
from agents.optimization import OptimizationAgent
from agents.posting import PostingAgent
from agents.research import ResearchAgent
from agents.script import ScriptAgent
from agents.video import VideoAgent
from llm_router.router import LLMRouter
from memory.store import MemoryStore
from posting.readiness import PostingReadinessChecker
from self_healing.healer import SelfHealingEngine
from utils.json_io import load_json, save_json
from utils.media_host import resolve_public_media_base_url


class ViralForgePipeline:
    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger
        self.memory = MemoryStore(config, logger=logger)
        self.router = LLMRouter(config, memory=self.memory, logger=logger)
        self.healer = SelfHealingEngine(config, llm_router=self.router, logger=logger)
        self.research_agent = ResearchAgent(config, self.router, self.memory, self.healer, logger=logger)
        self.script_agent = ScriptAgent(config, self.router, self.memory, self.healer, logger=logger)
        self.video_agent = VideoAgent(config, self.router, self.memory, self.healer, logger=logger)
        self.optimize_agent = OptimizationAgent(config, self.router, self.memory, self.healer, logger=logger)
        self.post_agent = PostingAgent(config, self.router, self.memory, self.healer, logger=logger)
        self.analytics_agent = AnalyticsAgent(config, self.router, self.memory, self.healer, logger=logger)
        self.monetization_agent = MonetizationAgent(config, self.router, self.memory, self.healer, logger=logger)

    def run_once(self, topic: str | None = None) -> dict[str, Any]:
        topic = topic or "AI productivity hacks"
        state = PipelineState(topic=topic)
        result: dict[str, Any] = {"topic": topic}

        for name, agent in [
            ("research", self.research_agent),
            ("script", self.script_agent),
            ("optimize", self.optimize_agent),
            ("video", self.video_agent),
            ("post", self.post_agent),
            ("analytics", self.analytics_agent),
            ("monetize", self.monetization_agent),
        ]:
            payload = agent.run(state)
            result[name] = payload

        result["video_path"] = state.video_path
        result["subtitle_path"] = state.subtitle_path
        result["caption"] = state.caption
        result["hashtags"] = state.hashtags
        result["video_plan"] = state.video_plan
        result["analytics"] = state.analytics
        result["monetization"] = state.monetization
        result["readiness"] = PostingReadinessChecker(self.config, logger=self.logger).report()
        if state.video_path:
            base_url = resolve_public_media_base_url(self.config)
            if base_url:
                result["video_public_url"] = f"{base_url.rstrip('/')}/media/{Path(state.video_path).name}"
        self.memory.save_memory("pipeline_run", str(result), {"topic": topic})
        save_json(self.config.data_dir / "reports" / "last_run.json", result)
        return result

    def run_manual_self_post(self, topic: str | None = None) -> dict[str, Any]:
        original_mode = getattr(self.config, "posting_self_mode", "api")
        try:
            self.config.posting_self_mode = "manual"
            return self.run_once(topic=topic)
        finally:
            self.config.posting_self_mode = original_mode

    def snapshot(self) -> str:
        memory_snapshot = self.memory.snapshot()
        analytics_snapshot = self.analytics_agent.engine.summarize()
        last_run = load_json(self.config.data_dir / "reports" / "last_run.json", default={}) or {}
        readiness = PostingReadinessChecker(self.config, logger=self.logger).report()
        return (
            f"Topic pipeline ready\n"
            f"Video mode: {getattr(self.config, 'video_quality_mode', 'n/a')}\n"
            f"Video target: {getattr(self.config, 'video_target_duration_seconds', 'n/a')}s @ "
            f"{getattr(self.config, 'video_target_width', 'n/a')}x{getattr(self.config, 'video_target_height', 'n/a')}\n"
            f"Memory items: {memory_snapshot['memory_items']}\n"
            f"Learning patterns: {memory_snapshot['learning_patterns']}\n"
            f"Recent kinds: {', '.join(memory_snapshot['recent_kinds']) or 'none'}\n"
            f"Analytics: {analytics_snapshot}\n"
            f"Video brain: {last_run.get('video_plan', {}).get('theme', 'n/a')} / "
            f"{last_run.get('video_plan', {}).get('pacing', 'n/a')} / "
            f"{last_run.get('video_plan', {}).get('subtitle_preset', 'n/a')}\n"
            f"Posting readiness: {'ready' if readiness['ready'] else 'blocked'}\n"
            f"Last topic: {last_run.get('topic', 'n/a')}\n"
            f"Last video: {last_run.get('video_path', 'n/a')}"
        )
