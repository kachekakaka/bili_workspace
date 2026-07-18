from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from app.bbdown import find_bbdown_exe, find_ffmpeg
from app.config import ConfigStore
from app.cover_cache import CoverCache
from app.cookie import CookieChecker
from app.index_store import IndexStore
from app.integrity import IntegrityStatus, verify_tool_manifest
from app.metadata import fetch_video_metadata
from app.nas import NasStore
from app.paths import ROOT
from app.qr_login import QrLoginManager
from app.queue import TaskQueue
from app.runtime import RuntimeSettings


def _label(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


@dataclass
class AppState:
    runtime: RuntimeSettings
    config_store: ConfigStore
    index: IndexStore
    queue: TaskQueue
    export_config_store: ConfigStore
    export_index: IndexStore
    export_queue: TaskQueue
    nas: NasStore
    cover_cache: CoverCache
    qr_login: QrLoginManager
    cookie_checker: CookieChecker
    tool_integrity: IntegrityStatus

    @classmethod
    def create(
        cls,
        *,
        config_path: Path | None = None,
        initial_config: dict | None = None,
        runner: Callable | None = None,
        cookie_checker: CookieChecker | None = None,
        metadata_fetcher: Callable | None = None,
    ) -> "AppState":
        runtime = RuntimeSettings.from_env()
        explicit_config_path = config_path is not None
        if config_path is None:
            config_path = runtime.config_dir / "config.json"

        startup_overrides: dict[str, object] = {}
        if runtime.server_mode:
            startup_overrides = {
                "host": runtime.host,
                "port": runtime.port,
                "download_dir": str(runtime.media_dir),
                "bbdown_dir": str(runtime.bbdown_dir),
            }
        store = ConfigStore(
            path=config_path,
            initial=initial_config,
            startup_overrides=startup_overrides,
            server_mode=runtime.server_mode,
        )
        cfg = store.get()

        # A non-loopback host in config automatically becomes authenticated
        # server mode, allowing phone/LAN access without an unsafe local bind.
        if store.server_mode and not runtime.server_mode:
            runtime = replace(
                runtime,
                mode="server",
                host=cfg.host,
                port=cfg.port,
                auth_required=True,
                allow_ip_hosts=True,
            )
        elif not runtime.server_mode:
            runtime = replace(runtime, host=cfg.host, port=cfg.port)

        # Tests and custom local configurations keep all V0.5 state beside their config.
        if explicit_config_path and not runtime.server_mode:
            base = Path(config_path).resolve().parent / ".v05_state"
            runtime = replace(
                runtime,
                config_dir=base,
                media_dir=cfg.download_path(),
                cache_dir=base / "cache",
                temp_dir=base / "tmp",
                database_path=base / "bili_workspace.db",
                auth_required=False,
                cookie_secure=False,
            )
            for directory in (
                runtime.config_dir,
                runtime.media_dir,
                runtime.cache_dir,
                runtime.temp_dir,
            ):
                directory.mkdir(parents=True, exist_ok=True)
        elif not runtime.server_mode:
            runtime = replace(runtime, media_dir=cfg.download_path())

        integrity = verify_tool_manifest(cfg.bbdown_path())
        if integrity.checked and not integrity.ok:
            raise RuntimeError("工具完整性校验失败: " + "; ".join(integrity.errors))
        index = IndexStore(cfg.download_path())
        fetcher = metadata_fetcher
        if fetcher is None and runner is None:
            fetcher = fetch_video_metadata

        export_root = (runtime.temp_dir / "exports").resolve()
        export_root.mkdir(parents=True, exist_ok=True)
        export_config = dict(store.as_dict())
        export_config["download_dir"] = str(export_root)
        export_config["default_group"] = "设备导出"
        export_store = ConfigStore(
            path=runtime.config_dir / ".export_runtime.json",
            initial=export_config,
            server_mode=runtime.server_mode,
            startup_overrides={
                "host": runtime.host,
                "port": runtime.port,
                "download_dir": str(export_root),
                "bbdown_dir": str(cfg.bbdown_path()),
            }
            if runtime.server_mode
            else None,
        )
        export_index = IndexStore(export_root)

        nas = NasStore(runtime, index)
        nas.bind_export_index(export_index)
        download_slots = threading.Semaphore(runtime.download_concurrency)
        queue = TaskQueue(
            store,
            index,
            runner=runner,
            metadata_fetcher=fetcher,
            initial_tasks=nas.load_task_snapshots("library"),
            on_state_change=lambda task_id, payload: nas.save_task_snapshot(
                "library", task_id, payload
            ),
            execution_semaphore=download_slots,
            min_free_bytes=runtime.min_free_bytes,
            worker_count=runtime.download_concurrency,
            worker_name="library-worker",
        )

        def persist_device_task(task_id: str, payload: dict | None) -> None:
            nas.save_task_snapshot("device", task_id, payload)
            nas.update_export_from_task(task_id, payload)

        export_queue = TaskQueue(
            export_store,
            export_index,
            runner=runner,
            metadata_fetcher=fetcher,
            initial_tasks=nas.load_task_snapshots("device"),
            on_state_change=persist_device_task,
            execution_semaphore=download_slots,
            min_free_bytes=runtime.min_free_bytes,
            worker_count=runtime.download_concurrency,
            worker_name="export-worker",
        )

        checker = cookie_checker or CookieChecker(lambda: store.get().bbdown_path())
        cover_cache = CoverCache(runtime.cache_dir / "covers")
        qr = QrLoginManager(lambda: store.get().bbdown_path())
        return cls(
            runtime=runtime,
            config_store=store,
            index=index,
            queue=queue,
            export_config_store=export_store,
            export_index=export_index,
            export_queue=export_queue,
            nas=nas,
            cover_cache=cover_cache,
            qr_login=qr,
            cookie_checker=checker,
            tool_integrity=integrity,
        )

    def stop(self) -> None:
        self.queue.stop()
        self.export_queue.stop()
        self.qr_login.stop()
        self.nas.close()

    def readiness(self) -> dict:
        cfg = self.config_store.get()
        bbdown_dir = cfg.bbdown_path()
        exe = find_bbdown_exe(bbdown_dir)
        ffmpeg = find_ffmpeg(bbdown_dir)
        return {
            "mode": self.runtime.mode,
            "server_mode": self.runtime.server_mode,
            "auth_required": self.runtime.auth_required,
            "public_base_url": self.runtime.public_base_url,
            "bbdown_ready": exe is not None,
            "bbdown_file": _label(exe) if exe else "BBDown_portable/BBDown.exe",
            "ffmpeg_ready": ffmpeg is not None,
            "ffmpeg_file": _label(ffmpeg),
            "download_dir": cfg.download_dir,
            "temp_dir": str(self.runtime.temp_dir),
            "cache_dir": str(self.runtime.cache_dir),
            "library": self.nas.library_summary(),
            "tool_integrity": self.tool_integrity.to_dict(),
        }
