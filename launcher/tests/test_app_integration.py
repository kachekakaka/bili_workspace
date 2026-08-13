from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.bbdown import find_ffmpeg, run_bbdown_info
from app.api import api_search, get_config, put_config
from app.config import AppConfig
from app.models import ConfigUpdate
from app.nas import _compatible_video_encode_args
from app.state import AppState
from bili_workspace_launcher.paths import AppPaths, DataRootManager


def _fake_tools(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "BBDown.exe").write_bytes(b"fake")
    ffmpeg = root / "ffmpeg" / "bin"
    ffmpeg.mkdir(parents=True)
    (ffmpeg / "ffmpeg.exe").write_bytes(b"fake")
    return root


def test_launcher_child_uses_only_explicit_data_and_tool_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = AppPaths(tmp_path / "control")
    layout = DataRootManager(paths).prepare(tmp_path / "data")
    tools = _fake_tools(tmp_path / "control" / "resources" / "0123456789ab" / "windows-tools")
    legacy_database = layout.config_dir / "bili_workspace.db"
    legacy_database.write_bytes(b"legacy-do-not-move")
    legacy_index = layout.downloads_dir / ".bili_index.json"
    legacy_index.write_text('{"items": {}}', encoding="utf-8")

    values = {
        "BILI_LAUNCHER_CHILD": "1",
        "BILI_DISABLE_LEGACY_MIGRATION": "1",
        "BILI_APP_MODE": "local",
        "BILI_HOST": "127.0.0.1",
        "BILI_PORT": "3398",
        "BILI_CONFIG_DIR": str(layout.config_dir),
        "BILI_USERDATA_DIR": str(layout.userdata_dir),
        "BILI_DATABASE_PATH": str(layout.userdata_dir / "bili_workspace.db"),
        "BILI_MEDIA_DIR": str(layout.downloads_dir),
        "BILI_CACHE_DIR": str(layout.userdata_dir / "cache"),
        "BILI_TEMP_DIR": str(layout.userdata_dir / "tmp"),
        "BILI_BBDOWN_TOOLS_DIR": str(tools),
        "BILI_BBDOWN_DATA_DIR": str(layout.bbdown_data_dir),
        "BILI_TRUSTED_HOSTS": "127.0.0.1,localhost,testserver",
        "BILI_TRUSTED_PROXY_IPS": "127.0.0.1",
        "BILI_PUBLIC_BASE_URL": "",
        "BILI_ALLOW_IP_HOSTS": "false",
        "BILI_COOKIE_SECURE": "false",
        "BILI_HSTS": "false",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    state = AppState.create(
        runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="test"),
        cookie_checker=object(),
    )
    try:
        cfg = state.config_store.get()
        assert cfg.download_path() == layout.downloads_dir
        assert cfg.bbdown_path() == tools
        assert state.runtime.bbdown_credentials_dir == layout.bbdown_data_dir
        assert state.runtime.database_path == layout.userdata_dir / "bili_workspace.db"
        persisted = json.loads(layout.config_file.read_text(encoding="utf-8"))
        assert persisted["download_dir"] == "downloads"
        assert persisted["bbdown_dir"] == "bbdown"
        with pytest.raises(ValueError, match="不可通过网页修改"):
            state.config_store.update({"download_dir": str(tmp_path / "escape")})
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(app_state=state)))
        config_response = get_config(request)
        assert set(config_response["protected_fields"]) == {
            "host",
            "port",
            "bbdown_dir",
            "download_dir",
        }
        rejected = put_config(request, ConfigUpdate(port=3400))
        assert rejected.status_code == 409
        assert b"Windows" in rejected.body
        assert legacy_database.read_bytes() == b"legacy-do-not-move"
        assert legacy_index.is_file()
    finally:
        state.stop()


def test_bbdown_process_uses_credential_directory_as_cwd(tmp_path: Path) -> None:
    tools = _fake_tools(tmp_path / "tools")
    credentials = tmp_path / "credentials"
    credentials.mkdir()
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    cfg = AppConfig(download_dir=str(downloads), bbdown_dir=str(tools))
    captured = {}

    def runner(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="共计1条视频流.", stderr="")

    runner.supports_info = True
    result = run_bbdown_info(
        "https://www.bilibili.com/video/BV1xx411c7mD",
        cfg,
        runner=runner,
        credential_dir=credentials,
    )
    assert result.ok
    assert Path(captured["cwd"]) == credentials
    assert Path(captured["argv"][0]) == tools / "BBDown.exe"


def test_launcher_child_never_falls_back_to_system_ffmpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fallback = tmp_path / "system" / "ffmpeg.exe"
    monkeypatch.setenv("BILI_LAUNCHER_CHILD", "1")
    monkeypatch.setattr("app.bbdown.shutil.which", lambda _name: str(fallback))
    assert find_ffmpeg(tmp_path / "missing-tools") is None


def test_compatible_transcode_uses_only_the_encoder_in_each_delivery() -> None:
    launcher_args = _compatible_video_encode_args(SimpleNamespace(launcher_managed=True))
    assert launcher_args == [
        "-vf",
        "format=nv12",
        "-c:v",
        "h264_mf",
        "-rate_control",
        "quality",
        "-quality",
        "80",
        "-hw_encoding",
        "0",
    ]
    assert "libx264" not in launcher_args

    source_args = _compatible_video_encode_args(SimpleNamespace(launcher_managed=False))
    assert source_args == ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
    assert "h264_mf" not in source_args


def test_search_reads_cookie_from_data_root_not_tool_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    credentials = tmp_path / "data" / "config" / "bbdown"
    tools = tmp_path / "resources" / "windows-tools"
    captured = {}

    def fake_search(_query, **kwargs):
        captured.update(kwargs)
        return {"items": []}

    monkeypatch.setattr("app.api.search_videos", fake_search)
    monkeypatch.setattr("app.api._decorate_search_catalog", lambda _request, data: data)
    state = SimpleNamespace(
        runtime=SimpleNamespace(bbdown_credentials_dir=credentials, bbdown_dir=tools)
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(app_state=state)))
    response = api_search(request, q="test", order="totalrank", page=1, fresh=False)
    assert response["ok"] is True
    assert Path(captured["bbdown_dir"]) == credentials
