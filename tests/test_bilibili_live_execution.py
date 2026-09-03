from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tools.bilibili_live import execution
from tools.bilibili_live.contracts import (
    LiveBlockedError,
    LiveFailedError,
    LiveInconclusiveError,
)


BVIDS = tuple(f"BV1TEST0000{index}" for index in range(1, 9))


def _preview() -> dict[str, Any]:
    return {
        "quality": {
            "parts": [
                {
                    "available": [
                        {
                            "dfn": "1080P",
                            "height": 1080,
                            "bandwidth_kbps": 4000,
                            "size_text": "~500 MB",
                        },
                        {
                            "dfn": "360P",
                            "height": 360,
                            "bandwidth_kbps": 300,
                            "size_text": "~10 MB",
                        },
                    ]
                }
            ]
        }
    }


def _items() -> list[dict[str, Any]]:
    return [
        {
            "bvid": bvid,
            "url": f"https://www.bilibili.com/video/{bvid}",
            "duration_seconds": 60,
        }
        for bvid in BVIDS
    ]


class FakeApi:
    def __init__(self) -> None:
        self.prepared: list[dict[str, Any]] = []
        self.cancelled: list[str] = []
        self._tasks: list[dict[str, Any]] = []

    def preview(self, _item: dict[str, Any]) -> dict[str, Any]:
        return _preview()

    def submit_selection(self, items: list[dict[str, Any]]) -> list[str]:
        self.prepared = [dict(item) for item in items]
        self._tasks = [
            {
                "id": f"task-{index}",
                "bvid": item["bvid"],
                "status": "success",
                "selected_quality": item["preferred_quality"],
            }
            for index, item in enumerate(items)
        ]
        return [str(item["id"]) for item in self._tasks]

    def tasks(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._tasks]

    def cancel_tasks(self, task_ids: list[str]) -> None:
        self.cancelled.extend(task_ids)
        for item in self._tasks:
            if item["id"] in task_ids:
                item["status"] = "cancelled"

    def library_item_for_bvid(self, bvid: str) -> dict[str, Any] | None:
        return {"id": "media-1", "bvid": bvid}

    def get(self, _path: str) -> dict[str, Any]:
        return {"ok": True, "data": {"files": [{"name": "video.mp4"}]}}


def test_download_preflight_selects_quality_within_fair_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeApi()
    monkeypatch.setattr(execution, "run_size_bytes", lambda *_args: 0)

    result = execution.execute_bounded_download(
        api=api,  # type: ignore[arg-type]
        run_root=tmp_path,
        workspace_root=tmp_path / "workspace",
        items=_items(),
        started_at=time.monotonic(),
    )

    assert api.prepared[0]["preferred_quality"] == "360P"
    assert {item["preferred_quality"] for item in api.prepared} <= {"360P", "1080P"}
    assert result.preferred_quality == "360P"
    assert result.selected_quality == "360P"
    assert result.predicted_size_bytes * 2 < (
        execution.MAX_RUN_GROWTH_BYTES - execution._DOWNLOAD_BUDGET_RESERVE_BYTES
    )


def test_growth_limit_is_checked_before_terminal_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeApi()
    calls = 0

    def size(*_args: Any) -> int:
        nonlocal calls
        calls += 1
        return 0 if calls <= 9 else execution.MAX_RUN_GROWTH_BYTES

    original_submit = api.submit_selection

    def submit(items: list[dict[str, Any]]) -> list[str]:
        task_ids = original_submit(items)
        for task in api._tasks[1:]:
            task["status"] = "running"
        return task_ids

    api.submit_selection = submit  # type: ignore[method-assign]
    monkeypatch.setattr(execution, "run_size_bytes", size)

    result = execution.execute_bounded_download(
        api=api,  # type: ignore[arg-type]
        run_root=tmp_path,
        workspace_root=tmp_path / "workspace",
        items=_items(),
        started_at=time.monotonic(),
    )

    assert result.stop_reason == "growth_limit"
    assert result.completed_count == 1
    assert result.cancelled_count == 7
    assert len(api.cancelled) == 7


def test_download_rejects_non_fixed_selection_before_preview(tmp_path: Path) -> None:
    api = FakeApi()
    with pytest.raises(LiveFailedError, match="恰好"):
        execution.execute_bounded_download(
            api=api,  # type: ignore[arg-type]
            run_root=tmp_path,
            workspace_root=tmp_path / "workspace",
            items=_items()[:7],
            started_at=time.monotonic(),
        )
    assert api.prepared == []


def test_download_blocks_before_preview_when_free_space_is_too_low(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeApi()
    monkeypatch.setattr(
        execution.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=execution.MIN_DOWNLOAD_FREE_BYTES - 1),
    )
    with pytest.raises(LiveBlockedError, match="5 GiB"):
        execution.execute_bounded_download(
            api=api,  # type: ignore[arg-type]
            run_root=tmp_path,
            workspace_root=tmp_path / "workspace",
            items=_items(),
            started_at=0,
        )


def test_download_stops_before_submit_when_eight_item_estimate_exceeds_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeApi()
    oversized = _preview()
    for track in oversized["quality"]["parts"][0]["available"]:
        track["size_text"] = "~150 MB"
    api.preview = lambda _item: oversized  # type: ignore[method-assign]
    monkeypatch.setattr(execution, "run_size_bytes", lambda *_args: 0)

    with pytest.raises(LiveInconclusiveError, match="预估总量"):
        execution.execute_bounded_download(
            api=api,  # type: ignore[arg-type]
            run_root=tmp_path,
            workspace_root=tmp_path / "workspace",
            items=_items(),
            started_at=time.monotonic(),
        )

    assert api.prepared == []


def test_download_reports_terminal_counts_before_raising_product_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeApi()
    updates: list[dict[str, int]] = []
    original_submit = api.submit_selection

    def submit(items: list[dict[str, Any]]) -> list[str]:
        task_ids = original_submit(items)
        api._tasks[-1]["status"] = "failed"
        return task_ids

    api.submit_selection = submit  # type: ignore[method-assign]
    monkeypatch.setattr(execution, "run_size_bytes", lambda *_args: 0)

    with pytest.raises(LiveFailedError, match="下载失败"):
        execution.execute_bounded_download(
            api=api,  # type: ignore[arg-type]
            run_root=tmp_path,
            workspace_root=tmp_path / "workspace",
            items=_items(),
            started_at=time.monotonic(),
            progress_callback=lambda values: updates.append(dict(values)),
        )

    assert updates[0]["predicted_size_bytes"] > 0
    assert updates[-1] == {
        "completed_count": 7,
        "failed_count": 1,
        "cancelled_count": 0,
    }


def test_time_limit_cancels_owned_batch_after_one_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeApi()
    original_submit = api.submit_selection

    def submit(items: list[dict[str, Any]]) -> list[str]:
        task_ids = original_submit(items)
        for task in api._tasks[1:]:
            task["status"] = "running"
        return task_ids

    clock_calls = 0

    def clock() -> float:
        nonlocal clock_calls
        clock_calls += 1
        return 0 if clock_calls <= 8 else 15 * 60

    api.submit_selection = submit  # type: ignore[method-assign]
    monkeypatch.setattr(execution, "run_size_bytes", lambda *_args: 0)
    monkeypatch.setattr(execution.time, "monotonic", clock)

    result = execution.execute_bounded_download(
        api=api,  # type: ignore[arg-type]
        run_root=tmp_path,
        workspace_root=tmp_path / "workspace",
        items=_items(),
        started_at=0,
    )

    assert result.stop_reason == "time_limit"
    assert result.completed_count == 1
    assert result.cancelled_count == 7
