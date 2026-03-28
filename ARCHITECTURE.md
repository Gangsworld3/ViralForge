# ViralForge Architecture

## Layered structure

The codebase follows a pragmatic layered design:

- `interfaces/`
  - CLI and Flask transport
  - request parsing, console rendering, and HTTP surface only
- `application/`
  - runtime composition and pipeline orchestration
  - owns dependency wiring and use-case execution
- `agents/`
  - stage-level workflow controllers
  - research, script, optimization, video, posting, analytics, monetization
- domain and infrastructure modules
  - `analytics/`
  - `llm_router/`
  - `memory/`
  - `monetization/`
  - `posting/`
  - `research/`
  - `self_healing/`
  - `subtitles/`
  - `video_engine/`
- `utils/`
  - shared infrastructure helpers

## Dependency direction

Dependencies are intended to flow inward:

- `interfaces -> application`
- `application -> agents/domain/infrastructure`
- `agents -> domain/infrastructure`
- `domain/infrastructure -> utils`

Interface code should not contain business logic.
Domain modules should not import CLI or web transport code.

## Runtime composition

The application starts in one of these entrypoints:

- [`main.py`](C:\Users\hp\Documents\New project\viralforge\main.py)
- [`__main__.py`](C:\Users\hp\Documents\New project\viralforge\__main__.py)
- [`run_example.py`](C:\Users\hp\Documents\New project\viralforge\run_example.py)

Those entrypoints delegate into:

- [`interfaces/cli.py`](C:\Users\hp\Documents\New project\viralforge\interfaces\cli.py)
- [`interfaces/web.py`](C:\Users\hp\Documents\New project\viralforge\interfaces\web.py)
- [`application/bootstrap.py`](C:\Users\hp\Documents\New project\viralforge\application\bootstrap.py)
- [`application/pipeline_service.py`](C:\Users\hp\Documents\New project\viralforge\application\pipeline_service.py)

`build_runtime()` creates:

- `AppConfig`
- project directories
- logger
- `ViralForgePipeline`

## Pipeline flow

The main application pipeline is:

1. research
2. script
3. optimize
4. video
5. post
6. analytics
7. monetize

State is passed through [`PipelineState`](C:\Users\hp\Documents\New project\viralforge\agents\base.py) so stage outputs remain explicit and inspectable.

## Persistence model

Local-first persistence is used throughout the app:

- SQLite-backed memory history and learning records
- SQLite-backed analytics records
- SQLite-backed posting state, retries, and outbox history
- SQLite-backed account profiles
- generated reports and manual posting bundles

Design rules currently enforced:

- local state growth is bounded in critical stores
- posting, analytics, memory, and accounts use transactional SQLite storage
- malformed local state falls back safely instead of crashing the app

## Video subsystem

The video subsystem is split into:

- [`video_engine/engine.py`](C:\Users\hp\Documents\New project\viralforge\video_engine\engine.py)
- [`video_engine/brain.py`](C:\Users\hp\Documents\New project\viralforge\video_engine\brain.py)
- [`video_engine/ffmpeg_generator.py`](C:\Users\hp\Documents\New project\viralforge\video_engine\ffmpeg_generator.py)
- [`video_engine/free_scene.py`](C:\Users\hp\Documents\New project\viralforge\video_engine\free_scene.py)
- [`subtitles/subtitles.py`](C:\Users\hp\Documents\New project\viralforge\subtitles\subtitles.py)

The control path is:

1. build a validated video plan
2. render with FFmpeg
3. score the rendered artifact
4. revise and rerender when quality gates fail

## Posting subsystem

The posting subsystem is split into:

- adapter readiness and live publish logic
- browser-assisted fallback
- queue and retry management
- manual self-post bundle generation

The publish path is intentionally layered so failed direct posting does not crash the pipeline.

## Self-healing rules

The self-healing layer captures failures and repair suggestions, but it does not mutate source code directly.

Current guardrails:

- no direct source rewriting
- patch suggestions are persisted as artifacts
- provider failures degrade to structured results
- retries are scheduled explicitly

## Release standards

The current publish baseline assumes:

- deterministic configuration loading
- bounded local persistence
- safe compatibility shims for legacy entrypoints
- transport-independent application orchestration
- validation and tests before release
