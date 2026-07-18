from __future__ import annotations

import asyncio
import json
import mimetypes
import time

import httpx
from urllib.parse import urlparse

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse

from app import __version__
from app.bbdown import find_ffmpeg
from app.constants import MAX_BATCH_ITEMS, MAX_LOG_API_CHARS
from app.index_store import UnsafeIndexPathError
from app.media_stream import file_response
from app.models import (
    AuthLoginRequest,
    AuthPasswordChangeRequest,
    AuthSetupRequest,
    CompatibleRequest,
    ConfigUpdate,
    DownloadItem,
    DownloadRequest,
    GroupCreateRequest,
    GroupMergeRequest,
    GroupRenameRequest,
    MediaMoveRequest,
    PreviewRequest,
    RetryRequest,
    WatchProgressRequest,
)
from app.queue import QueueFullError
from app.search import SearchError, search_videos
from app.state import AppState
from app.urls import Target, parse_inputs

router = APIRouter(prefix="/api")
SESSION_COOKIE = "bili_session"
_COVER_HOST_SUFFIXES = ("bilibili.com", "hdslb.com", "biliimg.com")
_LOCAL_STATUS_LABELS = {
    "not_downloaded": "未下载",
    "downloaded": "已下载",
    "queued": "排队中",
    "running": "下载中",
    "failed": "下载失败",
    "cancelled": "已取消",
    "index_error": "索引异常",
}


def _state(request: Request) -> AppState:
    return request.app.state.app_state


def _session(request: Request) -> dict | None:
    return getattr(request.state, "auth_session", None)


def _user_id(request: Request) -> str:
    session = _session(request)
    return str(session.get("user_id")) if session else "local"


def _cookie_name(state: AppState) -> str:
    return "__Host-bili_session" if state.runtime.cookie_secure else SESSION_COOKIE


def ok(data=None, **extra):
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    body.update(extra)
    return body


def err(message: str, status_code: int = 400):
    return JSONResponse({"ok": False, "error": message}, status_code=status_code)


def _safe_cover_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host:
        return ""
    if not any(host == suffix or host.endswith("." + suffix) for suffix in _COVER_HOST_SUFFIXES):
        return ""
    if parsed.username is not None or parsed.password is not None:
        return ""
    try:
        if parsed.port not in (None, 443):
            return ""
    except ValueError:
        return ""
    return text


def _item_target(item: DownloadItem) -> Target:
    targets = parse_inputs(
        [item.url] if item.url else [],
        [item.bvid] if item.bvid else [],
        max_items=2,
    )
    if len(targets) != 1:
        raise ValueError("作品元数据中的 bvid 与 url 不一致")
    return targets[0]


def _parse_download_body(body: DownloadRequest) -> tuple[list[Target], dict[str, dict]]:
    result: list[Target] = []
    metadata: dict[str, dict] = {}
    seen: set[str] = set()
    if body.urls or body.bvids:
        for target in parse_inputs(body.urls, body.bvids, max_items=MAX_BATCH_ITEMS):
            if target.key not in seen:
                seen.add(target.key)
                result.append(target)
    for item in body.items:
        target = _item_target(item)
        display = item.display_metadata()
        display["cover"] = _safe_cover_url(str(display.get("cover") or ""))
        metadata[target.key] = display
        if target.key not in seen:
            seen.add(target.key)
            result.append(target)
        if len(result) > MAX_BATCH_ITEMS:
            raise ValueError(f"单次最多提交 {MAX_BATCH_ITEMS} 个作品")
    if not result:
        raise ValueError("请提供有效的链接或 BV/av/ep/ss 编号")
    return result, metadata


