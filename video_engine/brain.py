from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from analytics.retention import RetentionOptimizer
from analytics.viral_scoring import ViralScorer
from utils.text import extract_keywords, split_sentences, split_words


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _topic_theme(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ["ai", "tech", "startup", "app", "software", "automation", "productivity"]):
        return "neon"
    if any(word in lowered for word in ["money", "finance", "invest", "crypto", "stocks", "business", "sales", "marketing"]):
        return "editorial"
    if any(word in lowered for word in ["life", "style", "fashion", "fitness", "food", "travel", "home", "beauty"]):
        return "playful"
    return "editorial"


def _theme_defaults(theme: str) -> dict[str, Any]:
    defaults = {
        "neon": {
            "subtitle_preset": "neon_bounce",
            "pacing": "fast",
            "motion": "high",
            "scene_count": 5,
            "music_intensity": "high",
            "voice_energy": "high",
            "footer_text": "Tap in before it explodes",
            "intro_style": "punchy",
            "scene_backend": "free",
        },
        "playful": {
            "subtitle_preset": "capcut_pop",
            "pacing": "fast",
            "motion": "high",
            "scene_count": 5,
            "music_intensity": "medium",
            "voice_energy": "warm",
            "footer_text": "Watch this one twice",
            "intro_style": "relatable",
            "scene_backend": "free",
        },
        "editorial": {
            "subtitle_preset": "clean_karaoke",
            "pacing": "balanced",
            "motion": "medium",
            "scene_count": 4,
            "music_intensity": "low",
            "voice_energy": "calm",
            "footer_text": "Watch to the end",
            "intro_style": "clean",
            "scene_backend": "free",
        },
    }
    return defaults.get(theme, defaults["editorial"]).copy()


_ALLOWED_THEMES = {"neon", "editorial", "playful"}
_ALLOWED_PACING = {"fast", "balanced", "slow"}
_ALLOWED_MOTION = {"low", "medium", "high"}
_ALLOWED_PRESETS = {"capcut_pop", "neon_bounce", "clean_karaoke"}


def _normalize_enum(value: Any, allowed: set[str], default: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else default


def _extract_json(text: str) -> dict[str, Any]:
    raw = text.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found")
    return json.loads(raw[start : end + 1])


@dataclass
class VideoPlan:
    theme: str
    pacing: str
    subtitle_preset: str
    scene_count: int
    motion: str
    music_intensity: str
    voice_energy: str
    footer_text: str
    intro_style: str
    scene_backend: str = "free"
    render_mode: str = "trend_story"
    hook_text: str = ""
    color_palette: list[list[int]] = field(default_factory=list)
    emphasis_words: list[str] = field(default_factory=list)
    card_density: str = "medium"
    story_beat_count: int = 4
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "theme": self.theme,
            "pacing": self.pacing,
            "subtitle_preset": self.subtitle_preset,
            "scene_count": self.scene_count,
            "motion": self.motion,
            "music_intensity": self.music_intensity,
            "voice_energy": self.voice_energy,
            "footer_text": self.footer_text,
            "intro_style": self.intro_style,
            "scene_backend": self.scene_backend,
            "render_mode": self.render_mode,
            "hook_text": self.hook_text,
            "color_palette": self.color_palette,
            "emphasis_words": self.emphasis_words,
            "card_density": self.card_density,
            "story_beat_count": self.story_beat_count,
            "notes": self.notes,
        }


