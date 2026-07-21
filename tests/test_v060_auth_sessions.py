from __future__ import annotations

from pathlib import Path

from tests._v060_auth_sessions_original import *  # noqa: F401,F403


def test_remote_setup_form_collects_chinese_display_name() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "web" / "assets" / "app" / "main.mjs"
    ).read_text(encoding="utf-8")
    assert 'id="authDisplayName"' in source
    assert "display_name: authRoot.querySelector('#authDisplayName').value" in source
