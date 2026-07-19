from __future__ import annotations

import asyncio
import json
import mimetypes
import time
from collections import Counter
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import ConfigDict

from app import __version__
from app.api import (
    _compact_task,
    _decorate_task,
    _parse_download_body,
    _remote,
    _session,
    _state,
    api_preview as legacy_preview,
    get_status as legacy_status,
    err,
    ok,
)
from app.constants import (
    MAX_BATCH_ITEMS,
    MAX_LOG_API_CHARS,
    NORMAL_USER_ACTIVE_TASK_LIMIT,
    SSE_AUTH_HEARTBEAT_SECONDS,
    TERMINAL_STATUSES,
)
from app.enhancement_api import ClearTasksRequest, TaskActionRequest, TaskBatchRequest
from app.media_stream import file_response
from app.models import DownloadRequest, PreviewRequest, RetryRequest
from app.queue import QueueFullError
from app.task_extensions import (
    cancel_task,
    delete_task,
    install_task_extensions,
    pause_task,
    retry_in_place,
)

router = APIRouter(prefix="/api", tags=["task-ownership"])
enhancement_router = APIRouter(
    prefix="/api/enhancements", tags=["task-ownership-enhancements"]
)


class OwnershipDownloadRequest(DownloadRequest):
    # Explicit identity fields and any other legacy client extras are ignored.
    # The owner is always derived from request.state.auth_context.
    model_config = ConfigDict(extra="ignore")


def _auth(request: Request) -> dict[str, Any]:
    context = getattr(request.state, "auth_context", None)
    if context:
        return dict(context)
    session = _session(request) or {}
    return {
        "user_id": str(session.get("user_id") or ""),
        "username": str(session.get("username") or ""),
        "display_name": str(session.get("display_name") or ""),
        "role": str(session.get("role") or "user"),
        "session_id": str(session.get("session_id") or ""),
    }


def _is_admin(auth: dict[str, Any]) -> bool:
    return str(auth.get("role") or "") == "admin"


def _record_for_request(request: Request, task_id: str) -> dict[str, Any] | None:
    auth = _auth(request)
    record = _state(request).nas.task_record(task_id)
    if not record:
        return None
    if not _is_admin(auth) and str(record.get("owner_user_id") or "") != str(
        auth.get("user_id") or ""
    ):
        # Do not reveal that another user's task exists.
        return None
    return record


def _queue_for_record(state, record: dict[str, Any]):
    return state.export_queue if record.get("destination") == "device" else state.queue


def _live_record(
    state, record: dict[str, Any], *, compact: bool = True
) -> dict[str, Any]:
    queue = _queue_for_record(state, record)
    live = queue.get_task(str(record["id"]))
    value = dict(record)
    if live:
        owner = value.get("owner")
        owner_label = value.get("owner_label")
        value.update(live)
        value["owner_user_id"] = record["owner_user_id"]
        if owner:
            value["owner"] = owner
        if owner_label:
            value["owner_label"] = owner_label
    decorated = _decorate_task(state, value, str(value["destination"]))
    return _compact_task(decorated) if compact else decorated


def _summary(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(item.get("status") or "") for item in items)
    return {
        "all": len(items),
        "queued": counts["queued"],
        "running": counts["running"],
        "success": counts["success"],
        "skipped": counts["skipped"],
        "failed": counts["failed"],
        "cancelled": counts["cancelled"],
        "active": counts["queued"] + counts["running"],
    }


def _list_records(
    request: Request,
    *,
    owner_user_id: str = "",
    status: str = "",
    destination: str = "",
    query: str = "",
    sort: str = "created_at",
    direction: str = "desc",
) -> list[dict[str, Any]]:
    auth = _auth(request)
    owner_filter: str | None
    if _is_admin(auth):
        owner_filter = owner_user_id or None
    else:
        owner_filter = str(auth["user_id"])
    state = _state(request)
    records = state.nas.list_task_records(
        owner_user_id=owner_filter,
        status=status,
        destination=destination,
        query=query,
        sort=sort,
        direction=direction,
    )
    return [_live_record(state, item) for item in records]


def _audit_task(request: Request, action: str, task: dict[str, Any]) -> None:
    auth = _auth(request)
    _state(request).nas.audit(
        str(auth.get("user_id") or ""),
        action,
        f"task={task.get('id','')}; destination={task.get('destination','')}",
        _remote(request),
        session_id=str(auth.get("session_id") or "") or None,
        target_user_id=str(task.get("owner_user_id") or "") or None,
    )


@router.get("/status")
def status(request: Request, refresh_login: bool = False):
    auth = _auth(request)
    if _is_admin(auth):
        return legacy_status(request, refresh_login=refresh_login)
    state = _state(request)
    items = _list_records(request)
    return ok(
        {
            "version": __version__,
            "server_mode": state.runtime.server_mode,
            "default_min_height": state.config_store.get().default_min_height,
            "active_tasks": state.export_queue.active_count_for_owner(
                str(auth["user_id"])
            ),
            "task_summary": _summary(items),
        }
    )


