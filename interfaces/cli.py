from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from application.bootstrap import build_runtime
from config import load_config
from posting.readiness import PostingReadinessChecker
from utils.fs import ensure_project_dirs
from utils.json_io import save_json
from utils.media_host import MediaHost, MediaHostConfig
from utils.scheduler import LocalScheduler
from utils.state_db import StateDbManager
from utils.youtube_oauth import generate_youtube_tokens, upsert_env_file


console = Console()


def _compact_posting_summary(report: dict) -> dict:
    platforms = report.get("platforms", [])
    ready_platforms = report.get("ready_platforms", [])
    blocked_platforms = report.get("blocked_platforms", [])
    missing_keys = sorted({key for item in platforms for key in item.get("missing", [])})
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "all_ready": not blocked_platforms,
        "status_reason": (
            "All platforms are ready for live posting."
            if not blocked_platforms
            else "Some platforms are still missing required credentials or public media access."
        ),
        "ready_platforms": ready_platforms,
        "blocked_platforms": blocked_platforms,
        "missing_keys": missing_keys,
        "counts": {
            "total": len(platforms),
            "ready": len(ready_platforms),
            "blocked": len(blocked_platforms),
            "missing_keys": len(missing_keys),
        },
        "platforms": [
            {
                "platform": item.get("platform", "unknown"),
                "ready": bool(item.get("ready")),
                "status_reason": (
                    "Ready for live posting."
                    if item.get("ready")
                    else f"Blocked: {', '.join(item.get('missing', [])) or 'missing required inputs'}"
                ),
                "missing_keys": list(item.get("missing", [])),
                "missing_count": len(item.get("missing", [])),
                "expected_scopes_count": len(item.get("expected_scopes", [])),
            }
            for item in platforms
        ],
    }


