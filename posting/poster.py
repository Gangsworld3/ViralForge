from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from posting.accounts import AccountManager
from posting.adapters import PostingAdapterRouter
from posting.browser import BrowserAutomationPoster
from posting.models import PostDraft
from posting.workflow import PostingWorkflow
from utils.media_host import resolve_public_media_base_url
from utils.sqlite_db import ensure_state_db, open_db


class PostingEngine:
    RETRY_BASE_SECONDS = 300
    RETRY_MAX_SECONDS = 6 * 3600
    RETRY_MAX_ATTEMPTS = 5

    def __init__(self, config, memory, logger=None):
        self.config = config
        self.memory = memory
        self.logger = logger
        self.outbox = config.data_dir / "outbox" / "posts.jsonl"
        self.platform_queues = config.data_dir / "queues"
        self.retry_queue = self.platform_queues / "retry.jsonl"
        self.browser = BrowserAutomationPoster(config, logger=logger)
        self.adapters = PostingAdapterRouter(config, logger=logger)
        self.accounts = AccountManager(config, logger=logger)
        self.workflow = PostingWorkflow(self, self.accounts, logger=logger)
        ensure_state_db(config.state_db_path)
        self._migrate_legacy_posting_records()

    def _connection(self):
        return open_db(self.config.state_db_path)

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _iso(self, value: datetime | None = None) -> str:
        return (value or self._now()).isoformat()

    def _parse_iso(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None

    def _migrate_legacy_posting_records(self) -> None:
        with self._connection() as conn:
            existing = conn.execute("SELECT COUNT(*) FROM posting_records").fetchone()[0]
            if existing:
                return
            legacy_paths = [self.outbox, self.retry_queue]
            legacy_paths.extend(self.platform_queues.glob("*.jsonl"))
            seen_ids: set[str] = set()
            for path in legacy_paths:
                if not path.exists():
                    continue
                for raw_line in path.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except Exception:
                        continue
                    record_id = str(record.get("id", "")).strip()
                    if not record_id or record_id in seen_ids:
                        continue
                    seen_ids.add(record_id)
                    self._upsert_posting_record(conn, record)

    def _upsert_posting_record(self, conn, record: dict[str, Any]) -> None:
        record_id = str(record.get("id", "")).strip() or uuid.uuid4().hex
        record["id"] = record_id
        conn.execute(
            """
            INSERT INTO posting_records (
                id, platform, status, payload_json, retryable, next_attempt_at, attempts, max_attempts, retry_source, last_error, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                platform = excluded.platform,
                status = excluded.status,
                payload_json = excluded.payload_json,
                retryable = excluded.retryable,
                next_attempt_at = excluded.next_attempt_at,
                attempts = excluded.attempts,
                max_attempts = excluded.max_attempts,
                retry_source = excluded.retry_source,
                last_error = excluded.last_error,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                record_id,
                str(record.get("platform", "unknown")),
                str(record.get("status", "unknown")),
                json.dumps(record, ensure_ascii=False, sort_keys=True),
                1 if record.get("retryable", False) else 0,
                record.get("next_attempt_at"),
                int(record.get("attempts", 0) or 0),
                int(record.get("max_attempts", 0) or 0),
                record.get("retry_source"),
                record.get("last_error"),
            ),
        )

    def _retry_delay(self, attempts: int) -> int:
        attempts = max(1, attempts)
        return min(self.RETRY_MAX_SECONDS, self.RETRY_BASE_SECONDS * (2 ** (attempts - 1)))

    def _schedule_retry(
        self,
        record: dict[str, Any],
        reason: str,
        source: str,
        *,
        max_attempts: int | None = None,
    ) -> dict[str, Any]:
        attempts = int(record.get("attempts", 0) or 0) + 1
        max_attempts = max_attempts or self.RETRY_MAX_ATTEMPTS
        delay_seconds = self._retry_delay(attempts)
        next_attempt = self._now() + timedelta(seconds=delay_seconds)
        retry_record = dict(record)
        retry_record.update(
            {
                "status": "retry_scheduled" if attempts < max_attempts else "dead_letter",
                "retryable": attempts < max_attempts,
                "retry_source": source,
                "last_error": reason,
                "attempts": attempts,
                "max_attempts": max_attempts,
                "backoff_seconds": delay_seconds,
                "next_attempt_at": self._iso(next_attempt),
            }
        )
        with self._connection() as conn:
            self._upsert_posting_record(conn, retry_record)
        self.memory.save_memory(
            "post_retry",
            json.dumps(retry_record, ensure_ascii=False),
            {"platform": retry_record.get("platform", "unknown"), "source": source, "attempts": attempts},
        )
        return retry_record

    def _persist_final(self, record: dict[str, Any], memory_kind: str = "post_final") -> dict[str, Any]:
        final_record = dict(record)
        final_record["retryable"] = False
        final_record.setdefault("attempts", 0)
        final_record.setdefault("max_attempts", self.RETRY_MAX_ATTEMPTS)
        with self._connection() as conn:
            self._upsert_posting_record(conn, final_record)
        self.memory.save_memory(
            memory_kind,
            json.dumps(final_record, ensure_ascii=False),
            {"platform": final_record.get("platform", "unknown")},
        )
        return final_record

    def _prepare_manual_handoff(self, record: dict[str, Any]) -> dict[str, Any]:
        handoff_dir = self.config.data_dir / "self_post"
        handoff_dir.mkdir(parents=True, exist_ok=True)
        public_base = resolve_public_media_base_url(self.config)
        media_path = Path(record["media_path"])
        media_url = ""
        if public_base and media_path.name:
            media_url = f"{public_base.rstrip('/')}/{media_path.name}"
        handoff = {
            "id": record.get("id", uuid.uuid4().hex),
            "status": "handoff_prepared",
            "platform": record.get("platform", "unknown"),
            "provider": "manual",
            "message": "Manual self-post handoff prepared.",
            "title": record.get("title", ""),
            "caption": record.get("caption", ""),
            "hashtags": record.get("hashtags", []),
            "media_path": record.get("media_path", ""),
            "media_url": media_url,
            "instructions": [
                "Open the target platform account you own.",
                "Upload the generated video manually.",
                "Paste the caption and hashtags from this bundle.",
                "Use the provided public media URL if the platform asks for a remote source.",
            ],
            "metadata": {
                "self_post_mode": "manual",
                "public_media_url": media_url,
                "state_db_path": str(self.config.state_db_path),
            },
        }
        bundle_path = handoff_dir / f"{handoff['platform']}_{handoff['id']}.json"
        bundle_path.write_text(json.dumps(handoff, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        handoff["bundle_path"] = str(bundle_path)
        return self._persist_final(handoff, memory_kind="post_handoff")

    def list_manual_bundles(self, limit: int = 5) -> list[dict[str, Any]]:
        handoff_dir = self.config.data_dir / "self_post"
        if not handoff_dir.exists():
            return []
        bundles: list[dict[str, Any]] = []
        for path in sorted(handoff_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if len(bundles) >= limit:
                break
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            bundles.append(
                {
                    "file": str(path),
                    "platform": data.get("platform", "unknown"),
                    "status": data.get("status", "unknown"),
                    "title": data.get("title", ""),
                    "media_path": data.get("media_path", ""),
                    "media_url": data.get("media_url", ""),
                    "generated_at": path.stat().st_mtime,
                }
            )
        return bundles

    def list_outbox(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM posting_records
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            try:
                items.append(json.loads(row["payload_json"]))
            except Exception:
                continue
        return items

    def retry_due_posts(self, limit: int = 20) -> list[dict[str, Any]]:
        now_iso = self._iso()
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM posting_records
                WHERE retryable = 1
                  AND status = 'retry_scheduled'
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                ORDER BY updated_at ASC, id ASC
                LIMIT ?
                """,
                (now_iso, limit),
            ).fetchall()
        queued: list[dict[str, Any]] = []
        for row in rows:
            try:
                queued.append(json.loads(row["payload_json"]))
            except Exception:
                continue
        if not queued:
            return []
        processed: list[dict[str, Any]] = []
        for record in queued:
            retry_record = dict(record)
            retry_record["status"] = "retrying"
            retry_record["retryable"] = True
            result = self._post_live(retry_record, from_retry=True)
            if result.get("status") == "published":
                result["retried_from"] = record.get("id", "")
            processed.append(result)
        return processed

    def queue_post(self, draft: PostDraft) -> dict[str, Any]:
        record = asdict(draft)
        record["id"] = uuid.uuid4().hex
        if getattr(self.config, "posting_self_mode", "api") == "manual":
            return self._prepare_manual_handoff(record)
        if not self.config.posting_auto_publish and self.config.posting_dry_run:
            record["status"] = "queued"
            return self._persist_final(record, memory_kind="post_draft")
        return self._post_live(record)

    def _post_live(self, record: dict[str, Any], from_retry: bool = False) -> dict[str, Any]:
        platform = record.get("platform")
        if getattr(self.config, "posting_self_mode", "api") == "manual":
            return self._prepare_manual_handoff(record)
        if self.config.posting_auto_publish or not self.config.posting_dry_run:
            direct_result = self.adapters.publish(record)
            if direct_result.get("status") == "published":
                direct_result["id"] = record.get("id", direct_result.get("id", ""))
                return self._persist_final(
                    direct_result,
                    memory_kind="post_live" if not from_retry else "post_retry_success",
                )
            record["adapter_result"] = direct_result
            record["status"] = direct_result.get("status", "adapter_failed")
            if self.config.enable_browser_automation:
                browser_result = self.browser.post(record)
                if browser_result.get("status") in {"browser_opened", "browser_failed"}:
                    if browser_result.get("status") == "browser_opened":
                        browser_result["id"] = record.get("id", browser_result.get("id", ""))
                        return self._persist_final(browser_result, memory_kind="post_browser")
                    return self._schedule_retry(
                        {**record, "browser_result": browser_result},
                        browser_result.get("error", "Browser automation failed"),
                        "browser",
                    )
            return self._schedule_retry(
                record,
                direct_result.get("message", "Direct publish failed"),
                direct_result.get("provider", platform),
            )

        if platform == "youtube" and self.config.youtube_api_key:
            record["status"] = "prepared"
        elif platform == "meta" and self.config.meta_access_token:
            record["status"] = "prepared"
        elif platform == "x" and self.config.x_bearer_token:
            record["status"] = "prepared"
        elif platform == "tiktok" and self.config.tiktok_access_token:
            record["status"] = "prepared"
        else:
            record["status"] = "queued"
        return self._persist_final(record)

    def format_caption(self, title: str, script: str, hashtags: list[str]) -> str:
        items = [title.strip(), script.strip(), "", " ".join(hashtags).strip()]
        return "\n".join([item for item in items if item])

    def optimize_hashtags(self, topic: str, extra: list[str] | None = None) -> list[str]:
        base = [topic.replace(" ", ""), "fyp", "viral", "shorts", "ai"]
        extra = extra or []
        tags = []
        seen: set[str] = set()
        for tag in base + extra:
            normalized = tag.replace("#", "").strip()
            lowered = normalized.lower()
            if normalized and lowered not in seen:
                seen.add(lowered)
                tags.append(f"#{normalized}")
        return tags[:10]

    def queue_multi_account(
        self,
        title: str,
        caption: str,
        media_path: str,
        hashtags: list[str],
        platforms: list[str],
    ) -> list[dict[str, Any]]:
        self.retry_due_posts()
        jobs = self.workflow.build_jobs(
            title=title,
            caption=caption,
            media_path=media_path,
            hashtags=hashtags,
            platforms=platforms,
        )
        return self.workflow.execute(jobs)