def _decorate_search_items(state: AppState, data: dict) -> dict:
    items = data.get("items") or []
    keys = [str(item.get("bvid") or "") for item in items if item.get("bvid")]
    task_states = state.queue.key_statuses(keys)
    for item in items:
        item["cover"] = _safe_cover_url(str(item.get("cover") or ""))
        key = str(item.get("bvid") or "")
        local_status, task_id, output_path = "not_downloaded", "", ""
        downloaded_at, local_group, local_quality = None, "", ""
        task = task_states.get(key)
        if task and task.get("status") in ("queued", "running"):
            local_status = str(task["status"])
            task_id = str(task.get("id") or "")
            local_group = str(task.get("group") or "")
            local_quality = str(task.get("quality_summary") or task.get("selected_quality") or "")
        else:
            try:
                indexed = state.index.get_valid(key)
            except UnsafeIndexPathError:
                indexed = None
                local_status = "index_error"
            if indexed is not None:
                local_status = "downloaded"
                output_path = str(indexed.get("path") or "")
                downloaded_at = indexed.get("finished_at")
                local_group = str(indexed.get("group") or "")
                local_quality = str(indexed.get("quality_summary") or indexed.get("selected_quality") or "")
            elif task and task.get("status") in ("failed", "cancelled"):
                local_status = str(task["status"])
                task_id = str(task.get("id") or "")
                local_group = str(task.get("group") or "")
                local_quality = str(task.get("quality_summary") or task.get("selected_quality") or "")
        item.update(
            local_status=local_status,
            local_status_label=_LOCAL_STATUS_LABELS.get(local_status, local_status),
            task_id=task_id,
            output_path=output_path,
            downloaded_at=downloaded_at,
            local_group=local_group,
            local_quality=local_quality,
        )
    return data


def _remote(request: Request) -> str:
    return request.client.host if request.client else ""


def _audit(request: Request, action: str, detail: str = "") -> None:
    session = _session(request)
    _state(request).nas.audit(
        str(session.get("user_id")) if session else None,
        action,
        detail,
        _remote(request),
    )


def _combined_summary(state: AppState) -> dict[str, int]:
    a, b = state.queue.summary(), state.export_queue.summary()
    keys = set(a) | set(b)
    return {key: int(a.get(key, 0)) + int(b.get(key, 0)) for key in keys}


def _decorate_group_task_counts(state: AppState, records: list[dict]) -> list[dict]:
    by_id = {str(item.get("id") or ""): item for item in records}
    by_name = {str(item.get("display_name") or "").casefold(): item for item in records}
    for item in records:
        item["active_count"] = 0
        item["failed_count"] = 0
    for task in state.queue.list_tasks():
        status = str(task.get("status") or "")
        if status not in {"queued", "running", "failed"}:
            continue
        group = by_id.get(str(task.get("group_id") or ""))
        if group is None:
            group = by_name.get(str(task.get("group") or "").casefold())
        if group is None:
            continue
        key = "active_count" if status in {"queued", "running"} else "failed_count"
        group[key] = int(group.get(key) or 0) + 1
    return records


def _decorate_task(state: AppState, task: dict, destination: str) -> dict:
    value = dict(task)
    value["destination"] = destination
    value["destination_label"] = "设备导出" if destination == "device" else "NAS 媒体库"
    if destination == "device":
        record = state.nas.export_record(str(task["id"])) or {}
        value["export_state"] = record.get("state", "preparing")
        value["export_ready"] = record.get("state") == "ready"
        value["export_available"] = (
            task.get("status") == "success"
            and record.get("state", "preparing") in {"preparing", "ready"}
        )
        value["export_filename"] = record.get("filename", "")
        value["export_size"] = int(record.get("size") or 0)
        value["export_expires_at"] = record.get("expires_at")
    else:
        if not value.get("group_id"):
            group = state.nas.group_by_folder(
                str(task.get("group_folder") or "")
            ) or state.nas.group_by_name(str(task.get("group") or ""))
            value["group_id"] = group.get("id", "") if group else ""
            if group:
                value["group"] = group["display_name"]
    return value


