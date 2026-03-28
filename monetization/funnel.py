from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from utils.text import slugify


@dataclass
class FunnelAsset:
    title: str
    body: str
    cta: str


@dataclass
class AffiliateFunnel:
    slug: str
    products: list[dict[str, str]]
    landing_assets: list[FunnelAsset] = field(default_factory=list)
    email_sequence: list[str] = field(default_factory=list)
    disclosure: str = ""


class AffiliateFunnelEngine:
    def __init__(self, memory=None, logger=None):
        self.memory = memory
        self.logger = logger

    def build(self, topic: str, products: list[dict[str, str]], disclosure: str) -> AffiliateFunnel:
        slug = slugify(topic)
        landing_assets = [
            FunnelAsset(
                title=f"The {topic} toolkit",
                body=f"Everything you need to copy the workflow behind {topic}.",
                cta="Get the exact setup",
            ),
            FunnelAsset(
                title="Why it works",
                body="Fast steps, low friction, and a strong result-focused hook.",
                cta="See the breakdown",
            ),
        ]
        email_sequence = [
            f"Subject: {topic} tools you can use today",
            f"Subject: The exact workflow behind {topic}",
            f"Subject: Quick win for your {topic} setup",
        ]
        return AffiliateFunnel(
            slug=slug,
            products=products,
            landing_assets=landing_assets,
            email_sequence=email_sequence,
            disclosure=disclosure,
        )

