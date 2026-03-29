from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from subtitles.subtitles import SubtitleRenderer, build_word_timings, write_srt
from utils.text import slugify


class FFmpegVideoGenerator:
    def __init__(self, config, assets, logger=None):
        self.config = config
        self.assets = assets
        self.logger = logger
        self._font_cache: dict[tuple[str, int], Any] = {}
        self._plan_palette_cache: dict[str, list[tuple[int, int, int]]] = {}

    def _plan(self, plan: dict[str, Any] | None) -> dict[str, Any]:
        return plan or {}

    def _plan_cache_key(self, plan: dict[str, Any] | None) -> str:
        plan = self._plan(plan)
        palette = tuple(
            tuple(color[:3]) for color in (plan.get("color_palette") or []) if isinstance(color, (list, tuple))
        )
        return f"{str(plan.get('theme', '')).strip().lower()}|{palette}"

    def _plan_palette(self, plan: dict[str, Any] | None) -> list[tuple[int, int, int]]:
        cache_key = self._plan_cache_key(plan)
        cached = self._plan_palette_cache.get(cache_key)
        if cached is not None:
            return cached
        palette = self._plan(plan).get("color_palette") or []
        normalized: list[tuple[int, int, int]] = []
        for color in palette[:4]:
            if isinstance(color, (list, tuple)) and len(color) >= 3:
                normalized.append((int(color[0]), int(color[1]), int(color[2])))
        if normalized:
            self._plan_palette_cache[cache_key] = normalized
            return normalized
        theme = str(self._plan(plan).get("theme") or "").strip().lower()
        if theme == "neon":
            result = [(25, 34, 64), (49, 89, 182), (96, 165, 250)]
            self._plan_palette_cache[cache_key] = result
            return result
        if theme == "playful":
            result = [(22, 29, 50), (236, 72, 153), (74, 222, 128)]
            self._plan_palette_cache[cache_key] = result
            return result
        result = [(24, 20, 18), (93, 63, 211), (251, 146, 60)]
        self._plan_palette_cache[cache_key] = result
        return result

    def _load_font(self, path: str, size: int):
        cache_key = (path, size)
        cached = self._font_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            font = ImageFont.truetype(path, size=size)
        except Exception:
            font = ImageFont.load_default()
        self._font_cache[cache_key] = font
        return font

    def available(self) -> bool:
        return shutil.which("ffmpeg") is not None

    def _render_scene_frame(self, image_path: Path, size: tuple[int, int], t: float, scene_duration: float, plan: dict[str, Any] | None = None) -> np.ndarray:
        img = Image.open(image_path).convert("RGB")
        progress = max(0.0, min(1.0, t / max(0.01, scene_duration)))
        zoom = 1.08 + 0.05 * math.sin(progress * math.pi)
        target = (int(size[0] * zoom), int(size[1] * zoom))
        fitted = ImageOps.fit(img, target, method=Image.Resampling.LANCZOS)
        left = max(0, (fitted.width - size[0]) // 2)
        top = max(0, (fitted.height - size[1]) // 2)
        cropped = fitted.crop((left, top, left + size[0], top + size[1]))
        palette = self._plan_palette(plan)
        saturation = 1.12 if str(self._plan(plan).get("motion", "")).strip().lower() == "high" else 1.08
        contrast = 1.12 if str(self._plan(plan).get("theme", "")).strip().lower() == "neon" else 1.08
        cropped = ImageEnhance.Contrast(cropped).enhance(contrast)
        cropped = ImageEnhance.Color(cropped).enhance(saturation)
        overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        # Darken edges to center attention and keep text legible.
        top = palette[1] if len(palette) > 1 else (6, 8, 18)
        bottom = palette[2] if len(palette) > 2 else (4, 4, 8)
        draw.rectangle([0, 0, size[0], size[1]], fill=(0, 0, 0, 34))
        draw.rectangle([0, 0, size[0], int(size[1] * 0.18)], fill=(*top, 74))
        draw.rectangle([0, int(size[1] * 0.78), size[0], size[1]], fill=(*bottom, 98))
        vignette = overlay.filter(ImageFilter.GaussianBlur(radius=18))
        composed = Image.alpha_composite(cropped.convert("RGBA"), vignette)
        return np.array(composed.convert("RGB"))

    def _intro_frame(self, topic: str, size: tuple[int, int], progress: float, plan: dict[str, Any] | None = None) -> np.ndarray:
        plan = self._plan(plan)
        bg = Image.new("RGBA", size, color=(9, 12, 22, 255))
        draw = ImageDraw.Draw(bg)
        # Gradient-like layered bands for a polished hook card.
        palette = self._plan_palette(plan)
        top = palette[0] if palette else (16, 18, 35)
        mid = palette[1] if len(palette) > 1 else (34, 42, 72)
        for y in range(size[1]):
            mix = y / max(1, size[1] - 1)
            r = int(top[0] * (1 - mix) + mid[0] * mix)
            g = int(top[1] * (1 - mix) + mid[1] * mix)
            b = int(top[2] * (1 - mix) + mid[2] * mix)
            draw.line((0, y, size[0], y), fill=(r, g, b))

        pulse = 1.0 + (0.06 if str(plan.get("motion", "")).lower() == "high" else 0.04) * math.sin(progress * math.pi * 2)
        card_w = int(size[0] * 0.82 * pulse)
        card_h = int(size[1] * 0.34)
        x0 = (size[0] - card_w) // 2
        y0 = int(size[1] * 0.20)
        x1 = x0 + card_w
        y1 = y0 + card_h
        draw.rounded_rectangle((x0, y0, x1, y1), radius=42, fill=(12, 12, 18, 225), outline=(255, 255, 255, 32), width=2)

        title_font = self._load_font("C:/Windows/Fonts/arialbd.ttf", 78)
        sub_font = self._load_font("C:/Windows/Fonts/arial.ttf", 40)

        title = (plan.get("hook_text") or topic or "ViralForge").strip()
        subtitle = plan.get("intro_style") or "Scroll-stopping short form"
        title_bbox = draw.textbbox((0, 0), title, font=title_font, stroke_width=4)
        title_w = title_bbox[2] - title_bbox[0]
        title_h = title_bbox[3] - title_bbox[1]
        title_x = (size[0] - title_w) // 2
        title_y = y0 + 40
        subtitle_bbox = draw.textbbox((0, 0), subtitle, font=sub_font)
        subtitle_w = subtitle_bbox[2] - subtitle_bbox[0]
        subtitle_x = (size[0] - subtitle_w) // 2
        subtitle_y = title_y + title_h + 26

        accent = palette[0] if palette else (255, 94, 58)
        draw.rounded_rectangle(
            (title_x - 20, title_y - 12, title_x + title_w + 20, title_y + title_h + 12),
            radius=24,
            fill=(*accent, 220),
        )
        draw.text((title_x + 4, title_y + 4), title, font=title_font, fill=(0, 0, 0, 170), stroke_width=0)
        draw.text((title_x, title_y), title, font=title_font, fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
        draw.text((subtitle_x, subtitle_y), subtitle, font=sub_font, fill=(229, 231, 235))

        return np.array(bg.convert("RGB"))

    def _motion_frame(
        self,
        topic: str,
        size: tuple[int, int],
        t: float,
        scene_duration: float,
        trend_item: dict[str, Any] | None = None,
        plan: dict[str, Any] | None = None,
    ) -> np.ndarray:
        plan = self._plan(plan)
        width, height = size
        progress = max(0.0, min(1.0, t / max(0.01, scene_duration)))
        base = Image.new("RGBA", size, color=(10, 12, 22, 255))
        draw = ImageDraw.Draw(base)

        palette = self._plan_palette(plan)
        palette_index = int(progress * len(palette)) % len(palette) if palette else 0
        top = palette[palette_index] if palette else (20, 24, 46)
        bottom = (8, 10, 18)
        for y in range(height):
            mix = y / max(1, height - 1)
            r = int(top[0] * (1 - mix) + bottom[0] * mix)
            g = int(top[1] * (1 - mix) + bottom[1] * mix)
            b = int(top[2] * (1 - mix) + bottom[2] * mix)
            draw.line((0, y, width, y), fill=(r, g, b, 255))

        # Floating accent rings for motion.
        ring_count = 6 if str(plan.get("motion", "")).strip().lower() == "high" else 4
        if str(plan.get("theme", "")).strip().lower() == "playful":
            ring_count = 3 if str(plan.get("motion", "")).strip().lower() != "high" else 4
        for index in range(ring_count):
            phase = progress * math.pi * 2 + index * 1.3
            cx = int(width * (0.2 + 0.18 * index) + math.sin(phase) * 28)
            cy = int(height * (0.18 + 0.12 * index) + math.cos(phase * 0.9) * 34)
            radius = int(48 + 16 * math.sin(phase * 1.2))
            draw.ellipse(
                (cx - radius, cy - radius, cx + radius, cy + radius),
                outline=(255, 255, 255, 26),
                width=4,
            )

        # Central motion card with trend context.
        card_w = int(width * (0.86 if str(plan.get("card_density", "")).strip().lower() == "dense" else 0.82))
        card_h = int(height * (0.32 if str(plan.get("card_density", "")).strip().lower() == "dense" else 0.30))
        card_x = (width - card_w) // 2
        motion_scale = {"low": 8, "medium": 18, "high": 28}.get(str(plan.get("motion", "")).strip().lower(), 18)
        card_y = int(height * 0.18 + math.sin(progress * math.pi * 2) * motion_scale)
        draw.rounded_rectangle(
            (card_x, card_y, card_x + card_w, card_y + card_h),
            radius=40,
            fill=(10, 12, 18, 220),
            outline=(255, 255, 255, 36),
            width=2,
        )

        hook = plan.get("hook_text") or (trend_item or {}).get("title") or topic
        detail = (trend_item or {}).get("description") or (trend_item or {}).get("source") or "Trend signal"
        hook = str(hook)[:44]
        detail = str(detail)[:110]
        hook_font = self._load_font("C:/Windows/Fonts/arialbd.ttf", 66)
        detail_font = self._load_font("C:/Windows/Fonts/arial.ttf", 32)
        tag_font = self._load_font("C:/Windows/Fonts/arialbd.ttf", 28)

        badge_text = str(plan.get("intro_style") or "TREND / SHORT FORM").upper()
        badge_box = draw.textbbox((0, 0), badge_text, font=tag_font)
        badge_w = badge_box[2] - badge_box[0]
        draw.rounded_rectangle(
            (card_x + 32, card_y + 28, card_x + 32 + badge_w + 28, card_y + 28 + 42),
            radius=20,
            fill=(255, 92, 92, 235),
        )
        draw.text((card_x + 46, card_y + 34), badge_text, fill=(0, 0, 0, 180), font=tag_font)
        draw.text((card_x + 44, card_y + 32), badge_text, fill=(255, 255, 255), font=tag_font)

        hook_box = draw.textbbox((0, 0), hook, font=hook_font, stroke_width=3)
        hook_w = hook_box[2] - hook_box[0]
        hook_x = (width - hook_w) // 2
        hook_y = card_y + 82
        draw.text((hook_x + 4, hook_y + 4), hook, fill=(0, 0, 0, 160), font=hook_font, stroke_width=0)
        draw.text((hook_x, hook_y), hook, fill=(255, 255, 255), font=hook_font, stroke_width=3, stroke_fill=(0, 0, 0))

        detail_box = draw.textbbox((0, 0), detail, font=detail_font)
        detail_w = detail_box[2] - detail_box[0]
        detail_x = (width - detail_w) // 2
        detail_y = card_y + card_h - 86
        draw.text((detail_x, detail_y + 3), detail, fill=(0, 0, 0, 150), font=detail_font)
        draw.text((detail_x, detail_y), detail, fill=(234, 236, 240), font=detail_font)

        footer = plan.get("footer_text") or "Watch to the end"
        footer_box = draw.textbbox((0, 0), footer, font=tag_font)
        footer_w = footer_box[2] - footer_box[0]
        footer_x = (width - footer_w) // 2
        footer_y = int(height * 0.82)
        draw.rounded_rectangle(
            (footer_x - 22, footer_y - 10, footer_x + footer_w + 22, footer_y + 36),
            radius=18,
            fill=(18, 18, 28, 180),
        )
        draw.text((footer_x, footer_y), footer, fill=(250, 250, 250), font=tag_font)

        overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle((0, 0, width, int(height * 0.12)), fill=(255, 255, 255, 18))
        overlay_draw.rectangle((0, int(height * 0.84), width, height), fill=(0, 0, 0, 56))
        base = Image.alpha_composite(base, overlay.filter(ImageFilter.GaussianBlur(radius=7)))
        return np.array(base.convert("RGB"))

    def _compose_progress_bar(self, frame: np.ndarray, progress: float, plan: dict[str, Any] | None = None) -> np.ndarray:
        image = Image.fromarray(frame).convert("RGBA")
        draw = ImageDraw.Draw(image)
        width, height = image.size
        bar_h = 12
        margin = int(width * 0.08)
        y = height - 68
        palette = self._plan_palette(plan)
        draw.rounded_rectangle((margin, y, width - margin, y + bar_h), radius=10, fill=(255, 255, 255, 56))
        fill_w = int((width - margin * 2) * max(0.0, min(1.0, progress)))
        accent = palette[0] if palette else (255, 92, 92)
        draw.rounded_rectangle((margin, y, margin + fill_w, y + bar_h), radius=10, fill=(*accent, 220))
        return np.array(image.convert("RGB"))

    def _target_duration(self, script: str) -> float:
        words = split_words(script)
        target_duration = max(12.0, float(getattr(self.config, "video_target_duration_seconds", 60)))
        duration = max(target_duration, len(words) * (60.0 / max(1, self.config.video_speech_wpm)))
        if self.config.smoke_test:
            duration = min(duration, 4.0)
        return duration

    def _resolve_scenes(
        self,
        topic: str,
        script: str,
        size: tuple[int, int],
        trend_items: list[dict[str, Any]],
        plan: dict[str, Any],
    ) -> tuple[list[Path], bool]:
        first_line = script.splitlines()[0] if script.splitlines() else script[:60]
        scene_count = int(plan.get("scene_count") or 4)
        selected_trends = trend_items[:scene_count]
        scenes = self.assets.generate_trend_story_images(first_line[:60], selected_trends, size, plan=plan)
        use_motion_fallback = not scenes and str(plan.get("render_mode", "")).strip().lower() == "motion"
        if not scenes and not use_motion_fallback:
            scenes = self.assets.generate_story_images(first_line[:60], 4, size)
        if not scenes and not use_motion_fallback:
            scenes = self.assets.generate_story_images(topic, 4, size)
        return scenes, use_motion_fallback

    def _build_subtitles(self, script: str, duration: float, output_path: Path, plan: dict[str, Any], size: tuple[int, int]):
        subtitle_entries = build_word_timings(script.replace("\n", " "), duration, speech_wpm=self.config.video_speech_wpm)
        srt_path = output_path.with_suffix(".srt")
        write_srt(subtitle_entries, srt_path)
        renderer = SubtitleRenderer(
            size,
            style={
                "preset": plan.get("subtitle_preset", "capcut_pop"),
                "position": plan.get("subtitle_position", "bottom"),
                "context_window": 5,
                "motion_amp": {"low": 14, "medium": 22, "high": 30}.get(str(plan.get("motion", "")).strip().lower(), 22),
            },
        )
        return subtitle_entries, srt_path, renderer

    def _timeline_metrics(self, duration: float, scenes: list[Path]) -> tuple[int, float, float, float]:
        frame_count = max(1, int(duration * self.config.video_fps))
        intro_span = min(2.4, max(1.1, duration * 0.14))
        remaining = max(0.01, duration - intro_span)
        scene_span = remaining / max(1, len(scenes)) if scenes else remaining
        return frame_count, intro_span, remaining, scene_span

    def _frame_base(
        self,
        topic: str,
        size: tuple[int, int],
        t: float,
        intro_span: float,
        remaining: float,
        scene_span: float,
        scenes: list[Path],
        use_motion_fallback: bool,
        trend_items: list[dict[str, Any]],
        plan: dict[str, Any],
    ) -> np.ndarray:
        if t < intro_span:
            intro_progress = t / max(0.001, intro_span)
            return self._intro_frame(topic, size, intro_progress, plan=plan)
        t_scene = t - intro_span
        if use_motion_fallback:
            scene_index = min(max(0, len(trend_items) - 1), int((t_scene / remaining) * max(1, len(trend_items))))
            trend_item = trend_items[scene_index] if trend_items else None
            return self._motion_frame(topic, size, t_scene, remaining, trend_item=trend_item, plan=plan)
        scene_index = min(len(scenes) - 1, int(t_scene / scene_span))
        scene_t = t_scene - scene_index * scene_span
        return self._render_scene_frame(scenes[scene_index], size, scene_t, scene_span, plan=plan)

    def _render_frames(
        self,
        frame_dir: Path,
        topic: str,
        duration: float,
        size: tuple[int, int],
        scenes: list[Path],
        use_motion_fallback: bool,
        trend_items: list[dict[str, Any]],
        plan: dict[str, Any],
        renderer: SubtitleRenderer,
        subtitle_entries: list[dict[str, Any]],
    ) -> int:
        frame_count, intro_span, remaining, scene_span = self._timeline_metrics(duration, scenes)
        for index in range(frame_count):
            t = index / float(self.config.video_fps)
            base = self._frame_base(
                topic=topic,
                size=size,
                t=t,
                intro_span=intro_span,
                remaining=remaining,
                scene_span=scene_span,
                scenes=scenes,
                use_motion_fallback=use_motion_fallback,
                trend_items=trend_items,
                plan=plan,
            )
            base = self._compose_progress_bar(base, t / max(0.001, duration), plan=plan)
            frame = renderer.render(base, t, subtitle_entries)
            Image.fromarray(frame).save(frame_dir / f"frame_{index:06d}.png")
        return frame_count

    def _encode_temp_video(self, frame_pattern: str, temp_video: Path) -> None:
        encode_cmd = [
            "ffmpeg",
            "-y",
            "-framerate",
            str(self.config.video_fps),
            "-i",
            frame_pattern,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(temp_video),
        ]
        subprocess.run(encode_cmd, check=True, capture_output=True)

    def _audio_mux_spec(self, temp_video: Path, output_path: Path, voice_path: Path | None, music_path: Path | None) -> list[str] | None:
        voice_exists = bool(voice_path and voice_path.exists())
        music_exists = bool(music_path and music_path.exists())
        if not voice_exists and not music_exists:
            return None
        audio_inputs: list[str] = []
        filter_parts: list[str] = []
        maps: list[str] = []
        if voice_exists:
            audio_inputs.extend(["-i", str(voice_path)])
        if music_exists:
            audio_inputs.extend(["-stream_loop", "-1", "-i", str(music_path)])
        if voice_exists and music_exists:
            filter_parts = [
                "[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=1.0,aresample=44100[voice]",
                "[2:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=0.18,aresample=44100[music]",
                "[music][voice]sidechaincompress=threshold=0.02:ratio=12:attack=20:release=250[ducked]",
                "[voice][ducked]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            ]
            maps = ["-map", "0:v", "-map", "[aout]"]
        elif voice_exists:
            maps = ["-map", "0:v", "-map", "1:a"]
        else:
            maps = ["-map", "0:v", "-map", "1:a"]
        mux_cmd = ["ffmpeg", "-y", "-i", str(temp_video), *audio_inputs]
        if filter_parts:
            mux_cmd.extend(["-filter_complex", ";".join(filter_parts)])
        mux_cmd.extend([*maps, "-c:v", "copy", "-c:a", "aac", "-shortest", str(output_path)])
        return mux_cmd

    def _write_output(self, temp_video: Path, output_path: Path, voice_path: Path | None, music_path: Path | None) -> None:
        mux_cmd = self._audio_mux_spec(temp_video, output_path, voice_path, music_path)
        if mux_cmd:
            subprocess.run(mux_cmd, check=True, capture_output=True)
        else:
            temp_video.replace(output_path)
        if temp_video.exists():
            try:
                temp_video.unlink()
            except Exception:
                pass

    def build(
        self,
        topic: str,
        script: str,
        output_path: Path,
        voice_path: Path | None = None,
        music_path: Path | None = None,
        trend_items: list[dict[str, Any]] | None = None,
        plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        plan = self._plan(plan)
        size = (self.config.video_width, self.config.video_height)
        trend_items = trend_items or []
        duration = self._target_duration(script)
        scenes, use_motion_fallback = self._resolve_scenes(topic, script, size, trend_items, plan)
        subtitle_entries, srt_path, renderer = self._build_subtitles(script, duration, output_path, plan, size)

        with tempfile.TemporaryDirectory(prefix="viralforge_frames_") as tmp:
            frame_dir = Path(tmp)
            frame_count = self._render_frames(
                frame_dir=frame_dir,
                topic=topic,
                duration=duration,
                size=size,
                scenes=scenes,
                use_motion_fallback=use_motion_fallback,
                trend_items=trend_items,
                plan=plan,
                renderer=renderer,
                subtitle_entries=subtitle_entries,
            )
            temp_video = output_path.with_suffix(".temp.mp4")
            frame_pattern = str(frame_dir / "frame_%06d.png")
            self._encode_temp_video(frame_pattern, temp_video)
            self._write_output(temp_video, output_path, voice_path, music_path)

        return {
            "status": "ok",
            "video_path": str(output_path),
            "subtitle_path": str(srt_path),
            "duration": duration,
            "summary": f"FFmpeg rendered {output_path.name} with {frame_count} frames.",
        }
