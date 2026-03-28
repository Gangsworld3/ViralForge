# Changelog

All notable changes to this project are documented here.

## [1.0.0] - 2026-03-28

### Added

- SQLite-backed runtime state for memory, analytics, posting queues, retries, and account profiles
- State database operations for summary, integrity checks, backups, export, restore, and vacuum
- Local release metadata including project packaging and versioned release notes
- Regression coverage for config loading, package exports, posting flows, SQLite state, JSON I/O, and video-brain validation

### Changed

- Standardized the package entrypoint so `python -m viralforge` works consistently
- Simplified and tightened configuration loading and publish-facing documentation
- Hardened posting readiness checks and fallback behavior
- Improved video planning validation and render-path stability

### Fixed

- SQLite connection lifecycle issues that could leave the database locked
- Invalid LLM-shaped video-plan notes crashing the video brain
- Packaging and entrypoint inconsistencies across CLI and example scripts
