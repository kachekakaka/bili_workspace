from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools import playwright_runtime as runtime


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"browser")
    if os.name != "nt":
        path.chmod(0o755)
    return path.resolve()


def test_explicit_browser_path_has_priority(tmp_path: Path) -> None:
    explicit = _executable(tmp_path / "explicit-browser")
    candidate = _executable(tmp_path / "candidate-browser")

    resolved = runtime.resolve_existing_browser(
        environ={runtime.EXPLICIT_BROWSER_ENV: str(explicit)},
        candidates=[candidate],
    )

    assert resolved == explicit


def test_first_existing_candidate_is_selected(tmp_path: Path) -> None:
    missing = tmp_path / "missing-browser"
    existing = _executable(tmp_path / "existing-browser")

    resolved = runtime.resolve_existing_browser(
        environ={},
        candidates=[missing, existing],
    )

    assert resolved == existing


def test_missing_browser_is_blocked(tmp_path: Path) -> None:
    with pytest.raises(runtime.BrowserBlockedError, match="未找到已有"):
        runtime.resolve_existing_browser(
            environ={},
            candidates=[tmp_path / "missing-browser"],
        )


def test_probe_falls_back_to_next_existing_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _executable(tmp_path / "first-browser")
    second = _executable(tmp_path / "second-browser")
    probed: list[Path] = []

    def fake_probe(executable: Path, run_root: Path) -> None:
        assert run_root == tmp_path
        probed.append(executable)
        if executable == first:
            raise runtime.BrowserBlockedError("first failed")

    monkeypatch.setattr(runtime, "probe_browser", fake_probe)

    resolved = runtime.resolve_probeable_browser(
        tmp_path,
        environ={},
        candidates=[first, second],
    )

    assert resolved == second
    assert probed == [first, second]


def test_explicit_probe_failure_does_not_fall_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit = _executable(tmp_path / "explicit-browser")
    fallback = _executable(tmp_path / "fallback-browser")
    probed: list[Path] = []

    def fake_probe(executable: Path, run_root: Path) -> None:
        assert run_root == tmp_path
        probed.append(executable)
        raise runtime.BrowserBlockedError("explicit failed")

    monkeypatch.setattr(runtime, "probe_browser", fake_probe)

    with pytest.raises(runtime.BrowserBlockedError, match="explicit failed"):
        runtime.resolve_probeable_browser(
            tmp_path,
            environ={runtime.EXPLICIT_BROWSER_ENV: str(explicit)},
            candidates=[fallback],
        )

    assert probed == [explicit]


@pytest.mark.parametrize("unsafe", ["relative-browser", "browser-directory"])
def test_explicit_browser_rejects_unsafe_paths(
    tmp_path: Path,
    unsafe: str,
) -> None:
    if unsafe == "browser-directory":
        configured = tmp_path / unsafe
        configured.mkdir()
    else:
        configured = Path(unsafe)

    with pytest.raises(runtime.BrowserBlockedError, match="不可用路径"):
        runtime.resolve_existing_browser(
            environ={runtime.EXPLICIT_BROWSER_ENV: str(configured)},
            candidates=[],
        )


def test_explicit_browser_rejects_symbolic_link(tmp_path: Path) -> None:
    target = _executable(tmp_path / "browser-target")
    link = tmp_path / "browser-link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("当前平台不允许创建测试用文件符号链接")

    with pytest.raises(runtime.BrowserBlockedError, match="符号链接或重解析点"):
        runtime.resolve_existing_browser(
            environ={runtime.EXPLICIT_BROWSER_ENV: str(link)},
            candidates=[],
        )


def test_runtime_environment_must_stay_inside_run_root(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    environ = {
        "HOME": str(run_root / "home"),
        "XDG_CACHE_HOME": str(run_root / "cache"),
        "PYTHONPYCACHEPREFIX": str(run_root / "pycache"),
    }
    if os.name == "nt":
        environ.update(
            {
                "TEMP": str(run_root / "tmp"),
                "TMP": str(run_root / "tmp"),
            }
        )
    else:
        environ["TMPDIR"] = str(run_root / "tmp")

    runtime.validate_runtime_environment(run_root.resolve(), environ)
    environ["HOME"] = str(tmp_path / "outside")

    with pytest.raises(runtime.RuntimeIsolationError, match="当前 run-id"):
        runtime.validate_runtime_environment(run_root.resolve(), environ)


def test_cli_classifies_missing_browser_as_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(runtime, "validate_run", lambda *_: tmp_path)
    monkeypatch.setattr(runtime, "validate_runtime_environment", lambda *_: None)
    monkeypatch.setattr(
        runtime,
        "resolve_existing_browser",
        lambda: (_ for _ in ()).throw(runtime.BrowserBlockedError("missing")),
    )

    result = runtime.main(
        ["--workspace-root", str(tmp_path), "--run-root", str(tmp_path)]
    )

    assert result == runtime.EXIT_BLOCKED
    assert "[阻断]" in capsys.readouterr().err


def test_cli_classifies_runner_error_as_inconclusive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        runtime,
        "validate_run",
        lambda *_: (_ for _ in ()).throw(runtime.IsolationError("bad run")),
    )

    result = runtime.main(
        ["--workspace-root", str(tmp_path), "--run-root", str(tmp_path)]
    )

    assert result == runtime.EXIT_INCONCLUSIVE
    assert "[不确定]" in capsys.readouterr().err