def _env_block_lines(config, report: dict) -> list[str]:
    missing_by_platform: dict[str, set[str]] = {
        item.get("platform", "unknown"): set(item.get("missing", [])) for item in report.get("platforms", [])
    }

    def missing(name: str, platform: str | None = None) -> bool:
        if platform is None:
            return any(name in missing_set for missing_set in missing_by_platform.values())
        return name in missing_by_platform.get(platform, set())

    lines: list[str] = []

    def section(title: str, fields: list[tuple[str, str, bool]]) -> None:
        lines.append(f"# {title}")
        for key, value, is_missing in fields:
            if is_missing:
                lines.append(f"# MISSING: {key}")
                lines.append(f"{key}=")
                hint = {
                    "YOUTUBE_ACCESS_TOKEN": "Used for direct YouTube uploads; can be refreshed from the client bundle.",
                    "YOUTUBE_REFRESH_TOKEN": "Used with the client id/secret to mint a new YouTube access token.",
                    "YOUTUBE_CLIENT_ID": "Part of the Google OAuth bundle required for YouTube upload refresh.",
                    "YOUTUBE_CLIENT_SECRET": "Part of the Google OAuth bundle required for YouTube upload refresh.",
                    "X_API_KEY": "Used with the X user OAuth flow for posting tweets and uploading media.",
                    "X_API_SECRET": "Used with the X user OAuth flow for signing requests.",
                    "X_ACCESS_TOKEN": "User-context access token for X posting.",
                    "X_ACCESS_TOKEN_SECRET": "User-context secret token for X posting.",
                    "META_ACCESS_TOKEN": "Used for Meta Graph API Page and Instagram publishing.",
                    "META_PAGE_ID": "Required for Facebook Page video uploads.",
                    "META_APP_ID": "Used to introspect Meta token scopes.",
                    "META_APP_SECRET": "Used to introspect Meta token scopes.",
                    "META_INSTAGRAM_ACCOUNT_ID": "Required for Instagram Graph API publishing.",
                    "INSTAGRAM_MEDIA_URL_BASE": "Needed so Instagram can fetch the video from a public URL.",
                    "MEDIA_HOST_BASE_URL": "Fallback public URL for hosted media if you use the free tunnel.",
                    "TIKTOK_ACCESS_TOKEN": "Used by the TikTok Content Posting API upload flow.",
                    "TIKTOK_OPEN_ID": "Identifies the authorized TikTok user for publishing.",
                }.get(key, "This value is required for live posting.")
                lines.append(f"# WHY: {hint}")
            else:
                lines.append(f"{key}={value}")
        lines.append("")

    section(
        "YouTube",
        [
            ("YOUTUBE_ACCESS_TOKEN", config.youtube_access_token, missing("youtube_access_token", "youtube")),
            ("YOUTUBE_REFRESH_TOKEN", config.youtube_refresh_token, missing("youtube_access_token", "youtube")),
            ("YOUTUBE_CLIENT_ID", config.youtube_client_id, missing("youtube_access_token", "youtube")),
            ("YOUTUBE_CLIENT_SECRET", config.youtube_client_secret, missing("youtube_access_token", "youtube")),
            ("YOUTUBE_PRIVACY_STATUS", getattr(config, "youtube_privacy_status", "unlisted"), False),
        ],
    )
    lines.append("# Uses Google OAuth scopes for direct video upload.")
    lines.append("")
    section(
        "X",
        [
            ("X_API_KEY", config.x_api_key, missing("x_api_key", "x")),
            ("X_API_SECRET", config.x_api_secret, missing("x_api_key", "x")),
            ("X_ACCESS_TOKEN", config.x_access_token, missing("x_access_token", "x")),
            ("X_ACCESS_TOKEN_SECRET", config.x_access_token_secret, missing("x_access_token_secret", "x")),
        ],
    )
    lines.append("# Uses user-context OAuth for media upload and tweet creation.")
    lines.append("")
    section(
        "Meta / Facebook Page",
        [
            ("META_ACCESS_TOKEN", config.meta_access_token, missing("meta_access_token", "meta") or missing("meta_access_token", "instagram")),
            ("META_PAGE_ID", config.meta_page_id, missing("meta_page_id", "meta")),
            ("META_APP_ID", config.meta_app_id, missing("meta_access_token", "meta") or missing("meta_access_token", "instagram")),
            ("META_APP_SECRET", config.meta_app_secret, missing("meta_access_token", "meta") or missing("meta_access_token", "instagram")),
            ("META_GRAPH_VERSION", getattr(config, "meta_graph_version", "v20.0"), False),
        ],
    )
    lines.append("# Needed for Facebook Page publishing and Instagram Graph API access.")
    lines.append("")
    section(
        "Instagram",
        [
            ("META_INSTAGRAM_ACCOUNT_ID", config.meta_instagram_account_id, missing("meta_instagram_account_id", "instagram")),
            ("INSTAGRAM_MEDIA_URL_BASE", config.instagram_media_url_base or config.media_host_base_url, missing("meta_instagram_account_id", "instagram")),
            ("MEDIA_HOST_BASE_URL", config.media_host_base_url, missing("meta_instagram_account_id", "instagram")),
        ],
    )
    lines.append("# Needs a public media URL for the video container publish step.")
    lines.append("")
    section(
        "TikTok",
        [
            ("TIKTOK_ACCESS_TOKEN", config.tiktok_access_token, missing("tiktok_access_token", "tiktok")),
            ("TIKTOK_OPEN_ID", config.tiktok_open_id, missing("tiktok_open_id", "tiktok")),
        ],
    )
    lines.append("# Uses TikTok Content Posting API upload and publish flow.")
    lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def render_summary(result: dict) -> None:
    table = Table(title="ViralForge AI Run Summary", show_lines=True)
    table.add_column("Stage", style="bold cyan")
    table.add_column("Status", style="bold green")
    table.add_column("Details", overflow="fold")
    for stage in ["research", "script", "video", "optimize", "post", "analytics", "monetize"]:
        payload = result.get(stage, {})
        status = payload.get("status", "ok")
        details = payload.get("summary") or payload.get("message") or str(payload)[:220]
        table.add_row(stage.title(), status, details)
    console.print(table)
    console.print(Panel.fit(f"Output video: {result.get('video_path', 'n/a')}", title="Artifacts"))
    if result.get("video_public_url"):
        console.print(Panel.fit(str(result["video_public_url"]), title="Public Media URL"))
    readiness = result.get("readiness")
    if readiness:
        lines = []
        for item in readiness.get("platforms", []):
            status = "ready" if item.get("ready") else "blocked"
            missing = ", ".join(item.get("missing", [])) or "none"
            lines.append(f"{item.get('platform', 'unknown')}: {status} | missing: {missing}")
        console.print(Panel.fit("\n".join(lines), title="Posting Readiness"))


