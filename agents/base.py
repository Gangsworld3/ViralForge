from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelineState:
    topic: str
    audience: str = "general"
    trend_items: list[dict[str, Any]] = field(default_factory=list)
    research_text: str = ""
    script: str = ""
    video_plan: dict[str, Any] = field(default_factory=dict)
    video_path: str = ""
    subtitle_path: str = ""
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)
    monetization: dict[str, Any] = field(default_factory=dict)
    analytics: dict[str, Any] = field(default_factory=dict)


class BaseAgent:
    name = "base"

    def __init__(self, config, router, memory, healer, logger=None):
        self.config = config
        self.router = router
        self.memory = memory
        self.healer = healer
        self.logger = logger

    def run(self, state: PipelineState) -> dict[str, Any]:
        raise NotImplementedError