def _compact_task(value: dict) -> dict:
    result = dict(value)
    files = result.pop("files", None) or []
    result["file_count"] = len(files)
    result.pop("log_tail", None)
    result.pop("selected_tracks", None)
    return result


def _find_task(state: AppState, task_id: str) -> tuple[dict | None, str]:
    task = state.queue.get_task(task_id)
    if task:
        return task, "library"
    task = state.export_queue.get_task(task_id)
    if task:
        return task, "device"
    snapshot = state.nas.task_snapshot(task_id)
    if snapshot:
        return snapshot, str(snapshot.get("destination") or "library")
    payload = state.nas.export_task_payload(task_id)
    return (payload, "device") if payload else (None, "")


# Authentication ---------------------------------------------------------
@router.get("/auth/status")
def auth_status(request: Request):
    state = _state(request)
    token = request.cookies.get(_cookie_name(state), "")
    return ok(state.nas.auth_status(token))


@router.post("/auth/setup")
def auth_setup(request: Request, body: AuthSetupRequest):
    state = _state(request)
    try:
        user = state.nas.setup_admin(body.username, body.password, body.bootstrap_token)
        token, session = state.nas.login(
            user["username"], body.password, remote_addr=_remote(request), user_agent=request.headers.get("user-agent", "")
        )
    except RuntimeError as exc:
        return err(str(exc), 429)
    except ValueError as exc:
        return err(str(exc), 400)
    response = JSONResponse(ok({"username": session["username"], "csrf_token": session["csrf_token"]}))
    response.set_cookie(
        _cookie_name(state), token, httponly=True, secure=state.runtime.cookie_secure,
        samesite="lax", path="/", max_age=30 * 24 * 3600,
    )
    return response


@router.post("/auth/login")
def auth_login(request: Request, body: AuthLoginRequest):
    state = _state(request)
    try:
        token, session = state.nas.login(
            body.username, body.password, remote_addr=_remote(request), user_agent=request.headers.get("user-agent", "")
        )
    except RuntimeError as exc:
        return err(str(exc), 429)
    except ValueError as exc:
        return err(str(exc), 401)
    response = JSONResponse(ok({"username": session["username"], "csrf_token": session["csrf_token"]}))
    response.set_cookie(
        _cookie_name(state), token, httponly=True, secure=state.runtime.cookie_secure,
        samesite="lax", path="/", max_age=30 * 24 * 3600,
    )
    return response


@router.post("/auth/password")
def auth_change_password(request: Request, body: AuthPasswordChangeRequest):
    state = _state(request)
    session = _session(request)
    if not session:
        return err("本地免登录模式没有可修改的网站管理员密码", 400)
    try:
        result = state.nas.change_password(
            str(session["user_id"]),
            body.current_password,
            body.new_password,
            keep_session_id=str(session["id"]),
        )
    except ValueError as exc:
        return err(str(exc), 400)
    request.state.auth_session = {**session, "csrf_token": result["csrf_token"]}
    state.nas.audit(
        str(session["user_id"]),
        "auth.password.change",
        f"撤销其他会话 {result['other_sessions_revoked']} 个",
        _remote(request),
    )
    return ok(result)


@router.post("/auth/logout")
def auth_logout(request: Request):
    state = _state(request)
    session = _session(request)
    if session:
        state.nas.audit(str(session["user_id"]), "auth.logout", "管理员退出", _remote(request))
        state.nas.logout(str(session["id"]))
    response = JSONResponse(ok({"logged_out": True}))
    response.delete_cookie(
        _cookie_name(state), path="/", secure=state.runtime.cookie_secure,
        httponly=True, samesite="lax",
    )
    return response


