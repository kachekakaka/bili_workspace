from __future__ import annotations

import ipaddress
import socket
from typing import Annotated

import httpx
from urllib.parse import urlparse

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app import __version__
from app.auth import ROLE_ADMIN
from app.bbdown import find_ffmpeg
from app.constants import (
    MAX_BATCH_ITEMS,
    SESSION_ABSOLUTE_DAYS,
)
from app.index_store import UnsafeIndexPathError
from app.io_utils import atomic_write_json
from app.media_stream import file_response
from app.models import (
    AdminPasswordResetRequest,
    AdminUserCreateRequest,
    AdminUserUpdateRequest,
    AuthLoginRequest,
    AuthPasswordChangeRequest,
    AuthProfileUpdateRequest,
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
    WatchProgressRequest,
)
from app.search import SearchError, search_videos
from app.state import AppState
from app.urls import Target, parse_inputs

account_router = APIRouter(prefix="/api", tags=["account"])
system_router = APIRouter(prefix="/api", tags=["system"])
catalog_router = APIRouter(prefix="/api", tags=["catalog"])
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


def err(message: str, status_code: int = 400, *, code: str = ""):
    body = {"ok": False, "error": message}
    if code:
        body["code"] = code
    return JSONResponse(body, status_code=status_code)


def _set_session_cookie(response: JSONResponse, state: AppState, token: str) -> None:
    response.set_cookie(
        _cookie_name(state),
        token,
        httponly=True,
        secure=state.runtime.cookie_secure,
        samesite="lax",
        path="/",
        max_age=SESSION_ABSOLUTE_DAYS * 24 * 3600,
    )


def _require_admin(request: Request) -> dict | JSONResponse:
    session = _session(request)
    if not session or str(session.get("role") or "") != ROLE_ADMIN:
        return err("需要管理员权限", 403, code="forbidden")
    return session


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


def _decorate_search_catalog(request: Request, data: dict) -> dict:
    state = _state(request)
    data = _decorate_search_items(state, data)
    items = data.get("items") or []
    keys = [str(item.get("bvid") or "").strip() for item in items]
    keys = [key for key in keys if key]
    tags_by_key = state.tag_store.tags_for_keys(keys)
    tombstones = state.deletion_store.for_keys(keys)
    restored: list[str] = []
    for item in items:
        key = str(item.get("bvid") or "").strip()
        item["tags"] = list(tags_by_key.get(key, []))
        item["deleted_record"] = False
        status = str(item.get("local_status") or "")
        if status == "downloaded":
            if key in tombstones:
                restored.append(key)
            continue
        if status in {"queued", "running"}:
            continue
        deleted = tombstones.get(key)
        if deleted:
            item.update(
                local_status="deleted",
                local_status_label="已删除",
                deleted_at=deleted.get("deleted_at"),
                deleted_record=True,
            )
    if restored:
        state.deletion_store.clear(restored)
    return data


def _remote(request: Request) -> str:
    return request.client.host if request.client else ""


