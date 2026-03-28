from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class ScheduleState:
    last_run: float = 0.0
    next_run: float = 0.0


class LocalScheduler:
    def __init__(self, interval_hours: float = 24.0):
        self.interval_seconds = max(60.0, interval_hours * 3600.0)
        self.state = ScheduleState()

    def mark_ran(self) -> None:
        now = time.time()
        self.state.last_run = now
        self.state.next_run = now + self.interval_seconds

    def seconds_until_next_run(self) -> float:
        if self.state.next_run <= 0:
            return 0.0
        return max(0.0, self.state.next_run - time.time())

    def sleep_until_next_run(self) -> None:
        delay = self.seconds_until_next_run()
        if delay > 0:
            time.sleep(delay)

    def next_run_datetime(self) -> datetime:
        base = datetime.now(timezone.utc)
        return base + timedelta(seconds=self.seconds_until_next_run())
