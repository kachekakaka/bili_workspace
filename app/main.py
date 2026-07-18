from __future__ import annotations

from contextlib import asynccontextmanager
import ipaddress

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import SESSION_COOKIE, router as api_router
from app.constants import MAX_REQUEST_BODY_BYTES
from app.enhancement_api import compat_router, router as enhancement_router
from app.paths import ROOT
from app.refinement_api import router as refinement_router
from app.state import AppState
from app.tag_store import TagStore

WEB_DIR = ROOT / "web"
_PUBLIC_API = {
    "/api/auth/status",
    "/api/auth/setup",
    "/api/auth/login",
}


def create_app(state: AppState | None = None) -> FastAPI:
    app_state = state or AppState.create()
    tag_store = TagStore(app_state.runtime)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        tag_store.close()
        app_state.stop()

    app = FastAPI(
        title="bili_workspace",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.app_state = app_state
    app.state.tag_store = tag_store

    def host_allowed(value: str) -> bool:
        raw = value.strip()
        if not raw:
            return False
        if raw.startswith("["):
            end = raw.find("]")
            if end < 0:
                return False
            hostname = raw[1:end]
            remainder = raw[end + 1 :]
            if remainder and (not remainder.startswith(":") or not remainder[1:].isdigit()):
                return False
        else:
            hostname = raw
            if raw.count(":") == 1:
                candidate, port = raw.rsplit(":", 1)
                if port.isdigit():
                    hostname = candidate
        hostname = hostname.rstrip(".").lower()
        trusted = {item.strip("[]").rstrip(".").lower() for item in app_state.runtime.trusted_hosts}
        if hostname in trusted:
            return True
        if app_state.runtime.allow_ip_hosts:
            try:
                ipaddress.ip_address(hostname)
                return True
            except ValueError:
                pass
        return False

    @app.middleware("http")
    async def security_and_auth(request: Request, call_next):
        response = None
        request.state.auth_session = None

        if not host_allowed(request.headers.get("host", "")):
            response = JSONResponse({"ok": False, "error": "Host 不受信任"}, status_code=400)

        if response is None and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            value = request.headers.get("content-length")
            if value:
                try:
                    if int(value) > MAX_REQUEST_BODY_BYTES:
                        response = JSONResponse(
                            {"ok": False, "error": "请求体过大"}, status_code=413
                        )
                except ValueError:
                    response = JSONResponse(
                        {"ok": False, "error": "Content-Length 无效"}, status_code=400
                    )

        if (
            response is None
            and app_state.runtime.auth_required
            and request.url.path.startswith("/api/")
            and request.url.path not in _PUBLIC_API
        ):
            cookie_name = (
                "__Host-bili_session"
                if app_state.runtime.cookie_secure
                else SESSION_COOKIE
            )
            session = app_state.nas.get_session(request.cookies.get(cookie_name, ""))
            if session is None:
                response = JSONResponse(
                    {"ok": False, "error": "请先登录"}, status_code=401
                )
            else:
                request.state.auth_session = session
                if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                    supplied = request.headers.get("x-csrf-token", "")
                    if not supplied or supplied != str(session["csrf_token"]):
                        response = JSONResponse(
                            {"ok": False, "error": "CSRF 校验失败，请刷新页面后重试"},
                            status_code=403,
                        )

        if response is None:
            response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        if app_state.runtime.hsts_enabled:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "version": __version__, "mode": app_state.runtime.mode}

    # Compatibility/refinement overrides must be registered before historical routes.
    app.include_router(refinement_router)
    app.include_router(compat_router)
    app.include_router(api_router)
    app.include_router(enhancement_router)

    if WEB_DIR.exists():
        @app.get("/")
        def index():
            return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-store"})

        @app.get("/m")
        @app.get("/m/")
        def mobile_index():
            return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-store"})

        if (WEB_DIR / "assets").exists():
            app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

    return app


def run() -> None:
    import uvicorn

    state = AppState.create()
    runtime = state.runtime
    app = create_app(state)
    uvicorn.run(
        app,
        host=runtime.host,
        port=runtime.port,
        log_level="info",
        proxy_headers=runtime.server_mode,
        forwarded_allow_ips=",".join(runtime.trusted_proxy_ips) if runtime.server_mode else "",
    )
