from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from analytics.analytics import AnalyticsEngine, MetricRecord
from posting.accounts import AccountManager
from posting.models import PostDraft
from posting.poster import PostingEngine
from utils.state_db import StateDbManager


class _MemoryStub:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict]] = []

    def save_memory(self, kind, content, metadata):
        self.records.append((kind, content, metadata))

    def update_learning(self, record):
        self.records.append(("learning", str(record), record))


def _build_config(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        data_dir=root / "data",
        output_dir=root / "output",
        memory_dir=root / "memory",
        log_dir=root / "logs",
        state_db_path=root / "data" / "state.db",
        posting_default_platforms=["youtube", "x"],
        posting_auto_publish=False,
        posting_dry_run=True,
        posting_self_mode="api",
        enable_browser_automation=False,
        youtube_api_key="",
        youtube_access_token="",
        youtube_refresh_token="",
        youtube_client_id="",
        youtube_client_secret="",
        youtube_privacy_status="unlisted",
        meta_access_token="",
        meta_page_id="",
        meta_graph_version="v20.0",
        meta_app_id="",
        meta_app_secret="",
        meta_instagram_account_id="",
        instagram_media_url_base="",
        media_host_base_url="",
        media_host_host="127.0.0.1",
        media_host_port=8088,
        x_bearer_token="",
        x_api_key="",
        x_api_secret="",
        x_access_token="",
        x_access_token_secret="",
        tiktok_access_token="",
        tiktok_open_id="",
    )


class SQLiteStateTests(unittest.TestCase):
    def test_account_manager_persists_usage_in_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _build_config(Path(tmp))
            manager = AccountManager(config)
            accounts = manager.list_active("youtube")
            self.assertEqual(len(accounts), 1)
            self.assertEqual(accounts[0].account_id, "youtube-primary")
            manager.mark_used("youtube-primary")

            refreshed = AccountManager(config)
            accounts = refreshed.list_active("youtube")
            self.assertEqual(accounts[0].usage_count, 1)

    def test_analytics_engine_persists_and_summarizes_from_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _build_config(Path(tmp))
            memory = _MemoryStub()
            engine = AnalyticsEngine(config, memory)
            engine.ingest(MetricRecord(content_id="abc", platform="youtube", views=100, likes=10, comments=5, shares=2))
            summary = engine.summarize()
            self.assertEqual(summary["entries"], 1)
            self.assertEqual(summary["total_views"], 100)
            self.assertEqual(engine.winning_patterns(), ["abc"])

    def test_posting_engine_writes_outbox_to_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _build_config(root)
            memory = _MemoryStub()
            media_path = root / "output" / "clip.mp4"
            media_path.parent.mkdir(parents=True, exist_ok=True)
            media_path.write_bytes(b"video")
            engine = PostingEngine(config, memory)
            result = engine.queue_post(
                PostDraft(
                    platform="youtube",
                    title="Test",
                    caption="Caption",
                    media_path=str(media_path),
                    hashtags=["#a"],
                )
            )
            self.assertEqual(result["status"], "queued")
            outbox = engine.list_outbox(limit=10)
            self.assertEqual(len(outbox), 1)
            self.assertEqual(outbox[0]["title"], "Test")

    def test_state_db_export_and_restore_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _build_config(root)
            memory = _MemoryStub()
            AnalyticsEngine(config, memory).ingest(
                MetricRecord(content_id="abc", platform="youtube", views=10, likes=2, comments=1, shares=1)
            )
            manager = StateDbManager(config.state_db_path)
            export_path = manager.export_json(root / "export.json")
            self.assertTrue(export_path.exists())

            restored_db = root / "data" / "restored.db"
            restored = StateDbManager(restored_db)
            counts = restored.restore_json(export_path)
            self.assertEqual(counts["analytics_records"], 1)
            summary = restored.summary()
            self.assertEqual(summary["tables"]["analytics_records"], 1)


if __name__ == "__main__":
    unittest.main()
