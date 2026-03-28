from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from utils.media_host import resolve_public_media_base_url


@dataclass
class AdapterResult:
    status: str
    platform: str
    provider: str
    message: str
    remote_id: str = ""
    url: str = ""
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "status": self.status,
            "platform": self.platform,
            "provider": self.provider,
            "message": self.message,
            "remote_id": self.remote_id,
            "url": self.url,
        }
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


class BasePostingAdapter:
    platform = "generic"

    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger

    def can_publish(self) -> bool:
        return False

    def publish(self, record: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def _fail(self, message: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return AdapterResult(
            status="unavailable",
            platform=self.platform,
            provider=self.platform,
            message=message,
            metadata=metadata,
        ).to_dict()

    def _success(self, message: str, remote_id: str = "", url: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return AdapterResult(
            status="published",
            platform=self.platform,
            provider=self.platform,
            message=message,
            remote_id=remote_id,
            url=url,
            metadata=metadata,
        ).to_dict()


class YouTubeAdapter(BasePostingAdapter):
    platform = "youtube"

    def _access_token(self) -> str:
        token = self.config.youtube_access_token
        if token:
            return token
        refresh = self.config.youtube_refresh_token
        if not (refresh and self.config.youtube_client_id and self.config.youtube_client_secret):
            return ""
        payload = {
            "client_id": self.config.youtube_client_id,
            "client_secret": self.config.youtube_client_secret,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        }
        response = requests.post("https://oauth2.googleapis.com/token", data=payload, timeout=45)
        response.raise_for_status()
        data = response.json()
        return data.get("access_token", "")

    def can_publish(self) -> bool:
        try:
            return bool(self._access_token())
        except Exception as exc:
            if self.logger:
                self.logger.warning("YouTube readiness check failed: %s", exc)
            return False

    def publish(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            token = self._access_token()
            if not token:
                return self._fail("Missing YouTube OAuth access token or refresh credentials.")

            media_path = Path(record["media_path"])
            if not media_path.exists():
                return self._fail(f"Media file not found: {media_path}")

            title = (record.get("title") or "ViralForge Short")[:100]
            caption = record.get("caption") or ""
            tags = [tag.lstrip("#") for tag in record.get("hashtags", [])[:10] if tag]
            privacy_status = (getattr(self.config, "youtube_privacy_status", "unlisted") or "unlisted").strip().lower()
            video_body = {
                "snippet": {
                    "title": title,
                    "description": caption,
                    "tags": tags,
                    "categoryId": "22",
                },
                "status": {
                    "privacyStatus": privacy_status,
                    "selfDeclaredMadeForKids": False,
                },
            }

            size = media_path.stat().st_size
            init_headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(size),
            }
            init_url = "https://www.googleapis.com/upload/youtube/v3/videos?part=snippet,status&uploadType=resumable"
            init_response = requests.post(init_url, headers=init_headers, json=video_body, timeout=90)
            init_response.raise_for_status()
            upload_url = init_response.headers.get("Location")
            if not upload_url:
                return self._fail("YouTube resumable upload did not return an upload URL.")

            with media_path.open("rb") as handle:
                upload_response = requests.put(
                    upload_url,
                    data=handle,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "video/mp4",
                        "Content-Length": str(size),
                    },
                    timeout=900,
                )
            upload_response.raise_for_status()
            result: dict[str, Any] = {}
            if upload_response.content:
                try:
                    result = upload_response.json()
                except Exception:
                    result = {}

            remote_id = str(result.get("id", ""))
            url = f"https://www.youtube.com/watch?v={remote_id}" if remote_id else ""
            return self._success("Uploaded to YouTube", remote_id=remote_id, url=url, metadata=result or None)
        except Exception as exc:
            return self._fail(f"YouTube upload failed: {exc}")


class XAdapter(BasePostingAdapter):
    platform = "x"

    def _auth(self):
        try:
            from requests_oauthlib import OAuth1
        except Exception as exc:
            if self.logger:
                self.logger.warning("requests-oauthlib unavailable: %s", exc)
            return None
        if not all([self.config.x_api_key, self.config.x_api_secret, self.config.x_access_token, self.config.x_access_token_secret]):
            return None
        return OAuth1(
            self.config.x_api_key,
            self.config.x_api_secret,
            self.config.x_access_token,
            self.config.x_access_token_secret,
        )

    def can_publish(self) -> bool:
        return self._auth() is not None

    def _upload_media(self, media_path: Path) -> str:
        auth = self._auth()
        if auth is None:
            raise RuntimeError("Missing X user-context OAuth credentials.")

        total_bytes = media_path.stat().st_size
        media_type = "video/mp4"
        init_response = requests.post(
            "https://upload.twitter.com/1.1/media/upload.json",
            auth=auth,
            data={
                "command": "INIT",
                "media_type": media_type,
                "total_bytes": total_bytes,
                "media_category": "tweet_video",
            },
            timeout=90,
        )
        init_response.raise_for_status()
        media_id = init_response.json().get("media_id_string") or init_response.json().get("media_id")
        if not media_id:
            raise RuntimeError("X media upload did not return a media_id.")

        chunk_size = 4 * 1024 * 1024
        with media_path.open("rb") as handle:
            segment_index = 0
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                append_response = requests.post(
                    "https://upload.twitter.com/1.1/media/upload.json",
                    auth=auth,
                    files={"media": ("chunk", chunk, "application/octet-stream")},
                    data={
                        "command": "APPEND",
                        "media_id": media_id,
                        "segment_index": segment_index,
                    },
                    timeout=180,
                )
                append_response.raise_for_status()
                segment_index += 1

        finalize_response = requests.post(
            "https://upload.twitter.com/1.1/media/upload.json",
            auth=auth,
            data={
                "command": "FINALIZE",
                "media_id": media_id,
            },
            timeout=120,
        )
        finalize_response.raise_for_status()
        finalize_data = finalize_response.json()
        processing_info = finalize_data.get("processing_info", {})
        while processing_info and processing_info.get("state") in {"pending", "in_progress"}:
            wait_seconds = int(processing_info.get("check_after_secs", 5))
            time.sleep(max(1, wait_seconds))
            status_response = requests.get(
                "https://upload.twitter.com/1.1/media/upload.json",
                auth=auth,
                params={"command": "STATUS", "media_id": media_id},
                timeout=120,
            )
            status_response.raise_for_status()
            status_data = status_response.json()
            processing_info = status_data.get("processing_info", {})
            if processing_info.get("state") == "failed":
                raise RuntimeError(f"X media processing failed: {processing_info.get('error', {})}")
        return str(media_id)

    def publish(self, record: dict[str, Any]) -> dict[str, Any]:
        media_path = Path(record["media_path"])
        if not media_path.exists():
            return self._fail(f"Media file not found: {media_path}")
        try:
            media_id = self._upload_media(media_path)
            auth = self._auth()
            assert auth is not None
            caption = record.get("caption") or record.get("title") or ""
            tweet_text = caption[:280]
            create_response = requests.post(
                "https://api.x.com/2/tweets",
                auth=auth,
                json={
                    "text": tweet_text,
                    "media": {"media_ids": [media_id]},
                },
                timeout=90,
            )
            create_response.raise_for_status()
            data = create_response.json()
            tweet_id = data.get("data", {}).get("id", "")
            url = f"https://x.com/i/web/status/{tweet_id}" if tweet_id else ""
            return self._success("Posted to X", remote_id=tweet_id, url=url, metadata=data)
        except Exception as exc:
            return self._fail(f"X posting failed: {exc}")


class MetaAdapter(BasePostingAdapter):
    platform = "meta"

    def _page_access_token(self) -> str:
        return self.config.meta_access_token

    def can_publish(self) -> bool:
        return bool(self._page_access_token() and self.config.meta_page_id)

    def publish(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            token = self._page_access_token()
            if not token or not self.config.meta_page_id:
                return self._fail("Missing Meta page token or page id.")

            media_path = Path(record["media_path"])
            if not media_path.exists():
                return self._fail(f"Media file not found: {media_path}")

            endpoint = f"https://graph-video.facebook.com/{self.config.meta_graph_version}/{self.config.meta_page_id}/videos"
            caption = record.get("caption") or ""
            with media_path.open("rb") as handle:
                response = requests.post(
                    endpoint,
                    data={
                        "access_token": token,
                        "title": record.get("title") or "ViralForge Short",
                        "description": caption,
                        "published": "true",
                    },
                    files={"source": handle},
                    timeout=900,
                )
            response.raise_for_status()
            data = response.json()
            remote_id = str(data.get("id", ""))
            url = f"https://www.facebook.com/{self.config.meta_page_id}/videos/{remote_id}" if remote_id else ""
            return self._success("Posted to Meta", remote_id=remote_id, url=url, metadata=data)
        except Exception as exc:
            return self._fail(f"Meta posting failed: {exc}")


class InstagramAdapter(BasePostingAdapter):
    platform = "instagram"

    def can_publish(self) -> bool:
        return bool(self.config.meta_access_token and self.config.meta_instagram_account_id)

    def _media_url(self, record: dict[str, Any]) -> str:
        metadata = record.get("metadata") or {}
        base_url = resolve_public_media_base_url(self.config)
        candidates = [
            record.get("media_url", ""),
            metadata.get("media_url", ""),
            metadata.get("instagram_media_url", ""),
            f"{base_url}/{Path(record['media_path']).name}" if base_url else "",
        ]
        for candidate in candidates:
            if candidate:
                return candidate
        return ""

    def publish(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            token = self.config.meta_access_token
            ig_user_id = self.config.meta_instagram_account_id
            if not token or not ig_user_id:
                return self._fail("Missing Meta access token or Instagram account id.")

            media_url = self._media_url(record)
            if not media_url:
                return self._fail("Instagram publishing requires a public media URL. Set instagram_media_url_base or pass media_url in metadata.")

            caption = record.get("caption") or ""
            is_video = str(record.get("metadata", {}).get("media_type", "video")).lower() != "image"
            version = self.config.meta_graph_version
            create_payload: dict[str, Any] = {
                "access_token": token,
                "caption": caption,
                "share_to_feed": True,
            }
            create_payload["media_type"] = "REELS" if is_video else "IMAGE"
            create_payload["video_url" if is_video else "image_url"] = media_url

            create_response = requests.post(
                f"https://graph.facebook.com/{version}/{ig_user_id}/media",
                data=create_payload,
                timeout=120,
            )
            create_response.raise_for_status()
            create_data = create_response.json()
            creation_id = create_data.get("id", "")
            if not creation_id:
                return self._fail("Instagram media container creation did not return an id.", metadata=create_data)

            publish_response = requests.post(
                f"https://graph.facebook.com/{version}/{ig_user_id}/media_publish",
                data={"access_token": token, "creation_id": creation_id},
                timeout=120,
            )
            publish_response.raise_for_status()
            publish_data = publish_response.json()
            remote_id = str(publish_data.get("id", creation_id))
            return self._success("Posted to Instagram", remote_id=remote_id, metadata={"container": create_data, "publish": publish_data})
        except Exception as exc:
            return self._fail(f"Instagram posting failed: {exc}")


class TikTokAdapter(BasePostingAdapter):
    platform = "tiktok"

    def can_publish(self) -> bool:
        return bool(self.config.tiktok_access_token)

    def _init_upload(self, media_path: Path, post_mode: str) -> dict[str, Any]:
        endpoint = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
        total_size = media_path.stat().st_size
        payload = {
            "post_info": {
                "title": (media_path.stem.replace("_", " ")[:150]),
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": total_size,
                "chunk_size": 10 * 1024 * 1024,
                "total_chunk_count": max(1, (total_size + (10 * 1024 * 1024) - 1) // (10 * 1024 * 1024)),
            },
        }
        headers = {
            "Authorization": f"Bearer {self.config.tiktok_access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }
        if post_mode:
            payload["post_info"]["privacy_level"] = post_mode
        response = requests.post(endpoint, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        return response.json()

    def publish(self, record: dict[str, Any]) -> dict[str, Any]:
        token = self.config.tiktok_access_token
        if not token:
            return self._fail("Missing TikTok access token.")

        media_path = Path(record["media_path"])
        if not media_path.exists():
            return self._fail(f"Media file not found: {media_path}")

        try:
            init_data = self._init_upload(media_path, post_mode="PUBLIC_TO_SELF")
            upload_url = init_data.get("data", {}).get("upload_url")
            publish_id = init_data.get("data", {}).get("publish_id", "")
            if not upload_url:
                return self._fail("TikTok init response did not return an upload URL.", metadata=init_data)

            chunk_size = 10 * 1024 * 1024
            with media_path.open("rb") as handle:
                index = 0
                while True:
                    chunk = handle.read(chunk_size)
                    if not chunk:
                        break
                    put_response = requests.put(
                        upload_url,
                        data=chunk,
                        headers={
                            "Content-Type": "video/mp4",
                            "Content-Length": str(len(chunk)),
                        },
                        timeout=300,
                    )
                    put_response.raise_for_status()
                    index += 1

            status_endpoint = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
            status_response = requests.post(
                status_endpoint,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                json={"publish_id": publish_id},
                timeout=90,
            )
            status_response.raise_for_status()
            status_data = status_response.json()
            return self._success("Uploaded to TikTok", remote_id=publish_id, metadata=status_data)
        except Exception as exc:
            return self._fail(f"TikTok upload failed: {exc}")


class PostingAdapterRouter:
    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger
        self.adapters: dict[str, BasePostingAdapter] = {
            "youtube": YouTubeAdapter(config, logger=logger),
            "x": XAdapter(config, logger=logger),
            "meta": MetaAdapter(config, logger=logger),
            "instagram": InstagramAdapter(config, logger=logger),
            "tiktok": TikTokAdapter(config, logger=logger),
        }

    def get(self, platform: str) -> BasePostingAdapter | None:
        return self.adapters.get(platform)

    def can_publish(self, platform: str) -> bool:
        adapter = self.get(platform)
        if adapter is None:
            return False
        try:
            return bool(adapter.can_publish())
        except Exception as exc:
            if self.logger:
                self.logger.warning("Adapter readiness failed for %s: %s", platform, exc)
            return False

    def publish(self, record: dict[str, Any]) -> dict[str, Any] | None:
        adapter = self.get(record.get("platform", ""))
        if adapter is None:
            return None
        try:
            if not adapter.can_publish():
                return None
            return adapter.publish(record)
        except Exception as exc:
            if self.logger:
                self.logger.exception("Adapter publish crashed for %s", record.get("platform", "unknown"))
            return {
                "status": "unavailable",
                "platform": record.get("platform", "unknown"),
                "provider": record.get("platform", "unknown"),
                "message": f"Adapter crashed: {exc}",
            }
