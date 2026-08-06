from __future__ import annotations

import os
from pathlib import Path

from app.config_files import (
    ensure_env_from_default,
    ensure_json_from_default,
    load_env_file,
    migrate_legacy_json,
)
from app.paths import ROOT
from tools.t_project_isolation import validate_run


def _config_dir() -> Path:
    raw = os.getenv("BILI_CONFIG_DIR", "").strip()
    if raw:
        path = Path(raw).expanduser()
        return path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    mode = os.getenv("BILI_APP_MODE", "auto").strip().lower()
    return Path("/data/config") if mode in {"nas", "docker"} else ROOT / "config"


def _verification_run_root() -> Path | None:
    raw = os.getenv("BILI_VERIFY_RUN_ROOT", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    candidate = path if path.is_absolute() else ROOT / path
    return validate_run(candidate, ROOT)


def _root_env_path(verification_run_root: Path | None = None) -> Path:
    raw = os.getenv("BILI_VERIFY_ROOT_ENV_PATH", "").strip()
    if not raw:
        return ROOT / ".env"
    if verification_run_root is None:
        raise ValueError(
            "BILI_VERIFY_ROOT_ENV_PATH 只能与有效的 BILI_VERIFY_RUN_ROOT 一起使用"
        )
    path = Path(raw).expanduser()
    candidate = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    try:
        candidate.relative_to(verification_run_root)
    except ValueError as exc:
        raise ValueError("验证用根环境文件必须位于已验证的运行目录内") from exc
    return candidate


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
    root_env = _root_env_path(verification_run_root)
    ensure_env_from_default(ROOT / ".env.default", root_env)
    load_env_file(root_env)

    config_dir = _config_dir()
    if verification_run_root is not None:
        config_dir = _require_within_verification_run(
            config_dir,
            verification_run_root,
            "配置目录",
        )
    runtime_env = config_dir / "runtime.env"
    ensure_env_from_default(ROOT / "config" / "runtime.env.default", runtime_env)
    load_env_file(runtime_env, override=False)

    app_config = config_dir / "config.json"
    if verification_run_root is None:
        legacy_config = ROOT / "config.json"
        migrate_legacy_json(legacy_config, app_config)

    try:
        ensure_json_from_default(ROOT / "config" / "config.json.default", app_config)
    except ValueError as exc:
        backup = app_config.with_suffix(app_config.suffix + ".bak")
        recoverable = backup.is_file() and (
            "实际配置 JSON 无效" in str(exc)
            or "实际配置 顶层必须是 JSON 对象" in str(exc)
        )
        if not recoverable:
            raise
    return {
        "root_env": str(root_env),
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
