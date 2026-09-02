"""在唯一忽略目录中构建、验证并默认清理 Windows 启动器候选。"""

from __future__ import annotations

import argparse
import json
import shutil
import uuid
from pathlib import Path

from tools.build_launcher import (
    DEFAULT_CACHE,
    ROOT,
    _is_reparse_point,
    _path_exists,
    _reject_reparse_ancestors,
    main as build_launcher_main,
)

_CANDIDATE_PARENT = ROOT / "build" / "launcher-candidates"
_MARKER_NAME = ".bili-launcher-candidate.json"


def _create_candidate_root() -> tuple[Path, str]:
    build_root = (ROOT / "build").resolve(strict=False)
    candidate_parent = _CANDIDATE_PARENT.resolve(strict=False)
    if candidate_parent == build_root or build_root not in candidate_parent.parents:
        raise RuntimeError("候选父目录必须是 build 下的具体子目录")
    if _path_exists(candidate_parent) and (
        not candidate_parent.is_dir()
        or candidate_parent.is_symlink()
        or _is_reparse_point(candidate_parent)
    ):
        raise RuntimeError("候选父目录类型无效")
    _reject_reparse_ancestors(candidate_parent, "候选父目录")
    candidate_parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    candidate_root = candidate_parent / f"candidate-{token}"
    candidate_root.mkdir(exist_ok=False)
    marker = {
        "schema_version": 1,
        "kind": "launcher-candidate",
        "token": token,
    }
    (candidate_root / _MARKER_NAME).write_text(
        json.dumps(marker, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return candidate_root, token


def _cleanup_candidate(candidate_root: Path, token: str) -> None:
    candidate_parent = _CANDIDATE_PARENT.resolve(strict=True)
    resolved = candidate_root.resolve(strict=True)
    if (
        resolved.parent != candidate_parent
        or resolved.name != f"candidate-{token}"
        or not resolved.is_dir()
        or resolved.is_symlink()
        or _is_reparse_point(resolved)
    ):
        raise RuntimeError("拒绝清理所有权不明确的候选目录")
    marker_path = resolved / _MARKER_NAME
    try:
        if (
            not marker_path.is_file()
            or marker_path.is_symlink()
            or _is_reparse_point(marker_path)
            or marker_path.stat().st_size > 4096
        ):
            raise RuntimeError("候选目录所有权标记类型无效，拒绝清理")
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("候选目录所有权标记不可读，拒绝清理") from exc
    if marker != {
        "schema_version": 1,
        "kind": "launcher-candidate",
        "token": token,
    }:
        raise RuntimeError("候选目录所有权标记不匹配，拒绝清理")
    shutil.rmtree(resolved)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--keep-candidate",
        action="store_true",
        help="通过验证后保留候选 EXE 和 build.json 供人工检查",
    )
    arguments = parser.parse_args(argv)
    candidate_root, token = _create_candidate_root()
    try:
        result = build_launcher_main(
            [
                "--mode",
                "candidate",
                "--dist-dir",
                str(candidate_root / "dist"),
                "--work-dir",
                str(candidate_root / "work"),
                "--resource-dir",
                str(candidate_root / "resources"),
                "--cache",
                str(DEFAULT_CACHE),
                "--record",
                str(candidate_root / "build.json"),
                "--run-exe-self-check",
                "--run-exe-runtime-smoke",
            ]
        )
    except Exception:
        print(f"候选验证失败，诊断目录已保留：{candidate_root}")
        raise
    if result != 0:
        print(f"候选验证失败，诊断目录已保留：{candidate_root}")
        return result
    if arguments.keep_candidate:
        print(f"候选验证通过，已保留：{candidate_root}")
    else:
        _cleanup_candidate(candidate_root, token)
        print("候选验证通过，任务自有候选目录已精确清理。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
