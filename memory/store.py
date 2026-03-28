from __future__ import annotations

import json
import hashlib
import math
from dataclasses import dataclass
from typing import Any

try:
    import chromadb
except Exception:  # pragma: no cover
    chromadb = None

from utils.json_io import append_jsonl, load_json
from utils.sqlite_db import ensure_state_db, open_db
from utils.text import split_words


class HashEmbeddingFunction:
    def __call__(self, input: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in input]

    def name(self) -> str:
        return "hash-embedding"

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self.__call__(input)

    def embed_query(self, input):
        if isinstance(input, list):
            return [self._embed(text) for text in input]
        return self._embed(input)

    def _sanitize_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        sanitized: dict[str, Any] = {}
        for key, value in metadata.items():
            if isinstance(value, (str, int, float, bool)):
                sanitized[key] = value
            else:
                sanitized[key] = str(value)
        return sanitized

    def _embed(self, text: str, dim: int = 128) -> list[float]:
        vec = [0.0] * dim
        for token in split_words(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = digest[0] % dim
            weight = 1.0 + (digest[1] / 255.0)
            vec[index] += weight
        norm = math.sqrt(sum(value * value for value in vec)) or 1.0
        return [value / norm for value in vec]


@dataclass
class MemoryItem:
    kind: str
    content: str
    metadata: dict[str, Any]


class MemoryStore:
    MAX_HISTORY_ITEMS = 5000
    MAX_LEARNING_PATTERNS = 2000

    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger
        self.json_path = config.memory_dir / "long_term.json"
        self.learning_path = config.memory_dir / "learning.json"
        self.events_path = config.memory_dir / "events.jsonl"
        self.embedding_function = HashEmbeddingFunction()
        self._client = None
        self._collection = None
        ensure_state_db(config.state_db_path)
        self._migrate_legacy_memory()
        self._ensure_store()

    def _connection(self):
        return open_db(self.config.state_db_path)

    def _trim_history(self, conn) -> None:
        conn.execute(
            """
            DELETE FROM memory_items
            WHERE id NOT IN (
                SELECT id FROM memory_items
                ORDER BY id DESC
                LIMIT ?
            )
            """,
            (self.MAX_HISTORY_ITEMS,),
        )

    def _trim_learning(self, conn) -> None:
        conn.execute(
            """
            DELETE FROM learning_patterns
            WHERE id NOT IN (
                SELECT id FROM learning_patterns
                ORDER BY id DESC
                LIMIT ?
            )
            """,
            (self.MAX_LEARNING_PATTERNS,),
        )

    def _migrate_legacy_memory(self) -> None:
        history = load_json(self.json_path, default=[])
        learning = load_json(self.learning_path, default={"patterns": []})
        with self._connection() as conn:
            memory_count = conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0]
            if not memory_count and isinstance(history, list):
                for item in history[-self.MAX_HISTORY_ITEMS :]:
                    if not isinstance(item, dict):
                        continue
                    conn.execute(
                        """
                        INSERT INTO memory_items (kind, content, metadata_json)
                        VALUES (?, ?, ?)
                        """,
                        (
                            str(item.get("kind", "")),
                            str(item.get("content", "")),
                            json.dumps(item.get("metadata", {}), ensure_ascii=False, sort_keys=True),
                        ),
                    )
            learning_count = conn.execute("SELECT COUNT(*) FROM learning_patterns").fetchone()[0]
            patterns = learning.get("patterns", []) if isinstance(learning, dict) else []
            if not learning_count and isinstance(patterns, list):
                for record in patterns[-self.MAX_LEARNING_PATTERNS :]:
                    conn.execute(
                        """
                        INSERT INTO learning_patterns (record_json)
                        VALUES (?)
                        """,
                        (json.dumps(record, ensure_ascii=False, sort_keys=True),),
                    )

    def _ensure_store(self) -> None:
        self.config.memory_dir.mkdir(parents=True, exist_ok=True)
        if chromadb is None:
            return
        try:
            self._client = chromadb.PersistentClient(path=str(self.config.chroma_path))
            self._collection = self._client.get_or_create_collection(
                name="viralforge_memory",
                embedding_function=self.embedding_function,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as exc:
            if self.logger:
                self.logger.warning("Chroma init failed, falling back to SQLite only: %s", exc)
            self._client = None
            self._collection = None

    def save_memory(self, kind: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        metadata = metadata or {}
        item = {"kind": kind, "content": content, "metadata": metadata}
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO memory_items (kind, content, metadata_json)
                VALUES (?, ?, ?)
                """,
                (kind, content, json.dumps(metadata, ensure_ascii=False, sort_keys=True)),
            )
            self._trim_history(conn)
        append_jsonl(self.events_path, item)

        if self._collection is not None:
            try:
                metadata_blob = json.dumps(metadata, sort_keys=True, ensure_ascii=False)
                uid = hashlib.sha1(f"{kind}:{content}:{metadata_blob}".encode("utf-8")).hexdigest()
                payload = self.embedding_function._sanitize_metadata({"kind": kind, **metadata})
                if hasattr(self._collection, "upsert"):
                    self._collection.upsert(ids=[uid], documents=[content], metadatas=[payload])
                else:
                    self._collection.add(ids=[uid], documents=[content], metadatas=[payload])
            except Exception as exc:
                if self.logger:
                    self.logger.warning("Chroma save failed: %s", exc)

    def retrieve_relevant_context(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        results: list[dict[str, Any]] = []
        if self._collection is not None:
            try:
                query_result = self._collection.query(query_texts=[query], n_results=limit)
                docs = query_result.get("documents", [[]])[0]
                metas = query_result.get("metadatas", [[]])[0]
                for document, meta in zip(docs, metas):
                    results.append({"document": document, "metadata": meta})
                if results:
                    return results
            except Exception as exc:
                if self.logger:
                    self.logger.warning("Chroma query failed: %s", exc)

        tokens = set(split_words(query.lower()))
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT content, metadata_json
                FROM memory_items
                ORDER BY id DESC
                LIMIT 200
                """
            ).fetchall()
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            text = row["content"] or ""
            overlap = len(tokens.intersection(split_words(text.lower())))
            if not overlap:
                continue
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except Exception:
                metadata = {}
            scored.append((overlap, {"document": text, "metadata": metadata}))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def update_learning(self, record: dict[str, Any]) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO learning_patterns (record_json)
                VALUES (?)
                """,
                (json.dumps(record, ensure_ascii=False, sort_keys=True),),
            )
            self._trim_learning(conn)
        self.save_memory("learning", str(record), record)

    def snapshot(self) -> dict[str, Any]:
        with self._connection() as conn:
            memory_items = conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0]
            learning_patterns = conn.execute("SELECT COUNT(*) FROM learning_patterns").fetchone()[0]
            rows = conn.execute(
                """
                SELECT kind
                FROM memory_items
                ORDER BY id DESC
                LIMIT 5
                """
            ).fetchall()
        recent_kinds = [row["kind"] for row in reversed(rows)]
        return {
            "memory_items": memory_items,
            "learning_patterns": learning_patterns,
            "recent_kinds": recent_kinds,
        }