# Status/config/search ----------------------------------------------------
@router.get("/status")
def get_status(request: Request, refresh_login: bool = False):
    state = _state(request)
    cfg = state.config_store.get()
    cookie = state.cookie_checker.status(force=refresh_login)
    state.nas.sync_index()
    records = _decorate_group_task_counts(state, state.nas.list_groups())
    return ok(
        {
            "version": __version__,
            **cookie.to_dict(),
            "host": cfg.host,
            "port": cfg.port,
            "poll_hint_ms": cfg.poll_hint_ms,
            "download_timeout_sec": cfg.download_timeout_sec,
            "default_group": cfg.default_group,
            "default_min_height": cfg.default_min_height,
            "groups": [item["display_name"] for item in records],
            "group_records": records,
            "active_tasks": state.queue.active_count() + state.export_queue.active_count(),
            "task_summary": _combined_summary(state),
            "storage": state.nas.storage_status(),
            **state.readiness(),
        }
    )


@router.get("/config")
def get_config(request: Request):
    state = _state(request)
    config = state.config_store.as_dict()
    config["app_mode"] = state.runtime.mode
    config["public_base_url"] = state.runtime.public_base_url
    config["auth_required"] = state.runtime.auth_required
    config["temp_dir"] = str(state.runtime.temp_dir)
    config["cache_dir"] = str(state.runtime.cache_dir)
    config["export_ttl_sec"] = state.runtime.export_ttl_sec
    return ok(config, protected_fields=["host", "bbdown_dir", "download_dir"] if state.runtime.server_mode else ["host", "bbdown_dir"])


@router.put("/config")
def put_config(request: Request, body: ConfigUpdate):
    state = _state(request)
    patch = body.as_patch()
    if not patch:
        return err("没有可更新的字段")
    if state.runtime.server_mode and any(key in patch for key in ("port", "download_dir")):
        return err("NAS 模式的端口和目录由 Docker 环境变量及目录映射管理", 409)
    if "download_dir" in patch and state.queue.active_count() > 0:
        return err("存在排队或下载中的任务，暂不能切换下载目录", 409)
    try:
        cfg, restart = state.config_store.update(patch)
        state.index.set_download_dir(cfg.download_path())
    except ValueError as exc:
        return err(str(exc))
    return ok(cfg.to_dict(), restart_required=restart)


@router.get("/search")
def api_search(
    request: Request,
    q: str = Query(default="", max_length=100),
    order: str = Query(default="totalrank", max_length=32),
    page: int = Query(default=1, ge=1, le=1000),
):
    state = _state(request)
    cfg = state.config_store.get()
    try:
        data = search_videos(q, order=order, page=page, bbdown_dir=cfg.bbdown_path())
        data = _decorate_search_items(state, data)
    except SearchError as exc:
        return err(str(exc))
    except Exception as exc:  # noqa: BLE001
        return err(f"搜索失败: {exc}", 502)
    return ok(data)


# Groups ------------------------------------------------------------------
@router.get("/groups")
def api_groups(request: Request):
    state = _state(request)
    cfg = state.config_store.get()
    state.nas.sync_index()
    records = _decorate_group_task_counts(state, state.nas.list_groups())
    return ok(
        {
            "default_group": cfg.default_group,
            "default_min_height": cfg.default_min_height,
            "items": [item["display_name"] for item in records],
            "records": records,
        }
    )


@router.post("/groups")
def api_create_group(request: Request, body: GroupCreateRequest):
    try:
        group = _state(request).nas.create_group(body.name)
    except ValueError as exc:
        return err(str(exc))
    _audit(request, "group.create", str(group.get("display_name") or body.name))
    return ok(group)


@router.patch("/groups/{group_id}")
def api_rename_group(request: Request, group_id: str, body: GroupRenameRequest):
    state = _state(request)
    before = state.nas.get_group(group_id)
    try:
        group = state.nas.rename_group(group_id, body.name)
        if before and state.config_store.get().default_group.casefold() == str(before["display_name"]).casefold():
            state.config_store.update({"default_group": group["display_name"]})
    except KeyError as exc:
        return err(str(exc), 404)
    except ValueError as exc:
        return err(str(exc), 409)
    _audit(request, "group.rename", f"{before.get('display_name') if before else group_id} -> {group['display_name']}")
    return ok(group)