@router.post("/preview")
def preview(request: Request, body: PreviewRequest):
    return legacy_preview(request, body)


@router.post("/download")
def create_download(request: Request, body: OwnershipDownloadRequest):
    state = _state(request)
    auth = _auth(request)
    owner_user_id = str(auth["user_id"])
    normal_user = not _is_admin(auth)
    destination = "device" if normal_user else body.destination
    group_id = "" if normal_user else body.group_id
    group_name = "" if normal_user else body.group
    force = False if normal_user else body.force
    try:
        targets, metadata = _parse_download_body(body)
        if destination == "device":
            for target in targets:
                record = state.nas.active_export_for_source(
                    target.key, owner_user_id=owner_user_id
                )
                if record:
                    return err(
                        f"{target.bvid or target.key} 已有尚未下载或过期的设备导出任务"
                        f"（任务 {record.get('task_id', '')}）",
                        409,
                    )
            tasks = state.export_queue.enqueue(
                targets,
                force=True,
                metadata=metadata,
                group="设备导出",
                group_folder="device",
                min_height=body.min_height,
                owner_user_id=owner_user_id,
                owner_active_limit=(
                    NORMAL_USER_ACTIVE_TASK_LIMIT if normal_user else None
                ),
            )
            for task in tasks:
                if task.get("status") in {"queued", "running"}:
                    state.nas.register_export_task(task)
            tasks = [_decorate_task(state, task, "device") for task in tasks]
        else:
            group = state.nas.resolve_group(group_id, group_name)
            tasks = state.queue.enqueue(
                targets,
                force=force,
                metadata=metadata,
                group=group["display_name"],
                group_id=group["id"],
                group_folder=group["folder_key"],
                min_height=body.min_height,
                owner_user_id=owner_user_id,
            )
            tasks = [_decorate_task(state, task, "library") for task in tasks]
    except QueueFullError as exc:
        return err(str(exc), 429, code="active_task_limit")
    except ValueError as exc:
        return err(str(exc))
    for task in tasks:
        task["owner_user_id"] = owner_user_id
        _audit_task(request, "download.enqueue", task)
    return ok(tasks, total=len(tasks), limit=MAX_BATCH_ITEMS)


@router.get("/tasks")
def tasks_list(
    request: Request,
    owner_user_id: str = Query("", max_length=100),
    status: str = Query("", max_length=30),
    destination: str = Query("", max_length=20),
    q: str = Query("", max_length=200),
    sort: str = Query("created_at", max_length=30),
    direction: Literal["asc", "desc"] = "desc",
    group_by_user: bool = False,
):
    if status and status not in {
        "queued",
        "running",
        "success",
        "skipped",
        "failed",
        "cancelled",
    }:
        return err("任务状态筛选无效")
    if destination and destination not in {"library", "device"}:
        return err("任务目标筛选无效")
    items = _list_records(
        request,
        owner_user_id=owner_user_id,
        status=status,
        destination=destination,
        query=q,
        sort=sort,
        direction=direction,
    )
    grouped: list[dict[str, Any]] | None = None
    if group_by_user and _is_admin(_auth(request)):
        by_user: dict[str, dict[str, Any]] = {}
        for item in items:
            owner = str(item.get("owner_user_id") or "")
            group = by_user.setdefault(
                owner,
                {
                    "owner_user_id": owner,
                    "owner": item.get("owner") or {},
                    "owner_label": item.get("owner_label") or owner,
                    "items": [],
                },
            )
            group["items"].append(item)
        grouped = list(by_user.values())
    return ok(
        items,
        summary=_summary(items),
        grouped=grouped,
        filters={
            "owner_user_id": owner_user_id,
            "status": status,
            "destination": destination,
            "q": q,
            "sort": sort,
            "direction": direction,
            "group_by_user": group_by_user,
        },
    )


@router.get("/tasks/{task_id}")
def task_detail(request: Request, task_id: str):
    record = _record_for_request(request, task_id)
    if not record:
        return err("任务不存在", 404)
    return ok(_live_record(_state(request), record, compact=False))


@router.get("/tasks/{task_id}/log")
def task_log(
    request: Request,
    task_id: str,
    tail: int = Query(default=80_000, ge=1, le=MAX_LOG_API_CHARS),
):
    if not _record_for_request(request, task_id):
        return err("任务不存在", 404)
    try:
        return ok(_state(request).nas.task_log(task_id, tail_chars=tail))
    except KeyError:
        return err("任务不存在", 404)
    except ValueError as exc:
        return err(str(exc))


