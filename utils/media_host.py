from __future__ import annotations

import time
import threading
import shutil
from dataclasses import dataclass
from pathlib import Path

from flask import Flask, abort, send_from_directory
import requests
from werkzeug.serving import make_server

from utils.json_io import load_json, save_json
from utils.tunnel import CloudflareQuickTunnel


_URL_LIVENESS_CACHE: dict[str, tuple[float, bool]] = {}


@dataclass
class MediaHostConfig:
    host: str = "127.0.0.1"
    port: int = 8088
    public_base_url: str = ""
    state_path: Path | None = None


def _url_is_live(url: str, timeout_seconds: int = 2) -> bool:
    if not url:
        return False
    cached = _URL_LIVENESS_CACHE.get(url)
    now = time.time()
    if cached and now - cached[0] < 30:
        return cached[1]
    try:
        response = requests.get(str(url).rstrip("/"), timeout=timeout_seconds)
        live = response.status_code < 500
        _URL_LIVENESS_CACHE[url] = (now, live)
        return live
    except Exception:
        _URL_LIVENESS_CACHE[url] = (now, False)
        return False


def resolve_public_media_base_url(config) -> str:
    candidates = []
    state_path = getattr(config, "data_dir", None)
    if state_path is not None:
        report_path = Path(state_path) / "reports" / "media_host.json"
        state = load_json(report_path, default={}) or {}
        state_url = state.get("public_base_url", "")
        if state_url and _url_is_live(state_url):
            candidates.append(state_url)
    candidates.extend([
        getattr(config, "media_host_base_url", ""),
        getattr(config, "instagram_media_url_base", ""),
    ])
    for candidate in candidates:
        if candidate:
            return str(candidate).rstrip("/")
    return ""


def ensure_public_media_base_url(config, logger=None) -> str:
    existing = resolve_public_media_base_url(config)
    auto_host = getattr(config, "auto_host", None)
    if auto_host is False:
        return existing
    if existing:
        return existing
    instagram_enabled = bool(getattr(config, "meta_instagram_account_id", "") or "instagram" in getattr(config, "posting_default_platforms", []))
    if not instagram_enabled and auto_host is not True:
        return ""
    if not instagram_enabled:
        # Force mode can start a tunnel even when Instagram is not explicitly enabled.
        pass
    data_dir = getattr(config, "data_dir", None)
    state_path = (data_dir / "reports" / "media_host.json") if data_dir is not None else None
    host = MediaHost(
        getattr(config, "output_dir"),
        MediaHostConfig(
            host=getattr(config, "media_host_host", "127.0.0.1"),
            port=getattr(config, "media_host_port", 8088),
            public_base_url="",
            state_path=state_path,
        ),
        logger=logger,
    )
    try:
        return host.start_public_tunnel()
    except Exception as exc:
        if logger and hasattr(logger, "warning"):
            logger.warning("Auto-start media tunnel failed: %s", exc)
        return ""


class MediaHost:
    def __init__(self, root: Path, config: MediaHostConfig | None = None, logger=None):
        self.root = root
        self.config = config or MediaHostConfig()
        self.logger = logger
        self._tunnel: CloudflareQuickTunnel | None = None
        self._server = None
        self._server_thread: threading.Thread | None = None

    def create_app(self) -> Flask:
        app = Flask(__name__)

        @app.get("/")
        def index():
            items = []
            for path in sorted(self.root.glob("*")):
                if path.is_file():
                    items.append(f'<li><a href="/media/{path.name}">{path.name}</a></li>')
            body = "<h1>ViralForge Media Host</h1><ul>" + "".join(items) + "</ul>"
            return body

        @app.get("/media/<path:filename>")
        def media(filename: str):
            file_path = self.root / filename
            if not file_path.exists() or not file_path.is_file():
                abort(404)
            return send_from_directory(self.root, filename, as_attachment=False)

        return app

    def public_url_for(self, filename: str) -> str:
        base_url = self.config.public_base_url
        if not base_url and self.config.state_path:
            state = load_json(self.config.state_path, default={}) or {}
            candidate = state.get("public_base_url", "")
            base_url = candidate if candidate and _url_is_live(candidate) else ""
        if base_url:
            return f"{str(base_url).rstrip('/')}/media/{filename.lstrip('/')}"
        return f"http://{self.config.host}:{self.config.port}/media/{filename.lstrip('/')}"

    def _serve_background(self, app: Flask) -> threading.Thread:
        server = make_server(self.config.host, self.config.port, app, threaded=True)
        self._server = server

        def _run() -> None:
            server.serve_forever()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        self._server_thread = thread
        return thread

    def start_public_tunnel(self) -> str:
        if shutil.which("cloudflared") is None:
            raise RuntimeError("cloudflared is not installed or not on PATH. Install cloudflared to use the free Quick Tunnel.")
        app = self.create_app()
        self._serve_background(app)
        self._tunnel = CloudflareQuickTunnel(f"http://{self.config.host}:{self.config.port}", logger=self.logger)
        try:
            result = self._tunnel.start()
        except Exception:
            self.stop()
            raise
        if self.config.state_path:
            save_json(
                self.config.state_path,
                {
                    "provider": result.provider,
                    "public_base_url": result.public_url,
                    "local_url": f"http://{self.config.host}:{self.config.port}",
                },
            )
        if self.logger:
            self.logger.info("Media host public URL: %s", result.public_url)
        return result.public_url

    def run(self, use_tunnel: bool = False) -> str | None:
        app = self.create_app()
        if not use_tunnel:
            if self.logger:
                self.logger.info("Starting media host on http://%s:%s", self.config.host, self.config.port)
            app.run(host=self.config.host, port=self.config.port, debug=False, use_reloader=False)
            return None

        try:
            public_url = self.start_public_tunnel()
        except Exception as exc:
            if self.logger:
                self.logger.warning("Tunnel startup failed, falling back to local media host: %s", exc)
            app.run(host=self.config.host, port=self.config.port, debug=False, use_reloader=False)
            return None
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
        return public_url

    def stop(self) -> None:
        if self._tunnel:
            self._tunnel.stop()
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass
            self._server = None
