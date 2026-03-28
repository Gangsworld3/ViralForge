from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from utils.json_io import append_unique_jsonl


class JsonIOTests(unittest.TestCase):
    def test_append_unique_jsonl_deduplicates_by_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queue.jsonl"
            append_unique_jsonl(path, {"id": "abc", "value": 1})
            append_unique_jsonl(path, {"id": "abc", "value": 2})
            append_unique_jsonl(path, {"id": "def", "value": 3})
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
