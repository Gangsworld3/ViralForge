from __future__ import annotations

from types import SimpleNamespace
import unittest

from posting.adapters import BasePostingAdapter, PostingAdapterRouter


class CrashingAdapter(BasePostingAdapter):
    platform = "crash"

    def can_publish(self) -> bool:
        raise RuntimeError("boom")

    def publish(self, record: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("boom")


class PostingRouterTests(unittest.TestCase):
    def test_router_handles_adapter_crash(self) -> None:
        router = PostingAdapterRouter(SimpleNamespace(), logger=None)
        router.adapters["crash"] = CrashingAdapter(SimpleNamespace(), logger=None)
        self.assertFalse(router.can_publish("crash"))
        result = router.publish({"platform": "crash"})
        self.assertEqual(result["status"], "unavailable")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
