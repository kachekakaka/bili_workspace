import os
import threading
import time

import pytest

from app.bbdown import run_bbdown
from app.config import AppConfig


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
