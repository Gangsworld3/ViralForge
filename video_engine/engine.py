from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from moviepy import AudioFileClip, CompositeAudioClip, ImageClip, VideoClip, VideoFileClip, concatenate_videoclips

from subtitles.subtitles import SubtitleRenderer, build_word_timings, choose_position_for_faces, write_srt
from utils.text import split_sentences, split_words, slugify
from video_engine.assets import AssetManager
from video_engine.ffmpeg_generator import FFmpegVideoGenerator


class VideoEngine:
    def __init__(self, config, memory, logger=None):
        self.config = config
        self.memory = memory
        self.logger = logger
        self.assets = AssetManager(config, logger=logger)
        self.ffmpeg = FFmpegVideoGenerator(config, self.assets, logger=logger)

    async def _generate_voice_async(self, text: str, voice: str, path: Path) -> None:
        try:
            import edge_tts
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(f"edge-tts unavailable: {exc}") from exc
        communicate = edge_tts.Communicate(text=text, voice=voice)
        await communicate.save(str(path))

    def _generate_voiceover(self, text: str, path: Path) -> Path | None:
        try:
            try:
                asyncio.get_running_loop()
                error_holder: list[Exception] = []

                def _worker() -> None:
                    try:
                        asyncio.run(self._generate_voice_async(text, self.config.video_voice, path))
                    except Exception as exc:  # pragma: no cover - handled in caller
                        error_holder.append(exc)

                thread = threading.Thread(target=_worker, daemon=True)
                thread.start()
                thread.join()
                if error_holder:
                    raise error_holder[0]
            except RuntimeError:
                asyncio.run(self._generate_voice_async(text, self.config.video_voice, path))
            return path
        except Exception as exc:
            if self.logger:
                self.logger.warning("Voice generation failed: %s", exc)
            return None

    def _make_scene_clips(self, script: str, duration: float, trend_items: list[dict[str, Any]] | None = None, plan: dict[str, Any] | None = None):
        size = (self.config.video_width, self.config.video_height)
        first_line = script.splitlines()[0] if script.splitlines() else script[:60]
        clips = []
        trend_items = trend_items or []
        if self.config.smoke_test:
            stock_paths = []
        else:
            trend_queries = [item.get("title", "") for item in trend_items[:3] if item.get("title")]
            stock_paths = []
            for query in trend_queries or [first_line[:80]]:
                stock_paths = self.assets.download_from_pexels(query[:80], count=2) or self.assets.download_from_pixabay(query[:80], count=2)
                if stock_paths:
                    break
        if stock_paths:
            scene_duration = max(2.5, duration / max(1, len(stock_paths)))
            for video_path in stock_paths:
                try:
                    clip = VideoFileClip(str(video_path)).resized(new_size=size)
                    clip = clip.subclipped(0, min(scene_duration, clip.duration or scene_duration))
                    clips.append(clip)
                except Exception as exc:
                    if self.logger:
                        self.logger.warning("Stock video clip failed: %s", exc)
            if clips:
                return clips
        story_images = self.assets.generate_trend_story_images(first_line[:60], trend_items[:4], size, plan=plan)
        if not story_images:
            story_images = self.assets.generate_story_images(first_line[:60], 4, size)
        scene_duration = max(1.8, duration / max(1, len(story_images)))
        for image_path in story_images:
            clip = ImageClip(str(image_path)).with_duration(scene_duration).resized(new_size=size)
            clips.append(clip)
        return clips

    def _music_track(self, duration: float):
        music_dir = self.config.data_dir / "assets"
        for candidate in music_dir.glob("*.mp3"):
            try:
                return AudioFileClip(str(candidate)).subclipped(0, duration)
            except Exception:
                continue
        return None

    def _build_moviepy_video(
        self,
        topic: str,
        script: str,
        output_name: str | None = None,
        trend_items: list[dict[str, Any]] | None = None,
        plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        plan = plan or {}
        output_name = output_name or f"video_{slugify(topic)}.mp4"
        out_path = self.config.output_dir / output_name
        srt_path = out_path.with_suffix(".srt")
        voice_path = out_path.with_suffix(".mp3")

        plain_text = script.replace("\n", " ").strip()
        words = split_words(plain_text)
        target_seconds = max(12.0, float(getattr(self.config, "video_target_duration_seconds", 60)))
        estimated_duration = max(target_seconds, len(words) * (60.0 / max(1, self.config.video_speech_wpm)))
        if self.config.smoke_test:
            estimated_duration = min(estimated_duration, 4.0)

        voice_file = None if self.config.smoke_test else self._generate_voiceover(plain_text, voice_path)
        audio_clip = None
        if voice_file and voice_file.exists():
            audio_clip = AudioFileClip(str(voice_file))
            duration = max(estimated_duration, audio_clip.duration or estimated_duration)
        else:
            duration = estimated_duration

        scene_clips = self._make_scene_clips(script, duration, trend_items=trend_items, plan=plan)
        base = concatenate_videoclips(scene_clips, method="compose")
        base = base.with_duration(duration).resized(new_size=(self.config.video_width, self.config.video_height))

        subtitle_entries = build_word_timings(plain_text, duration, speech_wpm=self.config.video_speech_wpm)
        write_srt(subtitle_entries, srt_path)

        position = choose_position_for_faces(None, self.config.video_height)
        renderer = SubtitleRenderer(
            (self.config.video_width, self.config.video_height),
            style={
                "preset": plan.get("subtitle_preset", "capcut_pop"),
                "position": position,
                "context_window": 5,
                "motion_amp": {"low": 14, "medium": 22, "high": 30}.get(str(plan.get("motion", "")).strip().lower(), 22),
            },
        )

        def make_frame(t: float):
            frame = base.get_frame(t)
            return renderer.render(frame, t, subtitle_entries)

        rendered = VideoClip(frame_function=make_frame, duration=duration)
        if audio_clip is not None:
            rendered = rendered.with_audio(audio_clip)
        music = self._music_track(duration)
        if music is not None:
            rendered = rendered.with_audio(CompositeAudioClip([clip for clip in [audio_clip, music] if clip is not None]))

        rendered.write_videofile(
            str(out_path),
            fps=self.config.video_fps,
            codec="libx264",
            audio_codec="aac",
            threads=2,
            preset="medium",
            logger=None,
        )

        self.memory.save_memory("video_output", script, {"topic": topic, "output": str(out_path), "duration": duration})
        return {
            "status": "ok",
            "video_path": str(out_path),
            "subtitle_path": str(srt_path),
            "voice_path": str(voice_path),
            "duration": duration,
            "summary": f"Rendered {out_path.name} with subtitles and voiceover.",
        }

    def build_video(
        self,
        topic: str,
        script: str,
        output_name: str | None = None,
        trend_items: list[dict[str, Any]] | None = None,
        plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        plan = plan or {}
        output_name = output_name or f"video_{slugify(topic)}.mp4"
        out_path = self.config.output_dir / output_name
        voice_path = out_path.with_suffix(".mp3")
        plain_text = script.replace("\n", " ").strip()
        smoke_voice_text = " ".join(split_sentences(plain_text)[:2]).strip() or plain_text[:160]
        target_duration = max(12.0, float(getattr(self.config, "video_target_duration_seconds", 60)))

        if self.ffmpeg.available():
            try:
                voice_file = self._generate_voiceover(
                    smoke_voice_text if self.config.smoke_test else plain_text,
                    voice_path,
                )
                music_file = self._music_track(target_duration)
                result = self.ffmpeg.build(
                    topic=topic,
                    script=script,
                    output_path=out_path,
                    voice_path=voice_file,
                    music_path=music_file,
                    trend_items=trend_items,
                    plan=plan,
                )
                if voice_file and voice_file.exists():
                    result["voice_path"] = str(voice_file)
                self.memory.save_memory("video_output", script, {"topic": topic, "output": str(out_path), "backend": "ffmpeg"})
                return result
            except Exception as exc:
                if self.logger:
                    self.logger.warning("FFmpeg video path failed, falling back to MoviePy: %s", exc)

        return self._build_moviepy_video(topic=topic, script=script, output_name=output_name, trend_items=trend_items, plan=plan)