def render_retry_summary(results: list[dict]) -> None:
    table = Table(title="Retry Queue Results", show_lines=True)
    table.add_column("Platform", style="bold cyan")
    table.add_column("Status", style="bold green")
    table.add_column("Attempts", overflow="fold")
    table.add_column("Next Attempt", overflow="fold")
    table.add_column("Error / Message", overflow="fold")
    for item in results:
        table.add_row(
            item.get("platform", "unknown"),
            item.get("status", "n/a"),
            f"{item.get('attempts', 0)}/{item.get('max_attempts', 0)}",
            item.get("next_attempt_at", "n/a"),
            item.get("last_error") or item.get("message") or item.get("status_reason") or "n/a",
        )
    console.print(table)


def render_manual_self_post_bundles(poster, limit: int = 5) -> None:
    bundles = poster.list_manual_bundles(limit=limit)
    if not bundles:
        console.print(Panel.fit("No manual self-post bundles found.", title="Manual Self-Post Bundles"))
        return
    table = Table(title="Manual Self-Post Bundles", show_lines=True)
    table.add_column("Platform", style="bold cyan")
    table.add_column("Status", overflow="fold")
    table.add_column("Title", overflow="fold")
    table.add_column("File", overflow="fold")
    table.add_column("Media URL", overflow="fold")
    for bundle in bundles:
        table.add_row(
            str(bundle.get("platform", "unknown")),
            str(bundle.get("status", "unknown")),
            str(bundle.get("title", "")) or "n/a",
            str(bundle.get("file", "")),
            str(bundle.get("media_url", "")) or "n/a",
        )
    console.print(table)


def render_ai_connectivity(router) -> None:
    table = Table(title="AI Connectivity", show_lines=True)
    table.add_column("Provider", style="bold cyan")
    table.add_column("Model", overflow="fold")
    table.add_column("Status", style="bold green")
    table.add_column("Message", overflow="fold")
    for item in router.health_report():
        status = "connected" if item.get("connected") else item.get("status", "unknown")
        table.add_row(
            str(item.get("provider", "unknown")),
            str(item.get("model", "n/a")),
            status,
            str(item.get("message", "")) or "n/a",
        )
    console.print(table)


def render_ai_recommendation(router) -> None:
    recommendation = router.recommended_provider()
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"Best provider: {recommendation.get('provider', 'n/a')}",
                    f"Model: {recommendation.get('model', 'n/a')}",
                    f"Status: {recommendation.get('status', 'n/a')}",
                    f"Message: {recommendation.get('message', 'n/a')}",
                ]
            ),
            title="AI Recommendation",
        )
    )


def render_state_db_summary(summary: dict) -> None:
    lines = [
        f"Path: {summary.get('db_path', 'n/a')}",
        f"Exists: {'yes' if summary.get('exists') else 'no'}",
        f"Size: {summary.get('size_bytes', 0)} bytes",
    ]
    console.print(Panel.fit("\n".join(lines), title="State DB"))
    table = Table(title="State DB Tables", show_lines=True)
    table.add_column("Table", style="bold cyan")
    table.add_column("Rows", style="bold green")
    for table_name, row_count in summary.get("tables", {}).items():
        table.add_row(str(table_name), str(row_count))
    console.print(table)