@router.get("/tasks/{task_id}/log/download")
def task_log_download(request: Request, task_id: str):
    if not _record_for_request(request, task_id):
        return err("任务不存在", 404)
    try:
        data = _state(request).nas.task_log(task_id, tail_chars=None)
    except KeyError:
        return err("任务不存在", 404)
    except ValueError as exc:
        return err(str(exc))
    return PlainTextResponse(
        str(data.get("text") or ""),
        headers={"Content-Disposition": f'attachment; filename="task-{task_id}.log"'},
    )


def _apply_task_action(
    request: Request,
    task_id: str,
    action: str,
    body: TaskActionRequest,
) -> dict[str, Any]:
    state = _state(request)
    auth = _auth(request)
    record = _record_for_request(request, task_id)
    if not record:
        raise KeyError("任务不存在")
    queue = _queue_for_record(state, record)
    install_task_extensions(queue)
    if action in {"retry", "resume"}:
        if (
            not _is_admin(auth)
            and queue.active_count_for_owner(str(auth["user_id"]))
            >= NORMAL_USER_ACTIVE_TASK_LIMIT
        ):
            raise QueueFullError(
                f"当前账号活动任务已达到上限 {NORMAL_USER_ACTIVE_TASK_LIMIT} 个"
            )
        task = retry_in_place(
            queue,
            task_id,
            force=True if record["destination"] == "device" else body.force,
            min_height=body.min_height,
            preferred_quality=body.preferred_quality,
        )
        if record["destination"] == "device":
            task["owner_user_id"] = str(record["owner_user_id"])
            state.nas.register_export_task(task)
    elif action == "cancel":
        task = cancel_task(queue, task_id)
    elif action == "pause":
        task = pause_task(queue, task_id)
    elif action == "delete":
        if record["destination"] == "device":
            state.nas.discard_export(task_id)
        delete_task(queue, task_id)
        state.nas.delete_task_snapshot(task_id)
        result = {
            "id": task_id,
            "task_id": task_id,
            "destination": record["destination"],
            "owner_user_id": record["owner_user_id"],
            "deleted": True,
        }
        _audit_task(request, "download.task.delete", result)
        return result
    else:
        raise ValueError("不支持的任务操作")
    result = _decorate_task(state, task, str(record["destination"]))
    result["owner_user_id"] = str(record["owner_user_id"])
    result["owner"] = record.get("owner") or {}
    result["owner_label"] = record.get("owner_label") or ""
    _audit_task(request, f"download.task.{action}", result)
    return result


@router.post("/tasks/{task_id}/cancel")
def cancel(request: Request, task_id: str):
    try:
        return ok(_apply_task_action(request, task_id, "cancel", TaskActionRequest()))
    except KeyError as exc:
        return err(str(exc), 404)
    except ValueError as exc:
        return err(str(exc), 409)


@router.post("/tasks/{task_id}/retry")
def retry(request: Request, task_id: str, body: RetryRequest):
    try:
        return ok(
            _apply_task_action(
                request,
                task_id,
                "retry",
                TaskActionRequest(force=body.force),
            )
        )
    except KeyError as exc:
        return err(str(exc), 404)
    except QueueFullError as exc:
        return err(str(exc), 429, code="active_task_limit")
    except ValueError as exc:
        return err(str(exc), 409)


@router.post("/tasks/{task_id}/open-output")
def open_output(request: Request, task_id: str):
    record = _record_for_request(request, task_id)
    if not record:
        return err("任务不存在", 404)
    if record["destination"] == "device":
        return err("设备导出任务请使用“下载到当前设备”按钮", 409)
    try:
        relative = _state(request).queue.open_output(task_id)
    except KeyError:
        return err("任务不存在", 404)
    except FileNotFoundError as exc:
        return err(str(exc), 404)
    except RuntimeError as exc:
        return err(str(exc), 501)
    except ValueError as exc:
        return err(str(exc), 409)
    return ok({"opened": True, "path": relative})


@router.post("/tasks/clear-finished")
def clear_finished(request: Request):
    items = _list_records(request)
    removed = 0
    for item in items:
        if str(item.get("status") or "") not in TERMINAL_STATUSES:
            continue
        try:
            _apply_task_action(request, str(item["id"]), "delete", TaskActionRequest())
            removed += 1
        except (KeyError, ValueError):
            continue
    return ok({"removed": removed})


@enhancement_router.post("/tasks/{task_id}/{action}")
def enhanced_action(
    request: Request,
    task_id: str,
    action: Literal["retry", "cancel", "pause", "resume", "delete"],
    body: TaskActionRequest,
):
    try:
        return ok(_apply_task_action(request, task_id, action, body))
    except KeyError as exc:
        return err(str(exc), 404)
    except QueueFullError as exc:
        return err(str(exc), 429, code="active_task_limit")
    except ValueError as exc:
        return err(str(exc), 409)


