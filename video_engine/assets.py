from __future__ import annotations

from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from video_engine.free_scene import FreeSceneGenerator
from utils.text import slugify


class AssetManager:
    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger
        self.cache_dir = config.data_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.free_scene = FreeSceneGenerator(config, logger=logger)

    def _placeholder_image(self, topic: str, index: int, size: tuple[int, int]) -> Path:
        path = self.cache_dir / f"{slugify(topic)}-{index}.png"
        img = Image.new("RGB", size, color=(18, 18, 24))
        draw = ImageDraw.Draw(img)
        gradient_color = (50 + index * 20, 95 + index * 10, 160 + index * 12)
        draw.rectangle([0, 0, size[0], size[1]], fill=gradient_color)
        draw.ellipse([size[0] * 0.15, size[1] * 0.12, size[0] * 0.85, size[1] * 0.72], outline=(255, 255, 255), width=8)
        text = topic[:36]
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", size=64)
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        x = (size[0] - (bbox[2] - bbox[0])) // 2
        y = size[1] - 220
        draw.text((x, y), text, fill="white", font=font, stroke_width=4, stroke_fill="black")
        img.save(path)
        return path

    def generate_story_images(self, topic: str, count: int, size: tuple[int, int]) -> list[Path]:
        return [self._placeholder_image(topic, index, size) for index in range(count)]

    def generate_trend_story_images(
        self,
        topic: str,
        trend_items: list[dict],
        size: tuple[int, int],
        plan: dict | None = None,
    ) -> list[Path]:
        free_paths = self.free_scene.generate_trend_images(
            topic,
            trend_items,
            size,
            count=min(4, max(1, len(trend_items))),
            plan=plan,
        )
        if free_paths:
            return free_paths
        if not trend_items:
            return self.generate_story_images(topic, 4, size)

        paths: list[Path] = []
        for index, item in enumerate(trend_items):
            path = self.cache_dir / f"{slugify(topic)}-trend-{index}.png"
            img = Image.new("RGB", size, color=(11, 12, 18))
            draw = ImageDraw.Draw(img)
            top = (24 + index * 12, 64 + index * 10, 112 + index * 18)
            bottom = (24, 24, 38)
            for y in range(size[1]):
                mix = y / max(1, size[1] - 1)
                r = int(top[0] * (1 - mix) + bottom[0] * mix)
                g = int(top[1] * (1 - mix) + bottom[1] * mix)
                b = int(top[2] * (1 - mix) + bottom[2] * mix)
                draw.line((0, y, size[0], y), fill=(r, g, b))

            draw.rounded_rectangle([24, 40, size[0] - 24, size[1] - 40], radius=40, outline=(255, 255, 255), width=3)
            draw.rounded_rectangle([56, 88, size[0] - 56, 176], radius=24, fill=(255, 92, 92))
            title = str(item.get("title") or topic)[:40]
            desc = str(item.get("description") or item.get("source") or "Trend signal")[:120]
            try:
                title_font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", size=54)
                desc_font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", size=32)
            except Exception:
                title_font = ImageFont.load_default()
                desc_font = ImageFont.load_default()
            title_box = draw.textbbox((0, 0), title, font=title_font)
            title_x = (size[0] - (title_box[2] - title_box[0])) // 2
            draw.text((title_x, 102), title, fill="white", font=title_font, stroke_width=3, stroke_fill="black")
            draw.multiline_text((72, size[1] - 240), desc, fill=(240, 242, 248), font=desc_font, spacing=8)
            img.save(path)
            paths.append(path)
        return paths

    def download_from_pexels(self, query: str, count: int = 3) -> list[Path]:
        if not self.config.pexels_api_key:
            return []
        url = "https://api.pexels.com/videos/search"
        headers = {"Authorization": self.config.pexels_api_key}
        params = {"query": query, "per_page": count, "orientation": "portrait"}
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json().get("videos", [])
            clips: list[Path] = []
            for video in data[:count]:
                files = video.get("video_files", [])
                if not files:
                    continue
                file_url = files[0].get("link")
                if not file_url:
                    continue
                clip_bytes = requests.get(file_url, timeout=60).content
                path = self.cache_dir / f"pexels-{slugify(query)}-{len(clips)}.mp4"
                path.write_bytes(clip_bytes)
                clips.append(path)
            return clips
        except Exception as exc:
            if self.logger:
                self.logger.warning("Pexels fetch failed: %s", exc)
            return []

    def download_from_pixabay(self, query: str, count: int = 3) -> list[Path]:
        if not self.config.pixabay_api_key:
            return []
        url = "https://pixabay.com/api/videos/"
        params = {"key": self.config.pixabay_api_key, "q": query, "per_page": count}
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json().get("hits", [])
            clips: list[Path] = []
            for item in data[:count]:
                videos = item.get("videos", {})
                file_url = (videos.get("large") or videos.get("medium") or videos.get("small") or {}).get("url")
                if not file_url:
                    continue
                clip_bytes = requests.get(file_url, timeout=60).content
                path = self.cache_dir / f"pixabay-{slugify(query)}-{len(clips)}.mp4"
                path.write_bytes(clip_bytes)
                clips.append(path)
            return clips
        except Exception as exc:
            if self.logger:
                self.logger.warning("Pixabay fetch failed: %s", exc)
            return []