def _audit(request: Request, action: str, detail: str = "") -> None:
    session = _session(request)
    _state(request).auth_store.audit(
        str(session.get("user_id")) if session else None,
        action,
        detail,
        _remote(request),
        session_id=str(session.get("session_id")) if session else None,
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
        record = state.task_store.export_record(str(task["id"])) or {}
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
            group = state.catalog_store.group_by_folder(
                str(task.get("group_folder") or "")
            ) or state.catalog_store.group_by_name(str(task.get("group") or ""))
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


# Authentication ---------------------------------------------------------
@account_router.get("/auth/status")
def auth_status(request: Request):
    state = _state(request)
    token = request.cookies.get(_cookie_name(state), "")
    return ok(state.auth_store.auth_status(token))


@account_router.post("/auth/setup")
def auth_setup(request: Request, body: AuthSetupRequest):
    state = _state(request)
    try:
        user = state.auth_store.setup_admin(
            body.username,
            body.password,
            body.bootstrap_token,
            body.display_name,
        )
        token, _session_data = state.auth_store.login(
            user["username"],
            body.password,
            remote_addr=_remote(request),
            user_agent=request.headers.get("user-agent", ""),
        )
    except RuntimeError as exc:
        return err(str(exc), 429)
    except ValueError as exc:
        return err(str(exc), 400)
    response = JSONResponse(ok(state.auth_store.auth_status(token)))
    _set_session_cookie(response, state, token)
    return response


@account_router.post("/auth/login")
def auth_login(request: Request, body: AuthLoginRequest):
    state = _state(request)
    try:
        token, _session_data = state.auth_store.login(
            body.username,
            body.password,
            remote_addr=_remote(request),
            user_agent=request.headers.get("user-agent", ""),
        )
    except RuntimeError as exc:
        return err(str(exc), 429)
    except ValueError as exc:
        return err(str(exc), 401, code="invalid_credentials")
    response = JSONResponse(ok(state.auth_store.auth_status(token)))
    _set_session_cookie(response, state, token)
    return response


@account_router.post("/auth/password")
def auth_change_password(request: Request, body: AuthPasswordChangeRequest):
    state = _state(request)
    session = _session(request)
    if not session:
        return err("请先登录", 401)
    try:
        result = state.auth_store.change_password(
            str(session["user_id"]),
            body.current_password,
            body.new_password,
            keep_session_id=str(session["session_id"]),
        )
    except (RuntimeError, ValueError) as exc:
        return err(str(exc), 400)
    token = str(result.pop("token"))
    rotated = result.pop("session")
    request.state.auth_session = rotated
    state.auth_store.audit(
        str(session["user_id"]),
        "auth.password.change",
        f"撤销其他会话 {result['other_sessions_revoked']} 个",
        _remote(request),
        session_id=str(session["session_id"]),
    )
    payload = state.auth_store.auth_status(token)
    payload["other_sessions_revoked"] = result["other_sessions_revoked"]
    response = JSONResponse(ok(payload))
    _set_session_cookie(response, state, token)
    return response


@account_router.patch("/auth/profile")
def auth_update_profile(request: Request, body: AuthProfileUpdateRequest):
    state = _state(request)
    session = _session(request)
    if not session:
        return err("请先登录", 401)
    try:
        user = state.auth_store.update_profile(str(session["user_id"]), body.display_name)
    except (KeyError, ValueError) as exc:
        return err(str(exc), 400)
    state.auth_store.audit(
        str(session["user_id"]),
        "auth.profile.update",
        "修改中文显示名",
        _remote(request),
        session_id=str(session["session_id"]),
    )
    return ok(user)


@account_router.get("/auth/sessions")
def auth_sessions(request: Request):
    state = _state(request)
    session = _session(request)
    if not session:
        return err("请先登录", 401)
    return ok(
        {
            "items": state.auth_store.list_sessions(
                str(session["user_id"]), str(session["session_id"])
            ),
            "limit": 10,
        }
    )


@account_router.delete("/auth/sessions/{session_id}")
def auth_revoke_session(request: Request, session_id: str):
    state = _state(request)
    session = _session(request)
    if not session:
        return err("请先登录", 401)
    try:
        revoked = state.auth_store.revoke_session(
            str(session["user_id"]),
            session_id,
            current_session_id=str(session["session_id"]),
        )
    except ValueError as exc:
        return err(str(exc), 400)
    if not revoked:
        return err("会话不存在或已经失效", 404)
    state.auth_store.audit(
        str(session["user_id"]),
        "auth.session.revoke",
        "撤销其他设备",
        _remote(request),
        session_id=session_id,
    )
    return ok({"revoked": True})


@account_router.post("/auth/sessions/revoke-others")
def auth_revoke_other_sessions(request: Request):
    state = _state(request)
    session = _session(request)
    if not session:
        return err("请先登录", 401)
    count = state.auth_store.revoke_other_sessions(
        str(session["user_id"]), str(session["session_id"])
    )
    state.auth_store.audit(
        str(session["user_id"]),
        "auth.session.revoke_others",
        f"撤销其他会话 {count} 个",
        _remote(request),
        session_id=str(session["session_id"]),
    )
    return ok({"revoked": count})


@account_router.post("/auth/logout")
def auth_logout(request: Request):
    state = _state(request)
    session = _session(request)
    if session:
        state.auth_store.audit(
            str(session["user_id"]),
            "auth.logout",
            "退出当前设备",
            _remote(request),
            session_id=str(session["session_id"]),
        )
        state.auth_store.logout(str(session["session_id"]))
    response = JSONResponse(ok({"logged_out": True}))
    response.delete_cookie(
        _cookie_name(state),
        path="/",
        secure=state.runtime.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@account_router.get("/admin/users")
def admin_list_users(request: Request):
    admin = _require_admin(request)
    if isinstance(admin, JSONResponse):
        return admin
    return ok({"items": _state(request).auth_store.list_users()})


@account_router.post("/admin/users")
def admin_create_user(request: Request, body: AdminUserCreateRequest):
    admin = _require_admin(request)
    if isinstance(admin, JSONResponse):
        return admin
    state = _state(request)
    try:
        user = state.auth_store.create_user(
            body.username,
            body.display_name,
            body.temporary_password,
            created_by=str(admin["user_id"]),
        )
    except ValueError as exc:
        return err(str(exc), 400)
    state.auth_store.audit(
        str(admin["user_id"]),
        "admin.user.create",
        user["username"],
        _remote(request),
        session_id=str(admin["session_id"]),
        target_user_id=user["id"],
    )
    return ok(user)


@account_router.patch("/admin/users/{user_id}")
def admin_update_user(request: Request, user_id: str, body: AdminUserUpdateRequest):
    admin = _require_admin(request)
    if isinstance(admin, JSONResponse):
        return admin
    state = _state(request)
    try:
        user = None
        if body.display_name is not None:
            user = state.auth_store.set_user_display_name(user_id, body.display_name)
        if body.disabled is not None:
            user = state.auth_store.set_user_disabled(
                user_id, body.disabled, actor_user_id=str(admin["user_id"])
            )
        if user is None:
            return err("没有可更新字段", 400)
    except KeyError as exc:
        return err(str(exc), 404)
    except ValueError as exc:
        return err(str(exc), 400)
    return ok(user)


@account_router.post("/admin/users/{user_id}/reset-password")
def admin_reset_user_password(
    request: Request, user_id: str, body: AdminPasswordResetRequest
):
    admin = _require_admin(request)
    if isinstance(admin, JSONResponse):
        return admin
    try:
        result = _state(request).auth_store.reset_user_password(
            user_id,
            body.temporary_password,
            actor_user_id=str(admin["user_id"]),
        )
    except KeyError as exc:
        return err(str(exc), 404)
    except ValueError as exc:
        return err(str(exc), 400)
    return ok(result)


@account_router.post("/admin/users/{user_id}/revoke-sessions")
def admin_revoke_user_sessions(request: Request, user_id: str):
    admin = _require_admin(request)
    if isinstance(admin, JSONResponse):
        return admin
    state = _state(request)
    if user_id == str(admin["user_id"]):
        return err("不能通过管理员接口撤销当前管理员全部会话", 400)
    count = state.auth_store.revoke_all_sessions(user_id, "admin_revoke")
    state.auth_store.audit(
        str(admin["user_id"]),
        "admin.user.sessions_revoke",
        f"撤销会话 {count} 个",
        _remote(request),
        session_id=str(admin["session_id"]),
        target_user_id=user_id,
    )
    return ok({"revoked": count})


# Status/config/search ----------------------------------------------------
def status_response(request: Request, refresh_login: bool = False):
    state = _state(request)
    cfg = state.config_store.get()
    cookie = state.cookie_checker.status(force=refresh_login)
    state.catalog_store.sync_index()
    records = _decorate_group_task_counts(state, state.catalog_store.list_groups())
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
            "storage": state.catalog_store.storage_status(),
            **state.readiness(),
        }
    )


