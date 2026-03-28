from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PostDraft:
    platform: str
    title: str
    caption: str
    media_path: str
    hashtags: list[str]
    scheduled_for: str | None = None
    status: str = "draft"
    metadata: dict[str, Any] | None = None

