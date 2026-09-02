from __future__ import annotations

from pathlib import Path

import pytest

from tools import validate_launcher_candidate


def _configure_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    parent = tmp_path / "build" / "launcher-candidates"
    monkeypatch.setattr(validate_launcher_candidate, "ROOT", tmp_path)
    monkeypatch.setattr(validate_launcher_candidate, "_CANDIDATE_PARENT", parent)
    monkeypatch.setattr(
        validate_launcher_candidate,
        "DEFAULT_CACHE",
        tmp_path / "build" / "launcher-download-cache",
    )
    return parent


def _fake_success(argv: list[str]) -> int:
    def value(name: str) -> Path:
        return Path(argv[argv.index(name) + 1])

    dist = value("--dist-dir")
    dist.mkdir(parents=True)
    (dist / "bili-workspace-launcher-0.7.0.exe").write_bytes(b"candidate")
    value("--record").write_text("{}\n", encoding="utf-8")
    return 0


def test_candidate_entry_cleans_only_its_owned_directory_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _configure_root(tmp_path, monkeypatch)
    monkeypatch.setattr(validate_launcher_candidate, "build_launcher_main", _fake_success)

    assert validate_launcher_candidate.main([]) == 0
    assert parent.is_dir()
    assert list(parent.iterdir()) == []


def test_candidate_entry_can_explicitly_keep_validated_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _configure_root(tmp_path, monkeypatch)
    monkeypatch.setattr(validate_launcher_candidate, "build_launcher_main", _fake_success)

    assert validate_launcher_candidate.main(["--keep-candidate"]) == 0
    candidates = list(parent.iterdir())
    assert len(candidates) == 1
    candidate = candidates[0]
    assert (candidate / "dist" / "bili-workspace-launcher-0.7.0.exe").is_file()
    assert (candidate / "build.json").is_file()


def test_candidate_entry_preserves_failed_candidate_for_diagnosis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _configure_root(tmp_path, monkeypatch)

    def fail(_argv: list[str]) -> int:
        raise RuntimeError("injected failure")

    monkeypatch.setattr(validate_launcher_candidate, "build_launcher_main", fail)
    with pytest.raises(RuntimeError, match="injected"):
        validate_launcher_candidate.main([])
    candidates = list(parent.iterdir())
    assert len(candidates) == 1
    assert (candidates[0] / ".bili-launcher-candidate.json").is_file()
