from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from posting.models import PostDraft


@dataclass
class PostingJob:
    platform: str
    account_id: str
    title: str
    caption: str
    media_path: str
    hashtags: list[str]
    scheduled_for: str | None = None
    metadata: dict[str, Any] | None = None


class PostingWorkflow:
    def __init__(self, poster, account_manager, logger=None):
        self.poster = poster
        self.account_manager = account_manager
        self.logger = logger

    def build_jobs(self, title: str, caption: str, media_path: str, hashtags: list[str], platforms: list[str]) -> list[PostingJob]:
        jobs: list[PostingJob] = []
        seen_platforms: set[str] = set()
        for platform in platforms:
            normalized_platform = str(platform).strip().lower()
            if not normalized_platform or normalized_platform in seen_platforms:
                continue
            seen_platforms.add(normalized_platform)
            accounts = self.account_manager.plan_distribution(platform, posts=1)
            if not accounts:
                jobs.append(
                    PostingJob(
                        platform=normalized_platform,
                        account_id="unassigned",
                        title=title,
                        caption=caption,
                        media_path=media_path,
                        hashtags=hashtags,
                    )
                )
                continue
            for account in accounts:
                jobs.append(
                    PostingJob(
                        platform=normalized_platform,
                        account_id=account.account_id,
                        title=title,
                        caption=caption,
                        media_path=media_path,
                        hashtags=hashtags,
                        metadata={"display_name": account.display_name, "api_mode": account.api_mode},
                    )
                )
        return jobs

    def execute(self, jobs: list[PostingJob]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for job in jobs:
            draft = PostDraft(
                platform=job.platform,
                title=job.title,
                caption=job.caption,
                media_path=job.media_path,
                hashtags=job.hashtags,
                metadata={"account_id": job.account_id, **(job.metadata or {})},
            )
            result = self.poster.queue_post(draft)
            result["account_id"] = job.account_id
            if job.account_id and job.account_id != "unassigned":
                self.account_manager.mark_used(job.account_id)
            results.append(result)
        return results
