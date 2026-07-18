from __future__ import annotations

import ipaddress
import socket
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.io_utils import atomic_write_json
from app.task_extensions import (
    cancel_task,
    clear_tasks,
    delete_task,
    install_task_extensions,
    pause_task,
    retry_in_place,
)

router = APIRouter(prefix="/api/enhancements", tags=["enhancements"])
compat_router = APIRouter(prefix="/api", tags=["enhancements-compat"])
ShortText = Annotated[str, StringConstraints(max_length=300)]


class TagAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_key: ShortText = ""
    media_id: ShortText = ""
    tags: list[Annotated[str, StringConstraints(max_length=40)]] = Field(
        default_factory=list, max_length=50
    )


class TagBulkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keys: list[ShortText] = Field(default_factory=list, max_length=500)
    media_ids: list[ShortText] = Field(default_factory=list, max_length=500)


class TaskActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    force: bool = False
    min_height: int | None = Field(default=None, ge=0, le=4320)
    preferred_quality: Annotated[str, StringConstraints(max_length=120)] | None = None


class TaskBatchRequest(TaskActionRequest):
    task_ids: list[ShortText] = Field(default_factory=list, min_length=1, max_length=100)
    action: Literal["retry", "cancel", "pause", "resume", "delete"]


class ClearTasksRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statuses: list[Literal["success", "skipped", "failed", "cancelled"]] = Field(
        default_factory=lambda: ["failed", "cancelled"], max_length=4
    )
    destination: Literal["all", "library", "device"] = "all"


class LibraryDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_ids: list[ShortText] = Field(default_factory=list, min_length=1, max_length=100)
    delete_files: bool = True
    mark_tag: Annotated[str, StringConstraints(max_length=40)] = "不要"


class LibraryItemsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_ids: list[ShortText] = Field(default_factory=list, min_length=1, max_length=100)


