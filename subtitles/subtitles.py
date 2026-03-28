from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from utils.text import is_rtl, split_words


SUBTITLE_PRESETS: dict[str, dict[str, Any]] = {
    "capcut_pop": {
        "font_size": 64,
        "bar_color": (12, 12, 18, 176),
        "highlight_bg": (255, 109, 64, 235),
        "animation": "pop",
        "glow": True,
        "motion_amp": 22,
    },
    "neon_bounce": {
        "font_size": 62,
        "bar_color": (8, 10, 22, 164),
        "highlight_bg": (96, 165, 250, 225),
        "animation": "bounce",
        "glow": True,
        "accent_palette": [
            (96, 165, 250, 255),
            (45, 212, 191, 255),
            (250, 204, 21, 255),
            (244, 114, 182, 255),
            (167, 139, 250, 255),
        ],
    },
    "clean_karaoke": {
        "font_size": 58,
        "bar_color": (18, 18, 18, 150),
        "highlight_bg": (255, 255, 255, 210),
        "font_color": (255, 255, 255, 255),
        "stroke_color": (0, 0, 0, 255),
        "animation": "slide",
        "glow": False,
    },
}


@dataclass
class SubtitleEntry:
    start: float
    end: float
    text: str
    word_index: int = 0


def build_word_timings(text: str, duration: float, speech_wpm: int = 165) -> list[SubtitleEntry]:
    words = split_words(text)
    if not words:
        return []
    seconds_per_word = 60.0 / max(1, speech_wpm)
    inferred_duration = max(duration, len(words) * seconds_per_word)
    step = inferred_duration / len(words)
    entries: list[SubtitleEntry] = []
    for index, word in enumerate(words):
        start = index * step
        end = min(inferred_duration, start + step * 0.95)
        entries.append(SubtitleEntry(start=start, end=end, text=word, word_index=index))
    return entries


