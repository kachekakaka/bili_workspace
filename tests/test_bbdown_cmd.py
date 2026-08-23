
import io
import os
import subprocess
import threading

from app.bbdown import (
    _decode_output,
    _EncodingProbe,
    build_argv,
    run_bbdown,
    run_bbdown_info,
    sync_credentials_to_tool_dir,
)
from app.config import AppConfig
from app.constants import MAX_INFO_OUTPUT_CHARS, MAX_LOG_TAIL_CHARS

GBK_INFO = (
    "视频标题：测试作品标题\n"
    "共计1条视频流.\n"
    "0. [1080P 高清] [1920x1080] [HEVC] [30] [7000kbps] [~500 MB]\n"
).encode("gbk")
GBK_STREAM = (
    "BBDown version 1.6.3, Bilibili Downloader.\n"
    "[2026-08-15 12:00:00.000] - 检测账号登录...\n"
    "下载视频 100%\n"
).encode("gbk")


def test_build_argv_uses_isolated_work_dir(tmp_env):
    work = tmp_env.download_dir / ".bili_tmp" / "task"
    cfg = AppConfig(
        download_dir=str(tmp_env.download_dir),
        bbdown_dir=str(tmp_env.bbdown_dir),
        dfn_priority="1080P 高清",
        encoding_priority="hevc,avc",
    )
    argv = build_argv(
        "https://www.bilibili.com/video/BV1qt4y1X7TW", cfg, work_dir=work
    )
    assert argv[argv.index("--work-dir") + 1] == str(work.resolve())
    assert "--file-pattern" in argv and "<videoTitle>" in argv[argv.index("--file-pattern") + 1]
    assert "--ffmpeg-path" in argv
    assert "--dfn-priority" in argv and "1080P 高清" in argv
    assert "--encoding-priority" in argv


def test_probe_detects_gbk_output():
    probe = _EncodingProbe()
    decision = probe.feed(b"BBDown version 1.6.3\n" + GBK_INFO)
    assert decision is not None
    encoding, payload = decision
    assert encoding == "gbk"
    assert "检测账号登录" in payload.decode("gbk") or "视频标题" in payload.decode("gbk")


def test_probe_detects_utf8_output():
    probe = _EncodingProbe()
    decision = probe.feed("视频标题：测试作品标题\n".encode("utf-8"))
    assert decision is not None
    encoding, payload = decision
    assert encoding == "utf-8"


def test_probe_waits_across_chunk_boundary():
    text = "视频标题：测试".encode("utf-8")
    probe = _EncodingProbe()
    assert probe.feed(text[:-1]) is None
    decision = probe.feed(text[-1:])
    assert decision is not None
    assert decision[0] == "utf-8"


def test_decode_output_recovers_gbk_chinese():
    decoded = _decode_output(GBK_INFO)
    assert "视频标题：测试作品标题" in decoded
    assert "\ufffd" not in decoded


def test_sync_credentials_copies_to_tool_dir(tmp_path):
    credential_dir = tmp_path / "credentials"
    tool_dir = tmp_path / "tools"
    credential_dir.mkdir()
    tool_dir.mkdir()
    cookie = "SESS" + "DATA=abc; " + "bili" + "_jct=def;"
    (credential_dir / "BBDown.data").write_text(cookie, encoding="utf-8")
    sync_credentials_to_tool_dir(credential_dir, tool_dir)
    assert (tool_dir / "BBDown.data").read_text(encoding="utf-8") == cookie


def test_sync_credentials_removes_stale_copy(tmp_path):
    credential_dir = tmp_path / "credentials"
    tool_dir = tmp_path / "tools"
    credential_dir.mkdir()
    tool_dir.mkdir()
    stale = tool_dir / "BBDown.data"
    stale.write_text("stale", encoding="utf-8")
    sync_credentials_to_tool_dir(credential_dir, tool_dir)
    assert not stale.exists()


def test_sync_credentials_same_directory_is_noop(tmp_path):
    directory = tmp_path / "both"
    directory.mkdir()
    data = directory / "BBDown.data"
    data.write_text("cookie", encoding="utf-8")
    sync_credentials_to_tool_dir(directory, directory)
    assert data.read_text(encoding="utf-8") == "cookie"


def test_sync_credentials_tolerates_copy_failure(tmp_path, monkeypatch, capsys):
    credential_dir = tmp_path / "credentials"
    tool_dir = tmp_path / "tools"
    credential_dir.mkdir()
    tool_dir.mkdir()
    (credential_dir / "BBDown.data").write_text("cookie", encoding="utf-8")

    def broken_replace(source, destination):
        raise OSError("injected failure")

    monkeypatch.setattr("app.bbdown.os.replace", broken_replace)
    sync_credentials_to_tool_dir(credential_dir, tool_dir)
    assert "凭据同步失败" in capsys.readouterr().err


