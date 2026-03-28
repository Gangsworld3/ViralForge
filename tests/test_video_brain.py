from __future__ import annotations

from types import SimpleNamespace
import tempfile
from pathlib import Path
import unittest

from video_engine.brain import VideoBrain


class DummyRouter:
    def generate_text(self, prompt: str, task_type: str = "general") -> str:
        return "{}"


class DummyMemory:
    def save_memory(self, *args, **kwargs) -> None:
        return None


class VideoBrainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SimpleNamespace(
            video_target_duration_seconds=60,
            video_speech_wpm=165,
            data_dir=Path(tempfile.gettempdir()) / "viralforge-tests",
        )
        self.brain = VideoBrain(self.config, DummyRouter(), DummyMemory())

    def test_validate_plan_clamps_and_normalizes(self) -> None:
        plan = self.brain.validate_plan(
            {
                "theme": "unknown",
                "pacing": "slow",
                "subtitle_preset": "bad",
                "motion": "extreme",
                "scene_count": 99,
                "story_beat_count": -1,
                "footer_text": "Watch this now",
                "notes": "bad",
            }
        )
        self.assertEqual(plan["theme"], "editorial")
        self.assertEqual(plan["pacing"], "slow")
        self.assertEqual(plan["subtitle_preset"], "clean_karaoke")
        self.assertEqual(plan["motion"], "medium")
        self.assertEqual(plan["scene_count"], 7)
        self.assertEqual(plan["story_beat_count"], 3)
        self.assertIsInstance(plan["notes"], list)

    def test_score_render_artifact_missing_file(self) -> None:
        report = self.brain.score_render_artifact(Path(tempfile.gettempdir()) / "missing-video.mp4", {})
        self.assertFalse(report["video_exists"])
        self.assertLess(report["score"], 70)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
