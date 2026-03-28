from __future__ import annotations

import json
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any

from utils.json_io import load_json
from utils.sqlite_db import ensure_state_db, open_db


@dataclass
class AccountProfile:
    platform: str
    account_id: str
    display_name: str
    active: bool = True
    api_mode: str = "dry_run"
    last_used: str | None = None
    usage_count: int = 0
    priority: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class AccountManager:
    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger
        self.legacy_path = config.data_dir / "accounts.json"
        ensure_state_db(config.state_db_path)
        self._migrate_legacy_accounts()
        self._ensure_default_accounts()

    def _connection(self):
        return open_db(self.config.state_db_path)

    def _profile_from_row(self, row) -> AccountProfile:
        metadata = {}
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except Exception:
            metadata = {}
        return AccountProfile(
            platform=row["platform"],
            account_id=row["account_id"],
            display_name=row["display_name"],
            active=bool(row["active"]),
            api_mode=row["api_mode"],
            last_used=row["last_used"],
            usage_count=int(row["usage_count"] or 0),
            priority=int(row["priority"] or 0),
            metadata=metadata,
        )

    def _migrate_legacy_accounts(self) -> None:
        raw = load_json(self.legacy_path, default=[])
        if not isinstance(raw, list) or not raw:
            return
        with self._connection() as conn:
            existing = conn.execute("SELECT COUNT(*) FROM account_profiles").fetchone()[0]
            if existing:
                return
            seen_ids: set[str] = set()
            for item in raw:
                if not isinstance(item, dict):
                    continue
                try:
                    profile = AccountProfile(**item)
                except Exception:
                    continue
                if not profile.account_id or profile.account_id in seen_ids:
                    continue
                seen_ids.add(profile.account_id)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO account_profiles (
                        account_id, platform, display_name, active, api_mode, last_used, usage_count, priority, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile.account_id,
                        profile.platform,
                        profile.display_name,
                        1 if profile.active else 0,
                        profile.api_mode,
                        profile.last_used,
                        profile.usage_count,
                        profile.priority,
                        json.dumps(profile.metadata, ensure_ascii=False, sort_keys=True),
                    ),
                )

    def _ensure_default_accounts(self) -> None:
        with self._connection() as conn:
            existing = conn.execute("SELECT COUNT(*) FROM account_profiles").fetchone()[0]
            if existing:
                return
            for platform in self.config.posting_default_platforms:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO account_profiles (
                        account_id, platform, display_name, active, api_mode, usage_count, priority, metadata_json
                    ) VALUES (?, ?, ?, 1, 'dry_run', 0, 0, '{}')
                    """,
                    (f"{platform}-primary", platform, f"{platform.title()} Primary"),
                )

    def list_active(self, platform: str | None = None) -> list[AccountProfile]:
        sql = """
            SELECT account_id, platform, display_name, active, api_mode, last_used, usage_count, priority, metadata_json
            FROM account_profiles
            WHERE active = 1
        """
        params: list[Any] = []
        if platform:
            sql += " AND platform = ?"
            params.append(platform)
        sql += " ORDER BY usage_count ASC, COALESCE(last_used, '') ASC, account_id ASC"
        with self._connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._profile_from_row(row) for row in rows]

    def _rotation_key(self, account: AccountProfile) -> tuple[int, int, str]:
        last_used_score = 0
        if account.last_used:
            try:
                last_used_score = int(datetime.fromisoformat(account.last_used.replace("Z", "+00:00")).timestamp())
            except Exception:
                last_used_score = 0
        return (account.usage_count, last_used_score, account.account_id)

    def select_account(self, platform: str) -> AccountProfile | None:
        candidates = self.list_active(platform)
        return candidates[0] if candidates else None

    def mark_used(self, account_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE account_profiles
                SET usage_count = usage_count + 1,
                    last_used = ?
                WHERE account_id = ?
                """,
                (datetime.now(timezone.utc).isoformat(), account_id),
            )

    def plan_distribution(self, platform: str, posts: int = 1) -> list[AccountProfile]:
        candidates = self.list_active(platform)
        if not candidates:
            return []
        plan: list[AccountProfile] = []
        ordered = sorted(candidates, key=self._rotation_key)
        for index in range(posts):
            plan.append(ordered[index % len(ordered)])
        return plan

    def register_account(self, profile: AccountProfile) -> None:
        if not profile.account_id:
            return
        with self._connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO account_profiles (
                    account_id, platform, display_name, active, api_mode, last_used, usage_count, priority, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.account_id,
                    profile.platform,
                    profile.display_name,
                    1 if profile.active else 0,
                    profile.api_mode,
                    profile.last_used,
                    profile.usage_count,
                    profile.priority,
                    json.dumps(profile.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
