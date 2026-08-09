from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path

try:
    from tools.t_project_isolation import IsolationError, validate_run
except ModuleNotFoundError:  # 直接执行 tools/playwright_runtime.py 时使用。
    from t_project_isolation import IsolationError, validate_run


EXPLICIT_BROWSER_ENV = "BILI_PLAYWRIGHT_CHROMIUM"
EXIT_INCONCLUSIVE = 1
EXIT_BLOCKED = 3
PROBE_TIMEOUT_MS = 30_000
PROBE_ARGS = (
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-domain-reliability",
    "--disable-sync",
    "--metrics-recording-only",
    "--no-default-browser-check",
    "--no-first-run",
)


class BrowserBlockedError(RuntimeError):
    """浏览器前置缺失或无法完成受控启动。"""


class RuntimeIsolationError(RuntimeError):
    """浏览器运行环境没有被完整隔离到当前 run-id。"""


def _lexical_absolute(path: Path | str) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def validate_browser_executable(path: Path | str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise BrowserBlockedError(f"浏览器路径必须是绝对路径: {candidate}")
    lexical = _lexical_absolute(candidate)
    for current in (lexical, *lexical.parents):
        if current.exists() and _is_link_or_reparse(current):
            raise BrowserBlockedError(f"浏览器路径不得经过符号链接或重解析点: {current}")
    if not lexical.is_file():
        raise BrowserBlockedError(f"浏览器路径不是已有普通文件: {lexical}")
    if os.name != "nt" and not os.access(lexical, os.X_OK):
        raise BrowserBlockedError(f"浏览器文件不可执行: {lexical}")
    return lexical.resolve(strict=True)


def _playwright_chromium_candidate() -> Path | None:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            candidate = Path(playwright.chromium.executable_path)
    except Exception:
        return None
    return candidate.resolve(strict=False)


def _known_browser_paths(environ: Mapping[str, str]) -> Iterable[Path]:
    if os.name == "nt":
        roots = (
            environ.get("PROGRAMFILES", ""),
            environ.get("PROGRAMFILES(X86)", ""),
            environ.get("ProgramW6432", ""),
            environ.get("LOCALAPPDATA", ""),
        )
        suffixes = (
            Path("Google/Chrome/Application/chrome.exe"),
            Path("Microsoft/Edge/Application/msedge.exe"),
            Path("Chromium/Application/chrome.exe"),
        )
        seen_roots: set[str] = set()
        for root in roots:
            key = os.path.normcase(root)
            if root and key not in seen_roots:
                seen_roots.add(key)
                for suffix in suffixes:
                    yield Path(root) / suffix
        return
    if sys.platform == "darwin":
        yield Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        yield Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
        yield Path("/Applications/Chromium.app/Contents/MacOS/Chromium")
        return
    yield Path("/usr/bin/google-chrome")
    yield Path("/usr/bin/google-chrome-stable")
    yield Path("/usr/bin/microsoft-edge")
    yield Path("/usr/bin/microsoft-edge-stable")
    yield Path("/usr/bin/chromium")
    yield Path("/usr/bin/chromium-browser")


def discover_browser_candidates(
    environ: Mapping[str, str] | None = None,
) -> list[Path]:
    selected_environment = os.environ if environ is None else environ
    candidates: list[Path] = []
    playwright_candidate = _playwright_chromium_candidate()
    if playwright_candidate is not None:
        candidates.append(playwright_candidate)
    for command in (
        "google-chrome",
        "google-chrome-stable",
        "microsoft-edge",
        "microsoft-edge-stable",
        "chromium",
        "chromium-browser",
    ):
        located = shutil.which(command)
        if located:
            candidates.append(Path(located).resolve(strict=False))
    candidates.extend(_known_browser_paths(selected_environment))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate.resolve(strict=False)))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def resolve_existing_browser(
    *,
    environ: Mapping[str, str] | None = None,
    candidates: Iterable[Path | str] | None = None,
) -> Path:
    selected_environment = os.environ if environ is None else environ
    explicit = selected_environment.get(EXPLICIT_BROWSER_ENV, "").strip()
    if explicit:
        try:
            return validate_browser_executable(explicit)
        except BrowserBlockedError as exc:
            raise BrowserBlockedError(
                f"{EXPLICIT_BROWSER_ENV} 指向不可用路径：{exc}"
            ) from exc

    selected_candidates = (
        discover_browser_candidates(selected_environment)
        if candidates is None
        else candidates
    )
    for candidate in selected_candidates:
        try:
            return validate_browser_executable(candidate)
        except BrowserBlockedError:
            continue
    raise BrowserBlockedError(
        "未找到已有的 Playwright Chromium、Chrome、Edge 或 Chromium。"
    )


