from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests


@dataclass
class OAuthCallbackResult:
    code: str = ""
    state: str = ""
    error: str = ""
    raw: dict[str, str] | None = None


def build_code_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(64)).decode("ascii").rstrip("=")


def build_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def build_authorization_url(client_id: str, redirect_uri: str, scope: str, state: str, code_challenge: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "false",
        "select_account": "true",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def exchange_code_for_tokens(
    *,
    client_id: str,
    client_secret: str | None,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict[str, Any]:
    payload: dict[str, str] = {
        "client_id": client_id,
        "code": code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    # Desktop / installed-app OAuth flows can exchange without client_secret when PKCE is used.
    if client_secret:
        payload["client_secret"] = client_secret

    response = requests.post("https://oauth2.googleapis.com/token", data=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def upsert_env_file(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    updated: list[str] = []
    seen = set()
    keys = set(values.keys())
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            updated.append(raw_line)
            continue
        key, _ = stripped.split("=", 1)
        key = key.strip()
        if key in values:
            updated.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            updated.append(raw_line)
    for key in sorted(keys - seen):
        updated.append(f"{key}={values[key]}")
    path.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")


class _CallbackServer(HTTPServer):
    def __init__(self, server_address, RequestHandlerClass, expected_path: str, state: str):
        super().__init__(server_address, RequestHandlerClass)
        self.expected_path = expected_path
        self.expected_state = state
        self.result: OAuthCallbackResult | None = None
        self.done = threading.Event()


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != self.server.expected_path:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        self.server.result = OAuthCallbackResult(
            code=params.get("code", ""),
            state=params.get("state", ""),
            error=params.get("error", ""),
            raw=params,
        )
        self.server.done.set()

        message = "Authorization complete. You can close this tab."
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"<html><body><h1>{message}</h1></body></html>".encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def start_callback_server(redirect_uri: str) -> tuple[_CallbackServer, threading.Thread]:
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http":
        raise ValueError("The redirect URI must use http for the local loopback callback.")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8080
    path = parsed.path or "/"
    server = _CallbackServer((host, port), _CallbackHandler, path, "")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def wait_for_callback_server(server: _CallbackServer, timeout_seconds: int = 180) -> OAuthCallbackResult:
    try:
        if not server.done.wait(timeout_seconds):
            host, port = server.server_address[:2]
            raise TimeoutError(f"Timed out waiting for OAuth callback on http://{host}:{port}{server.expected_path}")
        result = server.result or OAuthCallbackResult()
        if result.error:
            raise RuntimeError(f"OAuth callback returned error: {result.error}")
        if not result.code:
            raise RuntimeError("OAuth callback did not include an authorization code.")
        return result
    finally:
        try:
            server.shutdown()
        except Exception:
            pass


def generate_youtube_tokens(
    *,
    client_id: str,
    client_secret: str | None = None,
    redirect_uri: str,
    scope: str = "https://www.googleapis.com/auth/youtube.upload",
    open_browser: bool = True,
    timeout_seconds: int = 180,
    use_client_secret: bool = False,
    login_hint: str | None = None,
) -> dict[str, Any]:
    code_verifier = build_code_verifier()
    code_challenge = build_code_challenge(code_verifier)
    state = secrets.token_urlsafe(24)
    auth_url = build_authorization_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=scope,
        state=state,
        code_challenge=code_challenge,
    )
    if login_hint:
        auth_url += f"&login_hint={urlencode({'login_hint': login_hint}).split('=', 1)[1]}"
    server, thread = start_callback_server(redirect_uri)
    if open_browser:
        webbrowser.open(auth_url)
    try:
        callback = wait_for_callback_server(server, timeout_seconds=timeout_seconds)
        if callback.state and callback.state != state:
            raise RuntimeError("OAuth state mismatch. Restart the flow and try again.")
        tokens = exchange_code_for_tokens(
            client_id=client_id,
            client_secret=client_secret if use_client_secret else None,
            code=callback.code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )
        tokens["auth_url"] = auth_url
        tokens["redirect_uri"] = redirect_uri
        return tokens
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
