from __future__ import annotations

import os

import pytest

from app.bbdown import run_bbdown
from app.config import AppConfig
from app.progress import BbdownProgressParser


def test_progress_parser_handles_carriage_return_and_metrics():
    parser = BbdownProgressParser()
    events = parser.feed(
        "[下载视频] P1/3 25.5% 25 MiB / 100 MiB 4.2 MiB/s ETA 00:18\r"
        "[下载音频] 50% 5 MiB / 10 MiB 1.0 MiB/s 剩余 00:05\r"
        "FFmpeg 混流中\n"
    )
    video = next(event for event in events if event.phase == "download_video")
    assert video.progress_percent == 25.5
    assert video.current_part == 1 and video.part_total == 3
    assert video.downloaded_bytes == 25 * 1024 * 1024
    assert video.total_bytes == 100 * 1024 * 1024
    assert video.speed_text == "4.2 MiB/s"
    assert video.eta_text == "00:18"
    assert any(event.phase == "download_audio" for event in events)
    merge = next(event for event in events if event.phase == "merge")
    assert merge.progress_percent is None


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX shebang fixture")
def test_real_streaming_process_emits_structured_progress(tmp_env):
    script = tmp_env.bbdown_dir / "BBDown.exe"
    script.write_text(
        "#!/bin/sh\nprintf '[下载视频] 40%% 4 MiB / 10 MiB 2 MiB/s ETA 00:03\\r'\n"
        "sleep 0.1\nprintf 'FFmpeg 混流中\\n'\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    cfg = AppConfig(download_dir=str(tmp_env.download_dir), bbdown_dir=str(tmp_env.bbdown_dir))
    events = []
    result = run_bbdown(
        "https://www.bilibili.com/video/BV1qt4y1X7TW",
        cfg,
        work_dir=tmp_env.download_dir / "progress-work",
        timeout=5,
        on_progress=events.append,
    )
    assert result.ok is True
    assert any(event.phase == "download_video" and event.progress_percent == 40 for event in events)
    assert any(event.phase == "merge" for event in events)
