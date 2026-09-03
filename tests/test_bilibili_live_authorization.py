from __future__ import annotations

import importlib
import json
import subprocess
from pathlib import Path

import pytest

from tools.bilibili_live.authorization import (
    AUTHORIZATION_KIND,
    AUTHORIZATION_RELATIVE_PATH,
    PROJECT_ID,
    RepositoryLiveAuthorization,
    load_repository_live_authorization,
    repository_git_common_dir,
)
from tools.bilibili_live.contracts import LiveBlockedError


def _run_git(repo: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    _run_git(repository, "init", "--initial-branch=main")
    _run_git(repository, "config", "user.name", "Bili Workspace Test")
    _run_git(repository, "config", "user.email", "bili@example.invalid")
    (repository / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    _run_git(repository, "add", "tracked.txt")
    _run_git(repository, "commit", "--quiet", "-m", "fixture")
    return repository


def _environment(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "bili-datas"
    (source / "config" / "bbdown").mkdir(parents=True)
    (source / ".bili-workspace-data-root.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product": PROJECT_ID,
                "created_at": 1,
            }
        ),
        encoding="utf-8",
    )
    (source / "config" / "bbdown" / "BBDown.data").write_text(
        "SESSDATA=fake",
        encoding="utf-8",
    )
    return source, tmp_path / "live-runs"


def _write_authorization(repository: Path, source: Path, test_root: Path) -> Path:
    path = repository_git_common_dir(repository) / AUTHORIZATION_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "authorization": AUTHORIZATION_KIND,
                "project_id": PROJECT_ID,
                "credential_source": str(source),
                "test_root": str(test_root),
            }
        ),
        encoding="utf-8",
    )
    return path


def test_repository_authorization_is_shared_by_worktree_not_clone(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    source, test_root = _environment(tmp_path)
    _write_authorization(repository, source, test_root)
    environ = {"LOCALAPPDATA": str(tmp_path / "local-app-data")}

    authorization = load_repository_live_authorization(
        repository,
        environ=environ,
    )
    assert authorization.credential_source == source.resolve()
    assert authorization.test_root == test_root.resolve(strict=False)

    worktree = tmp_path / "worktree"
    _run_git(
        repository,
        "worktree",
        "add",
        "--quiet",
        "-b",
        "authorization-fixture",
        str(worktree),
    )
    from_worktree = load_repository_live_authorization(
        worktree,
        environ=environ,
    )
    assert from_worktree.git_common_dir == authorization.git_common_dir

    clone = tmp_path / "clone"
    _run_git(tmp_path, "clone", "--quiet", str(repository), str(clone))
    with pytest.raises(LiveBlockedError, match="仓库本地真测授权"):
        load_repository_live_authorization(clone, environ=environ)


def test_repository_authorization_rejects_unknown_fields(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    source, test_root = _environment(tmp_path)
    path = _write_authorization(repository, source, test_root)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["unexpected"] = True
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(LiveBlockedError, match="字段或身份"):
        load_repository_live_authorization(
            repository,
            environ={"LOCALAPPDATA": str(tmp_path / "local-app-data")},
        )


def test_cli_uses_repository_authorization_when_data_root_is_omitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = importlib.import_module("tools.bilibili_live.__main__")
    source = tmp_path / "source"
    test_root = tmp_path / "runs"
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "load_repository_live_authorization",
        lambda _root: RepositoryLiveAuthorization(
            git_common_dir=tmp_path / ".git",
            credential_source=source,
            test_root=test_root,
        ),
    )

    def fake_run_live_test(**values: object) -> tuple[int, None]:
        captured.update(values)
        return 0, None

    monkeypatch.setattr(cli, "run_live_test", fake_run_live_test)

    assert cli.main(["run", "--impact", "discovery"]) == 0
    assert captured["credential_source"] == source
    environment = captured["environ"]
    assert isinstance(environment, dict)
    assert environment["BILI_TEST_ROOT"] == str(test_root)


def test_cli_keeps_explicit_data_root_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = importlib.import_module("tools.bilibili_live.__main__")
    source = tmp_path / "source"
    captured: dict[str, object] = {}

    def reject_repository_authorization(_root: Path) -> RepositoryLiveAuthorization:
        raise AssertionError("显式模式不应读取仓库本地授权")

    def fake_run_live_test(**values: object) -> tuple[int, None]:
        captured.update(values)
        return 0, None

    monkeypatch.setattr(
        cli,
        "load_repository_live_authorization",
        reject_repository_authorization,
    )
    monkeypatch.setattr(cli, "run_live_test", fake_run_live_test)

    assert (
        cli.main(
            ["run", "--data-root", str(source), "--impact", "discovery"]
        )
        == 0
    )
    assert captured["credential_source"] == source
    assert captured["environ"] is None