def run_once(topic: str | None, config_path: str | None = None, auto_host: bool | None = None) -> dict:
    runtime = build_runtime(config_path=config_path, auto_host=auto_host)
    return runtime.pipeline.run_once(topic=topic)


def retry_posts(config_path: str | None = None, limit: int = 20) -> list[dict]:
    runtime = build_runtime(config_path=config_path)
    results = runtime.pipeline.post_agent.poster.retry_due_posts(limit=limit)
    render_retry_summary(results)
    console.print(Panel.fit("\n".join([f"Processed: {len(results)}", f"Limit: {limit}"]), title="Retry Summary"))
    return results


def list_self_post_packages(config_path: str | None = None, limit: int = 5) -> list[dict]:
    runtime = build_runtime(config_path=config_path)
    bundles = runtime.pipeline.post_agent.poster.list_manual_bundles(limit=limit)
    render_manual_self_post_bundles(runtime.pipeline.post_agent.poster, limit=limit)
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"Found: {len(bundles)}",
                    f"Limit: {limit}",
                    f"Mode: {getattr(runtime.config, 'posting_self_mode', 'api')}",
                ]
            ),
            title="Self-Post Packages",
        )
    )
    return bundles


def run_loop(topic: str | None, interval_hours: float, config_path: str | None = None, auto_host: bool | None = None) -> None:
    scheduler = LocalScheduler(interval_hours=interval_hours)
    while True:
        result = run_once(topic=topic, config_path=config_path, auto_host=auto_host)
        render_summary(result)
        scheduler.mark_ran()
        sleep_seconds = scheduler.seconds_until_next_run()
        console.print(f"[dim]Sleeping for {sleep_seconds / 3600.0:.2f} hours...[/dim]")
        scheduler.sleep_until_next_run()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ViralForge AI")
    parser.add_argument("--config", default=None, help="Optional path to a JSON config file")
    parser.add_argument(
        "--auto-host",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Force or disable public media tunnel startup for Instagram-ready posts",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Run one generation cycle")
    demo.add_argument("--topic", default="AI productivity hacks", help="Primary topic")
    run = sub.add_parser("run", help="Run the full pipeline")
    run.add_argument("--topic", default="AI productivity hacks", help="Primary topic")
    run.add_argument("--daily", action="store_true", help="Loop once per 24 hours")
    run.add_argument("--interval-hours", type=float, default=24.0, help="Loop interval in hours")
    retry = sub.add_parser("retry-posts", help="Process due retries from the posting retry queue")
    retry.add_argument("--limit", type=int, default=20, help="Maximum number of retry records to process")
    self_post = sub.add_parser("self-post-packages", help="List the latest manual self-post bundles")
    self_post.add_argument("--limit", type=int, default=5, help="Maximum number of bundles to display")
    db = sub.add_parser("state-db", help="Inspect and maintain the SQLite runtime state database")
    db.add_argument("--summary", action="store_true", help="Print table counts and file size")
    db.add_argument("--integrity-check", action="store_true", help="Run SQLite integrity_check")
    db.add_argument("--vacuum", action="store_true", help="Vacuum the database in place")
    db.add_argument("--backup", action="store_true", help="Create a timestamped backup copy")
    db.add_argument("--backup-file", default=None, help="Optional explicit backup destination")
    db.add_argument("--export-json", action="store_true", help="Export all SQLite tables to a JSON file")
    db.add_argument("--export-file", default=None, help="Optional explicit JSON export destination")
    db.add_argument("--restore", default=None, help="Restore the database from a previously exported JSON file")
    sub.add_parser("dashboard", help="Print a quick local dashboard snapshot")
    sub.add_parser("serve", help="Start the optional Flask web UI if installed")
    media = sub.add_parser("serve-media", help="Serve generated media files from the output directory")
    media.add_argument("--tunnel", action="store_true", help="Use a free Cloudflare quick tunnel to expose the host publicly")
    yt = sub.add_parser("generate-youtube-token", help="Run the local YouTube OAuth flow and capture refresh tokens")
    yt.add_argument("--client-id", default=None, help="Google OAuth client ID")
    yt.add_argument("--client-secret", default=None, help="Google OAuth client secret")
    yt.add_argument("--redirect-uri", default="http://localhost:8080/", help="Loopback redirect URI registered in Google Cloud")
    yt.add_argument("--scope", default="https://www.googleapis.com/auth/youtube.upload", help="OAuth scope to request")
    yt.add_argument("--env-file", default=None, help="Optional .env file to update with the returned tokens")
    yt.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically")
    yt.add_argument("--use-client-secret", action="store_true", help="Include the client secret in the token exchange instead of using PKCE-only")
    yt.add_argument("--login-hint", default=None, help="Optional Google account email to bias the consent screen toward the right account")
    check = sub.add_parser("check-posting", help="Print posting credential readiness without running the pipeline")
    check.add_argument("--fix-env", action="store_true", help="Print a copy-paste .env block with missing values highlighted")
    check.add_argument("--fix-env-file", default=None, help="Write the grouped .env block to a file path, defaulting to data/reports/fix-env.txt")
    check.add_argument("--json", action="store_true", help="Print the readiness report as JSON")
    check.add_argument(
        "--json-file",
        nargs="?",
        const=str(Path("data") / "reports" / "check-posting.json"),
        default=None,
        help="Write the readiness report JSON to a file path, defaulting to data/reports/check-posting.json",
    )
    check.add_argument("--summary-only", action="store_true", help="Print only the compact readiness summary instead of the full report or table")
    return parser


