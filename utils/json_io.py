from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

_JSONL_ID_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent), encoding="utf-8") as handle:
        handle.write(payload)
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_unique_jsonl(path: Path, record: dict[str, Any], key: str = "id") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record_id = str(record.get(key, "")).strip()
    if not record_id:
        append_jsonl(path, record)
        return
    cache_key = (str(path.resolve()), key)
    stat = path.stat() if path.exists() else None
    cache = _JSONL_ID_CACHE.get(cache_key)
    if (
        cache
        and stat is not None
        and cache.get("mtime_ns") == stat.st_mtime_ns
        and cache.get("size") == stat.st_size
    ):
        existing_ids = cache["ids"]
    else:
        existing_ids: set[str] = set()
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except Exception:
                        continue
                    payload_id = str(payload.get(key, "")).strip()
                    if payload_id:
                        existing_ids.add(payload_id)
            stat = path.stat()
        _JSONL_ID_CACHE[cache_key] = {
            "ids": existing_ids,
            "mtime_ns": stat.st_mtime_ns if stat else None,
            "size": stat.st_size if stat else 0,
        }
    if record_id in existing_ids:
        return
    append_jsonl(path, record)
    stat = path.stat()
    existing_ids.add(record_id)
    _JSONL_ID_CACHE[cache_key] = {
        "ids": existing_ids,
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }
