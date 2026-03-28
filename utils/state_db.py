from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from utils.sqlite_db import ensure_state_db, open_db


class StateDbManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        ensure_state_db(db_path)
        self._tables = [
            "memory_items",
            "learning_patterns",
            "analytics_records",
            "account_profiles",
            "posting_records",
        ]

    def backup(self, destination: Path | None = None) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = destination or self.db_path.with_name(f"{self.db_path.stem}-{timestamp}.backup.sqlite3")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.db_path, destination)
        return destination

    def vacuum(self) -> None:
        with open_db(self.db_path) as conn:
            conn.execute("VACUUM")

    def integrity_check(self) -> dict[str, object]:
        with open_db(self.db_path) as conn:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
        messages = [str(row[0]) for row in rows]
        return {
            "ok": messages == ["ok"],
            "messages": messages,
        }

    def summary(self) -> dict[str, object]:
        with open_db(self.db_path) as conn:
            tables = {
                "memory_items": conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0],
                "learning_patterns": conn.execute("SELECT COUNT(*) FROM learning_patterns").fetchone()[0],
                "analytics_records": conn.execute("SELECT COUNT(*) FROM analytics_records").fetchone()[0],
                "account_profiles": conn.execute("SELECT COUNT(*) FROM account_profiles").fetchone()[0],
                "posting_records": conn.execute("SELECT COUNT(*) FROM posting_records").fetchone()[0],
            }
        return {
            "db_path": str(self.db_path),
            "exists": self.db_path.exists(),
            "size_bytes": self.db_path.stat().st_size if self.db_path.exists() else 0,
            "tables": tables,
        }

    def export_json(self, destination: Path | None = None) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = destination or self.db_path.with_name(f"{self.db_path.stem}-{timestamp}.export.json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, object] = {
            "exported_at_utc": datetime.now(timezone.utc).isoformat(),
            "db_path": str(self.db_path),
            "tables": {},
        }
        with open_db(self.db_path) as conn:
            for table in self._tables:
                rows = conn.execute(f"SELECT * FROM {table} ORDER BY 1 ASC").fetchall()
                payload["tables"][table] = [dict(row) for row in rows]
        destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return destination

    def restore_json(self, source: Path) -> dict[str, int]:
        data = json.loads(source.read_text(encoding="utf-8"))
        tables = data.get("tables", {})
        restored: dict[str, int] = {}
        with open_db(self.db_path) as conn:
            for table in self._tables:
                conn.execute(f"DELETE FROM {table}")
                rows = tables.get(table, [])
                if not isinstance(rows, list):
                    rows = []
                if not rows:
                    restored[table] = 0
                    continue
                columns = list(rows[0].keys())
                placeholders = ", ".join("?" for _ in columns)
                column_list = ", ".join(columns)
                values = [tuple(row.get(column) for column in columns) for row in rows if isinstance(row, dict)]
                if values:
                    conn.executemany(
                        f"INSERT INTO {table} ({column_list}) VALUES ({placeholders})",
                        values,
                    )
                restored[table] = len(values)
        return restored