def dashboard(config_path: str | None = None) -> None:
    runtime = build_runtime(config_path=config_path)
    console.print(Panel.fit(runtime.pipeline.snapshot(), title="ViralForge Dashboard"))
    render_ai_connectivity(runtime.pipeline.router)
    render_ai_recommendation(runtime.pipeline.router)
    render_manual_self_post_bundles(runtime.pipeline.post_agent.poster, limit=5)


def maintain_state_db(
    config_path: str | None = None,
    *,
    show_summary: bool = False,
    integrity_check: bool = False,
    vacuum: bool = False,
    backup: bool = False,
    backup_file: str | None = None,
    export_json: bool = False,
    export_file: str | None = None,
    restore: str | None = None,
) -> dict[str, object]:
    config = load_config(config_path=config_path)
    ensure_project_dirs(config)
    manager = StateDbManager(config.state_db_path)
    result: dict[str, object] = {}
    if restore:
        restore_path = Path(restore)
        restored = manager.restore_json(restore_path)
        result["restored"] = restored
        console.print(
            Panel.fit(
                "\n".join(f"{table}: {count}" for table, count in restored.items()),
                title=f"State DB Restored From {restore_path}",
            )
        )
    if backup:
        backup_path = manager.backup(Path(backup_file) if backup_file else None)
        result["backup_path"] = str(backup_path)
        console.print(Panel.fit(str(backup_path), title="State DB Backup"))
    if export_json:
        export_path = manager.export_json(Path(export_file) if export_file else None)
        result["export_path"] = str(export_path)
        console.print(Panel.fit(str(export_path), title="State DB JSON Export"))
    if vacuum:
        manager.vacuum()
        result["vacuumed"] = True
        console.print(Panel.fit("Completed", title="State DB Vacuum"))
    if integrity_check:
        integrity = manager.integrity_check()
        result["integrity"] = integrity
        console.print(
            Panel.fit(
                "\n".join(integrity.get("messages", [])) or "No messages",
                title="State DB Integrity",
            )
        )
    if show_summary or not any([integrity_check, vacuum, backup]):
        summary = manager.summary()
        result["summary"] = summary
        render_state_db_summary(summary)
    return result


