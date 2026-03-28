from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any

import requests


@dataclass
class LiveTrendItem:
    title: str
    source: str
    description: str
    url: str = ""
    score: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class LiveTrendCollector:
    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger

    def _debug(self, message: str, *args: Any) -> None:
        if self.logger and hasattr(self.logger, "debug"):
            self.logger.debug(message, *args)

    def _normalize_title(self, text: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s\-]+", "", text)).strip().lower()

    def _request_json(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
        response = requests.get(url, params=params, headers=headers, timeout=25)
        response.raise_for_status()
        text = response.text.strip()
        if text.startswith(")]}'"):
            text = text[4:]
        return response.json() if response.headers.get("content-type", "").startswith("application/json") else json.loads(text)

    def _browser_lines(self, url: str) -> list[str]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            self._debug("Playwright unavailable for browser fallback: %s", exc)
            return []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1800})
                page.goto(url, wait_until="networkidle", timeout=45_000)
                main_text = ""
                for selector in ["main", "body"]:
                    try:
                        main_text = page.locator(selector).inner_text(timeout=8000)
                        if main_text:
                            break
                    except Exception:
                        continue
                browser.close()
                return [line.strip() for line in main_text.splitlines() if line.strip()]
        except Exception as exc:
            self._debug("Browser trend scrape failed for %s: %s", url, exc)
            return []

    def _lines_to_items(self, lines: list[str], source: str, url_prefix: str = "") -> list[LiveTrendItem]:
        items: list[LiveTrendItem] = []
        skip_terms = {
            "google trends",
            "trending now",
            "home",
            "explore",
            "sign in",
            "reddit",
            "posts",
            "comments",
            "more",
            "sort by",
            "following",
        }
        for line in lines:
            normalized = re.sub(r"\s+", " ", line).strip()
            lower = normalized.lower()
            if (
                len(normalized) < 12
                or len(normalized) > 160
                or lower in skip_terms
                or any(term in lower for term in skip_terms)
                or normalized.count(" ") < 1
            ):
                continue
            if not any(ch.isalpha() for ch in normalized):
                continue
            score = 55
            if any(marker in lower for marker in ["ai", "viral", "trend", "breaking", "new", "watch", "update"]):
                score += 15
            if len(normalized.split()) <= 8:
                score += 5
            items.append(
                LiveTrendItem(
                    title=normalized,
                    source=source,
                    description=normalized[:240],
                    url=url_prefix,
                    score=min(100, score),
                )
            )
        return items

    def google_trends(self, geo: str = "US", limit: int = 10) -> list[LiveTrendItem]:
        candidates: list[LiveTrendItem] = []
        urls = [
            (
                "https://trends.google.com/trends/api/dailytrends",
                {
                    "hl": "en-US",
                    "tz": "0",
                    "geo": geo,
                    "ns": "15",
                    # Google Trends requires an explicit end-date for daily trends.
                    "ed": datetime.now(timezone.utc).strftime("%Y%m%d"),
                },
            ),
        ]
        for url, params in urls:
            try:
                data = self._request_json(url, params=params, headers={"User-Agent": "Mozilla/5.0"})
                days = data.get("default", {}).get("trendingSearchesDays", [])
                for day in days:
                    for item in day.get("trendingSearches", [])[:limit]:
                        title = item.get("title", {}).get("query", "")
                        articles = item.get("articles", [])
                        description = articles[0].get("snippet", "") if articles else item.get("formattedTraffic", "")
                        candidates.append(
                            LiveTrendItem(
                                title=title,
                                source="google_trends",
                                description=description,
                                url=item.get("shareUrl", ""),
                                score=80,
                                metadata={"traffic": item.get("formattedTraffic", "")},
                            )
                        )
                if candidates:
                    return candidates[:limit]
            except Exception as exc:
                self._debug("Google Trends fetch failed: %s", exc)
        browser_lines = self._browser_lines(f"https://trends.google.com/trends/trendingsearches/daily?geo={geo}&hl=en-US")
        candidates.extend(self._lines_to_items(browser_lines, source="google_trends_browser", url_prefix="https://trends.google.com/trends/trendingsearches/daily"))
        if candidates:
            candidates.sort(key=lambda item: item.score, reverse=True)
            return candidates[:limit]
        return candidates

    def reddit_popular(self, limit: int = 10) -> list[LiveTrendItem]:
        candidates: list[LiveTrendItem] = []
        urls = [
            ("https://api.reddit.com/r/popular", {"limit": limit, "raw_json": 1}),
            ("https://www.reddit.com/r/popular.json", {"limit": limit, "raw_json": 1}),
        ]
        for url, params in urls:
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ViralForge/1.0",
                        "Accept": "application/json",
                    },
                    timeout=25,
                )
                response.raise_for_status()
                data = response.json()
                children = data.get("data", {}).get("children", [])
                for child in children[:limit]:
                    post = child.get("data", {})
                    candidates.append(
                        LiveTrendItem(
                            title=post.get("title", ""),
                            source="reddit_popular",
                            description=post.get("selftext", "")[:240],
                            url=f"https://www.reddit.com{post.get('permalink', '')}",
                            score=max(40, min(95, int(post.get("score", 0) / 100))),
                            metadata={"subreddit": post.get("subreddit", ""), "score": post.get("score", 0)},
                        )
                    )
                if candidates:
                    return candidates[:limit]
            except Exception as exc:
                self._debug("Reddit popular fetch failed: %s", exc)
        browser_lines = self._browser_lines("https://www.reddit.com/r/popular/")
        candidates.extend(self._lines_to_items(browser_lines, source="reddit_browser", url_prefix="https://www.reddit.com/r/popular/"))
        if candidates:
            candidates.sort(key=lambda item: item.score, reverse=True)
            return candidates[:limit]
        return candidates

    def youtube_most_popular(self, geo: str = "US", limit: int = 10) -> list[LiveTrendItem]:
        if not self.config.youtube_api_key:
            return []
        if not self.config.youtube_api_key.startswith("AIza"):
            self._debug("YouTube API key does not look valid; skipping live YouTube trends.")
            return []
        try:
            data = self._request_json(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "part": "snippet,statistics",
                    "chart": "mostPopular",
                    "regionCode": geo,
                    "maxResults": limit,
                    "key": self.config.youtube_api_key,
                },
            )
            items: list[LiveTrendItem] = []
            for item in data.get("items", [])[:limit]:
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                items.append(
                    LiveTrendItem(
                        title=snippet.get("title", ""),
                        source="youtube_most_popular",
                        description=snippet.get("description", "")[:240],
                        url=f"https://www.youtube.com/watch?v={item.get('id', '')}",
                        score=max(50, min(100, int(int(stats.get("viewCount", 0)) / 100000))),
                        metadata={"channel": snippet.get("channelTitle", ""), "views": stats.get("viewCount", 0)},
                    )
                )
            return items[:limit]
        except Exception as exc:
            self._debug("YouTube popular fetch failed: %s", exc)
            return []

    def collect(self, topic: str, limit: int = 10) -> list[LiveTrendItem]:
        merged: dict[str, LiveTrendItem] = {}

        def add_candidates(candidates: list[LiveTrendItem]) -> None:
            for item in candidates:
                if not item.title:
                    continue
                key = self._normalize_title(item.title)
                if not key:
                    continue
                existing = merged.get(key)
                if existing is None:
                    merged[key] = item
                    merged[key].metadata = dict(item.metadata or {})
                    merged[key].metadata.setdefault("sources", [item.source])
                    merged[key].metadata.setdefault("source_count", 1)
                    continue
                sources = list(existing.metadata.get("sources", []))
                if item.source not in sources:
                    sources.append(item.source)
                existing.metadata["sources"] = sources
                existing.metadata["source_count"] = len(sources)
                existing.score = max(existing.score, item.score) + min(12, (len(sources) - 1) * 4)
                if len(item.description) > len(existing.description):
                    existing.description = item.description
                if item.url and not existing.url:
                    existing.url = item.url
                for meta_key, meta_value in (item.metadata or {}).items():
                    if meta_key not in existing.metadata:
                        existing.metadata[meta_key] = meta_value

        slice_size = max(2, limit // 3)
        add_candidates(self.google_trends(limit=slice_size))
        add_candidates(self.reddit_popular(limit=slice_size))
        add_candidates(self.youtube_most_popular(limit=slice_size))
        items = list(merged.values())
        if not items:
            items = [
                LiveTrendItem(
                    title=f"{topic} is growing",
                    source="local",
                    description="Fallback local trend signal",
                    score=50,
                )
            ]
        def rank(item: LiveTrendItem) -> tuple[int, int, int, int]:
            sources = item.metadata.get("sources", []) if item.metadata else []
            source_bonus = len(sources) * 5
            title_bonus = 5 if len(item.title.split()) <= 8 else 0
            trend_bonus = 10 if any(token in item.title.lower() for token in ["ai", "viral", "trend", "breaking", "new"]) else 0
            return (item.score + source_bonus + title_bonus + trend_bonus, source_bonus, title_bonus, trend_bonus)

        items.sort(key=rank, reverse=True)
        return items[:limit]
