from __future__ import annotations

import secrets
import threading
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

import httpx

from app.io_utils import atomic_write_text

_GENERATE = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
_POLL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class QrLoginManager:
    """Bilibili web QR flow. Full cookies are never returned to the browser."""

    def __init__(self, bbdown_dir_getter):
        self._get_dir = bbdown_dir_getter
        self._lock = threading.RLock()
        self._sessions: dict[str, dict] = {}

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=10,
            follow_redirects=False,
            trust_env=False,
            headers={
                "User-Agent": _UA,
                "Referer": "https://passport.bilibili.com/login",
                "Accept": "application/json,text/plain,*/*",
            },
        )

    def create(self) -> dict:
        client = self._client()
        try:
            response = client.get(_GENERATE)
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") or {}
            login_url = str(data.get("url") or "").strip()
            key = str(data.get("qrcode_key") or "").strip()
            if payload.get("code") != 0 or not login_url or not key:
                raise RuntimeError(str(payload.get("message") or "二维码生成失败"))
        except Exception:
            client.close()
            raise
        session_id = "qr_" + secrets.token_urlsafe(18)
        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            if len(self._sessions) >= 5:
                client.close()
                raise RuntimeError("正在进行的二维码会话过多，请关闭旧二维码后重试")
            self._sessions[session_id] = {
                "client": client,
                "key": key,
                "login_url": login_url,
                "status": "waiting",
                "expires_at": now + 180,
            }
        return {
            "id": session_id,
            "login_url": login_url,
            "status": "waiting",
            "status_label": "等待扫码",
            "expires_at": now + 180,
        }

    def poll(self, session_id: str) -> dict:
        with self._lock:
            self._cleanup_locked(time.time())
            session = self._sessions.get(session_id)
            if not session:
                raise KeyError("二维码会话不存在或已过期")
            client: httpx.Client = session["client"]
            key = session["key"]
        response = client.get(_POLL, params={"qrcode_key": key})
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(str(payload.get("message") or "扫码状态查询失败"))
        data = payload.get("data") or {}
        if "code" not in data:
            raise RuntimeError("扫码状态响应缺少状态码")
        code = int(data["code"])
        status, label = {
            86101: ("waiting", "等待扫码"),
            86090: ("scanned", "已扫码，请在手机确认"),
            86038: ("expired", "二维码已过期"),
            0: ("success", "登录成功"),
        }.get(code, ("waiting", str(data.get("message") or "等待确认")))
        if status == "success":
            self._persist(client, str(data.get("url") or ""))
        with self._lock:
            current = self._sessions.get(session_id)
            if current:
                current["status"] = status
                if status in {"success", "expired"}:
                    current["expires_at"] = time.time() + 10
        return {
            "id": session_id,
            "status": status,
            "status_label": label,
            "message": str(data.get("message") or label),
            "expires_at": float(current["expires_at"]) if current else time.time(),
        }

    def _persist(self, client: httpx.Client, success_url: str) -> None:
        values: dict[str, str] = {str(item.name): str(item.value) for item in client.cookies.jar}
        if success_url:
            for key, value in parse_qsl(urlparse(success_url).query, keep_blank_values=False):
                if key in {"SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"}:
                    values[key] = value
        if not {"SESSDATA", "bili_jct"}.issubset(values):
            raise RuntimeError("手机已确认，但没有取得完整登录 Cookie")
        clean: dict[str, str] = {}
        for name, value in values.items():
            if not name or any(ch in name for ch in "=;\r\n"):
                continue
            if not value or any(ch in value for ch in ";\r\n") or len(value) > 16_384:
                raise RuntimeError("登录 Cookie 格式异常，拒绝写入凭据文件")
            clean[name] = value
        preferred = ["SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"]
        parts = [f"{name}={clean[name]}" for name in preferred if clean.get(name)]
        parts += [
            f"{name}={value}"
            for name, value in sorted(clean.items())
            if name not in preferred and value
        ]
        if sum(len(item) + 2 for item in parts) > 64 * 1024:
            raise RuntimeError("登录 Cookie 总长度异常，拒绝写入凭据文件")
        directory = Path(self._get_dir()).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / "BBDown.data"
        # Credential files deliberately have no plaintext backup copy.
        atomic_write_text(destination, "; ".join(parts) + ";", backup=False)
        try:
            destination.chmod(0o600)
        except OSError:
            pass

    def logout(self) -> bool:
        path = Path(self._get_dir()).resolve() / "BBDown.data"
        removed = False
        for candidate in (path, path.with_suffix(path.suffix + ".bak")):
            if not candidate.exists():
                continue
            if candidate.is_symlink() or not candidate.is_file():
                raise ValueError(f"{candidate.name} 类型异常，拒绝删除")
            candidate.unlink()
            removed = True
        return removed

    def _cleanup_locked(self, now: float) -> None:
        stale = [key for key, value in self._sessions.items() if value["expires_at"] <= now]
        for key in stale:
            session = self._sessions.pop(key, None)
            if session:
                try:
                    session["client"].close()
                except Exception:
                    pass

    def stop(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            try:
                session["client"].close()
            except Exception:
                pass
