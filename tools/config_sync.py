from __future__ import annotations

import os
from pathlib import Path

from app.config_files import (
    ensure_env_from_default,
    ensure_json_from_default,
    load_env_file,
)
from app.paths import ROOT, defaults_dir
from tools.t_project_isolation import validate_run


def _config_dir() -> Path:
    raw = os.getenv("BILI_CONFIG_DIR", "").strip()
    if raw:
        path = Path(raw).expanduser()
        return path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    mode = os.getenv("BILI_APP_MODE", "auto").strip().lower()
    if mode in {"nas", "docker"}:
        return Path("/data/config")
    raise ValueError("本机配置同步必须显式指定仓库外 BILI_CONFIG_DIR")


def _verification_run_root() -> Path | None:
    raw = os.getenv("BILI_VERIFY_RUN_ROOT", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    candidate = path if path.is_absolute() else ROOT / path
    return validate_run(candidate, ROOT)


def _require_within_verification_run(
    path: Path,
    verification_run_root: Path,
    label: str,
) -> Path:
    candidate = path.resolve()
    try:
        candidate.relative_to(verification_run_root)
    except ValueError as exc:
        raise ValueError(f"验证用{label}必须位于已验证的运行目录内") from exc
    return candidate


def sync_configs() -> dict[str, str]:
    verification_run_root = _verification_run_root()
    config_dir = _config_dir()
    if verification_run_root is not None:
        config_dir = _require_within_verification_run(
            config_dir,
            verification_run_root,
            "配置目录",
        )
    runtime_env = config_dir / "runtime.env"
    ensure_env_from_default(defaults_dir() / "runtime.env.default", runtime_env)
    load_env_file(runtime_env, override=False)

    app_config = config_dir / "config.json"
    try:
        ensure_json_from_default(defaults_dir() / "config.json.default", app_config)
    except ValueError as exc:
        backup = app_config.with_suffix(app_config.suffix + ".bak")
        recoverable = backup.is_file() and (
            "实际配置 JSON 无效" in str(exc)
            or "实际配置 顶层必须是 JSON 对象" in str(exc)
        )
        if not recoverable:
            raise
    return {
        "runtime_env": str(runtime_env),
        "app_config": str(app_config),
    }


def main() -> int:
    paths = sync_configs()
    print("[通过] 配置模板同步完成：")
    for name, value in paths.items():
        print(f"  {name}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
