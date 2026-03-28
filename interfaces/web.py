from __future__ import annotations

from flask import Flask, jsonify, request

from application.pipeline_service import ViralForgePipeline
from posting.readiness import PostingReadinessChecker
from utils.json_io import load_json


def create_app(config) -> Flask:
    app = Flask(__name__)
    pipeline = ViralForgePipeline(config)

    @app.get("/")
    def index():
        return (
            "<!doctype html>"
            "<html><head><title>ViralForge AI</title>"
            "<style>body{font-family:Arial,sans-serif;max-width:900px;margin:40px auto;padding:0 20px;}"
            "button{padding:12px 18px;border:0;border-radius:10px;background:#111827;color:#fff;font-size:15px;cursor:pointer;}"
            "code,pre{background:#f3f4f6;padding:12px;border-radius:10px;display:block;overflow:auto;}"
            ".card{border:1px solid #e5e7eb;border-radius:16px;padding:18px;margin:16px 0;box-shadow:0 1px 2px rgba(0,0,0,.04);}"
            "</style></head><body>"
            "<h1>ViralForge AI</h1>"
            "<div class='card'><p>Local dashboard is running.</p><p>Use <code>/api/status</code> for a snapshot.</p></div>"
            "<div class='card'><h2>Manual Self-Post</h2>"
            "<form method='post' action='/api/self-post-packages'>"
            "<label>Topic <input name='topic' value='AI productivity hacks' style='width:320px;padding:8px;margin-left:8px;'></label>"
            "<button type='submit' style='margin-left:12px;'>Generate Bundles</button>"
            "</form>"
            "<p>The button prepares manual self-post bundles without live publishing.</p>"
            "</div>"
            "</body></html>"
        )

    @app.get("/api/status")
    def status():
        return jsonify(
            {
                "project": "ViralForge AI",
                "memory": pipeline.memory.snapshot(),
                "analytics": pipeline.analytics_agent.engine.summarize(),
                "readiness": PostingReadinessChecker(config).report(),
                "ai_recommendation": pipeline.router.recommended_provider(),
                "ai_connectivity": pipeline.router.health_report(),
                "last_run": load_json(config.data_dir / "reports" / "last_run.json", default={}),
            }
        )

    @app.get("/api/queue")
    def queue():
        items = pipeline.post_agent.poster.list_outbox(limit=50)
        return jsonify({"items": items, "count": len(items)})

    @app.post("/api/run")
    def run_pipeline():
        payload = request.get_json(silent=True) or {}
        topic = payload.get("topic") or "AI productivity hacks"
        result = pipeline.run_once(topic=topic)
        return jsonify(result)

    @app.post("/api/self-post-packages")
    def self_post_packages():
        payload = request.get_json(silent=True) or {}
        topic = payload.get("topic") or request.form.get("topic") or "AI productivity hacks"
        result = pipeline.run_manual_self_post(topic=topic)
        bundles = pipeline.post_agent.poster.list_manual_bundles(limit=10)
        return jsonify({"topic": topic, "result": result, "bundles": bundles, "count": len(bundles)})

    @app.get("/api/self-post-packages")
    def self_post_packages_list():
        bundles = pipeline.post_agent.poster.list_manual_bundles(limit=10)
        return jsonify({"bundles": bundles, "count": len(bundles)})

    return app
