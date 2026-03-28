from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont


class FreeSceneGenerator:
    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger
        self.cache_dir = config.data_dir / "cache" / "free_scene"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, prompt: str, size: tuple[int, int], index: int) -> Path:
        key = hashlib.sha256(
            f"{prompt}|{size[0]}x{size[1]}|{index}|{getattr(self.config, 'video_scene_style', 'free')}|{getattr(self.config, 'video_scene_seed', 0)}".encode(
                "utf-8"
            )
        ).hexdigest()
        return self.cache_dir / f"{key}.png"

    def _font(self, size: int, bold: bool = False):
        candidates = [
            "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for path in candidates:
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _topic_profile(
        self,
        topic: str,
        trend_items: list[dict[str, Any]] | None = None,
        plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text = " ".join([topic] + [str(item.get("title", "")) for item in (trend_items or [])[:4]]).lower()
        if plan:
            theme = str(plan.get("theme") or "").strip().lower()
            if theme in {"neon", "editorial", "playful"}:
                palette = plan.get("color_palette") or plan.get("palette")
                if isinstance(palette, list) and palette:
                    normalized: list[tuple[int, int, int]] = []
                    for color in palette[:4]:
                        if isinstance(color, (list, tuple)) and len(color) >= 3:
                            normalized.append((int(color[0]), int(color[1]), int(color[2])))
                    if normalized:
                        return {
                            "category": str(plan.get("category") or theme),
                            "theme": theme,
                            "palette": normalized,
                        }
        if any(word in text for word in ["ai", "tech", "startup", "app", "software", "automation", "productivity"]):
            return {
                "category": "tech",
                "theme": "neon",
                "palette": [(25, 34, 64), (49, 89, 182), (96, 165, 250)],
            }
        if any(word in text for word in ["money", "finance", "invest", "crypto", "stocks", "business", "sales", "marketing"]):
            return {
                "category": "finance",
                "theme": "editorial",
                "palette": [(24, 20, 18), (93, 63, 211), (251, 146, 60)],
            }
        if any(word in text for word in ["life", "style", "fashion", "fitness", "food", "travel", "home", "beauty"]):
            return {
                "category": "lifestyle",
                "theme": "playful",
                "palette": [(22, 29, 50), (236, 72, 153), (74, 222, 128)],
            }
        return {
            "category": "general",
            "theme": "editorial",
            "palette": [(18, 24, 42), (59, 130, 246), (244, 114, 182)],
        }

    def _theme_layout(
        self,
        theme: str,
        index: int,
        progress: float,
        width: int,
        height: int,
        plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        motion = str((plan or {}).get("motion", "")).strip().lower()
        motion_scale_override = {
            "low": 12,
            "medium": 20,
            "high": 30,
        }.get(motion)
        footer_override = (plan or {}).get("footer_text")
        scene_count = int((plan or {}).get("scene_count") or 0)
        card_density = str((plan or {}).get("card_density", "")).strip().lower()
        if theme == "neon":
            return {
                "bg_alpha": 255,
                "ring_count": 6 if motion == "high" else 5,
                "card_y": int(height * (0.17 + 0.02 * math.sin(progress * math.pi * 2 + index))),
                "card_w": int(width * (0.88 if card_density == "dense" else 0.84)),
                "card_h": int(height * (0.38 if card_density == "dense" else 0.36)),
                "accent": (96, 165, 250, 232),
                "badge": (74, 222, 128, 235),
                "motion_scale": motion_scale_override or (18 + index * 2),
                "footer": footer_override or "Tap in before it explodes",
            }
        if theme == "playful":
            return {
                "bg_alpha": 255,
                "ring_count": 4 if motion == "high" else 3,
                "card_y": int(height * (0.15 + 0.03 * math.cos(progress * math.pi * 2 + index * 0.5))),
                "card_w": int(width * (0.82 if card_density == "dense" else 0.80)),
                "card_h": int(height * (0.36 if card_density == "dense" else 0.34)),
                "accent": (244, 114, 182, 232),
                "badge": (34, 197, 94, 235),
                "motion_scale": motion_scale_override or (26 + index * 3),
                "footer": footer_override or "Watch this one twice",
            }
        return {
            "bg_alpha": 255,
            "ring_count": 5 if motion == "high" else 4,
            "card_y": int(height * (0.18 + 0.02 * math.sin(progress * math.pi * 2 + index * 0.3))),
            "card_w": int(width * (0.84 if card_density == "dense" else 0.82)),
            "card_h": int(height * (0.37 if card_density == "dense" else 0.35)),
            "accent": (255, 92, 92, 232),
            "badge": (251, 146, 60, 235),
            "motion_scale": motion_scale_override or (20 + index * 2),
            "footer": footer_override or "Watch to the end",
        }

    def _trend_card(
        self,
        topic: str,
        item: dict[str, Any] | None,
        size: tuple[int, int],
        index: int,
        progress: float,
        plan: dict[str, Any] | None = None,
    ) -> Image.Image:
        width, height = size
        profile = self._topic_profile(topic, [item] if item else None, plan=plan)
        theme = profile["theme"]
        palette = profile["palette"]
        layout = self._theme_layout(theme, index, progress, width, height, plan=plan)

        bg = Image.new("RGBA", size, (10, 12, 20, layout["bg_alpha"]))
        draw = ImageDraw.Draw(bg)

        top = palette[index % len(palette)]
        bottom = (6, 8, 14)
        for y in range(height):
            mix = y / max(1, height - 1)
            r = int(top[0] * (1 - mix) + bottom[0] * mix)
            g = int(top[1] * (1 - mix) + bottom[1] * mix)
            b = int(top[2] * (1 - mix) + bottom[2] * mix)
            draw.line((0, y, width, y), fill=(r, g, b, 255))

        for ring in range(layout["ring_count"]):
            phase = progress * math.pi * 2 + ring * (1.0 if theme == "neon" else 1.35)
            cx = int(width * (0.15 + ring * (0.18 if theme != "playful" else 0.22)) + math.sin(phase) * (18 + layout["motion_scale"] * 0.5))
            cy = int(height * (0.16 + ring * 0.11) + math.cos(phase * 0.9) * (16 + layout["motion_scale"] * 0.35))
            radius = int(38 + 12 * math.sin(phase * 1.2))
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=(255, 255, 255, 34), width=4)

        card_w = layout["card_w"]
        card_h = layout["card_h"]
        card_x = (width - card_w) // 2
        card_y = layout["card_y"]
        draw.rounded_rectangle((card_x, card_y, card_x + card_w, card_y + card_h), radius=42, fill=(12, 12, 18, 225), outline=(255, 255, 255, 30), width=2)

        hook = str((plan or {}).get("hook_text") or (item or {}).get("title") or topic)[:44]
        detail = str((item or {}).get("description") or (item or {}).get("source") or "Free scene generator")[:118]
        badge = profile["category"].upper()
        badge_font = self._font(28, bold=True)
        hook_font = self._font(64 if theme != "playful" else 60, bold=True)
        detail_font = self._font(32, bold=False)

        badge_box = draw.textbbox((0, 0), badge, font=badge_font)
        badge_w = badge_box[2] - badge_box[0]
        draw.rounded_rectangle((card_x + 32, card_y + 28, card_x + 32 + badge_w + 30, card_y + 28 + 42), radius=20, fill=layout["badge"])
        draw.text((card_x + 46, card_y + 34), badge, fill=(0, 0, 0, 180), font=badge_font)
        draw.text((card_x + 44, card_y + 32), badge, fill=(255, 255, 255), font=badge_font)

        hook_box = draw.textbbox((0, 0), hook, font=hook_font, stroke_width=3)
        hook_w = hook_box[2] - hook_box[0]
        hook_x = (width - hook_w) // 2
        hook_y = card_y + (78 if theme != "playful" else 90)
        draw.text((hook_x + 4, hook_y + 4), hook, fill=(0, 0, 0, 160), font=hook_font)
        draw.text((hook_x, hook_y), hook, fill=(255, 255, 255), font=hook_font, stroke_width=3, stroke_fill=(0, 0, 0))

        detail_box = draw.multiline_textbbox((0, 0), detail, font=detail_font, spacing=6)
        detail_w = detail_box[2] - detail_box[0]
        detail_x = (width - detail_w) // 2
        detail_y = card_y + card_h - (96 if theme != "playful" else 104)
        draw.multiline_text((detail_x, detail_y + 3), detail, fill=(0, 0, 0, 150), font=detail_font, spacing=6)
        draw.multiline_text((detail_x, detail_y), detail, fill=(234, 236, 240), font=detail_font, spacing=6)

        footer = layout["footer"]
        footer_font = self._font(28, bold=True)
        footer_box = draw.textbbox((0, 0), footer, font=footer_font)
        footer_w = footer_box[2] - footer_box[0]
        footer_x = (width - footer_w) // 2
        footer_y = int(height * (0.81 if theme != "playful" else 0.79))
        draw.rounded_rectangle((footer_x - 22, footer_y - 10, footer_x + footer_w + 22, footer_y + 36), radius=18, fill=(18, 18, 28, 180))
        draw.text((footer_x, footer_y), footer, fill=(250, 250, 250), font=footer_font)

        overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle((0, 0, width, int(height * 0.12)), fill=(255, 255, 255, 16))
        overlay_draw.rectangle((0, int(height * 0.84), width, height), fill=(0, 0, 0, 58))
        bg = Image.alpha_composite(bg, overlay.filter(ImageFilter.GaussianBlur(radius=7)))
        return bg.convert("RGB")

    def generate_trend_images(
        self,
        topic: str,
        trend_items: list[dict[str, Any]],
        size: tuple[int, int],
        count: int = 4,
        plan: dict[str, Any] | None = None,
    ) -> list[Path]:
        if getattr(self.config, "smoke_test", False):
            return []

        item_count = int((plan or {}).get("scene_count") or count or 4)
        items = trend_items[:item_count] or [{"title": topic, "description": "Free scene rendering", "source": "local"}]
        paths: list[Path] = []
        for index, item in enumerate(items):
            topic_profile = self._topic_profile(topic, items, plan=plan)
            key_topic = f"{topic_profile['theme']}::{(plan or {}).get('motion', 'medium')}::{item.get('title') or topic}"
            path = self._cache_key(key_topic, size, index)
            if path.exists():
                paths.append(path)
                continue
            image = self._trend_card(topic, item, size, index, progress=index / max(1, len(items) - 1 or 1), plan=plan)
            image.save(path)
            paths.append(path)
        return paths
