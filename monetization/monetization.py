from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from monetization.funnel import AffiliateFunnelEngine
from utils.text import slugify


@dataclass
class MonetizationPlan:
    eligible: bool
    revenue_streams: list[str]
    affiliate_copy: str
    sponsorship_email: str
    disclosure: str


class MonetizationEngine:
    def __init__(self, config, memory, logger=None):
        self.config = config
        self.memory = memory
        self.logger = logger
        self.funnel = AffiliateFunnelEngine(memory=memory, logger=logger)

    @staticmethod
    def affiliate_link(base_url: str, affiliate_tag: str | None = None, params: dict[str, str] | None = None) -> str:
        params = params or {}
        if affiliate_tag:
            params["tag"] = affiliate_tag
        if params:
            separator = "&" if "?" in base_url else "?"
            query = urlencode(params)
            return base_url + separator + query
        return base_url

    @staticmethod
    def disclosure_text() -> str:
        return "Disclosure: This post may contain affiliate links, which means we may earn a commission at no extra cost to you."

    def detect_eligibility(self, analytics_summary: dict[str, Any]) -> bool:
        views = analytics_summary.get("total_views", 0)
        revenue = analytics_summary.get("total_revenue", 0.0)
        return views >= 1000 or revenue > 0

    def discover_products(self, topic: str, limit: int = 5) -> list[dict[str, str]]:
        query = f"{topic} best tools"
        url = "https://duckduckgo.com/html/"
        try:
            response = requests.get(url, params={"q": query}, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            products: list[dict[str, str]] = []
            for link in soup.select(".result__a")[:limit]:
                title = link.get_text(" ", strip=True)
                href = link.get("href", "")
                if title and href:
                    products.append({"title": title, "url": href})
            if products:
                return products
        except Exception:
            pass
        keywords = [token.strip() for token in topic.replace("-", " ").split() if token.strip()]
        fallback = [
            {"title": f"{topic} starter kit", "url": f"https://example.com/{slugify(topic)}-starter"},
            {"title": f"{topic} creator toolkit", "url": f"https://example.com/{slugify(topic)}-toolkit"},
        ]
        if keywords:
            fallback.append({"title": f"{keywords[0].title()} workflow upgrade", "url": f"https://example.com/{slugify(keywords[0])}-upgrade"})
        return fallback[:limit]

    def generate_plan(
        self,
        topic: str,
        analytics_summary: dict[str, Any],
        prompt: str,
        products: list[dict[str, str]] | None = None,
    ) -> MonetizationPlan:
        eligible = self.detect_eligibility(analytics_summary)
        revenue_streams = ["affiliate", "ads", "sponsorships"] if eligible else ["affiliate"]
        slug = slugify(topic)
        products = products or self.discover_products(topic)
        funnel = self.funnel.build(topic, products, self.disclosure_text())
        affiliate_copy = (
            f"Top pick for {topic}: grab the gear, tool, or product that matches this workflow.\n"
            f"Use the CTA: check the link in bio for the exact setup we used on {slug}.\n"
            + "\n".join(f"- {product['title']}" for product in products[:3])
        )
        sponsorship_email = (
            f"Subject: Sponsorship opportunity with ViralForge AI around {topic}\n\n"
            f"Hi,\n\n"
            f"We are building high-engagement short-form content around {topic}. "
            f"Your brand fits the audience and we would love to discuss a sponsored integration.\n\n"
            f"Best,\nViralForge AI"
        )
        return MonetizationPlan(
            eligible=eligible,
            revenue_streams=revenue_streams,
            affiliate_copy=affiliate_copy,
            sponsorship_email=sponsorship_email,
            disclosure=self.disclosure_text(),
        )
