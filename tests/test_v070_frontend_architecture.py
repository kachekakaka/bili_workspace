from __future__ import annotations

from pathlib import Path

from tests._v070_frontend_architecture_original import *  # noqa: F401,F403

ROOT = Path(__file__).resolve().parent.parent


def test_task_stream_and_route_generation_contracts_remain_single() -> None:
    stream = (ROOT / "web" / "assets" / "app" / "core" / "task-stream.mjs").read_text(
        encoding="utf-8"
    )
    router = (ROOT / "web" / "assets" / "app" / "core" / "router.mjs").read_text(
        encoding="utf-8"
    )
    tasks = (
        ROOT / "web" / "assets" / "app" / "pages" / "tasks-impl.mjs"
    ).read_text(encoding="utf-8")
    task_route = (
        ROOT / "web" / "assets" / "app" / "pages" / "tasks.mjs"
    ).read_text(encoding="utf-8")
    dashboard = (
        ROOT / "web" / "assets" / "app" / "pages" / "dashboard.mjs"
    ).read_text(encoding="utf-8")
    assert "url = '/api/events'" in stream
    assert stream.count("new EventSourceImpl(url)") == 1
    assert "createGenerationGate" in router
    assert "controller.abort()" in router
    assert "context.taskStream.start()" in tasks
    assert "context.taskStream.subscribe(" in tasks
    assert "context.taskStream.start()" in dashboard
    assert "context.taskStream.subscribe(" in dashboard
    assert "bili-v070-library-query" in tasks
    assert "bili-v070-task-owner" in task_route