@router.post("/groups/{group_id}/merge")
def api_merge_group(request: Request, group_id: str, body: GroupMergeRequest):
    state = _state(request)
    source = state.nas.get_group(group_id)
    try:
        group = state.nas.merge_group(group_id, body.target_id)
        if source and state.config_store.get().default_group.casefold() == str(source["display_name"]).casefold():
            state.config_store.update({"default_group": group["display_name"]})
    except KeyError as exc:
        return err(str(exc), 404)
    except ValueError as exc:
        return err(str(exc), 409)
    _audit(request, "group.merge", f"{source.get('display_name') if source else group_id} -> {group['display_name']}")
    return ok(group)


@router.delete("/groups/{group_id}")
def api_delete_group(request: Request, group_id: str):
    state = _state(request)
    group = state.nas.get_group(group_id)
    if group and state.config_store.get().default_group.casefold() == str(group["display_name"]).casefold():
        return err("当前默认分组不能删除，请先在设置中修改默认分组", 409)
    try:
        state.nas.delete_group(group_id)
    except KeyError as exc:
        return err(str(exc), 404)
    except ValueError as exc:
        return err(str(exc), 409)
    _audit(request, "group.delete", str((group or {}).get("display_name") or group_id))
    return ok({"deleted": True})


# Preview/download/tasks --------------------------------------------------
@router.post("/preview")
def api_preview(request: Request, body: PreviewRequest):
    state = _state(request)
    try:
        target = _item_target(body.item)
        metadata = body.item.display_metadata()
        metadata["cover"] = _safe_cover_url(str(metadata.get("cover") or ""))
        preferred = body.preferred_quality.strip() or str(metadata.get("preferred_quality") or "")
        data = state.queue.preview(
            target, min_height=body.min_height, preferred_quality=preferred, submitted_metadata=metadata
        )
        preview_metadata = data.get("metadata") or {}
        preview_metadata["cover"] = _safe_cover_url(str(preview_metadata.get("cover") or ""))
    except ValueError as exc:
        return err(str(exc))
    except Exception as exc:  # noqa: BLE001
        return err(f"清晰度预览失败: {exc}", 502)
    return ok(data)


@router.post("/download")
def api_download(request: Request, body: DownloadRequest):
    state = _state(request)
    try:
        targets, metadata = _parse_download_body(body)
        if body.destination == "device":
            duplicate = None
            for target in targets:
                record = state.nas.active_export_for_source(target.key)
                if record:
                    duplicate = (target, record)
                    break
            if duplicate:
                target, record = duplicate
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
            )
            for task in tasks:
                if task.get("status") in {"queued", "running"}:
                    state.nas.register_export_task(task)
            tasks = [_decorate_task(state, task, "device") for task in tasks]
        else:
            group = state.nas.resolve_group(body.group_id, body.group)
            tasks = state.queue.enqueue(
                targets,
                force=body.force,
                metadata=metadata,
                group=group["display_name"],
                group_id=group["id"],
                group_folder=group["folder_key"],
                min_height=body.min_height,
            )
            tasks = [_decorate_task(state, task, "library") for task in tasks]
    except QueueFullError as exc:
        return err(str(exc), 429)
    except ValueError as exc:
        return err(str(exc))
    _audit(request, "download.enqueue", f"destination={body.destination}; count={len(tasks)}")
    return ok(tasks, total=len(tasks), limit=MAX_BATCH_ITEMS)


@router.get("/tasks")
def api_tasks(request: Request):
    state = _state(request)
    tasks = [
        _compact_task(_decorate_task(state, item, "library"))
        for item in state.queue.list_tasks()
    ]
    tasks += [
        _compact_task(_decorate_task(state, item, "device"))
        for item in state.export_queue.list_tasks()
    ]
    tasks.sort(key=lambda item: float(item.get("created_at") or 0), reverse=True)
    return ok(tasks, summary=_combined_summary(state))


