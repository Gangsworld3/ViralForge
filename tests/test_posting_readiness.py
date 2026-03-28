from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from posting.readiness import PostingReadinessChecker


class PostingReadinessTests(unittest.TestCase):
    def test_instagram_requires_public_media_url(self) -> None:
        config = SimpleNamespace(
            meta_access_token="token",
            meta_instagram_account_id="ig-id",
            meta_app_id="",
            meta_app_secret="",
            media_host_base_url="",
            instagram_media_url_base="",
            data_dir=Path(tempfile.gettempdir()) / "viralforge-readiness",
            youtube_access_token="",
            youtube_refresh_token="",
            youtube_client_id="",
            youtube_client_secret="",
            x_api_key="",
            x_api_secret="",
            x_access_token="",
            x_access_token_secret="",
            x_bearer_token="",
            meta_page_id="",
            tiktok_access_token="",
            tiktok_open_id="",
        )
        checker = PostingReadinessChecker(config)
        result = checker.instagram().to_dict()
        self.assertFalse(result["ready"])
        self.assertIn("public_media_url", result["missing"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