@system_router.get("/config")
def get_config(request: Request):
    state = _state(request)
    config = state.config_store.as_dict()
    config["app_mode"] = state.runtime.mode
    config["public_base_url"] = state.runtime.public_base_url
    config["auth_required"] = state.runtime.auth_required
    config["temp_dir"] = str(state.runtime.temp_dir)
    config["cache_dir"] = str(state.runtime.cache_dir)
    config["export_ttl_sec"] = state.runtime.export_ttl_sec
    protected_fields = ["host", "bbdown_dir"]
    if state.runtime.server_mode or state.runtime.launcher_managed:
        protected_fields.extend(["port", "download_dir"])
    return ok(config, protected_fields=protected_fields)


@system_router.put("/config")
def put_config(request: Request, body: ConfigUpdate):
    state = _state(request)
    patch = body.as_patch()
    if not patch:
        return err("没有可更新的字段")
    if state.runtime.launcher_managed and any(
        key in patch for key in ("port", "download_dir")
    ):
        return err("启动器模式的端口和数据目录只能在 Windows 启动器中管理", 409)
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


@catalog_router.get("/search")
def api_search(
    request: Request,
    q: str = Query(default="", max_length=100),
    order: str = Query(default="totalrank", max_length=32),
    page: int = Query(default=1, ge=1, le=1000),
    fresh: bool = Query(default=False),
):
    state = _state(request)
    try:
        data = search_videos(
            q,
            order=order,
            page=page,
            bbdown_dir=state.runtime.bbdown_credentials_dir,
            fresh=fresh,
        )
        data = _decorate_search_catalog(request, data)
    except SearchError as exc:
        return err(str(exc))
    except Exception as exc:  # noqa: BLE001
        return err(f"搜索失败: {exc}", 502)
    return ok(data)


