from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from bili_workspace_launcher.paths import AppPaths
from bili_workspace_launcher.resources import ResourceError, ResourceManager


def _bundle(root: Path) -> Path:
    source = root / "source"
    source.mkdir(parents=True)
    payload = source / "windows-tools" / "BBDown.exe"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"bbdown")
    manifest = {
        "schema_version": 1,
        "product_version": "0.7.0",
        "build_id": "0123456789ab",
        "files": {
            "windows-tools/BBDown.exe": {
                "sha256": hashlib.sha256(b"bbdown").hexdigest(),
                "size": 6,
            }
        },
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
    )
    return root


def test_resource_bundle_is_verified_and_extracted_by_build_id(tmp_path: Path) -> None:
    manager = ResourceManager(AppPaths(tmp_path / "control"), _bundle(tmp_path / "bundle"))
    target, manifest = manager.ensure_extracted()
    assert target.name == "0123456789ab"
    assert manifest.build_id == target.name
    assert (target / "windows-tools" / "BBDown.exe").read_bytes() == b"bbdown"


def test_resource_tamper_fails_closed(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle")
    (bundle / "source" / "windows-tools" / "BBDown.exe").write_bytes(b"tampered")
    manager = ResourceManager(AppPaths(tmp_path / "control"), bundle)
    with pytest.raises(ResourceError, match="摘要或大小"):
        manager.verify_embedded_bundle()


def test_resource_manifest_rejects_boolean_schema(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle")
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ResourceError, match="schema_version"):
        ResourceManager(AppPaths(tmp_path / "control"), bundle).load_manifest()


@pytest.mark.parametrize(
    "relative",
    ("..\\escape.txt", "C:/escape.txt", "CON/file.txt", "folder./file.txt"),
)
def test_resource_manifest_rejects_windows_unsafe_paths(
    tmp_path: Path, relative: str
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(iter(manifest["files"].values()))
    manifest["files"] = {relative: entry}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ResourceError, match="Windows"):
        ResourceManager(AppPaths(tmp_path / "control"), bundle).load_manifest()


def test_resource_target_reparse_point_is_never_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = ResourceManager(AppPaths(tmp_path / "control"), _bundle(tmp_path / "bundle"))
    target = manager.paths.resources_dir / "0123456789ab"
    monkeypatch.setattr(
        "bili_workspace_launcher.resources._is_reparse_point",
        lambda path: Path(path) == target,
    )
    with pytest.raises(ResourceError, match="类型无效"):
        manager.ensure_extracted()


def test_resource_replacement_restores_previous_tree_if_publish_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = ResourceManager(AppPaths(tmp_path / "control"), _bundle(tmp_path / "bundle"))
    target, _manifest = manager.ensure_extracted()
    payload = target / "windows-tools" / "BBDown.exe"
    payload.write_bytes(b"previous-invalid-copy")

    real_replace = os.replace
    calls = 0

    def fail_publish(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected resource publish failure")
        return real_replace(source, destination)

    monkeypatch.setattr("bili_workspace_launcher.resources.os.replace", fail_publish)
    with pytest.raises(ResourceError, match="无法展开"):
        manager.ensure_extracted()

    assert payload.read_bytes() == b"previous-invalid-copy"
    assert not list(manager.paths.resources_dir.glob(".*.bak-*"))
    assert not list(manager.paths.resources_dir.glob(".*.tmp-*"))
