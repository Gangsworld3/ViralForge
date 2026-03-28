from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


def _coerce_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass
class AppConfig:
    project_root: Path = field(default_factory=lambda: ROOT)
    data_dir: Path = field(default_factory=lambda: ROOT / "data")
    output_dir: Path = field(default_factory=lambda: ROOT / "output")
    memory_dir: Path = field(default_factory=lambda: ROOT / "memory")
    log_dir: Path = field(default_factory=lambda: ROOT / "logs")
    pexels_api_key: str = ""
    pixabay_api_key: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    openrouter_api_key: str = ""
    openrouter_api_key_2: str = ""
    openrouter_model: str = "openrouter/free"
    youtube_api_key: str = ""
    youtube_access_token: str = ""
    youtube_refresh_token: str = ""
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_privacy_status: str = "unlisted"
    meta_access_token: str = ""
    meta_page_id: str = ""
    meta_graph_version: str = "v20.0"
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_instagram_account_id: str = ""
    instagram_media_url_base: str = ""
    media_host_base_url: str = ""
    media_host_host: str = "127.0.0.1"
    media_host_port: int = 8088
    x_bearer_token: str = ""
    x_api_key: str = ""
    x_api_secret: str = ""
    x_access_token: str = ""
    x_access_token_secret: str = ""
    tiktok_access_token: str = ""
    tiktok_open_id: str = ""
    enable_browser_automation: bool = False
    posting_auto_publish: bool = False
    posting_self_mode: str = "api"
    auto_patch_errors: bool = False
    smoke_test: bool = False
    research_rss_sources: list[str] = field(default_factory=lambda: [
        "https://trends.google.com/trends/trendingsearches/daily/rss?geo=US",
        "https://www.reddit.com/r/popular/.rss",
    ])
    research_max_trends: int = 10
    video_width: int = 1080
    video_height: int = 1920
    video_fps: int = 30
    video_quality_mode: str = "hq_720p_60s"
    video_target_duration_seconds: int = 60
    video_target_width: int = 720
    video_target_height: int = 1280
    video_scene_backend: str = "free"
    video_scene_style: str = "free"
    video_scene_seed: int = 0
    video_voice: str = "en-US-AriaNeural"
    video_music_volume: float = 0.12
    video_speech_wpm: int = 165
    posting_default_platforms: list[str] = field(default_factory=lambda: ["youtube", "x", "meta", "tiktok"])
    posting_dry_run: bool = True

    @property
    def chroma_path(self) -> Path:
        return self.memory_dir / "chroma"

    @property
    def state_db_path(self) -> Path:
        return self.data_dir / "state.db"


def _flatten_config(raw: dict) -> dict[str, str]:
    flattened: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                flattened[f"{key}.{nested_key}"] = str(nested_value)
        else:
            flattened[key] = str(value)
    return flattened


def _merged_env(env_values: dict[str, str]) -> dict[str, str]:
    merged = dict(env_values)
    for key, value in os.environ.items():
        merged[key] = value
    return merged


def _pick(top_level_value: Any, merged_env: dict[str, str], env_key: str, default: Any = "") -> Any:
    if top_level_value is not None:
        return top_level_value
    return merged_env.get(env_key, default)


def _pick_bool(top_level_value: Any, merged_env: dict[str, str], env_key: str, default: bool = False) -> bool:
    if top_level_value is not None:
        return _coerce_bool(str(top_level_value), default)
    return _coerce_bool(merged_env.get(env_key), default)


def _pick_int(top_level_value: Any, merged_env: dict[str, str], env_key: str, default: int) -> int:
    value = _pick(top_level_value, merged_env, env_key, default)
    return int(value)


def _pick_str(top_level_value: Any, merged_env: dict[str, str], env_key: str, default: str = "") -> str:
    value = _pick(top_level_value, merged_env, env_key, default)
    return str(value)