# Groups ------------------------------------------------------------------
@catalog_router.get("/groups")
def api_groups(request: Request):
    state = _state(request)
    cfg = state.config_store.get()
    state.catalog_store.sync_index()
    records = _decorate_group_task_counts(state, state.catalog_store.list_groups())
    return ok(
        {
            "default_group": cfg.default_group,
            "default_min_height": cfg.default_min_height,
            "items": [item["display_name"] for item in records],
            "records": records,
        }
    )


@catalog_router.post("/groups")
def api_create_group(request: Request, body: GroupCreateRequest):
    try:
        group = _state(request).catalog_store.create_group(body.name)
    except ValueError as exc:
        return err(str(exc))
    _audit(request, "group.create", str(group.get("display_name") or body.name))
    return ok(group)


@catalog_router.patch("/groups/{group_id}")
def api_rename_group(request: Request, group_id: str, body: GroupRenameRequest):
    state = _state(request)
    before = state.catalog_store.get_group(group_id)
    try:
        group = state.catalog_store.rename_group(group_id, body.name)
        if before and state.config_store.get().default_group.casefold() == str(before["display_name"]).casefold():
            state.config_store.update({"default_group": group["display_name"]})
    except KeyError as exc:
        return err(str(exc), 404)
    except ValueError as exc:
        return err(str(exc), 409)
    _audit(request, "group.rename", f"{before.get('display_name') if before else group_id} -> {group['display_name']}")
    return ok(group)


@catalog_router.post("/groups/{group_id}/merge")
def api_merge_group(request: Request, group_id: str, body: GroupMergeRequest):
    state = _state(request)
    source = state.catalog_store.get_group(group_id)
    try:
        group = state.catalog_store.merge_group(group_id, body.target_id)
        if source and state.config_store.get().default_group.casefold() == str(source["display_name"]).casefold():
            state.config_store.update({"default_group": group["display_name"]})
    except KeyError as exc:
        return err(str(exc), 404)
    except ValueError as exc:
        return err(str(exc), 409)
    _audit(request, "group.merge", f"{source.get('display_name') if source else group_id} -> {group['display_name']}")
    return ok(group)


@catalog_router.delete("/groups/{group_id}")
def api_delete_group(request: Request, group_id: str):
    state = _state(request)
    group = state.catalog_store.get_group(group_id)
    if group and state.config_store.get().default_group.casefold() == str(group["display_name"]).casefold():
        return err("当前默认分组不能删除，请先在设置中修改默认分组", 409)
    try:
        state.catalog_store.delete_group(group_id)
    except KeyError as exc:
        return err(str(exc), 404)
    except ValueError as exc:
        return err(str(exc), 409)
    _audit(request, "group.delete", str((group or {}).get("display_name") or group_id))
    return ok({"deleted": True})


# Preview/download/tasks --------------------------------------------------
def preview_response(request: Request, body: PreviewRequest):
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


# Cover proxy/cache --------------------------------------------------------
@catalog_router.get("/cover")
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
@catalog_router.get("/library/summary")
def api_library_summary(request: Request):
    return ok(_state(request).catalog_store.library_summary())


@catalog_router.get("/library")
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
        _state(request).catalog_store.library_list(
            page=page, page_size=page_size, query=q, group_id=group_id,
            sort=sort, user_id=_user_id(request), codec=codec,
            min_height=min_height, watched=watched,
        )
    )


@catalog_router.get("/library/{media_id}")
def api_media_detail(request: Request, media_id: str):
    value = _state(request).catalog_store.media_detail(media_id, _user_id(request))
    if not value:
        return err("作品不存在", 404)
    return ok(value)


