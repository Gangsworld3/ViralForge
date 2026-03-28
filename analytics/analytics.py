from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from utils.json_io import load_json
from utils.sqlite_db import ensure_state_db, open_db


@dataclass
class MetricRecord:
    content_id: str
    platform: str
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    watch_time_seconds: float = 0.0
    revenue: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class AnalyticsEngine:
    MAX_ANALYTICS_RECORDS = 5000

    def __init__(self, config, memory, logger=None):
        self.config = config
        self.memory = memory
        self.logger = logger
        self.legacy_path = config.data_dir / "analytics.json"
        ensure_state_db(config.state_db_path)
        self._migrate_legacy_records()

    def _connection(self):
        return open_db(self.config.state_db_path)

    def _migrate_legacy_records(self) -> None:
        raw = load_json(self.legacy_path, default=[])
        if not isinstance(raw, list) or not raw:
            return
        with self._connection() as conn:
            existing = conn.execute("SELECT COUNT(*) FROM analytics_records").fetchone()[0]
            if existing:
                return
            for item in raw[-self.MAX_ANALYTICS_RECORDS :]:
                if not isinstance(item, dict):
                    continue
                conn.execute(
                    """
                    INSERT INTO analytics_records (
                        content_id, platform, views, likes, comments, shares, watch_time_seconds, revenue, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(item.get("content_id", "")),
                        str(item.get("platform", "")),
                        int(item.get("views", 0) or 0),
                        int(item.get("likes", 0) or 0),
                        int(item.get("comments", 0) or 0),
                        int(item.get("shares", 0) or 0),
                        float(item.get("watch_time_seconds", 0.0) or 0.0),
                        float(item.get("revenue", 0.0) or 0.0),
                        json.dumps(item.get("metadata", {}), ensure_ascii=False, sort_keys=True),
                    ),
                )

    def _trim_records(self, conn) -> None:
        conn.execute(
            """
            DELETE FROM analytics_records
            WHERE id NOT IN (
                SELECT id FROM analytics_records
                ORDER BY id DESC
                LIMIT ?
            )
            """,
            (self.MAX_ANALYTICS_RECORDS,),
        )

    def _fetch_all(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT content_id, platform, views, likes, comments, shares, watch_time_seconds, revenue, metadata_json
                FROM analytics_records
                ORDER BY id ASC
                """
            ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except Exception:
                metadata = {}
            records.append(
                {
                    "content_id": row["content_id"],
                    "platform": row["platform"],
                    "views": row["views"],
                    "likes": row["likes"],
                    "comments": row["comments"],
                    "shares": row["shares"],
                    "watch_time_seconds": row["watch_time_seconds"],
                    "revenue": row["revenue"],
                    "metadata": metadata,
                }
            )
        return records

    def ingest(self, record: MetricRecord) -> dict[str, Any]:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO analytics_records (
                    content_id, platform, views, likes, comments, shares, watch_time_seconds, revenue, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.content_id,
                    record.platform,
                    int(record.views),
                    int(record.likes),
                    int(record.comments),
                    int(record.shares),
                    float(record.watch_time_seconds),
                    float(record.revenue),
                    json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
            self._trim_records(conn)
        score = self.engagement_score(record.views, record.likes, record.comments, record.shares)
        summary = {
            "content_id": record.content_id,
            "platform": record.platform,
            "engagement_score": round(score, 2),
            "views": record.views,
            "revenue": record.revenue,
        }
        self.memory.update_learning({"kind": "analytics", **summary})
        return summary

    @staticmethod
    def engagement_score(views: int, likes: int, comments: int, shares: int) -> float:
        if views <= 0:
            return 0.0
        return ((likes * 1.0) + (comments * 2.0) + (shares * 3.0)) / max(1.0, views) * 100.0

    def summarize(self) -> dict[str, Any]:
        data = self._fetch_all()
        if not data:
            return {"message": "No analytics yet"}
        total_views = sum(item.get("views", 0) for item in data)
        total_revenue = sum(item.get("revenue", 0.0) for item in data)
        avg_engagement = sum(
            self.engagement_score(
                item.get("views", 0),
                item.get("likes", 0),
                item.get("comments", 0),
                item.get("shares", 0),
            )
            for item in data
        ) / len(data)
        return {
            "entries": len(data),
            "total_views": total_views,
            "total_revenue": round(total_revenue, 2),
            "avg_engagement": round(avg_engagement, 2),
        }

    def winning_patterns(self) -> list[str]:
        data = self._fetch_all()
        if not data:
            return []
        ranked = sorted(
            data,
            key=lambda item: self.engagement_score(
                item.get("views", 0), item.get("likes", 0), item.get("comments", 0), item.get("shares", 0)
            ),
            reverse=True,
        )
        winners: list[str] = []
        seen: set[str] = set()
        for item in ranked:
            content_id = str(item.get("content_id", "")).strip()
            if not content_id or content_id in seen:
                continue
            seen.add(content_id)
            winners.append(content_id)
            if len(winners) >= 5:
                break
        return winners
