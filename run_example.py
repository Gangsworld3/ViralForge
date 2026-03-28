from __future__ import annotations

from interfaces.cli import render_summary, run_once


if __name__ == "__main__":
    result = run_once(topic="AI productivity hacks")
    render_summary(result)