def serve_web(config_path: str | None = None) -> None:
    runtime = build_runtime(config_path=config_path)
    try:
        from interfaces.web import create_app
    except Exception as exc:
        console.print(f"[red]Web UI unavailable:[/red] {exc}")
        return
    app = create_app(runtime.config)
    app.run(host="127.0.0.1", port=5050, debug=False)


def serve_media(config_path: str | None = None, tunnel: bool = False) -> None:
    runtime = build_runtime(config_path=config_path)
    host = MediaHost(
        runtime.config.output_dir,
        MediaHostConfig(
            host=runtime.config.media_host_host,
            port=runtime.config.media_host_port,
            public_base_url=runtime.config.media_host_base_url,
            state_path=runtime.config.data_dir / "reports" / "media_host.json",
        ),
        logger=runtime.logger,
    )
    public_url = host.run(use_tunnel=tunnel)
    if public_url and not tunnel:
        console.print(Panel.fit(public_url, title="Public Media URL"))


def generate_youtube_token(
    config_path: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    redirect_uri: str = "http://localhost:8080/",
    scope: str = "https://www.googleapis.com/auth/youtube.upload",
    env_file: str | None = None,
    open_browser: bool = True,
    use_client_secret: bool = False,
    login_hint: str | None = None,
) -> dict[str, object]:
    runtime = build_runtime(config_path=config_path)
    client_id = client_id or runtime.config.youtube_client_id
    client_secret = client_secret or runtime.config.youtube_client_secret
    if not client_id:
        raise ValueError("Missing YouTube client_id. Pass it on the command line or set YOUTUBE_CLIENT_ID.")
    if use_client_secret and not client_secret:
        raise ValueError("Missing YouTube client_secret. Pass it on the command line or set YOUTUBE_CLIENT_SECRET, or omit --use-client-secret to use PKCE-only exchange.")
    tokens = generate_youtube_tokens(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=scope,
        open_browser=open_browser,
        use_client_secret=use_client_secret,
        login_hint=login_hint,
    )
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"Redirect URI: {redirect_uri}",
                    f"Token exchange: {'client secret + PKCE' if use_client_secret else 'PKCE only'}",
                    f"Scope: {tokens.get('scope', scope)}",
                    f"Access token expires in: {tokens.get('expires_in', 'n/a')} seconds",
                    f"Refresh token present: {'yes' if tokens.get('refresh_token') else 'no'}",
                ]
            ),
            title="YouTube OAuth",
        )
    )
    if env_file:
        env_path = Path(env_file)
        updates = {"YOUTUBE_ACCESS_TOKEN": str(tokens.get("access_token", ""))}
        if tokens.get("refresh_token"):
            updates["YOUTUBE_REFRESH_TOKEN"] = str(tokens["refresh_token"])
        upsert_env_file(env_path, updates)
        console.print(Panel.fit(str(env_path), title="YouTube Tokens Saved"))
    return tokens