def validate_runtime_environment(run_root: Path, environ: Mapping[str, str]) -> None:
    required = ["HOME", "XDG_CACHE_HOME", "PYTHONPYCACHEPREFIX"]
    required.extend(("TEMP", "TMP") if os.name == "nt" else ("TMPDIR",))
    for name in required:
        raw_value = environ.get(name, "").strip()
        if not raw_value:
            raise RuntimeIsolationError(f"浏览器隔离环境缺少 {name}")
        value = _lexical_absolute(raw_value).resolve(strict=False)
        if not _is_within(value, run_root):
            raise RuntimeIsolationError(
                f"浏览器隔离环境 {name} 必须位于当前 run-id: {value}"
            )


def probe_browser(executable: Path, run_root: Path) -> None:
    profile_parent = run_root / "tmp"
    profile_parent.mkdir(exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="playwright-probe-", dir=profile_parent))
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                executable_path=str(executable),
                headless=True,
                args=list(PROBE_ARGS),
                timeout=PROBE_TIMEOUT_MS,
            )
            context.close()
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        raise BrowserBlockedError(
            f"已有浏览器无法完成受控无头启动: {executable}\n{detail}"
        ) from exc


def resolve_probeable_browser(
    run_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    candidates: Iterable[Path | str] | None = None,
) -> Path:
    selected_environment = os.environ if environ is None else environ
    if selected_environment.get(EXPLICIT_BROWSER_ENV, "").strip():
        executable = resolve_existing_browser(
            environ=selected_environment,
            candidates=candidates,
        )
        probe_browser(executable, run_root)
        return executable

    selected_candidates = (
        discover_browser_candidates(selected_environment)
        if candidates is None
        else candidates
    )
    failures: list[str] = []
    seen: set[str] = set()
    for candidate in selected_candidates:
        try:
            executable = validate_browser_executable(candidate)
        except BrowserBlockedError:
            continue
        key = os.path.normcase(str(executable))
        if key in seen:
            continue
        seen.add(key)
        try:
            probe_browser(executable, run_root)
        except BrowserBlockedError as exc:
            failures.append(str(exc))
            continue
        return executable

    if not failures:
        raise BrowserBlockedError(
            "未找到已有的 Playwright Chromium、Chrome、Edge 或 Chromium。"
        )
    raise BrowserBlockedError(
        "已发现浏览器，但所有候选均无法完成受控无头启动：\n"
        + "\n\n".join(failures)
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="解析并探测 T-PROJECT 使用的已有 Playwright 浏览器。"
    )
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--probe", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        run_root = validate_run(args.run_root, args.workspace_root)
        validate_runtime_environment(run_root, os.environ)
    except (IsolationError, RuntimeIsolationError, OSError) as exc:
        print(f"[不确定] 浏览器运行隔离校验失败：{exc}", file=sys.stderr)
        return EXIT_INCONCLUSIVE

    try:
        executable = (
            resolve_probeable_browser(run_root)
            if args.probe
            else resolve_existing_browser()
        )
    except BrowserBlockedError as exc:
        print(f"[阻断] {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    except Exception as exc:
        print(f"[不确定] 浏览器运行器异常：{exc}", file=sys.stderr)
        return EXIT_INCONCLUSIVE

    print(executable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
