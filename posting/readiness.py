from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests

from utils.media_host import resolve_public_media_base_url


@dataclass
class PlatformReadiness:
    platform: str
    ready: bool
    missing: list[str] = field(default_factory=list)
    expected_scopes: list[str] = field(default_factory=list)
    granted_scopes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "ready": self.ready,
            "missing": self.missing,
            "expected_scopes": self.expected_scopes,
            "granted_scopes": self.granted_scopes,
            "notes": self.notes,
        }


class PostingReadinessChecker:
    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger

    def _debug(self, message: str, *args: Any) -> None:
        if self.logger and hasattr(self.logger, "debug"):
            self.logger.debug(message, *args)

    def _google_token_scopes(self, access_token: str) -> list[str]:
        if not access_token:
            return []
        try:
            response = requests.get(
                "https://oauth2.googleapis.com/tokeninfo",
                params={"access_token": access_token},
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
            scope_text = data.get("scope", "")
            return [scope for scope in scope_text.split(" ") if scope]
        except Exception as exc:
            self._debug("Google tokeninfo lookup failed: %s", exc)
            return []

    def _meta_token_scopes(self, access_token: str) -> list[str]:
        if not access_token or not (self.config.meta_app_id and self.config.meta_app_secret):
            return []
        try:
            app_token = f"{self.config.meta_app_id}|{self.config.meta_app_secret}"
            response = requests.get(
                "https://graph.facebook.com/debug_token",
                params={"input_token": access_token, "access_token": app_token},
                timeout=20,
            )
            response.raise_for_status()
            data = response.json().get("data", {})
            scopes = data.get("scopes") or []
            granular = data.get("granular_scopes") or []
            for item in granular:
                if isinstance(item, dict):
                    scopes.extend(item.get("scope", []) if isinstance(item.get("scope"), list) else [item.get("scope", "")])
            return [scope for scope in scopes if scope]
        except Exception as exc:
            self._debug("Meta debug_token lookup failed: %s", exc)
            return []

    def youtube(self) -> PlatformReadiness:
        expected = ["https://www.googleapis.com/auth/youtube.upload"]
        access_token = self.config.youtube_access_token
        refresh_ready = bool(self.config.youtube_refresh_token and self.config.youtube_client_id and self.config.youtube_client_secret)
        granted = self._google_token_scopes(access_token)
        missing: list[str] = []
        if not access_token and not refresh_ready:
            missing.extend(["youtube_access_token or refresh token client bundle"])
        if access_token and expected[0] not in granted:
            missing.append("youtube.upload scope")
        notes = []
        if refresh_ready and not access_token:
            notes.append("Refresh token path is configured; access token can be refreshed on demand.")
        if access_token and not granted:
            notes.append("Access token scope introspection unavailable or failed.")
        return PlatformReadiness(
            platform="youtube",
            ready=not missing,
            missing=missing,
            expected_scopes=expected,
            granted_scopes=granted,
            notes=notes,
        )

    def x(self) -> PlatformReadiness:
        expected = ["tweet.write", "users.read", "offline.access"]
        missing = []
        required_fields = {
            "x_api_key": self.config.x_api_key,
            "x_api_secret": self.config.x_api_secret,
            "x_access_token": self.config.x_access_token,
            "x_access_token_secret": self.config.x_access_token_secret,
        }
        for name, value in required_fields.items():
            if not value:
                missing.append(name)
        notes = []
        if self.config.x_bearer_token and not any(required_fields.values()):
            notes.append("Bearer token alone is not enough to publish posts; user-context OAuth credentials are required.")
        return PlatformReadiness(
            platform="x",
            ready=not missing,
            missing=missing,
            expected_scopes=expected,
            notes=notes,
        )

    def meta_page(self) -> PlatformReadiness:
        expected = ["pages_show_list", "pages_read_engagement", "pages_manage_posts"]
        missing = []
        if not self.config.meta_access_token:
            missing.append("meta_access_token")
        if not self.config.meta_page_id:
            missing.append("meta_page_id")
        granted = self._meta_token_scopes(self.config.meta_access_token)
        if self.config.meta_access_token and granted and not all(scope in granted for scope in expected):
            missing.append("page publishing scopes")
        notes = []
        if not (self.config.meta_app_id and self.config.meta_app_secret):
            notes.append("Meta scope introspection is unavailable without app id and app secret.")
        return PlatformReadiness(
            platform="meta",
            ready=not missing,
            missing=missing,
            expected_scopes=expected,
            granted_scopes=granted,
            notes=notes,
        )

    def instagram(self) -> PlatformReadiness:
        expected = ["instagram_basic", "instagram_content_publish", "pages_show_list", "pages_read_engagement"]
        missing = []
        if not self.config.meta_access_token:
            missing.append("meta_access_token")
        if not self.config.meta_instagram_account_id:
            missing.append("meta_instagram_account_id")
        granted = self._meta_token_scopes(self.config.meta_access_token)
        if self.config.meta_access_token and granted and not all(scope in granted for scope in expected):
            missing.append("instagram publishing scopes")
        notes = []
        if not resolve_public_media_base_url(self.config):
            missing.append("public_media_url")
            notes.append("Instagram publishing requires a public media URL; use MEDIA_HOST_BASE_URL or INSTAGRAM_MEDIA_URL_BASE.")
        if not (self.config.meta_app_id and self.config.meta_app_secret):
            notes.append("Meta scope introspection is unavailable without app id and app secret.")
        return PlatformReadiness(
            platform="instagram",
            ready=not missing,
            missing=missing,
            expected_scopes=expected,
            granted_scopes=granted,
            notes=notes,
        )

    def tiktok(self) -> PlatformReadiness:
        expected = ["video.publish"]
        missing = []
        if not self.config.tiktok_access_token:
            missing.append("tiktok_access_token")
        if not self.config.tiktok_open_id:
            missing.append("tiktok_open_id")
        notes = []
        if self.config.tiktok_access_token and not self.config.tiktok_open_id:
            notes.append("TikTok publish tokens typically also need the authorizing user's open_id.")
        return PlatformReadiness(
            platform="tiktok",
            ready=not missing,
            missing=missing,
            expected_scopes=expected,
            notes=notes,
        )

    def report(self) -> dict[str, Any]:
        platforms = [self.youtube(), self.x(), self.meta_page(), self.instagram(), self.tiktok()]
        ready = [item.platform for item in platforms if item.ready]
        blocked = [item.platform for item in platforms if not item.ready]
        return {
            "ready": not blocked,
            "ready_platforms": ready,
            "blocked_platforms": blocked,
            "platforms": [item.to_dict() for item in platforms],
        }