@enhancement_router.post("/tasks/batch")
def enhanced_batch(request: Request, body: TaskBatchRequest):
    results: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    action_body = TaskActionRequest(
        force=body.force,
        min_height=body.min_height,
        preferred_quality=body.preferred_quality,
    )
    for task_id in list(dict.fromkeys(body.task_ids)):
        try:
            results.append(
                _apply_task_action(request, task_id, body.action, action_body)
            )
        except (KeyError, QueueFullError, ValueError) as exc:
            errors[task_id] = str(exc)
    return ok({"items": results, "errors": errors}, total=len(results))


@enhancement_router.post("/tasks/clear")
def enhanced_clear(request: Request, body: ClearTasksRequest):
    wanted = set(body.statuses)
    items = _list_records(
        request,
        destination="" if body.destination == "all" else body.destination,
    )
    removed = 0
    errors: dict[str, str] = {}
    for item in items:
        if str(item.get("status") or "") not in wanted:
            continue
        task_id = str(item["id"])
        try:
            _apply_task_action(request, task_id, "delete", TaskActionRequest())
            removed += 1
        except (KeyError, ValueError) as exc:
            errors[task_id] = str(exc)
    return ok({"removed": removed, "errors": errors})


@router.post("/exports/{task_id}/prepare")
def prepare_export(request: Request, task_id: str):
    record = _record_for_request(request, task_id)
    if not record or record.get("destination") != "device":
        return err("设备导出任务不存在", 404)
    state = _state(request)
    task = state.export_queue.get_task(task_id) or state.nas.export_task_payload(task_id)
    if not task:
        return err("设备导出任务不存在", 404)
    try:
        export = state.nas.prepare_export(task_id, task)
    except KeyError as exc:
        return err(str(exc), 404)
    except FileNotFoundError as exc:
        return err(str(exc), 404)
    except ValueError as exc:
        return err(str(exc), 409)
    return ok({**export, "download_url": f"/api/exports/{task_id}/download"})


@router.api_route("/exports/{task_id}/download", methods=["GET", "HEAD"])
def download_export(request: Request, task_id: str):
    record = _record_for_request(request, task_id)
    if not record or record.get("destination") != "device":
        return err("设备导出任务不存在", 404)
    state = _state(request)
    task = state.export_queue.get_task(task_id) or state.nas.export_task_payload(task_id)
    if not task:
        return err("设备导出任务不存在", 404)
    try:
        export = state.nas.export_record(task_id)
        if not export or export.get("state") != "ready":
            state.nas.prepare_export(task_id, task)
        export, path = state.nas.resolve_export(task_id)
    except KeyError as exc:
        return err(str(exc), 404)
    except FileNotFoundError as exc:
        return err(str(exc), 404)
    except ValueError as exc:
        return err(
            str(exc), 410 if "过期" in str(exc) or "清理" in str(exc) else 409
        )
    return file_response(
        request,
        path,
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        filename=str(export["filename"]),
        attachment=True,
        allow_range=False,
        on_complete=lambda: state.nas.complete_export(task_id),
    )


@router.delete("/exports/{task_id}")
def discard_export(request: Request, task_id: str):
    record = _record_for_request(request, task_id)
    if not record or record.get("destination") != "device":
        return err("设备导出记录不存在", 404)
    if not _state(request).nas.discard_export(task_id):
        return err("设备导出记录不存在", 404)
    return ok({"discarded": True})


@router.get("/events")
async def events(
    request: Request,
    owner_user_id: str = Query("", max_length=100),
):
    state = _state(request)
    auth = _auth(request)
    session_id = str(auth.get("session_id") or "")

    async def stream():
        last = ""
        last_keepalive = 0.0
        last_auth_check = time.monotonic()
        while True:
            if await request.is_disconnected():
                break
            now_mono = time.monotonic()
            if (
                session_id
                and now_mono - last_auth_check >= SSE_AUTH_HEARTBEAT_SECONDS
            ):
                if not state.nas.session_is_active(session_id):
                    break
                last_auth_check = now_mono
            items = _list_records(request, owner_user_id=owner_user_id)
            event_data = {"tasks": items, "summary": _summary(items)}
            fingerprint = json.dumps(
                event_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            if fingerprint != last:
                event_data["at"] = time.time()
                payload = json.dumps(
                    event_data, ensure_ascii=False, separators=(",", ":")
                )
                yield f"event: tasks\ndata: {payload}\n\n"
                last = fingerprint
                last_keepalive = time.monotonic()
            elif now_mono - last_keepalive >= SSE_AUTH_HEARTBEAT_SECONDS:
                yield ": keepalive\n\n"
                last_keepalive = now_mono
            await asyncio.sleep(1.0)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
