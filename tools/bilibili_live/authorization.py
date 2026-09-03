"""仓库本地长期真测授权的定位、解析与环境绑定。"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from tools.bilibili_live.contracts import (
    MAX_MARKER_BYTES,
    LiveBlockedError,
    credential_file,
    is_reparse,
    resolve_credential_source,
    validate_test_root,
)


AUTHORIZATION_RELATIVE_PATH = (
    Path("bili-workspace") / "automatic-live-test.json"
)
AUTHORIZATION_KIND = "automatic_live_test"
PROJECT_ID = "bili_workspace"
DATA_ROOT_MARKER_NAME = ".bili-workspace-data-root.json"


@dataclass(frozen=True, slots=True)
class RepositoryLiveAuthorization:
    git_common_dir: Path
    credential_source: Path
    test_root: Path


def _regular_json_file(path: Path, label: str) -> dict[str, object]:
    if not path.is_file() or path.is_symlink() or is_reparse(path):
        raise LiveBlockedError(f"{label}不是有效普通文件")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise LiveBlockedError(f"无法读取{label}状态") from exc
    if size <= 0 or size > MAX_MARKER_BYTES:
        raise LiveBlockedError(f"{label}大小超出允许范围")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveBlockedError(f"{label}不是有效 UTF-8 JSON") from exc
    if not isinstance(raw, dict):
        raise LiveBlockedError(f"{label}必须是 JSON object")
    return raw


def repository_git_common_dir(workspace_root: Path) -> Path:
    workspace = Path(workspace_root).resolve(strict=True)
    try:
        result = subprocess.run(
            [
                "git",
                "rev-parse",
                "--path-format=absolute",
                "--show-toplevel",
                "--git-common-dir",
            ],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise LiveBlockedError("无法定位当前仓库的 Git common directory") from exc
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(lines) != 2:
        raise LiveBlockedError("Git common directory 返回格式无效")
    try:
        top_level = Path(lines[0]).resolve(strict=True)
        common_dir = Path(lines[1]).resolve(strict=True)
    except OSError as exc:
        raise LiveBlockedError("无法解析当前仓库的 Git common directory") from exc
    if top_level != workspace:
        raise LiveBlockedError("真测授权必须从当前 Git 工作树根解析")
    if (
        not common_dir.is_dir()
        or common_dir.is_symlink()
        or is_reparse(common_dir)
    ):
        raise LiveBlockedError("Git common directory 类型无效")
    return common_dir


def repository_authorization_path(workspace_root: Path) -> Path:
    return repository_git_common_dir(workspace_root) / AUTHORIZATION_RELATIVE_PATH


def _validate_data_root_identity(source: Path) -> None:
    marker = _regular_json_file(
        source / DATA_ROOT_MARKER_NAME,
        "日常数据根标记",
    )
    if (
        set(marker) != {"schema_version", "product", "created_at"}
        or type(marker.get("schema_version")) is not int
        or marker.get("schema_version") != 1
        or marker.get("product") != PROJECT_ID
        or type(marker.get("created_at")) is not int
        or int(marker["created_at"]) <= 0
    ):
        raise LiveBlockedError("日常数据根标记身份无效")


def load_repository_live_authorization(
    workspace_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> RepositoryLiveAuthorization:
    """只读解析当前仓库本地授权；缺失或漂移时安全阻断。"""

    workspace = Path(workspace_root).resolve(strict=True)
    common_dir = repository_git_common_dir(workspace)
    authorization_dir = common_dir / AUTHORIZATION_RELATIVE_PATH.parent
    if (
        not authorization_dir.is_dir()
        or authorization_dir.is_symlink()
        or is_reparse(authorization_dir)
    ):
        raise LiveBlockedError("仓库本地真测授权目录类型无效")
    marker = _regular_json_file(
        authorization_dir / AUTHORIZATION_RELATIVE_PATH.name,
        "仓库本地真测授权",
    )
    expected_fields = {
        "schema_version",
        "authorization",
        "project_id",
        "credential_source",
        "test_root",
    }
    if (
        set(marker) != expected_fields
        or type(marker.get("schema_version")) is not int
        or marker.get("schema_version") != 1
        or marker.get("authorization") != AUTHORIZATION_KIND
        or marker.get("project_id") != PROJECT_ID
    ):
        raise LiveBlockedError("仓库本地真测授权字段或身份无效")
    source_value = marker.get("credential_source")
    test_root_value = marker.get("test_root")
    if (
        not isinstance(source_value, str)
        or not Path(source_value).expanduser().is_absolute()
        or not isinstance(test_root_value, str)
        or not Path(test_root_value).expanduser().is_absolute()
    ):
        raise LiveBlockedError("仓库本地真测授权必须绑定绝对路径")
    source = resolve_credential_source(source_value)
    _validate_data_root_identity(source)
    credential_file(source)
    test_root = validate_test_root(
        test_root_value,
        workspace_root=workspace,
        credential_source=source,
        environ=os.environ if environ is None else environ,
    )
    return RepositoryLiveAuthorization(
        git_common_dir=common_dir,
        credential_source=source,
        test_root=test_root,
    )