@router.get("/tasks/{task_id}")
def api_task(request: Request, task_id: str):
    state = _state(request)
    task, destination = _find_task(state, task_id)
    if not task:
        return err("任务不存在", 404)
    return ok(_decorate_task(state, task, destination))


@router.get("/tasks/{task_id}/log")
def api_task_log(request: Request, task_id: str, tail: int = Query(default=80_000, ge=1, le=MAX_LOG_API_CHARS)):
    state = _state(request)
    queue = state.export_queue if state.export_queue.get_task(task_id) else state.queue
    try:
        data = queue.get_log(task_id, tail_chars=tail)
    except KeyError:
        return err("任务不存在", 404)
    except ValueError as exc:
        return err(str(exc))
    return ok(data)


@router.get("/tasks/{task_id}/log/download")
def api_task_log_download(request: Request, task_id: str):
    state = _state(request)
    queue = state.export_queue if state.export_queue.get_task(task_id) else state.queue
    try:
        data = queue.get_log(task_id, tail_chars=None)
    except KeyError:
        return err("任务不存在", 404)
    except ValueError as exc:
        return err(str(exc))
    return PlainTextResponse(
        str(data.get("text") or ""),
        headers={"Content-Disposition": f'attachment; filename="task-{task_id}.log"'},
    )


@router.post("/tasks/{task_id}/cancel")
def api_cancel_task(request: Request, task_id: str):
    state = _state(request)
    task, destination = _find_task(state, task_id)
    if not task:
        return err("任务不存在", 404)
    queue = state.export_queue if destination == "device" else state.queue
    if not queue.cancel(task_id):
        return err("任务已结束，无法取消", 409)
    return ok({"cancelled": True, "task_id": task_id})


@router.post("/tasks/{task_id}/retry")
def api_retry_task(request: Request, task_id: str, body: RetryRequest):
    state = _state(request)
    task, destination = _find_task(state, task_id)
    if not task:
        return err("任务不存在", 404)
    queue = state.export_queue if destination == "device" else state.queue
    try:
        tasks = queue.retry(task_id, force=True if destination == "device" else body.force)
        if destination == "device":
            for item in tasks:
                if item.get("status") in {"queued", "running"}:
                    state.nas.register_export_task(item)
        tasks = [_decorate_task(state, item, destination) for item in tasks]
    except QueueFullError as exc:
        return err(str(exc), 429)
    except ValueError as exc:
        return err(str(exc), 409)
    return ok(tasks, total=len(tasks))


@router.post("/tasks/{task_id}/open-output")
def api_open_output(request: Request, task_id: str):
    state = _state(request)
    if state.export_queue.get_task(task_id):
        return err("设备导出任务请使用“下载到当前设备”按钮", 409)
    try:
        relative = state.queue.open_output(task_id)
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
def api_clear_finished(request: Request):
    # Device export history remains until it is downloaded or expires, so a user cannot
    # accidentally clear the only pointer to a ready temporary file.
    removed = _state(request).queue.clear_finished()
    return ok({"removed": removed})


# Device export -----------------------------------------------------------
@router.post("/exports/{task_id}/prepare")
def api_prepare_export(request: Request, task_id: str):
    state = _state(request)
    task = state.export_queue.get_task(task_id) or state.nas.export_task_payload(task_id)
    if not task:
        return err("设备导出任务不存在", 404)
    try:
        record = state.nas.prepare_export(task_id, task)
    except KeyError as exc:
        return err(str(exc), 404)
    except FileNotFoundError as exc:
        return err(str(exc), 404)
    except ValueError as exc:
        return err(str(exc), 409)
    return ok({**record, "download_url": f"/api/exports/{task_id}/download"})


