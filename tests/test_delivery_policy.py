from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import __version__
from app import build_info


ROOT = Path(__file__).resolve().parents[1]


def test_build_metadata_describes_the_running_source() -> None:
    metadata = build_info.build_metadata()

    assert metadata["service"] == "bili_workspace"
    assert metadata["version"] == __version__
    assert metadata["frontend_version"]
    assert re.fullmatch(r"[0-9a-f]{12}", metadata["build_id"])


def test_build_id_override_is_validated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_info.build_id.cache_clear()
    monkeypatch.setenv("BILI_BUILD_ID", "0123456789abcdef")
    assert build_info.build_id() == "0123456789abcdef"

    build_info.build_id.cache_clear()
    monkeypatch.setenv("BILI_BUILD_ID", "not-a-digest")
    with pytest.raises(ValueError, match="BILI_BUILD_ID"):
        build_info.build_id()
    build_info.build_id.cache_clear()


def test_active_workflows_cannot_publish_formal_releases() -> None:
    workflow_root = ROOT / ".github" / "workflows"
    workflows = tuple(sorted((*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml"))))
    assert workflows

    forbidden = {
        "创建 Git tag": re.compile(r"\bgit\s+tag\s"),
        "创建 GitHub Release": re.compile(r"\bgh\s+release\s+create\b"),
        "推送 tag": re.compile(r"\bgit\s+push\b[^\n]*refs/tags/"),
        "登录镜像仓库": re.compile(r"docker/login-action", re.IGNORECASE),
        "推送镜像": re.compile(r"(?m)^\s*push:\s*true\s*$", re.IGNORECASE),
        "写 packages": re.compile(r"(?m)^\s*packages:\s*write\s*$", re.IGNORECASE),
    }
    for path in workflows:
        content = path.read_text(encoding="utf-8")
        for label, pattern in forbidden.items():
            assert pattern.search(content) is None, f"{path.name} 不得{label}"

    decision = (ROOT / "docs" / "adr" / "0002-source-push-does-not-publish.md").read_text(
        encoding="utf-8"
    )
    assert "停止未来" in decision and "正式发布" in decision