class VideoBrain:
    def __init__(self, config, router, memory, logger=None):
        self.config = config
        self.router = router
        self.memory = memory
        self.logger = logger
        self.retention = RetentionOptimizer(memory=memory, logger=logger)
        self.scorer = ViralScorer(memory=memory, logger=logger)

    def _base_plan(self, topic: str, script: str, trend_items: list[dict[str, Any]] | None = None) -> VideoPlan:
        trend_items = trend_items or []
        merged_text = " ".join([topic, script] + [str(item.get("title", "")) for item in trend_items[:4]])
        theme = _topic_theme(merged_text)
        defaults = _theme_defaults(theme)
        target_seconds = max(12, int(getattr(self.config, "video_target_duration_seconds", 60)))
        target_words = max(90, int(target_seconds * max(1, int(getattr(self.config, "video_speech_wpm", 165))) / 60))
        hook_text = (split_sentences(script)[0] if script else topic)[:80]
        keywords = extract_keywords(merged_text, limit=8)
        scene_count = _clamp(max(defaults["scene_count"], min(6, len(trend_items) or defaults["scene_count"])), 3, 7)
        motion = defaults["motion"]
        if len(script.split()) > target_words * 1.2:
            motion = "high"
        elif len(script.split()) < target_words * 0.7:
            motion = "medium"
        return VideoPlan(
            theme=theme,
            pacing=defaults["pacing"],
            subtitle_preset=defaults["subtitle_preset"],
            scene_count=scene_count,
            motion=motion,
            music_intensity=defaults["music_intensity"],
            voice_energy=defaults["voice_energy"],
            footer_text=defaults["footer_text"],
            intro_style=defaults["intro_style"],
            scene_backend=defaults["scene_backend"],
            hook_text=hook_text,
            color_palette=[],
            emphasis_words=keywords[:5],
            card_density="dense" if theme == "neon" else "balanced" if theme == "editorial" else "playful",
            story_beat_count=min(5, max(3, len(split_sentences(script)) or 4)),
            notes=[
                f"Theme selected from topic and trend keywords: {theme}.",
                f"Target length is about {target_words} words for {target_seconds} seconds.",
            ],
        )

    def _llm_refine(self, plan: VideoPlan, topic: str, script: str, trend_items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        trend_lines = "\n".join(
            f"- {item.get('title', '')}: {item.get('description', '')}" for item in (trend_items or [])[:4]
        )
        prompt = (
            "You are the ViralForge video brain. Return JSON only.\n"
            "Choose values that make a short-form vertical video feel premium, fast, and viral.\n"
            "Allowed themes: neon, editorial, playful.\n"
            "Allowed pacing: fast, balanced, slow.\n"
            "Allowed motion: low, medium, high.\n"
            "Allowed subtitle presets: capcut_pop, neon_bounce, clean_karaoke.\n\n"
            f"Topic: {topic}\n"
            f"Script:\n{script}\n\n"
            f"Trend items:\n{trend_lines or '- none'}\n\n"
            "Return a JSON object with keys: theme, pacing, subtitle_preset, scene_count, motion, music_intensity, "
            "voice_energy, footer_text, intro_style, render_mode, hook_text, emphasis_words, card_density, story_beat_count, notes, color_palette.\n"
            "Keep notes short."
        )
        refined_text = self.router.generate_text(prompt, task_type="video")
        try:
            parsed = _extract_json(refined_text)
            if self.logger:
                self.logger.info("Video brain refinement parsed from LLM.")
            return parsed
        except Exception as exc:
            if self.logger:
                self.logger.debug("Video brain refinement fell back to heuristic plan: %s", exc)
            return {}

    def plan_video(
        self,
        topic: str,
        script: str,
        trend_items: list[dict[str, Any]] | None = None,
        research_text: str = "",
        analytics_hint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        plan = self._base_plan(topic, script, trend_items)
        refined = self._llm_refine(plan, topic, script, trend_items)
        if refined:
            allowed = {
                "theme",
                "pacing",
                "subtitle_preset",
                "scene_count",
                "motion",
                "music_intensity",
                "voice_energy",
                "footer_text",
                "intro_style",
                "render_mode",
                "hook_text",
                "emphasis_words",
                "card_density",
                "story_beat_count",
                "notes",
                "color_palette",
                "scene_backend",
            }
            for key in allowed:
                if key not in refined:
                    continue
                value = refined[key]
                if key == "scene_count":
                    try:
                        plan.scene_count = _clamp(int(value), 3, 7)
                    except Exception:
                        continue
                elif key == "story_beat_count":
                    try:
                        plan.story_beat_count = _clamp(int(value), 3, 7)
                    except Exception:
                        continue
                elif key == "emphasis_words" and isinstance(value, list):
                    plan.emphasis_words = [str(item)[:24] for item in value[:8]]
                elif key == "notes":
                    if isinstance(value, list):
                        plan.notes = [str(item)[:120] for item in value[:5]]
                    elif value:
                        plan.notes = [str(value)[:120]]
                elif key == "color_palette" and isinstance(value, list):
                    palette: list[list[int]] = []
                    for color in value[:4]:
                        if isinstance(color, (list, tuple)) and len(color) >= 3:
                            palette.append([int(color[0]), int(color[1]), int(color[2])])
                    plan.color_palette = palette
                else:
                    if key == "theme":
                        plan.theme = _normalize_enum(value, _ALLOWED_THEMES, plan.theme)
                    elif key == "pacing":
                        plan.pacing = _normalize_enum(value, _ALLOWED_PACING, plan.pacing)
                    elif key == "subtitle_preset":
                        plan.subtitle_preset = _normalize_enum(value, _ALLOWED_PRESETS, plan.subtitle_preset)
                    elif key == "motion":
                        plan.motion = _normalize_enum(value, _ALLOWED_MOTION, plan.motion)
                    elif key in {"music_intensity", "voice_energy", "intro_style", "render_mode", "card_density", "scene_backend"}:
                        setattr(plan, key, str(value).strip().lower())
                    else:
                        setattr(plan, key, str(value))
        if not isinstance(plan.notes, list):
            plan.notes = [] if not plan.notes else [str(plan.notes)[:120]]
        if not isinstance(plan.emphasis_words, list):
            plan.emphasis_words = []
        if not plan.color_palette:
            defaults = _theme_defaults(plan.theme)
            if plan.theme == "neon":
                plan.color_palette = [[25, 34, 64], [49, 89, 182], [96, 165, 250]]
            elif plan.theme == "playful":
                plan.color_palette = [[22, 29, 50], [236, 72, 153], [74, 222, 128]]
            else:
                plan.color_palette = [[24, 20, 18], [93, 63, 211], [251, 146, 60]]
            plan.footer_text = plan.footer_text or defaults["footer_text"]
        plan.notes.extend(
            [
                f"Research context length: {len(research_text.split()) if research_text else 0} words.",
            ]
        )
        if analytics_hint:
            plan.notes.append("Analytics hint applied from prior runs.")
        payload = plan.as_dict()
        try:
            if self.memory:
                self.memory.save_memory(
                    "video_brain_plan",
                    json.dumps(payload, ensure_ascii=False),
                    {"topic": topic, "theme": plan.theme, "subtitle_preset": plan.subtitle_preset},
                )
        except Exception as exc:
            if self.logger:
                self.logger.warning("Failed to save video brain plan: %s", exc)
        return payload

    def validate_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        sanitized = dict(plan or {})
        sanitized["theme"] = _normalize_enum(sanitized.get("theme"), _ALLOWED_THEMES, "editorial")
        sanitized["pacing"] = _normalize_enum(sanitized.get("pacing"), _ALLOWED_PACING, "balanced")
        sanitized["subtitle_preset"] = _normalize_enum(sanitized.get("subtitle_preset"), _ALLOWED_PRESETS, "clean_karaoke")
        sanitized["motion"] = _normalize_enum(sanitized.get("motion"), _ALLOWED_MOTION, "medium")
        try:
            sanitized["scene_count"] = _clamp(int(sanitized.get("scene_count", 4)), 3, 7)
        except Exception:
            sanitized["scene_count"] = 4
        try:
            sanitized["story_beat_count"] = _clamp(int(sanitized.get("story_beat_count", 4)), 3, 7)
        except Exception:
            sanitized["story_beat_count"] = 4
        sanitized["footer_text"] = str(sanitized.get("footer_text") or "Watch to the end")[:80]
        sanitized["intro_style"] = str(sanitized.get("intro_style") or "clean").strip().lower()
        sanitized["card_density"] = str(sanitized.get("card_density") or "medium").strip().lower()
        sanitized["scene_backend"] = str(sanitized.get("scene_backend") or "free").strip().lower()
        if not isinstance(sanitized.get("emphasis_words"), list):
            sanitized["emphasis_words"] = []
        if not isinstance(sanitized.get("notes"), list):
            sanitized["notes"] = []
        if not isinstance(sanitized.get("color_palette"), list):
            sanitized["color_palette"] = []
        return sanitized

    def score_plan(self, plan: dict[str, Any], topic: str, script: str, trend_items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        plan = self.validate_plan(plan)
        trend_items = trend_items or []
        retention = self.retention.analyze(script)
        script_score = self.scorer.score(script, " ".join([topic] + [str(item.get("title", "")) for item in trend_items[:4]]))
        issues: list[str] = []
        score = 40

        hook = str(plan.get("hook_text") or "").strip()
        if hook:
            score += 12
            if len(hook) <= 90:
                score += 6
            if hook.endswith("?") or any(token in hook.lower() for token in ["why", "how", "what", "secret", "watch"]):
                score += 6
        else:
            issues.append("Missing hook text.")

        pacing = str(plan.get("pacing") or "").strip().lower()
        if pacing == "fast":
            score += 12
        elif pacing == "balanced":
            score += 8
        else:
            issues.append("Pacing is too slow for short-form retention.")

        motion = str(plan.get("motion") or "").strip().lower()
        if motion == "high":
            score += 10
        elif motion == "medium":
            score += 6
        else:
            issues.append("Motion is too low for a scroll-stopping video.")

        subtitle_preset = str(plan.get("subtitle_preset") or "").strip().lower()
        if subtitle_preset in {"capcut_pop", "neon_bounce", "clean_karaoke"}:
            score += 8
        else:
            issues.append("Unknown subtitle preset.")

        scene_count = int(plan.get("scene_count") or 0)
        if 4 <= scene_count <= 6:
            score += 10
        elif scene_count in {3, 7}:
            score += 6
        else:
            issues.append("Scene count is off target.")

        footer = str(plan.get("footer_text") or "").lower()
        if any(token in footer for token in ["watch", "tap", "save", "comment", "follow"]):
            score += 8
        else:
            issues.append("Footer lacks a retention CTA.")

        if retention.pacing_notes:
            score += max(0, 10 - len(retention.pacing_notes) * 2)
            issues.extend(retention.pacing_notes[:3])

        score += min(12, script_score.total // 10)
        score = min(100, score)

        if score < 72:
            issues.append("Plan is weak against retention rules.")
        return {
            "score": score,
            "issues": issues,
            "retention": retention.__dict__,
            "script_score": script_score.__dict__,
        }

    def revise_plan(
        self,
        plan: dict[str, Any],
        topic: str,
        script: str,
        trend_items: list[dict[str, Any]] | None = None,
        score_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        trend_items = trend_items or []
        score_report = score_report or {}
        issues = score_report.get("issues", [])
        trend_lines = "\n".join(
            f"- {item.get('title', '')}: {item.get('description', '')}" for item in trend_items[:4]
        )
        prompt = (
            "You are the ViralForge video brain. Return JSON only.\n"
            "Revise the video plan to improve retention, hook strength, pacing, subtitle emphasis, and CTA.\n"
            "Keep the output compact and practical.\n\n"
            f"Topic: {topic}\n"
            f"Current plan:\n{json.dumps(plan, ensure_ascii=False)}\n\n"
            f"Retention issues:\n{json.dumps(issues, ensure_ascii=False)}\n\n"
            f"Script:\n{script}\n\n"
            f"Trend items:\n{trend_lines or '- none'}\n\n"
            "Return a JSON object with the same keys as the plan, plus optional notes."
        )
        refined_text = self.router.generate_text(prompt, task_type="optimize")
        try:
            revision = _extract_json(refined_text)
        except Exception:
            revision = {}
        updated = self.validate_plan(plan)
        if revision:
            for key, value in revision.items():
                if key in {"theme", "pacing", "subtitle_preset", "motion", "music_intensity", "voice_energy", "footer_text", "intro_style", "render_mode", "hook_text", "card_density", "scene_backend"}:
                    updated[key] = str(value).strip().lower()
                elif key in {"scene_count", "story_beat_count"}:
                    try:
                        updated[key] = _clamp(int(value), 3, 7)
                    except Exception:
                        continue
                elif key == "emphasis_words" and isinstance(value, list):
                    updated[key] = [str(item)[:24] for item in value[:8]]
                elif key == "notes" and isinstance(value, list):
                    updated[key] = [str(item)[:140] for item in value[:8]]
                elif key == "color_palette" and isinstance(value, list):
                    palette: list[list[int]] = []
                    for color in value[:4]:
                        if isinstance(color, (list, tuple)) and len(color) >= 3:
                            palette.append([int(color[0]), int(color[1]), int(color[2])])
                    if palette:
                        updated[key] = palette
        updated.setdefault("notes", [])
        updated["notes"] = list(updated["notes"])[:8]
        updated["notes"].append("Retained via revision pass after low retention score.")
        if not updated.get("subtitle_preset"):
            updated["subtitle_preset"] = "capcut_pop"
        if not updated.get("footer_text"):
            updated["footer_text"] = "Watch to the end"
        if not updated.get("motion"):
            updated["motion"] = "medium"
        if not updated.get("pacing"):
            updated["pacing"] = "balanced"
        return self.validate_plan(updated)

    def score_render_artifact(self, video_path: str | Path, plan: dict[str, Any] | None = None) -> dict[str, Any]:
        plan = self.validate_plan(plan or {})
        path = Path(video_path)
        report = {
            "score": 0,
            "issues": [],
            "video_exists": path.exists(),
            "video_size_bytes": path.stat().st_size if path.exists() else 0,
            "has_audio": False,
            "duration_seconds": 0.0,
        }
        if not path.exists():
            report["issues"].append("Video file does not exist.")
            return report
        report["score"] += 30
        if path.stat().st_size > 500_000:
            report["score"] += 10
        if shutil.which("ffprobe"):
            try:
                proc = subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_streams",
                        "-show_format",
                        "-of",
                        "json",
                        str(path),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                data = json.loads(proc.stdout or "{}")
                streams = data.get("streams", [])
                duration = float(data.get("format", {}).get("duration", 0.0) or 0.0)
                report["duration_seconds"] = duration
                if any(stream.get("codec_type") == "audio" for stream in streams):
                    report["has_audio"] = True
                    report["score"] += 25
                else:
                    report["issues"].append("No audio stream detected.")
                if duration >= max(8.0, float(getattr(self.config, "video_target_duration_seconds", 60)) * 0.75):
                    report["score"] += 15
                else:
                    report["issues"].append("Video duration is shorter than expected.")
                if any(stream.get("codec_type") == "video" for stream in streams):
                    report["score"] += 10
                else:
                    report["issues"].append("No video stream detected.")
            except Exception as exc:
                report["issues"].append(f"ffprobe failed: {exc}")
        else:
            report["issues"].append("ffprobe unavailable; artifact validation is limited.")
        if plan.get("subtitle_preset") not in _ALLOWED_PRESETS:
            report["issues"].append("Subtitle preset is invalid.")
        if plan.get("motion") == "high":
            report["score"] += 5
        if plan.get("theme") == "neon":
            report["score"] += 3
        report["score"] = min(100, report["score"])
        if report["score"] < 70:
            report["issues"].append("Rendered artifact did not pass quality threshold.")
        return report