@router.api_route("/exports/{task_id}/download", methods=["GET", "HEAD"])
def api_download_export(request: Request, task_id: str):
    state = _state(request)
    task = state.export_queue.get_task(task_id) or state.nas.export_task_payload(task_id)
    if not task:
        return err("设备导出任务不存在", 404)
    try:
        record = state.nas.export_record(task_id)
        if not record or record.get("state") != "ready":
            state.nas.prepare_export(task_id, task)
        record, path = state.nas.resolve_export(task_id)
    except KeyError as exc:
        return err(str(exc), 404)
    except FileNotFoundError as exc:
        return err(str(exc), 404)
    except ValueError as exc:
        return err(str(exc), 410 if "过期" in str(exc) or "清理" in str(exc) else 409)
    return file_response(
        request,
        path,
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        filename=str(record["filename"]),
        attachment=True,
        allow_range=False,
        on_complete=lambda: state.nas.complete_export(task_id),
    )


@router.delete("/exports/{task_id}")
def api_discard_export(request: Request, task_id: str):
    state = _state(request)
    if not state.nas.discard_export(task_id):
        return err("设备导出记录不存在", 404)
    return ok({"discarded": True})


# Cover proxy/cache --------------------------------------------------------
@router.get("/cover")
def api_cover(request: Request, url: str = Query(..., max_length=2048)):
    state = _state(request)
    try:
        path, media_type = state.cover_cache.fetch(url)
    except (ValueError, httpx.HTTPError, OSError) as exc:
        return err(f"封面读取失败: {exc}", 404)
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"},
    )


# Library/player ----------------------------------------------------------
@router.get("/library/summary")
def api_library_summary(request: Request):
    return ok(_state(request).nas.library_summary())


@router.get("/library")
def api_library(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=100),
    q: str = Query("", max_length=200),
    group_id: str = Query("", max_length=100),
    sort: str = Query("newest", max_length=30),
    codec: str = Query("", max_length=80),
    min_height: int = Query(0, ge=0, le=4320),
    watched: str = Query("", max_length=30),
):
    return ok(
        _state(request).nas.library_list(
            page=page, page_size=page_size, query=q, group_id=group_id,
            sort=sort, user_id=_user_id(request), codec=codec,
            min_height=min_height, watched=watched,
        )
    )


@router.get("/library/{media_id}")
def api_media_detail(request: Request, media_id: str):
    value = _state(request).nas.media_detail(media_id, _user_id(request))
    if not value:
        return err("作品不存在", 404)
    return ok(value)


@router.api_route("/media/{file_id}/stream", methods=["GET", "HEAD"])
def api_media_stream(request: Request, file_id: str):
    try:
        row, path = _state(request).nas.resolve_media_file(file_id)
    except KeyError as exc:
        return err(str(exc), 404)
    except FileNotFoundError as exc:
        return err(str(exc), 404)
    return file_response(
        request, path, media_type=str(row["mime_type"]), filename=str(row["filename"]),
        attachment=False, allow_range=True,
    )


@router.api_route("/media/{file_id}/download", methods=["GET", "HEAD"])
def api_media_download(request: Request, file_id: str):
    try:
        row, path = _state(request).nas.resolve_media_file(file_id)
    except KeyError as exc:
        return err(str(exc), 404)
    except FileNotFoundError as exc:
        return err(str(exc), 404)
    return file_response(
        request, path, media_type=str(row["mime_type"]), filename=str(row["filename"]),
        attachment=True, allow_range=True,
    )


@router.put("/library/{media_id}/progress")
def api_watch_progress(request: Request, media_id: str, body: WatchProgressRequest):
    try:
        data = _state(request).nas.save_progress(
            _user_id(request), media_id, body.file_id, body.position_sec, body.duration_sec
        )
    except KeyError as exc:
        return err(str(exc), 404)
    return ok(data)


