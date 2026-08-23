import os
import sys
import threading
import time

import pytest

from app.bbdown import run_bbdown, run_bbdown_info
from app.config import AppConfig


def test_info_process_cancellation_uses_streaming_process_path(
    tmp_env, monkeypatch
):
    cfg = AppConfig(
        download_dir=str(tmp_env.download_dir),
        bbdown_dir=str(tmp_env.bbdown_dir),
        download_timeout_sec=30,
    )
    cancel = threading.Event()
    box = {}
    argv = [
        sys.executable,
        "-u",
        "-c",
        "import time; print('info-started', flush=True); time.sleep(30)",
    ]
    monkeypatch.setattr("app.bbdown.build_info_argv", lambda *_args, **_kwargs: argv)
    monkeypatch.setattr("app.bbdown.sync_credentials_to_tool_dir", lambda *_args: None)

    thread = threading.Thread(
        target=lambda: box.setdefault(
            "result",
            run_bbdown_info(
                "https://www.bilibili.com/video/BV1qt4y1X7TW",
                cfg,
                timeout=10,
                cancel_event=cancel,
            ),
        )
    )
    thread.start()
    time.sleep(0.3)
    cancel.set()
    thread.join(timeout=12)
    assert not thread.is_alive()
    assert box["result"].cancelled is True
    assert box["result"].ok is False
    assert "info-started" in box["result"].stdout


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX shebang fixture")
def test_real_process_can_be_cancelled_and_tree_is_terminated(tmp_env):
    script = tmp_env.bbdown_dir / "BBDown.exe"
    script.write_text("#!/bin/sh\necho started\nsleep 30\n", encoding="utf-8")
    script.chmod(0o755)
    cfg = AppConfig(
        download_dir=str(tmp_env.download_dir),
        bbdown_dir=str(tmp_env.bbdown_dir),
        download_timeout_sec=30,
    )
    cancel = threading.Event()
    box = {}

    def run():
        box["result"] = run_bbdown(
            "https://www.bilibili.com/video/BV1qt4y1X7TW",
            cfg,
            work_dir=tmp_env.download_dir / "work",
            timeout=10,
            cancel_event=cancel,
        )

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.3)
    cancel.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert box["result"].cancelled is True
    assert box["result"].ok is False


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX shebang fixture")
def test_real_info_process_can_be_cancelled_and_tree_is_terminated(tmp_env):
    script = tmp_env.bbdown_dir / "BBDown.exe"
    script.write_text("#!/bin/sh\necho info-started\nsleep 30\n", encoding="utf-8")
    script.chmod(0o755)
    cfg = AppConfig(
        download_dir=str(tmp_env.download_dir),
        bbdown_dir=str(tmp_env.bbdown_dir),
        download_timeout_sec=30,
    )
    cancel = threading.Event()
    box = {}

    thread = threading.Thread(
        target=lambda: box.setdefault(
            "result",
            run_bbdown_info(
                "https://www.bilibili.com/video/BV1qt4y1X7TW",
                cfg,
                timeout=10,
                cancel_event=cancel,
            ),
        )
    )
    thread.start()
    time.sleep(0.3)
    cancel.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert box["result"].cancelled is True
    assert box["result"].ok is False


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX shebang fixture")
def test_real_process_timeout_is_reported(tmp_env):
    script = tmp_env.bbdown_dir / "BBDown.exe"
    script.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
    script.chmod(0o755)
    cfg = AppConfig(download_dir=str(tmp_env.download_dir), bbdown_dir=str(tmp_env.bbdown_dir))
    result = run_bbdown(
        "https://www.bilibili.com/video/BV1qt4y1X7TW",
        cfg,
        work_dir=tmp_env.download_dir / "work-timeout",
        timeout=0.25,
    )
    assert result.timed_out is True
    assert result.ok is False