def write_srt(entries: list[SubtitleEntry], path: Path) -> None:
    def fmt(seconds: float) -> str:
        ms = int((seconds - int(seconds)) * 1000)
        total = int(seconds)
        h = total // 3600
        m = (total % 3600) // 60
        s = total % 60
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    lines = []
    for i, entry in enumerate(entries, 1):
        lines.extend([str(i), f"{fmt(entry.start)} --> {fmt(entry.end)}", entry.text, ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


class SubtitleRenderer:
    def __init__(self, size: tuple[int, int], style: dict[str, Any] | None = None):
        self.width, self.height = size
        self.style = {
            "font_size": 60,
            "font_color": (255, 255, 255, 255),
            "stroke_color": (0, 0, 0, 255),
            "background": (0, 0, 0, 0),
            "shadow": True,
            "position": "bottom",
            "bar_color": (10, 10, 10, 168),
            "highlight_bg": (255, 90, 60, 230),
            "accent_palette": [
                (255, 92, 92, 255),
                (255, 163, 77, 255),
                (99, 232, 170, 255),
                (96, 165, 250, 255),
                (196, 125, 255, 255),
            ],
            "motion_amp": 18,
            "context_window": 4,
            "top_padding": 120,
            "bottom_padding": 140,
            "animation": "bounce",
            "glow": True,
            "preset": "capcut_pop",
        }
        preset_name = (style or {}).get("preset", self.style["preset"])
        if preset_name in SUBTITLE_PRESETS:
            self.style.update(SUBTITLE_PRESETS[preset_name])
        if style:
            self.style.update(style)
        self._font_cache: dict[int, Any] = {}
        self._entry_starts: list[float] = []
        self._last_active_index: int | None = None
        self.font = self._load_font(self.style["font_size"])

    def _load_font(self, size: int):
        cached = self._font_cache.get(size)
        if cached is not None:
            return cached
        candidates = [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        for path in candidates:
            try:
                font = ImageFont.truetype(path, size=size)
                self._font_cache[size] = font
                return font
            except Exception:
                continue
        font = ImageFont.load_default()
        self._font_cache[size] = font
        return font

    def _ensure_entry_index(self, entries: list[SubtitleEntry]) -> None:
        if len(self._entry_starts) != len(entries):
            self._entry_starts = [entry.start for entry in entries]
            self._last_active_index = None

    def _active_index(self, entries: list[SubtitleEntry], t: float) -> int | None:
        self._ensure_entry_index(entries)
        last = self._last_active_index
        if last is not None and 0 <= last < len(entries):
            entry = entries[last]
            if entry.start <= t <= entry.end:
                return last
            if last + 1 < len(entries):
                next_entry = entries[last + 1]
                if next_entry.start <= t <= next_entry.end:
                    self._last_active_index = last + 1
                    return last + 1
        index = bisect.bisect_right(self._entry_starts, t) - 1
        if 0 <= index < len(entries):
            entry = entries[index]
            if entry.start <= t <= entry.end:
                self._last_active_index = index
                return index
        self._last_active_index = None
        return None

    def _color_for_word(self, index: int, progress: float) -> tuple[int, int, int, int]:
        palette = self.style["accent_palette"]
        base = palette[index % len(palette)]
        if progress <= 0:
            return base
        shift = 0.12 * math.sin(progress * math.pi * 2 + index * 0.7)
        r = max(0, min(255, int(base[0] * (1 - shift) + 255 * shift)))
        g = max(0, min(255, int(base[1] * (1 - shift / 2))))
        b = max(0, min(255, int(base[2] * (1 - shift) + 235 * shift)))
        return (r, g, b, base[3] if len(base) > 3 else 255)

    def _measure(self, draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=3)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _display_words(self, entries: list[SubtitleEntry], active_index: int, radius: int) -> list[SubtitleEntry]:
        start = max(0, active_index - radius)
        end = min(len(entries), active_index + radius + 1)
        return entries[start:end]

    def render(self, base_frame: np.ndarray, t: float, entries: list[SubtitleEntry]) -> np.ndarray:
        active_index = self._active_index(entries, t)
        if active_index is None:
            return base_frame

        frame = Image.fromarray(base_frame).convert("RGBA")
        overlay = Image.new("RGBA", frame.size, self.style["background"])
        draw = ImageDraw.Draw(overlay)

        active = entries[active_index]
        progress = (t - active.start) / max(0.001, active.end - active.start)
        progress = max(0.0, min(1.0, progress))
        effect = self.style.get("animation", "bounce")
        if effect == "pop":
            bounce = math.sin(progress * math.pi) * (self.style["motion_amp"] * 0.8)
            scale_boost = 1.16 + 0.2 * math.sin(progress * math.pi)
        elif effect == "slide":
            bounce = math.sin(progress * math.pi) * (self.style["motion_amp"] * 0.35)
            scale_boost = 1.02 + 0.08 * math.sin(progress * math.pi)
        else:
            bounce = math.sin(progress * math.pi) * self.style["motion_amp"]
            scale_boost = 1.08 + 0.14 * math.sin(progress * math.pi)

        window = self._display_words(entries, active_index, int(self.style["context_window"]))
        rtl = any(is_rtl(item.text) for item in window)
        if rtl:
            window = list(reversed(window))

        display_items = [
            {
                "entry": item,
                "text": item.text[::-1] if is_rtl(item.text) else item.text,
                "is_active": item.word_index == active.word_index,
            }
            for item in window
        ]

        word_metrics = []
        total_width = 0
        max_height = 0
        spacing = 18
        for item in display_items:
            scale = scale_boost if item["is_active"] else 0.94
            font_size = max(24, int(self.style["font_size"] * scale))
            font = self._load_font(font_size)
            width, height = self._measure(draw, item["text"], font)
            word_metrics.append({"font": font, "width": width, "height": height, "scale": scale})
            total_width += width
            max_height = max(max_height, height)
        total_width += spacing * max(0, len(display_items) - 1)

        center_x = self.width // 2
        x = center_x - total_width // 2
        pad_x = 30
        pad_y = 18
        line_height = max_height + pad_y * 2
        if self.style.get("position") == "top":
            y = int(self.style["top_padding"] + bounce * 0.45)
        else:
            y = int(self.height - self.style["bottom_padding"] - line_height - bounce * 0.55)
        y = max(36, min(self.height - line_height - 36, y))

        bar_left = max(24, x - pad_x)
        bar_top = max(24, y - pad_y)
        bar_right = min(self.width - 24, x + total_width + pad_x)
        bar_bottom = min(self.height - 24, y + max_height + pad_y)
        draw.rounded_rectangle(
            (bar_left, bar_top, bar_right, bar_bottom),
            radius=32,
            fill=self.style["bar_color"],
        )

        cursor_x = x
        for item, metric in zip(display_items, word_metrics):
            text = item["text"]
            font = metric["font"]
            width = metric["width"]
            height = metric["height"]
            is_active = item["is_active"]
            word_progress = progress if is_active else 0.0
            color = self._color_for_word(item["entry"].word_index, word_progress)
            x_offset = 0
            if is_active:
                accent = self.style["highlight_bg"]
                offset_y = int(-bounce * 0.9)
                if effect == "slide":
                    x_offset = int((1.0 - progress) * -18)
                if self.style.get("glow", True):
                    glow_layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
                    glow_draw = ImageDraw.Draw(glow_layer)
                    glow_color = color[:3] + (170,)
                    glow_draw.text(
                        (cursor_x + x_offset + 2, y + offset_y + 2),
                        text,
                        font=font,
                        fill=glow_color,
                        stroke_width=8,
                        stroke_fill=glow_color,
                    )
                    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=5))
                    overlay = Image.alpha_composite(overlay, glow_layer)
                draw.rounded_rectangle(
                    (
                        cursor_x + x_offset - 14,
                        y - 8 + offset_y,
                        cursor_x + x_offset + width + 14,
                        y + height + 8 + offset_y,
                    ),
                    radius=24,
                    fill=accent,
                )
            else:
                offset_y = 0
            if self.style.get("shadow", True):
                draw.text(
                    (cursor_x + x_offset + 4, y + 5 + offset_y),
                    text,
                    font=font,
                    fill=(0, 0, 0, 170),
                    stroke_width=2,
                    stroke_fill=(0, 0, 0, 170),
                )
            draw.text(
                (cursor_x + x_offset, y + offset_y),
                text,
                font=font,
                fill=self.style["font_color"] if not is_active else color,
                stroke_width=4,
                stroke_fill=self.style["stroke_color"],
            )
            cursor_x += width + spacing

        overlay = overlay.filter(ImageFilter.GaussianBlur(radius=0.35))
        combined = Image.alpha_composite(frame, overlay)
        return np.array(combined.convert("RGB"))


def choose_position_for_faces(face_boxes: list[tuple[int, int, int, int]] | None, height: int) -> str:
    if not face_boxes:
        return "bottom"
    for _, top, _, bottom in face_boxes:
        if bottom > height * 0.65:
            return "top"
    return "bottom"