@router.post("/library/{media_id}/move")
def api_move_media(request: Request, media_id: str, body: MediaMoveRequest):
    try:
        data = _state(request).nas.move_media(media_id, body.group_id)
    except KeyError as exc:
        return err(str(exc), 404)
    _audit(request, "media.move", f"media={media_id}; group={body.group_id}")
    return ok(data)


@router.delete("/library/{media_id}")
def api_delete_media(request: Request, media_id: str, delete_files: bool = False):
    try:
        data = _state(request).nas.delete_media(media_id, delete_files)
    except KeyError as exc:
        return err(str(exc), 404)
    except (ValueError, UnsafeIndexPathError) as exc:
        return err(str(exc), 409)
    _audit(request, "media.delete", f"media={media_id}; files={bool(delete_files)}")
    return ok(data)


@router.post("/library/{media_id}/compatible")
def api_compatible(request: Request, media_id: str, body: CompatibleRequest):
    state = _state(request)
    ffmpeg = find_ffmpeg(state.config_store.get().bbdown_path())
    if not ffmpeg:
        return err("未找到 FFmpeg", 503)
    try:
        job = state.nas.start_compatible(media_id, body.file_id, ffmpeg)
    except KeyError as exc:
        return err(str(exc), 404)
    except ValueError as exc:
        return err(str(exc), 409)
    return ok(job)


@router.get("/transcodes/{job_id}")
def api_transcode_status(request: Request, job_id: str):
    job = _state(request).nas.transcode_status(job_id)
    if not job:
        return err("转码任务不存在", 404)
    return ok(job)


# Bilibili account --------------------------------------------------------
@router.post("/account/bilibili/qr")
def api_bilibili_qr(request: Request):
    try:
        value = _state(request).qr_login.create()
        _audit(request, "bilibili.qr.create", str(value.get("id") or ""))
        return ok(value)
    except Exception as exc:  # noqa: BLE001
        return err(f"二维码创建失败: {exc}", 502)


@router.post("/account/bilibili/qr/{session_id}")
def api_bilibili_qr_poll(request: Request, session_id: str):
    state = _state(request)
    try:
        data = state.qr_login.poll(session_id)
        if data.get("status") == "success":
            state.cookie_checker.status(force=True)
            _audit(request, "bilibili.qr.success", session_id)
        return ok(data)
    except KeyError as exc:
        return err(str(exc), 404)
    except Exception as exc:  # noqa: BLE001
        return err(f"扫码状态查询失败: {exc}", 502)


@router.delete("/account/bilibili")
def api_bilibili_logout(request: Request):
    state = _state(request)
    try:
        removed = state.qr_login.logout()
        state.cookie_checker.status(force=True)
    except ValueError as exc:
        return err(str(exc), 409)
    _audit(request, "bilibili.logout", f"removed={removed}")
    return ok({"removed": removed})


# Server-sent events ------------------------------------------------------
@router.get("/events")
async def api_events(request: Request):
    state = _state(request)

    async def stream():
        last = ""
        last_keepalive = 0.0
        while True:
            if await request.is_disconnected():
                break
            tasks = [
                _compact_task(_decorate_task(state, item, "library"))
                for item in state.queue.list_tasks()
            ]
            tasks += [
                _compact_task(_decorate_task(state, item, "device"))
                for item in state.export_queue.list_tasks()
            ]
            tasks.sort(key=lambda item: float(item.get("created_at") or 0), reverse=True)
            event_data = {"tasks": tasks, "summary": _combined_summary(state)}
            fingerprint = json.dumps(event_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if fingerprint != last:
                event_data["at"] = time.time()
                payload = json.dumps(event_data, ensure_ascii=False, separators=(",", ":"))
                yield f"event: tasks\ndata: {payload}\n\n"
                last = fingerprint
                last_keepalive = time.monotonic()
            elif time.monotonic() - last_keepalive >= 15:
                yield ": keepalive\n\n"
                last_keepalive = time.monotonic()
            await asyncio.sleep(1.0)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
