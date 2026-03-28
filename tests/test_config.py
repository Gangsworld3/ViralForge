from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from config import load_config


class ConfigTests(unittest.TestCase):
    def test_load_config_does_not_mutate_process_environment(self) -> None:
        sentinel_key = "VIRALFORGE_CONFIG_SENTINEL"
        original = os.environ.get(sentinel_key)
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text('{"gemini_api_key": "test-key"}', encoding="utf-8")
            os.environ.pop("GEMINI_API_KEY", None)
            load_config(str(config_path))
            self.assertNotIn("GEMINI_API_KEY", os.environ)
        if original is not None:
            os.environ[sentinel_key] = original
        else:
            os.environ.pop(sentinel_key, None)

    def test_environment_overrides_dotenv_values(self) -> None:
        original = os.environ.get("GEMINI_MODEL")
        os.environ["GEMINI_MODEL"] = "override-model"
        try:
            config = load_config()
            self.assertEqual(config.gemini_model, "override-model")
        finally:
            if original is None:
                os.environ.pop("GEMINI_MODEL", None)
            else:
                os.environ["GEMINI_MODEL"] = original


if __name__ == "__main__":
    unittest.main()