@catalog_router.api_route("/media/{file_id}/stream", methods=["GET", "HEAD"])
def api_media_stream(request: Request, file_id: str):
    try:
        row, path = _state(request).catalog_store.resolve_media_file(file_id)
    except KeyError as exc:
        return err(str(exc), 404)
    except FileNotFoundError as exc:
        return err(str(exc), 404)
    return file_response(
        request, path, media_type=str(row["mime_type"]), filename=str(row["filename"]),
        attachment=False, allow_range=True,
    )


@catalog_router.api_route("/media/{file_id}/download", methods=["GET", "HEAD"])
def api_media_download(request: Request, file_id: str):
    try:
        row, path = _state(request).catalog_store.resolve_media_file(file_id)
    except KeyError as exc:
        return err(str(exc), 404)
    except FileNotFoundError as exc:
        return err(str(exc), 404)
    return file_response(
        request, path, media_type=str(row["mime_type"]), filename=str(row["filename"]),
        attachment=True, allow_range=True,
    )


@catalog_router.put("/library/{media_id}/progress")
def api_watch_progress(request: Request, media_id: str, body: WatchProgressRequest):
    try:
        data = _state(request).catalog_store.save_progress(
            _user_id(request), media_id, body.file_id, body.position_sec, body.duration_sec
        )
    except KeyError as exc:
        return err(str(exc), 404)
    return ok(data)


@catalog_router.post("/library/{media_id}/move")
def api_move_media(request: Request, media_id: str, body: MediaMoveRequest):
    try:
        data = _state(request).catalog_store.move_media(media_id, body.group_id)
    except KeyError as exc:
        return err(str(exc), 404)
    _audit(request, "media.move", f"media={media_id}; group={body.group_id}")
    return ok(data)


@catalog_router.post("/library/{media_id}/compatible")
def api_compatible(request: Request, media_id: str, body: CompatibleRequest):
    state = _state(request)
    ffmpeg = find_ffmpeg(state.runtime.bbdown_dir)
    if not ffmpeg:
        return err("未找到 FFmpeg", 503)
    try:
        job = state.catalog_store.start_compatible(media_id, body.file_id, ffmpeg)
    except KeyError as exc:
        return err(str(exc), 404)
    except ValueError as exc:
        return err(str(exc), 409)
    return ok(job)


@catalog_router.get("/transcodes/{job_id}")
def api_transcode_status(request: Request, job_id: str):
    job = _state(request).catalog_store.transcode_status(job_id)
    if not job:
        return err("转码任务不存在", 404)
    return ok(job)


# Bilibili account --------------------------------------------------------
@account_router.post("/account/bilibili/qr")
def api_bilibili_qr(request: Request):
    try:
        value = _state(request).qr_login.create()
        _audit(request, "bilibili.qr.create", str(value.get("id") or ""))
        return ok(value)
    except Exception as exc:  # noqa: BLE001
        return err(f"二维码创建失败: {exc}", 502)


@account_router.post("/account/bilibili/qr/{session_id}")
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


@account_router.delete("/account/bilibili")
def api_bilibili_logout(request: Request):
    state = _state(request)
    try:
        removed = state.qr_login.logout()
        state.cookie_checker.status(force=True)
    except ValueError as exc:
        return err(str(exc), 409)
    _audit(request, "bilibili.logout", f"removed={removed}")
    return ok({"removed": removed})


# Catalog enhancements ----------------------------------------------------
ShortText = Annotated[str, StringConstraints(max_length=300)]


class TagAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_key: ShortText = ""
    media_id: ShortText = ""
    tags: list[Annotated[str, StringConstraints(max_length=40)]] = Field(
        default_factory=list,
        max_length=50,
    )


class TagBulkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keys: list[ShortText] = Field(default_factory=list, max_length=500)
    media_ids: list[ShortText] = Field(default_factory=list, max_length=500)


class LibraryItemsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_ids: list[ShortText] = Field(default_factory=list, min_length=1, max_length=100)


class CatalogDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_ids: list[ShortText] = Field(default_factory=list, min_length=1, max_length=100)
    delete_files: bool = True
    mark_tag: Annotated[str, StringConstraints(max_length=40)] = ""


