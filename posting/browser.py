from __future__ import annotations

from typing import Any


class BrowserAutomationPoster:
    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger

    def post(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            return {"status": "browser_unavailable", "error": str(exc), **record}

        target = record.get("platform")
        urls = {
            "youtube": "https://studio.youtube.com/",
            "meta": "https://business.facebook.com/",
            "x": "https://x.com/compose/post",
            "tiktok": "https://www.tiktok.com/upload",
        }
        url = urls.get(target, "https://www.google.com/")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1800})
                page.goto(url, wait_until="domcontentloaded", timeout=90_000)
                if self.logger:
                    self.logger.info("Opened %s for manual or semi-automated publishing.", url)
                browser.close()
            return {"status": "browser_opened", "platform": target, "url": url, **record}
        except Exception as exc:
            return {"status": "browser_failed", "error": str(exc), "platform": target, "url": url, **record}
