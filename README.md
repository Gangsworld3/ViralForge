# ViralForge AI

![ViralForge AI Logo](assets/logo.svg)

ViralForge AI is a local-first short-form content automation pipeline. It researches trends, generates scripts, renders vertical videos, prepares or publishes posts, tracks analytics, and stores learning data for future runs.

## What It Does

- collects trend signals from live and fallback sources
- generates short-form scripts with Gemini / OpenRouter routing
- renders vertical videos with voice, subtitles, and FFmpeg
- prepares manual self-post bundles or uses posting adapters where configured
- stores runtime state in SQLite
- tracks analytics and learning signals

## Tech Stack

- Python 3.11+
- SQLite
- FFmpeg
- Flask
- Rich
- ChromaDB
- Edge-TTS
- Playwright
- Requests / BeautifulSoup4

## Installation

### Prerequisites

- Python 3.11+
- `ffmpeg` on `PATH`
- Playwright browser binaries

### Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install
copy .env.example .env
```

Optional editable install:

```bash
pip install -e .
```

## Usage

Run a demo:

```bash
python -m viralforge demo --topic "AI productivity hacks"
```

Run once:

```bash
python -m viralforge run --topic "AI productivity hacks"
```

Run daily:

```bash
python -m viralforge run --topic "AI productivity hacks" --daily
```

Open the web UI:

```bash
python -m viralforge serve
```

Check posting readiness:

```bash
python -m viralforge check-posting --summary-only
```

List manual self-post bundles:

```bash
python -m viralforge self-post-packages
```

## Project Structure

```text
viralforge/
|- agents/         # pipeline stages
|- analytics/      # scoring and analytics
|- application/    # runtime bootstrap and orchestration
|- interfaces/     # CLI and web entrypoints
|- llm_router/     # provider routing
|- memory/         # long-term memory
|- monetization/   # affiliate / sponsorship logic
|- posting/        # posting workflows and adapters
|- research/       # trend collection
|- self_healing/   # failure handling
|- subtitles/      # subtitle timing/rendering
|- utils/          # shared helpers
|- video_engine/   # planning and rendering
|- tests/          # regression tests
`- assets/         # static assets
```

## Configuration

Main config sources:

1. environment variables
2. optional JSON config via `--config`
3. `.env`

Key variables:

```env
GEMINI_API_KEY=
OPENROUTER_API_KEY=
OPENROUTER_API_KEY_2=

ENABLE_BROWSER_AUTOMATION=true
POSTING_AUTO_PUBLISH=false
POSTING_SELF_MODE=api
AUTO_PATCH_ERRORS=true

YOUTUBE_ACCESS_TOKEN=
YOUTUBE_REFRESH_TOKEN=
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=

META_ACCESS_TOKEN=
META_PAGE_ID=
META_INSTAGRAM_ACCOUNT_ID=

X_API_KEY=
X_API_SECRET=
X_ACCESS_TOKEN=
X_ACCESS_TOKEN_SECRET=

TIKTOK_ACCESS_TOKEN=
TIKTOK_OPEN_ID=
```

Templates:

- `.env.example`
- `config.sample.json`

## API

The optional Flask UI exposes:

- `GET /api/status`
- `GET /api/queue`
- `POST /api/run`
- `GET /api/self-post-packages`
- `POST /api/self-post-packages`

Start it with:

```bash
python -m viralforge serve
```

## Testing

```bash
python -m compileall .
python -m unittest discover -s tests
```

## Deployment

Recommended local production flow:

1. configure `.env`
2. validate posting readiness
3. run a smoke/demo pass
4. schedule the `run` command
5. monitor:
   - `data/state.db`
   - `data/reports/last_run.json`
   - `logs/`
   - `output/`

Useful DB commands:

```bash
python -m viralforge state-db --summary
python -m viralforge state-db --integrity-check
python -m viralforge state-db --backup
python -m viralforge state-db --export-json
python -m viralforge state-db --restore data/state.export.json
python -m viralforge state-db --vacuum
```

## Security Notes

- do not commit `.env`, `data/`, `logs/`, `output/`, or DB backups
- treat all API keys and OAuth tokens as secrets
- use browser automation only with accounts you control
- review generated content before enabling live auto-publish

## Performance Notes

- runtime state is SQLite-backed
- FFmpeg is the preferred production render path
- large renders are CPU- and disk-heavy
- use `SMOKE_TEST=true` for fast validation runs

## Contributing

- keep changes small and testable
- preserve the layered structure
- update tests for behavior changes
- keep docs and config templates in sync

## License

MIT
