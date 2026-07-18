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


def _config_dir() -> Path:
    raw = os.getenv("BILI_CONFIG_DIR", "").strip()
    if raw:
        path = Path(raw).expanduser()
        return path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    mode = os.getenv("BILI_APP_MODE", "auto").strip().lower()
    return Path("/data/config") if mode in {"nas", "docker"} else ROOT / "config"


def sync_configs() -> dict[str, str]:
    root_env = ROOT / ".env"
    ensure_env_from_default(ROOT / ".env.default", root_env)
    load_env_file(root_env)

    config_dir = _config_dir()
    runtime_env = config_dir / "runtime.env"
    ensure_env_from_default(ROOT / "config" / "runtime.env.default", runtime_env)
    load_env_file(runtime_env, override=False)

    app_config = config_dir / "config.json"
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
