from __future__ import annotations

from pathlib import Path
from typing import Iterable


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_project_dirs(config) -> None:
    for path in [config.data_dir, config.output_dir, config.memory_dir, config.log_dir, config.chroma_path]:
        ensure_dir(path)
    for sub in ["outbox", "cache", "assets", "reports", "media"]:
        ensure_dir(config.data_dir / sub)


def list_files(root: Path, suffixes: Iterable[str] | None = None) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and (suffixes is None or path.suffix.lower() in suffixes):
            files.append(path)
    return files
