from __future__ import annotations

from pathlib import Path

from tools.verify_package import _is_mutable


ROOT = Path(__file__).resolve().parent.parent


def test_mutable_runtime_files_do_not_hide_tracked_default_templates():
    assert _is_mutable("config/config.json") is True
    assert _is_mutable("config/config.json.bak") is True
    assert _is_mutable("config/runtime.env") is True
    assert _is_mutable("docker/.env") is True
    assert _is_mutable("downloads/item/video.mp4") is True

    assert _is_mutable("config/config.json.default") is False
    assert _is_mutable("config/runtime.env.default") is False
    assert _is_mutable("docker/.env.default") is False
    assert _is_mutable("config/README.md") is False


def test_source_verifier_bootstraps_without_runtime_download():
    text = (ROOT / "verify-source.bat").read_text(encoding="utf-8")
    skip_position = text.index('set "BILI_SKIP_RUNTIME_DOWNLOAD=1"')
    setup_position = text.index("call setup.bat")
    assert skip_position < setup_position


def test_source_verifier_repairs_partial_virtual_environment():
    text = (ROOT / "verify-source.bat").read_text(encoding="utf-8")
    assert 'set "NEED_SETUP=0"' in text
    assert "import fastapi,httpx,pydantic,pytest,uvicorn" in text
    assert '".venv\\Scripts\\python.exe" -m ruff --version' in text


def test_windows_setup_retries_slow_package_downloads():
    text = (ROOT / "setup.bat").read_text(encoding="utf-8")
    assert "--timeout 120 --retries 10" in text
    assert 'set "PIP_ATTEMPT=1"' in text
    assert 'if "%PIP_ATTEMPT%"=="3" exit /b 1' in text
    assert "PIP_INDEX_URL" in text
