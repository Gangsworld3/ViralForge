from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.base import BaseAgent, PipelineState
from posting.poster import PostingEngine
from utils.media_host import ensure_public_media_base_url


class PostingAgent(BaseAgent):
    name = "post"

    def __init__(self, config, router, memory, healer, logger=None):
        super().__init__(config, router, memory, healer, logger=logger)
        self.poster = PostingEngine(config, memory, logger=logger)

    def run(self, state: PipelineState) -> dict[str, Any]:
        def _execute() -> dict[str, Any]:
            if not state.video_path:
                raise ValueError("Posting stage requires a rendered video_path.")
            platforms = list(self.config.posting_default_platforms)
            if self.config.meta_instagram_account_id and "instagram" not in platforms:
                platforms.append("instagram")
            caption = self.poster.format_caption(title=state.topic, script=state.caption or state.script, hashtags=state.hashtags)
            public_media_url = ensure_public_media_base_url(self.config, logger=self.logger)
            media_name = Path(state.video_path).name if state.video_path else ""
            payloads = self.poster.queue_multi_account(
                title=state.topic,
                caption=caption,
                media_path=state.video_path,
                hashtags=state.hashtags,
                platforms=platforms,
            )
            mode = getattr(self.config, "posting_self_mode", "api")
            if public_media_url:
                for item in payloads:
                    metadata = item.setdefault("metadata", {})
                    metadata.setdefault("media_url", f"{public_media_url.rstrip('/')}/{media_name}")
                    metadata.setdefault("public_media_url", metadata["media_url"])
            return {
                "status": "ok",
                "summary": (
                    f"Prepared {len(payloads)} manual self-post bundles"
                    if mode == "manual"
                    else f"Queued {len(payloads)} posts"
                ),
                "posts": payloads,
                "caption": caption,
                "public_media_url": f"{public_media_url.rstrip('/')}/{media_name}" if public_media_url else "",
            }

        return self.healer.safe_execute(self.name, _execute, retries=1)