def check_posting(
    config_path: str | None = None,
    fix_env: bool = False,
    fix_env_file: str | None = None,
    json_output: bool = False,
    json_file: str | None = None,
    summary_only: bool = False,
) -> None:
    runtime = build_runtime(config_path=config_path)
    report = PostingReadinessChecker(runtime.config, logger=runtime.logger).report()
    summary = _compact_posting_summary(report)
    if json_file:
        output_path = Path(json_file)
        save_json(output_path, report)
        summary_path = output_path.with_name(f"{output_path.stem}.summary.json")
        save_json(summary_path, summary)
    if json_output:
        console.print_json(data=summary if summary_only else {"report": report, "summary": summary})
        return
    if summary_only:
        lines = [
            f"All ready: {'yes' if summary.get('all_ready') else 'no'}",
            f"Ready platforms: {', '.join(summary.get('ready_platforms', [])) or 'none'}",
            f"Blocked platforms: {', '.join(summary.get('blocked_platforms', [])) or 'none'}",
            f"Missing keys: {', '.join(summary.get('missing_keys', [])) or 'none'}",
            f"Status: {summary.get('status_reason', 'n/a')}",
        ]
        console.print(Panel.fit("\n".join(lines), title="Posting Summary"))
        return
    if fix_env:
        block_text = "\n".join(
            [
                "# ViralForge AI posting env fix block",
                f"# Generated: {datetime.now(timezone.utc).isoformat()}",
                f"# Ready platforms: {', '.join(report.get('ready_platforms', [])) or 'none'}",
                f"# Blocked platforms: {', '.join(report.get('blocked_platforms', [])) or 'none'}",
                "",
                "\n".join(_env_block_lines(runtime.config, report)),
            ]
        )
        console.print(Panel.fit(block_text, title=".env Fix Block"))
        output_path = Path(fix_env_file or (runtime.config.data_dir / "reports" / "fix-env.txt"))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(block_text + "\n", encoding="utf-8")
        console.print(Panel.fit(str(output_path), title="Fix Env Exported"))
    table = Table(title="Posting Readiness Check", show_lines=True)
    table.add_column("Platform", style="bold cyan")
    table.add_column("Status", style="bold green")
    table.add_column("Missing", overflow="fold")
    table.add_column("Expected Scopes", overflow="fold")
    table.add_column("Notes", overflow="fold")
    for item in report.get("platforms", []):
        table.add_row(
            item.get("platform", "unknown"),
            "ready" if item.get("ready") else "blocked",
            ", ".join(item.get("missing", [])) or "none",
            ", ".join(item.get("expected_scopes", [])) or "none",
            "\n".join(item.get("notes", [])) or "none",
        )
    console.print(table)
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"Ready platforms: {', '.join(report.get('ready_platforms', [])) or 'none'}",
                    f"Blocked platforms: {', '.join(report.get('blocked_platforms', [])) or 'none'}",
                ]
            ),
            title="Posting Summary",
        )
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "demo":
        render_summary(run_once(topic=args.topic, config_path=args.config, auto_host=args.auto_host))
    elif args.command == "run":
        if args.daily:
            run_loop(topic=args.topic, interval_hours=24.0, config_path=args.config, auto_host=args.auto_host)
        else:
            render_summary(run_once(topic=args.topic, config_path=args.config, auto_host=args.auto_host))
    elif args.command == "retry-posts":
        retry_posts(config_path=args.config, limit=args.limit)
    elif args.command == "self-post-packages":
        list_self_post_packages(config_path=args.config, limit=args.limit)
    elif args.command == "state-db":
        maintain_state_db(
            config_path=args.config,
            show_summary=args.summary,
            integrity_check=args.integrity_check,
            vacuum=args.vacuum,
            backup=args.backup,
            backup_file=args.backup_file,
            export_json=args.export_json,
            export_file=args.export_file,
            restore=args.restore,
        )
    elif args.command == "dashboard":
        dashboard(config_path=args.config)
    elif args.command == "serve":
        serve_web(config_path=args.config)
    elif args.command == "serve-media":
        serve_media(config_path=args.config, tunnel=args.tunnel)
    elif args.command == "generate-youtube-token":
        tokens = generate_youtube_token(
            config_path=args.config,
            client_id=args.client_id,
            client_secret=args.client_secret,
            redirect_uri=args.redirect_uri,
            scope=args.scope,
            env_file=args.env_file,
            open_browser=not args.no_browser,
            use_client_secret=args.use_client_secret,
            login_hint=args.login_hint,
        )
        console.print_json(
            data={
                "access_token_present": bool(tokens.get("access_token")),
                "refresh_token_present": bool(tokens.get("refresh_token")),
                "scope": tokens.get("scope", args.scope),
                "expires_in": tokens.get("expires_in"),
                "redirect_uri": tokens.get("redirect_uri", args.redirect_uri),
            }
        )
    elif args.command == "check-posting":
        check_posting(
            config_path=args.config,
            fix_env=args.fix_env,
            fix_env_file=args.fix_env_file,
            json_output=args.json,
            json_file=args.json_file,
            summary_only=args.summary_only,
        )
