from __future__ import annotations

from tools.verify_package import _is_mutable


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
