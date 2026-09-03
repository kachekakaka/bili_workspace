from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.bilibili_live import discovery
from tools.bilibili_live.contracts import LiveBlockedError, LiveMarker


def test_discovery_requires_online_login_before_public_target_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_root = tmp_path / "raw-public"
    monkeypatch.setattr(
        discovery,
        "check_cookie_status",
        lambda *_args, **_kwargs: SimpleNamespace(
            logged_in=False,
            online_verified=True,
        ),
    )
    monkeypatch.setattr(
        discovery,
        "creator_profile",
        lambda *_args, **_kwargs: pytest.fail("登录失败后不得读取 UP 主资料"),
    )

    with pytest.raises(LiveBlockedError, match="登录"):
        discovery.discover_marker_targets(
            marker=LiveMarker(
                creator_uid="10001",
                download_bvids=tuple(
                    f"BV1TEST0000{index}" for index in range(1, 9)
                ),
            ),
            bbdown_data_dir=tmp_path / "bbdown",
            raw_root=raw_root,
            deadline=time.monotonic() + 30,
        )

    assert (raw_root / "index.json").read_text(encoding="utf-8")
    assert not list(raw_root.glob("*-creator-profile.json"))