def test_run_bbdown_info_suppresses_window_and_decodes_gbk(tmp_env, monkeypatch):
    cfg = AppConfig(
        download_dir=str(tmp_env.download_dir),
        bbdown_dir=str(tmp_env.bbdown_dir),
    )
    captured = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["creationflags"] = kwargs.get("creationflags", 0)
        process = _FakePopen(argv, **kwargs)
        process.stdout = _FakeStream(GBK_INFO)
        return process

    monkeypatch.setattr("app.bbdown.subprocess.Popen", fake_popen)
    result = run_bbdown_info("https://www.bilibili.com/video/BV1qt4y1X7TW", cfg)
    assert result.ok
    assert "视频标题：测试作品标题" in result.stdout
    assert "\ufffd" not in result.stdout
    if os.name == "nt":
        assert captured["creationflags"] & subprocess.CREATE_NO_WINDOW


def test_run_bbdown_info_keeps_more_than_download_log_tail(tmp_env, monkeypatch):
    cfg = AppConfig(
        download_dir=str(tmp_env.download_dir),
        bbdown_dir=str(tmp_env.bbdown_dir),
    )
    payload = ("视频标题：长输出\n" + "x" * (MAX_LOG_TAIL_CHARS + 8192)).encode("utf-8")

    def fake_popen(argv, **kwargs):
        process = _FakePopen(argv, **kwargs)
        process.stdout = _FakeStream(payload)
        return process

    monkeypatch.setattr("app.bbdown.subprocess.Popen", fake_popen)
    result = run_bbdown_info("https://www.bilibili.com/video/BV1qt4y1X7TW", cfg)
    assert result.ok
    assert len(result.stdout) > MAX_LOG_TAIL_CHARS
    assert len(result.stdout) <= MAX_INFO_OUTPUT_CHARS
    assert "视频标题：长输出" in result.stdout


def test_run_bbdown_info_passes_cancellation_to_opted_in_runner(tmp_env):
    cfg = AppConfig(
        download_dir=str(tmp_env.download_dir),
        bbdown_dir=str(tmp_env.bbdown_dir),
    )
    cancel = threading.Event()
    started = threading.Event()
    box = {}

    def runner(argv, **kwargs):
        del argv
        received = kwargs.get("cancel_event")
        assert received is cancel
        started.set()
        received.wait(timeout=2)
        return type("Completed", (), {"returncode": 1, "stdout": "stopped", "stderr": ""})()

    runner.supports_info = True
    runner.supports_cancel_event = True

    thread = threading.Thread(
        target=lambda: box.setdefault(
            "result",
            run_bbdown_info(
                "https://www.bilibili.com/video/BV1qt4y1X7TW",
                cfg,
                runner=runner,
                cancel_event=cancel,
            ),
        )
    )
    thread.start()
    assert started.wait(timeout=1)
    cancel.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert box["result"].cancelled is True
    assert box["result"].ok is False


class _FakeStream:
    def __init__(self, data: bytes):
        self._buffer = io.BytesIO(data)
        self.eof = False

    def read(self, size: int = -1) -> bytes:
        chunk = self._buffer.read(size)
        if not chunk:
            self.eof = True
        return chunk

    def close(self) -> None:
        self._buffer.close()


class _FakePopen:
    def __init__(self, argv, **kwargs):
        self.argv = argv
        self.creationflags = kwargs.get("creationflags", 0)
        self.cwd = kwargs.get("cwd")
        self.stdout = _FakeStream(GBK_STREAM)
        self.pid = 1
        self.returncode = 0

    def poll(self):
        return 0 if self.stdout.eof else None

    def wait(self, timeout=None):
        return 0


def test_run_bbdown_suppresses_window_and_decodes_gbk(tmp_env, monkeypatch):
    cfg = AppConfig(
        download_dir=str(tmp_env.download_dir),
        bbdown_dir=str(tmp_env.bbdown_dir),
    )
    captured = {}

    def fake_popen(argv, **kwargs):
        captured["creationflags"] = kwargs.get("creationflags", 0)
        captured["cwd"] = kwargs.get("cwd")
        return _FakePopen(argv, **kwargs)

    monkeypatch.setattr("app.bbdown.subprocess.Popen", fake_popen)
    collected = []
    result = run_bbdown(
        "https://www.bilibili.com/video/BV1qt4y1X7TW",
        cfg,
        on_output=collected.append,
    )
    assert result.ok
    text = "".join(collected)
    assert "检测账号登录" in text
    assert "\ufffd" not in text
    if os.name == "nt":
        assert captured["creationflags"] & subprocess.CREATE_NO_WINDOW