@catalog_router.get("/enhancements/tags")
def tags_list(request: Request):
    store = _state(request).tag_store
    return ok({"items": store.definitions(), "config_path": str(store.config_path)})


@catalog_router.post("/enhancements/tags/reload")
def tags_reload(request: Request):
    store = _state(request).tag_store
    return ok(
        {
            "items": store.reload_definitions(),
            "config_path": str(store.config_path),
        }
    )


@catalog_router.post("/enhancements/tags/bulk")
def tags_bulk(request: Request, body: TagBulkRequest):
    state = _state(request)
    media_keys = state.library_service.media_keys(body.media_ids)
    keys = list(dict.fromkeys([*body.keys, *media_keys.values()]))
    by_key = state.tag_store.tags_for_keys(keys)
    return ok(
        {
            "by_key": by_key,
            "by_media_id": {
                media_id: by_key.get(source_key, [])
                for media_id, source_key in media_keys.items()
            },
            "media_keys": media_keys,
        }
    )


@catalog_router.put("/enhancements/tags")
def tags_assign(request: Request, body: TagAssignmentRequest):
    state = _state(request)
    source_key = body.source_key.strip()
    if not source_key and body.media_id:
        source_key = state.library_service.media_keys([body.media_id]).get(
            body.media_id,
            "",
        )
    if not source_key:
        return err("作品不存在或作品标识为空", 404)
    try:
        selected = state.tag_store.set_tags(source_key, body.tags)
    except ValueError as exc:
        return err(str(exc))
    return ok({"source_key": source_key, "tags": selected})


@catalog_router.post("/enhancements/library/items")
def enhanced_library_items(request: Request, body: LibraryItemsRequest):
    return ok(_state(request).library_service.library_items(body.media_ids))


@catalog_router.get("/enhancements/library")
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
    return ok(
        _state(request).library_service.library_list(
            page=page,
            page_size=page_size,
            query=q,
            group_id=group_id,
            sort=sort,
            user_id=_user_id(request),
            codec=codec,
            min_height=min_height,
            watched=watched,
            tag=tag,
        )
    )


@catalog_router.post("/enhancements/library/delete")
def catalog_batch_delete(request: Request, body: CatalogDeleteRequest):
    data = _state(request).library_service.delete_many(
        body.media_ids,
        delete_files=body.delete_files,
        user_id=_user_id(request),
    )
    return ok(data, total=len(data["deleted"]))


@catalog_router.delete("/library/{media_id}")
def catalog_delete_media(
    request: Request,
    media_id: str,
    delete_files: bool = Query(default=False),
):
    try:
        return ok(
            _state(request).library_service.delete_media(
                media_id,
                delete_files=delete_files,
                user_id=_user_id(request),
            )
        )
    except KeyError as exc:
        return err(str(exc), 404)
    except (OSError, ValueError, RuntimeError) as exc:
        return err(str(exc), 409)


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
            for item in socket.getaddrinfo(
                socket.gethostname(),
                None,
                type=socket.SOCK_STREAM,
            )
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


@system_router.get("/enhancements/network")
def enhanced_network(request: Request):
    state = _state(request)
    cfg = state.config_store.get()
    addresses = _lan_addresses()
    urls = [
        f"http://[{address}]:{cfg.port}/"
        if ":" in address
        else f"http://{address}:{cfg.port}/"
        for address in addresses
    ]
    host = str(cfg.host)
    return ok(
        {
            "host": host,
            "port": cfg.port,
            "lan_enabled": host.strip("[]")
            not in {"127.0.0.1", "::1", "localhost"},
            "addresses": addresses,
            "urls": urls,
            "proxy_hint": "若电脑或手机开启代理，请把局域网网段和这些 IP 加入直连/绕过代理列表。",
        }
    )


@system_router.post("/enhancements/network/enable-lan")
def enhanced_enable_lan(request: Request):
    state = _state(request)
    if state.runtime.launcher_managed:
        return err("启动器模式的监听与安全配置只能在 Windows 启动器中修改", 409)
    data = state.config_store.persisted_dict()
    data["host"] = "0.0.0.0"
    atomic_write_json(state.config_store.path, data, backup=True)
    return ok(
        {
            "host": "0.0.0.0",
            "restart_required": True,
            "message": "已设置为监听所有网卡。请通过当前启动入口重启；重启后会强制启用管理员登录。",
        }
    )
