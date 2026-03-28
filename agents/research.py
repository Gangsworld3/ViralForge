from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import requests

from agents.base import BaseAgent, PipelineState
from research.live_trends import LiveTrendCollector
from research.trend_miner import TrendMiner
from utils.text import extract_keywords


class ResearchAgent(BaseAgent):
    name = "research"

    def __init__(self, config, router, memory, healer, logger=None):
        super().__init__(config, router, memory, healer, logger=logger)
        self.miner = TrendMiner(memory=memory, logger=logger)
        self.live_trends = LiveTrendCollector(config, logger=logger)

    def _parse_rss(self, url: str) -> list[dict[str, Any]]:
        try:
            response = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            root = ET.fromstring(response.text)
            items = []
            candidates = root.findall(".//item") or root.findall(".//entry")
            for entry in candidates[:10]:
                title = (entry.findtext("title") or "").strip()
                description = (entry.findtext("description") or entry.findtext("summary") or "").strip()
                items.append({"title": title, "description": description, "source": url})
            return items
        except Exception as exc:
            if self.logger and hasattr(self.logger, "debug"):
                self.logger.debug("RSS parse failed for %s: %s", url, exc)
            return []

    def run(self, state: PipelineState) -> dict[str, Any]:
        def _execute() -> dict[str, Any]:
            trend_items: list[dict[str, Any]] = []
            live_items = self.live_trends.collect(state.topic, limit=self.config.research_max_trends)
            trend_items.extend(
                {
                    "title": item.title,
                    "description": item.description,
                    "source": item.source,
                    "url": item.url,
                    "score": item.score,
                    "metadata": item.metadata,
                }
                for item in live_items
            )
            if len(trend_items) < self.config.research_max_trends:
                for source in self.config.research_rss_sources:
                    trend_items.extend(self._parse_rss(source))
                    if len(trend_items) >= self.config.research_max_trends:
                        break
            trend_items = trend_items[: self.config.research_max_trends]
            if not trend_items:
                trend_items = [
                    {"title": f"{state.topic} is rising fast", "description": "Fallback local trend signal", "source": "local"},
                    {"title": "Creator economy and AI are converging", "description": "High intent general trend", "source": "local"},
                ]
            state.trend_items = trend_items
            mined = self.miner.mine(state.topic, trend_items)
            state.research_text = "\n".join(f"- {item['title']}: {item.get('description', '')}" for item in trend_items)
            competitor_prompt = (
                f"Summarize the common viral angles in these trend items for topic '{state.topic}'. "
                f"Return 3 hook patterns and 3 content opportunities in a short human tone.\n\n{state.research_text}"
            )
            competitor_summary = self.router.generate_text(competitor_prompt, task_type="research")
            hook_patterns = [item.hook for item in mined[:5]] or [item["title"][:90] for item in trend_items[:5]]
            self.memory.save_memory("trend_research", state.research_text, {"topic": state.topic, "count": len(trend_items)})
            self.memory.save_memory("trend_analysis", competitor_summary, {"topic": state.topic})
            return {
                "status": "ok",
                "summary": f"Collected {len(trend_items)} live trend signals",
                "trend_items": trend_items,
                "live_trends": [item.__dict__ for item in live_items],
                "keywords": extract_keywords(state.research_text),
                "hook_patterns": hook_patterns,
                "trend_findings": [finding.__dict__ for finding in mined],
                "competitor_summary": competitor_summary,
            }

        return self.healer.safe_execute(self.name, _execute, retries=1)