def load_config(config_path: str | None = None) -> AppConfig:
    env_values: dict[str, str] = {}
    raw_config: dict = {}
    env_values.update(_read_env_file(ROOT / ".env"))
    if config_path:
        path = Path(config_path)
        if path.exists():
            raw_config = json.loads(path.read_text(encoding="utf-8"))
            env_values.update(_flatten_config(raw_config))
    merged_env = _merged_env(env_values)

    top_level = {
        "data_dir": raw_config.get("data_dir"),
        "output_dir": raw_config.get("output_dir"),
        "memory_dir": raw_config.get("memory_dir"),
        "log_dir": raw_config.get("log_dir"),
        "pexels_api_key": raw_config.get("pexels_api_key"),
        "pixabay_api_key": raw_config.get("pixabay_api_key"),
        "gemini_api_key": raw_config.get("gemini_api_key"),
        "openrouter_api_key": raw_config.get("openrouter_api_key"),
        "openrouter_api_key_2": raw_config.get("openrouter_api_key_2"),
        "youtube_api_key": raw_config.get("youtube_api_key"),
        "youtube_access_token": raw_config.get("youtube_access_token"),
        "youtube_refresh_token": raw_config.get("youtube_refresh_token"),
        "youtube_client_id": raw_config.get("youtube_client_id"),
        "youtube_client_secret": raw_config.get("youtube_client_secret"),
        "youtube_privacy_status": raw_config.get("youtube_privacy_status"),
        "meta_access_token": raw_config.get("meta_access_token"),
        "meta_page_id": raw_config.get("meta_page_id"),
        "meta_graph_version": raw_config.get("meta_graph_version"),
        "meta_app_id": raw_config.get("meta_app_id"),
        "meta_app_secret": raw_config.get("meta_app_secret"),
        "meta_instagram_account_id": raw_config.get("meta_instagram_account_id"),
        "instagram_media_url_base": raw_config.get("instagram_media_url_base"),
        "media_host_base_url": raw_config.get("media_host_base_url"),
        "media_host_host": raw_config.get("media_host_host"),
        "media_host_port": raw_config.get("media_host_port"),
        "x_bearer_token": raw_config.get("x_bearer_token"),
        "x_api_key": raw_config.get("x_api_key"),
        "x_api_secret": raw_config.get("x_api_secret"),
        "x_access_token": raw_config.get("x_access_token"),
        "x_access_token_secret": raw_config.get("x_access_token_secret"),
        "tiktok_access_token": raw_config.get("tiktok_access_token"),
        "tiktok_open_id": raw_config.get("tiktok_open_id"),
        "enable_browser_automation": raw_config.get("enable_browser_automation"),
        "posting_auto_publish": raw_config.get("posting_auto_publish"),
        "posting_self_mode": raw_config.get("posting_self_mode"),
        "auto_patch_errors": raw_config.get("auto_patch_errors"),
        "smoke_test": raw_config.get("smoke_test"),
        "video_quality_mode": raw_config.get("video_quality_mode"),
        "video_target_duration_seconds": raw_config.get("video_target_duration_seconds"),
        "video_target_width": raw_config.get("video_target_width"),
        "video_target_height": raw_config.get("video_target_height"),
        "video_scene_backend": raw_config.get("video_scene_backend"),
        "video_scene_style": raw_config.get("video_scene_style"),
        "video_scene_seed": raw_config.get("video_scene_seed"),
    }
    providers = raw_config.get("providers", {}) if isinstance(raw_config.get("providers", {}), dict) else {}

    config = AppConfig(
        data_dir=Path(_pick_str(top_level["data_dir"], merged_env, "DATA_DIR", str(ROOT / "data"))),
        output_dir=Path(_pick_str(top_level["output_dir"], merged_env, "OUTPUT_DIR", str(ROOT / "output"))),
        memory_dir=Path(_pick_str(top_level["memory_dir"], merged_env, "MEMORY_DIR", str(ROOT / "memory"))),
        log_dir=Path(_pick_str(top_level["log_dir"], merged_env, "LOG_DIR", str(ROOT / "logs"))),
        pexels_api_key=_pick_str(top_level["pexels_api_key"], merged_env, "PEXELS_API_KEY"),
        pixabay_api_key=_pick_str(top_level["pixabay_api_key"], merged_env, "PIXABAY_API_KEY"),
        gemini_api_key=_pick_str(top_level["gemini_api_key"], merged_env, "GEMINI_API_KEY"),
        gemini_model=str(providers.get("gemini_model", merged_env.get("GEMINI_MODEL", "gemini-2.5-flash"))),
        openrouter_api_key=_pick_str(top_level["openrouter_api_key"], merged_env, "OPENROUTER_API_KEY"),
        openrouter_api_key_2=_pick_str(top_level["openrouter_api_key_2"], merged_env, "OPENROUTER_API_KEY_2"),
        openrouter_model=str(providers.get("openrouter_model", merged_env.get("OPENROUTER_MODEL", "openrouter/free"))),
        youtube_api_key=_pick_str(top_level["youtube_api_key"], merged_env, "YOUTUBE_API_KEY"),
        youtube_access_token=_pick_str(top_level["youtube_access_token"], merged_env, "YOUTUBE_ACCESS_TOKEN"),
        youtube_refresh_token=_pick_str(top_level["youtube_refresh_token"], merged_env, "YOUTUBE_REFRESH_TOKEN"),
        youtube_client_id=_pick_str(top_level["youtube_client_id"], merged_env, "YOUTUBE_CLIENT_ID"),
        youtube_client_secret=_pick_str(top_level["youtube_client_secret"], merged_env, "YOUTUBE_CLIENT_SECRET"),
        youtube_privacy_status=_pick_str(top_level["youtube_privacy_status"], merged_env, "YOUTUBE_PRIVACY_STATUS", "unlisted"),
        meta_access_token=_pick_str(top_level["meta_access_token"], merged_env, "META_ACCESS_TOKEN"),
        meta_page_id=_pick_str(top_level["meta_page_id"], merged_env, "META_PAGE_ID"),
        meta_graph_version=_pick_str(top_level["meta_graph_version"], merged_env, "META_GRAPH_VERSION", "v20.0"),
        meta_app_id=_pick_str(top_level["meta_app_id"], merged_env, "META_APP_ID"),
        meta_app_secret=_pick_str(top_level["meta_app_secret"], merged_env, "META_APP_SECRET"),
        meta_instagram_account_id=_pick_str(top_level["meta_instagram_account_id"], merged_env, "META_INSTAGRAM_ACCOUNT_ID"),
        instagram_media_url_base=_pick_str(top_level["instagram_media_url_base"], merged_env, "INSTAGRAM_MEDIA_URL_BASE"),
        media_host_base_url=_pick_str(top_level["media_host_base_url"], merged_env, "MEDIA_HOST_BASE_URL"),
        media_host_host=_pick_str(top_level["media_host_host"], merged_env, "MEDIA_HOST_HOST", "127.0.0.1"),
        media_host_port=_pick_int(top_level["media_host_port"], merged_env, "MEDIA_HOST_PORT", 8088),
        x_bearer_token=_pick_str(top_level["x_bearer_token"], merged_env, "X_BEARER_TOKEN"),
        x_api_key=_pick_str(top_level["x_api_key"], merged_env, "X_API_KEY"),
        x_api_secret=_pick_str(top_level["x_api_secret"], merged_env, "X_API_SECRET"),
        x_access_token=_pick_str(top_level["x_access_token"], merged_env, "X_ACCESS_TOKEN"),
        x_access_token_secret=_pick_str(top_level["x_access_token_secret"], merged_env, "X_ACCESS_TOKEN_SECRET"),
        tiktok_access_token=_pick_str(top_level["tiktok_access_token"], merged_env, "TIKTOK_ACCESS_TOKEN"),
        tiktok_open_id=_pick_str(top_level["tiktok_open_id"], merged_env, "TIKTOK_OPEN_ID"),
        enable_browser_automation=_pick_bool(top_level["enable_browser_automation"], merged_env, "ENABLE_BROWSER_AUTOMATION", False),
        posting_auto_publish=_pick_bool(top_level["posting_auto_publish"], merged_env, "POSTING_AUTO_PUBLISH", False),
        posting_self_mode=_pick_str(top_level["posting_self_mode"], merged_env, "POSTING_SELF_MODE", "api").strip().lower(),
        auto_patch_errors=_pick_bool(top_level["auto_patch_errors"], merged_env, "AUTO_PATCH_ERRORS", False),
        smoke_test=_pick_bool(top_level["smoke_test"], merged_env, "SMOKE_TEST", False),
        video_quality_mode=_pick_str(top_level["video_quality_mode"], merged_env, "VIDEO_QUALITY_MODE", "hq_720p_60s").strip().lower(),
        video_target_duration_seconds=_pick_int(top_level["video_target_duration_seconds"], merged_env, "VIDEO_TARGET_DURATION_SECONDS", 60),
        video_target_width=_pick_int(top_level["video_target_width"], merged_env, "VIDEO_TARGET_WIDTH", 720),
        video_target_height=_pick_int(top_level["video_target_height"], merged_env, "VIDEO_TARGET_HEIGHT", 1280),
        video_scene_backend=_pick_str(top_level["video_scene_backend"], merged_env, "VIDEO_SCENE_BACKEND", "free").strip().lower(),
        video_scene_style=_pick_str(top_level["video_scene_style"], merged_env, "VIDEO_SCENE_STYLE", "free").strip().lower(),
        video_scene_seed=_pick_int(top_level["video_scene_seed"], merged_env, "VIDEO_SCENE_SEED", 0),
    )
    video = raw_config.get("video", {})
    research = raw_config.get("research", {})
    posting = raw_config.get("posting", {})
    if video:
        config.video_width = int(video.get("width", config.video_width))
        config.video_height = int(video.get("height", config.video_height))
        config.video_fps = int(video.get("fps", config.video_fps))
        config.video_quality_mode = str(video.get("quality_mode", config.video_quality_mode))
        config.video_target_duration_seconds = int(video.get("target_duration_seconds", config.video_target_duration_seconds))
        config.video_target_width = int(video.get("target_width", config.video_target_width))
        config.video_target_height = int(video.get("target_height", config.video_target_height))
        config.video_scene_backend = str(video.get("scene_backend", config.video_scene_backend)).strip().lower()
        config.video_scene_style = str(video.get("scene_style", config.video_scene_style)).strip().lower()
        if video.get("scene_seed") is not None:
            config.video_scene_seed = int(video.get("scene_seed", config.video_scene_seed))
        config.video_voice = video.get("voice", config.video_voice)
        config.video_music_volume = float(video.get("music_volume", config.video_music_volume))
        config.video_speech_wpm = int(video.get("speech_wpm", config.video_speech_wpm))
    config.video_quality_mode = _pick_str(top_level["video_quality_mode"], merged_env, "VIDEO_QUALITY_MODE", config.video_quality_mode).strip().lower()
    config.video_target_duration_seconds = _pick_int(top_level["video_target_duration_seconds"], merged_env, "VIDEO_TARGET_DURATION_SECONDS", config.video_target_duration_seconds)
    config.video_target_width = _pick_int(top_level["video_target_width"], merged_env, "VIDEO_TARGET_WIDTH", config.video_target_width)
    config.video_target_height = _pick_int(top_level["video_target_height"], merged_env, "VIDEO_TARGET_HEIGHT", config.video_target_height)
    if research:
        config.research_rss_sources = list(research.get("rss_sources", config.research_rss_sources))
        config.research_max_trends = int(research.get("max_trends", config.research_max_trends))
    if posting:
        config.posting_default_platforms = list(posting.get("default_platforms", config.posting_default_platforms))
        config.posting_dry_run = bool(posting.get("dry_run", config.posting_dry_run))
    if config.video_quality_mode.startswith("hq"):
        config.video_width = config.video_target_width
        config.video_height = config.video_target_height
    return config
