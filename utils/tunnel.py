from __future__ import annotations

import re
import subprocess
import threading
import shutil
from dataclasses import dataclass
from typing import Any


@dataclass
class TunnelResult:
    provider: str
    public_url: str
    process: subprocess.Popen[str] | None = None


class CloudflareQuickTunnel:
    def __init__(self, local_url: str, logger=None):
        self.local_url = local_url
        self.logger = logger
        self.process: subprocess.Popen[str] | None = None
        self.public_url: str = ""
        self._reader: threading.Thread | None = None

    def _log(self, message: str, *args: Any) -> None:
        if self.logger and hasattr(self.logger, "info"):
            self.logger.info(message, *args)

    def _warn(self, message: str, *args: Any) -> None:
        if self.logger and hasattr(self.logger, "warning"):
            self.logger.warning(message, *args)

    def start(self, timeout_seconds: int = 60) -> TunnelResult:
        if shutil.which("cloudflared") is None:
            raise RuntimeError("cloudflared is not installed or not on PATH. Install cloudflared to use the free Quick Tunnel.")
        cmd = [
            "cloudflared",
            "tunnel",
            "--url",
            self.local_url,
            "--no-autoupdate",
        ]
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if not self.process.stdout:
            raise RuntimeError("cloudflared did not expose stdout for tunnel startup.")

        url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
        lines: list[str] = []

        def _consume_output() -> None:
            try:
                for raw_line in self.process.stdout:
                    line = raw_line.strip()
                    if not line:
                        continue
                    lines.append(line)
                    match = url_pattern.search(line)
                    if match and not self.public_url:
                        self.public_url = match.group(0)
                        self._log("Cloudflare quick tunnel started at %s", self.public_url)
            except Exception as exc:
                self._warn("Cloudflare tunnel output reader stopped: %s", exc)

        self._reader = threading.Thread(target=_consume_output, daemon=True)
        self._reader.start()

        deadline = timeout_seconds
        while deadline > 0 and not self.public_url:
            if self.process.poll() is not None:
                break
            threading.Event().wait(1)
            deadline -= 1

        if not self.public_url:
            self.stop()
            raise RuntimeError(
                "cloudflared started, but no public URL was reported. "
                f"Collected output: {' | '.join(lines[-10:])}"
            )

        return TunnelResult(provider="cloudflare", public_url=self.public_url, process=self.process)

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
            except Exception:
                pass
            try:
                self.process.wait(timeout=10)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
