from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
COOKIE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class CookieStatus:
    logged_in: bool
    login_state: str  # missing|malformed|valid|invalid|unknown
    file_present: bool
    has_sessdata: bool
    online_verified: bool
    message: str
    file_label: str = "BBDown_portable/BBDown.data"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def cookie_file(bbdown_dir: Path) -> Path:
    return Path(bbdown_dir) / "BBDown.data"


def read_cookie_string(bbdown_dir: Path) -> str:
    path = cookie_file(bbdown_dir)
    if not path.is_file() or path.is_symlink():
        return ""
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    return text.replace("\r", "").replace("\n", "")


def _offline_status(bbdown_dir: Path) -> tuple[Path, str, CookieStatus | None]:
    path = cookie_file(bbdown_dir)
    if not path.is_file() or path.is_symlink():
        return path, "", CookieStatus(
            logged_in=False,
            login_state="missing",
            file_present=False,
            has_sessdata=False,
            online_verified=False,
            message="未找到登录文件；请在网站账号页扫码登录，命令行备用入口见 scripts/windows/bilibili-login.bat",
        )
    raw = read_cookie_string(bbdown_dir)
    marker = "SESS" + "DATA="
    has_sess = marker in raw
    if not has_sess:
        return path, raw, CookieStatus(
            logged_in=False,
            login_state="malformed",
            file_present=True,
            has_sessdata=False,
            online_verified=False,
            message="登录文件存在，但缺少必要会话字段，请重新登录",
        )
    return path, raw, None


def check_cookie_status(
    bbdown_dir: Path,
    *,
    client: httpx.Client | Any | None = None,
) -> CookieStatus:
    _path, raw, early = _offline_status(bbdown_dir)
    if early is not None:
        return early

    owns_client = client is None
    client = client or httpx.Client(timeout=5.0, trust_env=False)
    try:
        response = client.get(
            NAV_URL,
            headers={
                "User-Agent": COOKIE_UA,
                "Referer": "https://www.bilibili.com/",
                "Cookie": raw,
            },
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") or {}
        valid = payload.get("code") == 0 and data.get("isLogin") is True
        if valid:
            return CookieStatus(
                logged_in=True,
                login_state="valid",
                file_present=True,
                has_sessdata=True,
                online_verified=True,
                message="登录状态已在线验证",
            )
        return CookieStatus(
            logged_in=False,
            login_state="invalid",
            file_present=True,
            has_sessdata=True,
            online_verified=True,
            message="登录文件已失效或未登录，请在网站账号页重新扫码登录",
        )
    except Exception as exc:  # noqa: BLE001
        reason = str(exc).strip().replace("\n", " ")[:180]
        return CookieStatus(
            logged_in=False,
            login_state="unknown",
            file_present=True,
            has_sessdata=True,
            online_verified=False,
            message=f"检测到登录文件，但在线验证失败{': ' + reason if reason else ''}",
        )
    finally:
        if owns_client:
            client.close()


class CookieChecker:
    def __init__(self, bbdown_dir_getter, *, ttl_sec: float = 300.0, client=None):
        self._bbdown_dir_getter = bbdown_dir_getter
        self._ttl_sec = max(1.0, float(ttl_sec))
        self._client = client
        self._lock = threading.RLock()
        self._cached: CookieStatus | None = None
        self._cached_at = 0.0
        self._signature: tuple[bool, int, int] | None = None

    def _file_signature(self, directory: Path) -> tuple[bool, int, int]:
        path = cookie_file(directory)
        try:
            stat = path.stat()
            return True, stat.st_mtime_ns, stat.st_size
        except OSError:
            return False, 0, 0

    def status(self, *, force: bool = False) -> CookieStatus:
        directory = Path(self._bbdown_dir_getter())
        signature = self._file_signature(directory)
        now = time.monotonic()
        with self._lock:
            if (
                not force
                and self._cached is not None
                and signature == self._signature
                and now - self._cached_at < self._ttl_sec
            ):
                return self._cached
            result = check_cookie_status(directory, client=self._client)
            self._cached = result
            self._cached_at = now
            self._signature = signature
            return result
