from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.cookie import CookieStatus
from app.main import create_app
from app.state import AppState


class StaticCookieChecker:
    def __init__(self, *, logged_in: bool = True):
        self.logged_in = logged_in

    def status(self, *, force: bool = False) -> CookieStatus:
        del force
        return CookieStatus(
            logged_in=self.logged_in,
            login_state="valid" if self.logged_in else "missing",
            file_present=self.logged_in,
            has_sessdata=self.logged_in,
            online_verified=self.logged_in,
            message="测试登录状态",
        )


@pytest.fixture
def tmp_env(tmp_path: Path):
    download_dir = tmp_path / "downloads"
    bbdown_dir = tmp_path / "BBDown_portable"
    bbdown_dir.mkdir()
    download_dir.mkdir()
    (bbdown_dir / "BBDown.exe").write_bytes(b"fake")
    ffmpeg = bbdown_dir / "ffmpeg" / "bin"
    ffmpeg.mkdir(parents=True)
    (ffmpeg / "ffmpeg.exe").write_bytes(b"fake")
    cookie = "SESS" + "DATA=fake-session; " + "bili" + "_jct=fake-csrf;"
    (bbdown_dir / "BBDown.data").write_text(cookie, encoding="utf-8")
    config_path = tmp_path / "config.json"
    initial = {
        "host": "127.0.0.1",
        "port": 3398,
        "download_dir": str(download_dir),
        "bbdown_dir": str(bbdown_dir),
        "poll_hint_ms": 500,
        "download_timeout_sec": 30,
        "dfn_priority": "",
        "encoding_priority": "",
        "default_group": "未分组",
        "default_min_height": 1080,
    }
    return SimpleNamespace(
        root=tmp_path,
        download_dir=download_dir,
        bbdown_dir=bbdown_dir,
        config_path=config_path,
        initial=initial,
    )


FAKE_INFO_OUTPUT = """
视频标题：测试作品标题
共计3条视频流.
0. [4K 超清] [3840x2160] [HEVC] [60] [18000kbps] [~1.2 GB]
1. [1080P 高清] [1920x1080] [AVC] [30] [6000kbps] [~450 MB]
2. [720P 高清] [1280x720] [AVC] [30] [2500kbps] [~180 MB]
"""


def artifact_runner(content: bytes = b"video"):
    def run(argv, **kwargs):
        del kwargs
        if "--only-show-info" in argv:
            return SimpleNamespace(returncode=0, stdout=FAKE_INFO_OUTPUT, stderr="")
        work_dir = Path(argv[argv.index("--work-dir") + 1])
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "demo.mp4").write_bytes(content)
        output = "[视频] [4K 超清] [3840x2160] [HEVC] [60] [18000kbps] [~1.2 GB]\n下载视频 100%"
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    run.supports_info = True
    run.supports_quality_output = True
    return run


def failing_runner(argv, **kwargs):
    del argv, kwargs
    return SimpleNamespace(returncode=1, stdout="", stderr="boom")


def wait_terminal(queue, task_id: str, timeout: float = 5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = queue.get_task(task_id)
        if task and task["status"] in {"success", "failed", "skipped", "cancelled"}:
            return task
        time.sleep(0.02)
    raise AssertionError(f"task did not finish: {task_id}")


@pytest.fixture
def client(tmp_env):
    state = AppState.create(
        config_path=tmp_env.config_path,
        initial_config=tmp_env.initial,
        runner=artifact_runner(),
        cookie_checker=StaticCookieChecker(logged_in=True),
    )
    app = create_app(state)
    with TestClient(app, base_url="http://127.0.0.1") as test_client:
        test_client.state_ref = state
        test_client.tmp_env = tmp_env
        yield test_client
    state.queue.stop()


@pytest.fixture
def fail_client(tmp_env):
    state = AppState.create(
        config_path=tmp_env.config_path,
        initial_config=tmp_env.initial,
        runner=failing_runner,
        cookie_checker=StaticCookieChecker(logged_in=False),
    )
    app = create_app(state)
    with TestClient(app, base_url="http://127.0.0.1") as test_client:
        test_client.state_ref = state
        yield test_client
    state.queue.stop()
