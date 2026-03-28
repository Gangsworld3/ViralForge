from __future__ import annotations

import traceback
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable

from utils.json_io import append_jsonl


@dataclass
class HealingReport:
    step: str
    error_type: str
    root_cause: str
    retryable: bool
    suggestion: str
    traceback_text: str


class SelfHealingEngine:
    def __init__(self, config, llm_router=None, logger=None):
        self.config = config
        self.llm_router = llm_router
        self.logger = logger
        self.history_path = config.memory_dir / "healings.jsonl"

    def _classify(self, exc: Exception, tb_text: str) -> HealingReport:
        text = f"{type(exc).__name__}: {exc}\n{tb_text}".lower()
        retryable = any(token in text for token in ["timeout", "rate limit", "429", "temporarily unavailable", "connection"])
        if "filenotfounderror" in text:
            suggestion = "Create the missing file or ensure the output directory exists."
            root = "Missing file or directory"
        elif "429" in text or "rate limit" in text:
            suggestion = "Back off and switch providers."
            root = "Rate limit"
        elif "permission" in text:
            suggestion = "Check file permissions and path ownership."
            root = "Permission issue"
        else:
            suggestion = "Inspect traceback and retry with fallback logic."
            root = "Unexpected runtime failure"
        return HealingReport(
            step="unknown",
            error_type=type(exc).__name__,
            root_cause=root,
            retryable=retryable,
            suggestion=suggestion,
            traceback_text=tb_text,
        )

    def diagnose(self, step: str, exc: Exception) -> HealingReport:
        tb_text = traceback.format_exc()
        report = self._classify(exc, tb_text)
        report.step = step
        if self.llm_router is not None:
            try:
                prompt = (
                    f"Analyze this exception for step '{step}'. "
                    f"Return a short fix suggestion and whether retrying is safe.\n\n{tb_text}"
                )
                suggestion = self.llm_router.generate_text(prompt, task_type="analytics")
                report.suggestion = suggestion.strip()[:1200]
            except Exception as llm_exc:
                if self.logger:
                    self.logger.warning("Self-healing LLM diagnosis failed: %s", llm_exc)
        append_jsonl(self.history_path, report.__dict__)
        return report

    def safe_execute(self, step: str, func: Callable[..., Any], *args, retries: int = 1, **kwargs) -> Any:
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                last_error = exc
                report = self.diagnose(step, exc)
                if self.logger:
                    self.logger.error("Step %s failed: %s | suggestion=%s", step, exc, report.suggestion)
                if report.retryable and attempt < retries:
                    continue
                break
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Safe execute failed for step {step}")

    def log_fix(self, file_path: Path, new_text: str, note: str = "") -> None:
        if not self.config.auto_patch_errors:
            return
        # Do not mutate source code automatically in production. Capture a patch
        # artifact for review instead of overwriting code in-place.
        patch_dir = self.config.data_dir / "patches"
        patch_dir.mkdir(parents=True, exist_ok=True)
        patch_path = patch_dir / f"{file_path.stem}.suggested.patch"
        payload = {
            "target": str(file_path),
            "note": note,
            "suggested_text": new_text,
        }
        patch_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if self.logger:
            self.logger.info("Captured patch suggestion for %s at %s", file_path, patch_path)