def _ok(data: Any = None, **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": True}
    if data is not None:
        result["data"] = data
    result.update(extra)
    return result


def _err(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status_code)


def _state(request: Request):
    return request.app.state.app_state


def _tags(request: Request):
    return request.app.state.tag_store


def _session_user_id(request: Request) -> str:
    session = getattr(request.state, "auth_session", None)
    return str(session.get("user_id")) if session else "local"


def _queue_for_task(state, task_id: str):
    if state.queue.get_task(task_id):
        return state.queue, "library"
    if state.export_queue.get_task(task_id):
        return state.export_queue, "device"
    raise KeyError("任务不存在")


def _task_action(state, task_id: str, action: str, body: TaskActionRequest) -> dict[str, Any]:
    queue, destination = _queue_for_task(state, task_id)
    install_task_extensions(queue)
    if action in {"retry", "resume"}:
        task = retry_in_place(
            queue,
            task_id,
            force=True if destination == "device" else body.force,
            min_height=body.min_height,
            preferred_quality=body.preferred_quality,
        )
        if destination == "device":
            state.nas.register_export_task(task)
    elif action == "cancel":
        task = cancel_task(queue, task_id)
    elif action == "pause":
        task = pause_task(queue, task_id)
    elif action == "delete":
        if destination == "device":
            state.nas.discard_export(task_id)
        delete_task(queue, task_id)
        return {"task_id": task_id, "destination": destination, "deleted": True}
    else:
        raise ValueError("不支持的任务操作")
    return {**task, "destination": destination}


@compat_router.post("/tasks/{task_id}/retry")
def compat_retry_task(request: Request, task_id: str, body: TaskActionRequest):
    """Keep the historical endpoint while changing retry semantics to in-place."""
    try:
        return _ok(_task_action(_state(request), task_id, "retry", body))
    except KeyError as exc:
        return _err(str(exc), 404)
    except ValueError as exc:
        return _err(str(exc), 409)


@router.get("/tags")
def tags_list(request: Request):
    store = _tags(request)
    return _ok(
        {
            "items": store.definitions(),
            "config_path": str(store.config_path),
        }
    )


@router.post("/tags/reload")
def tags_reload(request: Request):
    return _ok(
        {
            "items": _tags(request).reload_definitions(),
            "config_path": str(_tags(request).config_path),
        }
    )


@router.post("/tags/bulk")
def tags_bulk(request: Request, body: TagBulkRequest):
    store = _tags(request)
    media_keys = store.media_keys(body.media_ids)
    keys = list(dict.fromkeys([*body.keys, *media_keys.values()]))
    by_key = store.tags_for_keys(keys)
    return _ok(
        {
            "by_key": by_key,
            "by_media_id": {
                media_id: by_key.get(source_key, [])
                for media_id, source_key in media_keys.items()
            },
            "media_keys": media_keys,
        }
    )


@router.put("/tags")
def tags_assign(request: Request, body: TagAssignmentRequest):
    store = _tags(request)
    source_key = body.source_key.strip()
    if not source_key and body.media_id:
        source_key = store.media_keys([body.media_id]).get(body.media_id, "")
    if not source_key:
        return _err("作品不存在或作品标识为空", 404)
    try:
        selected = store.set_tags(source_key, body.tags)
    except ValueError as exc:
        return _err(str(exc))
    return _ok({"source_key": source_key, "tags": selected})


@router.get("/library")
def enhanced_library(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(36, ge=1, le=100),
    q: str = Query("", max_length=200),
    group_id: str = Query("", max_length=100),
    sort: str = Query("newest", max_length=30),
    codec: str = Query("", max_length=80),
    min_height: int = Query(0, ge=0, le=4320),
    watched: str = Query("", max_length=30),
    tag: str = Query("", max_length=40),
):
    state = _state(request)
    state.nas.sync_index()
    data = _tags(request).library_list(
        page=page,
        page_size=page_size,
        query=q,
        group_id=group_id,
        sort=sort,
        user_id=_session_user_id(request),
        codec=codec,
        min_height=min_height,
        watched=watched,
        tag=tag,
    )
    return _ok(data)


@router.post("/library/items")
def enhanced_library_items(request: Request, body: LibraryItemsRequest):
    return _ok(_tags(request).library_items(body.media_ids))


@router.post("/library/delete")
def enhanced_library_delete(request: Request, body: LibraryDeleteRequest):
    state = _state(request)
    store = _tags(request)
    rows = store.library_items(body.media_ids)
    by_id = {str(row["id"]): row for row in rows}
    deleted: list[str] = []
    errors: dict[str, str] = {}
    for media_id in body.media_ids:
        row = by_id.get(media_id)
        if not row:
            errors[media_id] = "作品不存在"
            continue
        try:
            if body.mark_tag.strip():
                store.add_tag(str(row["source_key"]), body.mark_tag.strip())
            state.nas.delete_media(media_id, body.delete_files)
            deleted.append(media_id)
        except Exception as exc:  # noqa: BLE001
            errors[media_id] = str(exc)
    return _ok(
        {
            "deleted": deleted,
            "errors": errors,
            "files_deleted": body.delete_files,
            "marked_tag": body.mark_tag.strip(),
        },
        total=len(deleted),
    )


@router.post("/tasks/{task_id}/{action}")
def enhanced_task_action(
    request: Request,
    task_id: str,
    action: Literal["retry", "cancel", "pause", "resume", "delete"],
    body: TaskActionRequest,
):
    state = _state(request)
    try:
        result = _task_action(state, task_id, action, body)
    except KeyError as exc:
        return _err(str(exc), 404)
    except ValueError as exc:
        return _err(str(exc), 409)
    return _ok(result)


@router.post("/tasks/batch")
def enhanced_task_batch(request: Request, body: TaskBatchRequest):
    state = _state(request)
    results: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    action_body = TaskActionRequest(
        force=body.force,
        min_height=body.min_height,
        preferred_quality=body.preferred_quality,
    )
    for task_id in list(dict.fromkeys(body.task_ids)):
        try:
            results.append(_task_action(state, task_id, body.action, action_body))
        except (KeyError, ValueError) as exc:
            errors[task_id] = str(exc)
    return _ok({"items": results, "errors": errors}, total=len(results))


@router.post("/tasks/clear")
def enhanced_task_clear(request: Request, body: ClearTasksRequest):
    state = _state(request)
    removed = 0
    if body.destination in {"all", "library"}:
        install_task_extensions(state.queue)
        removed += clear_tasks(state.queue, body.statuses)
    if body.destination in {"all", "device"}:
        install_task_extensions(state.export_queue)
        ids = [
            str(task["id"])
            for task in state.export_queue.list_tasks()
            if str(task.get("status") or "") in set(body.statuses)
        ]
        for task_id in ids:
            state.nas.discard_export(task_id)
        removed += clear_tasks(state.export_queue, body.statuses)
    return _ok({"removed": removed})


def _lan_addresses() -> list[str]:
    values: set[str] = set()
    candidates: list[str] = []
    try:
        candidates.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    try:
        candidates.extend(
            str(item[4][0])
            for item in socket.getaddrinfo(socket.gethostname(), None, type=socket.SOCK_STREAM)
        )
    except OSError:
        pass
    for raw in candidates:
        value = raw.split("%", 1)[0]
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if address.is_loopback or address.is_unspecified or address.is_link_local:
            continue
        values.add(str(address))
    return sorted(values, key=lambda item: (":" in item, item))


@router.get("/network")
def enhanced_network(request: Request):
    state = _state(request)
    cfg = state.config_store.get()
    addresses = _lan_addresses()
    urls = [
        f"http://[{address}]:{cfg.port}/" if ":" in address else f"http://{address}:{cfg.port}/"
        for address in addresses
    ]
    host = str(cfg.host)
    return _ok(
        {
            "host": host,
            "port": cfg.port,
            "lan_enabled": host.strip("[]") not in {"127.0.0.1", "::1", "localhost"},
            "addresses": addresses,
            "urls": urls,
            "proxy_hint": "若电脑或手机开启代理，请把局域网网段和这些 IP 加入直连/绕过代理列表。",
        }
    )


@router.post("/network/enable-lan")
def enhanced_enable_lan(request: Request):
    state = _state(request)
    data = state.config_store.as_dict()
    data["host"] = "0.0.0.0"
    atomic_write_json(state.config_store.path, data, backup=True)
    return _ok(
        {
            "host": "0.0.0.0",
            "restart_required": True,
            "message": "已设置为监听所有网卡。请重启 start.bat；重启后会强制启用管理员登录。",
        }
    )
