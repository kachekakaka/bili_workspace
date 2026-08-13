"""固定 linux/amd64 Docker 镜像的构建、三件套导出与精确清理。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tarfile
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.task_logs import redact_sensitive

from .commands import CommandError, CommandResult, CommandRunner
from .constants import (
    BUILD_LABEL_KEY,
    DOCKER_PLATFORM,
    JOB_LABEL_KEY,
    OWNER_LABEL_KEY,
    OWNER_LABEL_VALUE,
)
from .paths import AppPaths, _is_reparse_point
from .resources import ResourceError, ResourceManager, sha256_file
from .version import PRODUCT_VERSION

_BUILD_ID_RE = re.compile(r"^[0-9a-f]{12}$")
_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_TEMP_TAG_RE = re.compile(
    r"^bili-workspace-export:(?P<version>[0-9]+\.[0-9]+\.[0-9]+)-"
    r"(?P<build>[0-9a-f]{12})-(?P<job>[0-9a-f]{32})$"
)
_JOURNAL_STATES = {
    "building",
    "ready",
    "exporting",
    "publishing",
    "committed",
    "failed",
    "cleanup-required",
}
_OUTPUT_RECOVERY_STATES = {"exporting", "publishing", "committed"}
_MAX_JOURNAL_BYTES = 2 * 1024 * 1024
_MAX_EXPORT_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_CHECKSUM_BYTES = 4096
_MAX_TAR_MEMBERS = 100_000


class Runner(Protocol):
    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        on_output: Callable[[str], None] | None = None,
        check: bool = True,
    ) -> CommandResult: ...


class DockerJobError(RuntimeError):
    """Docker 不可用、身份不符或导出事务失败。"""


@dataclass(frozen=True, slots=True)
class ExportPaths:
    tar: Path
    checksum: Path
    manifest: Path


@dataclass(frozen=True, slots=True)
class ExportResult:
    paths: ExportPaths
    cleanup_warning: str = ""


@dataclass(frozen=True, slots=True)
class ExportPreflight:
    build_id: str
    output_dir: Path
    paths: ExportPaths
    old_files: tuple[dict[str, object], dict[str, object], dict[str, object]]
    old_build_id: str = ""


@dataclass(frozen=True, slots=True)
class RetainedImage:
    job_id: str
    build_id: str
    tag: str
    journal_path: Path


def expected_export_paths(output_dir: Path, build_id: str) -> ExportPaths:
    if not _BUILD_ID_RE.fullmatch(build_id):
        raise DockerJobError("build_id 必须是 12 位小写十六进制")
    stem = f"bili-workspace-{PRODUCT_VERSION}-{build_id}-linux-amd64"
    root = Path(output_dir)
    return ExportPaths(root / f"{stem}.tar", root / f"{stem}.tar.sha256", root / f"{stem}.json")


def _task_export_paths(targets: ExportPaths, job_id: str) -> tuple[ExportPaths, ExportPaths]:
    if not _JOB_ID_RE.fullmatch(job_id):
        raise DockerJobError("Docker 作业 ID 无效")
    root = targets.tar.parent
    temporary = ExportPaths(
        root / f".{targets.tar.name}.{job_id}.tmp",
        root / f".{targets.checksum.name}.{job_id}.tmp",
        root / f".{targets.manifest.name}.{job_id}.tmp",
    )
    backups = ExportPaths(
        root / f".{targets.tar.name}.{job_id}.bak",
        root / f".{targets.checksum.name}.{job_id}.bak",
        root / f".{targets.manifest.name}.{job_id}.bak",
    )
    return temporary, backups


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_bytes(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _inside(candidate: Path, parent: Path) -> bool:
    child = candidate.resolve(strict=False)
    root = parent.resolve(strict=False)
    return child == root or root in child.parents


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink() or _is_reparse_point(path)


def _regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink() and not _is_reparse_point(path)


def _file_identity(path: Path) -> dict[str, object]:
    if not _path_exists(path):
        return {"exists": False}
    if not _regular_file(path):
        raise DockerJobError(f"事务文件必须是普通文件：{path}")
    return {
        "exists": True,
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _verify_file_identity(path: Path, expected: object) -> None:
    if not isinstance(expected, dict) or not isinstance(expected.get("exists"), bool):
        raise DockerJobError("Docker 输出旧文件身份无效")
    if not expected["exists"]:
        if _path_exists(path):
            raise DockerJobError(f"本应不存在的事务文件出现：{path}")
        return
    if (
        not _regular_file(path)
        or isinstance(expected.get("size"), bool)
        or not isinstance(expected.get("size"), int)
        or expected["size"] < 0
        or not isinstance(expected.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", expected["sha256"]) is None
        or path.stat().st_size != expected["size"]
        or sha256_file(path) != expected["sha256"]
    ):
        raise DockerJobError(f"Docker 输出旧文件身份不匹配：{path}")


def _unlink_task_file(path: Path) -> None:
    if not _path_exists(path):
        return
    if not _regular_file(path):
        raise DockerJobError(f"任务临时路径类型无效：{path}")
    path.unlink()


def _git_boundary(path: Path) -> Path | None:
    for candidate in (path.resolve(), *path.resolve().parents):
        marker = candidate / ".git"
        if _path_exists(marker):
            return candidate
    return None


class DockerJobs:
    def __init__(
        self,
        paths: AppPaths,
        runner: Runner | None = None,
        *,
        resource_verifier: Callable[[Path, str], None] | None = None,
    ) -> None:
        self.paths = paths
        self.runner = runner or CommandRunner()
        self._resource_verifier = resource_verifier or self._verify_resource_tree
        self._retained: RetainedImage | None = None

    def _verify_resource_tree(self, source_root: Path, build_id: str) -> None:
        manager = ResourceManager(self.paths)
        try:
            manifest = manager.load_manifest()
            if manifest.build_id != build_id:
                raise DockerJobError("内置资源清单与 Docker build_id 不一致")
            manager.verify_tree(source_root, manifest)
        except ResourceError as exc:
            raise DockerJobError(f"内置 Docker 资源校验失败：{exc}") from exc

    @property
    def journal_dir(self) -> Path:
        return self.paths.work_dir / "docker-jobs"

    def _ensure_journal_dir(self, *, create: bool) -> bool:
        if create:
            self.paths.ensure_control_directories()
        directory = self.journal_dir
        self.paths.assert_owned_work_path(directory)
        if _path_exists(directory):
            if directory.is_symlink() or _is_reparse_point(directory) or not directory.is_dir():
                raise DockerJobError(f"Docker journal 目录类型无效：{directory}")
            return True
        if not create:
            return False
        directory.mkdir(parents=False, exist_ok=False)
        if directory.is_symlink() or _is_reparse_point(directory) or not directory.is_dir():
            raise DockerJobError(f"Docker journal 目录类型无效：{directory}")
        return True

    def docker_available(self) -> bool:
        try:
            result = self.runner.run(
                ["docker", "version", "--format", "{{.Server.Version}}"], check=False
            )
        except OSError:
            return False
        return result.returncode == 0 and bool(result.output.strip())

    def _journal_path(self, job_id: str) -> Path:
        if not _JOB_ID_RE.fullmatch(job_id):
            raise DockerJobError(f"Docker 作业 ID 无效：{job_id!r}")
        path = self.journal_dir / f"image-export-{job_id}.json"
        self.paths.assert_owned_work_path(path)
        return path

    def _read_journal(self, path: Path) -> dict[str, Any]:
        self._ensure_journal_dir(create=False)
        self.paths.assert_owned_work_path(path)
        if not _regular_file(path):
            raise DockerJobError(f"Docker 作业 journal 必须是普通文件：{path}")
        try:
            if path.stat().st_size > _MAX_JOURNAL_BYTES:
                raise DockerJobError(f"Docker 作业 journal 超过大小上限：{path}")
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DockerJobError(f"Docker 作业 journal 无效：{path}") from exc
        if (
            not isinstance(raw, dict)
            or raw.get("schema_version") != 1
            or isinstance(raw.get("schema_version"), bool)
            or isinstance(raw.get("created_at"), bool)
            or not isinstance(raw.get("created_at"), int)
            or raw["created_at"] < 0
        ):
            raise DockerJobError("Docker 作业 journal schema 无效")
        job_id = raw.get("job_id")
        if not isinstance(job_id, str) or path != self._journal_path(job_id):
            raise DockerJobError("Docker 作业 journal 路径与作业 ID 不匹配")
        build_id = raw.get("build_id")
        tag = raw.get("tag")
        match = _TEMP_TAG_RE.fullmatch(tag) if isinstance(tag, str) else None
        if (
            raw.get("kind") != "image-export"
            or raw.get("product_version") != PRODUCT_VERSION
            or raw.get("platform") != DOCKER_PLATFORM
            or not isinstance(build_id, str)
            or not _BUILD_ID_RE.fullmatch(build_id)
            or match is None
            or match.group("version") != PRODUCT_VERSION
            or match.group("build") != build_id
            or match.group("job") != job_id
            or raw.get("state") not in _JOURNAL_STATES
        ):
            raise DockerJobError("Docker 作业 journal 身份或状态无效")
        return raw

    def _write_journal(self, retained: RetainedImage, **updates: object) -> dict[str, Any]:
        self._ensure_journal_dir(create=True)
        if _path_exists(retained.journal_path) and not _regular_file(retained.journal_path):
            raise DockerJobError(f"Docker 作业 journal 必须是普通文件：{retained.journal_path}")
        if retained.journal_path.exists():
            raw = self._read_journal(retained.journal_path)
        else:
            raw = {
                "schema_version": 1,
                "kind": "image-export",
                "product_version": PRODUCT_VERSION,
                "platform": DOCKER_PLATFORM,
                "job_id": retained.job_id,
                "build_id": retained.build_id,
                "tag": retained.tag,
                "created_at": int(time.time()),
            }
        raw.update(updates)
        _atomic_json(retained.journal_path, raw)
        return raw

    def _inspect_image(self, reference: str) -> dict[str, Any] | None:
        result = self.runner.run(["docker", "image", "inspect", reference], check=False)
        if result.returncode != 0:
            listing = self.runner.run(
                [
                    "docker",
                    "image",
                    "ls",
                    "--quiet",
                    "--no-trunc",
                    "--filter",
                    f"reference={reference}",
                ],
                check=False,
            )
            if listing.returncode != 0:
                raise DockerJobError("无法确认 Docker 临时镜像是否存在")
            if listing.output.strip():
                raise DockerJobError("Docker 临时镜像存在，但 inspect 失败")
            return None
        try:
            payload = json.loads(result.output)
        except json.JSONDecodeError as exc:
            raise DockerJobError("docker image inspect 返回无效 JSON") from exc
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise DockerJobError("docker image inspect 返回结构无效")
        return payload[0]

    @staticmethod
    def _labels(image: dict[str, Any]) -> dict[str, str]:
        config = image.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        return labels if isinstance(labels, dict) else {}

    def _verify_owned_image(self, retained: RetainedImage, *, platform: bool = True) -> dict[str, Any]:
        image = self._inspect_image(retained.tag)
        if image is None:
            raise DockerJobError(f"临时镜像不存在：{retained.tag}")
        labels = self._labels(image)
        expected = {
            OWNER_LABEL_KEY: OWNER_LABEL_VALUE,
            JOB_LABEL_KEY: retained.job_id,
            BUILD_LABEL_KEY: retained.build_id,
        }
        if any(labels.get(key) != value for key, value in expected.items()):
            raise DockerJobError("临时镜像所有权标签不匹配")
        if platform and (image.get("Os") != "linux" or image.get("Architecture") != "amd64"):
            raise DockerJobError("临时镜像不是 linux/amd64")
        image_id = image.get("Id")
        if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise DockerJobError("临时镜像 ID 无效")
        return image

    def _new_retained(self, build_id: str) -> RetainedImage:
        job_id = uuid.uuid4().hex
        tag = f"bili-workspace-export:{PRODUCT_VERSION}-{build_id}-{job_id}"
        return RetainedImage(job_id, build_id, tag, self._journal_path(job_id))

    def _validate_output_dir(self, output_dir: Path) -> Path:
        selected = Path(output_dir)
        if selected.is_symlink() or _is_reparse_point(selected):
            raise DockerJobError(f"输出目录不能是符号链接或重解析点：{selected}")
        try:
            root = selected.resolve(strict=True)
        except OSError as exc:
            raise DockerJobError(f"输出目录不存在：{selected}") from exc
        if not root.is_dir():
            raise DockerJobError(f"输出目录不存在或类型无效：{root}")
        if _inside(root, self.paths.base_dir) or _inside(self.paths.base_dir, root):
            raise DockerJobError("Docker 输出目录不能与 EXE 控制根重叠")
        boundary = _git_boundary(root)
        if boundary is not None:
            raise DockerJobError(f"Docker 输出目录不能位于 Git 工作树内：{boundary}")
        return root

    @staticmethod
    def _old_build_id(paths: ExportPaths) -> str:
        if not _regular_file(paths.manifest):
            return ""
        try:
            if paths.manifest.stat().st_size > 2 * 1024 * 1024:
                return ""
            raw = json.loads(paths.manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return ""
        build_id = raw.get("build_id") if isinstance(raw, dict) else None
        return build_id if isinstance(build_id, str) and _BUILD_ID_RE.fullmatch(build_id) else ""

    def preflight_export(self, output_dir: Path, build_id: str) -> ExportPreflight:
        if not _BUILD_ID_RE.fullmatch(build_id):
            raise DockerJobError("build_id 无效")
        output_root = self._validate_output_dir(output_dir)
        paths = expected_export_paths(output_root, build_id)
        identities = tuple(
            _file_identity(path) for path in (paths.tar, paths.checksum, paths.manifest)
        )
        return ExportPreflight(
            build_id=build_id,
            output_dir=output_root,
            paths=paths,
            old_files=identities,
            old_build_id=self._old_build_id(paths),
        )

    def _verify_preflight(
        self,
        preflight: ExportPreflight,
        *,
        output_dir: Path,
        build_id: str,
    ) -> ExportPreflight:
        if not isinstance(preflight, ExportPreflight) or preflight.build_id != build_id:
            raise DockerJobError("Docker 输出预检身份无效")
        output_root = self._validate_output_dir(output_dir)
        expected = expected_export_paths(output_root, build_id)
        if preflight.output_dir != output_root or preflight.paths != expected:
            raise DockerJobError("Docker 输出预检路径与当前选择不一致")
        current = tuple(
            _file_identity(path)
            for path in (expected.tar, expected.checksum, expected.manifest)
        )
        if current != preflight.old_files:
            raise DockerJobError("Docker 输出目标在覆盖确认后发生变化，拒绝继续")
        return preflight

    @staticmethod
    def _read_unique_tar_member(
        path: Path,
        member_name: str,
        *,
        max_bytes: int,
        label: str,
    ) -> bytes:
        match_count = 0
        payload: bytes | None = None
        try:
            with tarfile.open(path, mode="r") as archive:
                for index, member in enumerate(archive, 1):
                    if index > _MAX_TAR_MEMBERS:
                        raise DockerJobError("Docker tar 成员数量超过安全上限")
                    if member.name != member_name:
                        continue
                    match_count += 1
                    if (
                        match_count > 1
                        or not member.isfile()
                        or member.size <= 0
                        or member.size > max_bytes
                    ):
                        raise DockerJobError(f"Docker tar 必须包含唯一普通{label}")
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise DockerJobError(f"Docker tar 的{label}不可读")
                    payload = stream.read(max_bytes + 1)
                    if len(payload) != member.size:
                        raise DockerJobError(f"Docker tar 的{label}长度无效")
        except (OSError, tarfile.TarError) as exc:
            raise DockerJobError("Docker tar 结构无效") from exc
        if match_count != 1 or payload is None:
            raise DockerJobError(f"Docker tar 必须包含唯一普通{label}")
        return payload

    @staticmethod
    def _validate_tar(path: Path, image_id: str, tag: str) -> None:
        if not _regular_file(path):
            raise DockerJobError("Docker tar 必须是普通文件")
        digest = image_id.removeprefix("sha256:")
        try:
            manifest_payload = DockerJobs._read_unique_tar_member(
                path,
                "manifest.json",
                max_bytes=_MAX_EXPORT_MANIFEST_BYTES,
                label="manifest.json",
            )
            raw = json.loads(manifest_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DockerJobError("Docker tar manifest 无效") from exc
        if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict):
            raise DockerJobError("Docker tar manifest 结构无效")
        config = str(raw[0].get("Config") or "")
        repo_tags = raw[0].get("RepoTags")
        if (
            re.fullmatch(rf"{digest}\.json", config) is None
            or not isinstance(repo_tags, list)
            or not all(isinstance(value, str) for value in repo_tags)
            or tag not in repo_tags
        ):
            raise DockerJobError("Docker tar 与已核验镜像身份不一致")
        try:
            config_payload = DockerJobs._read_unique_tar_member(
                path,
                config,
                max_bytes=8 * 1024 * 1024,
                label="镜像 config",
            )
            config_raw = json.loads(config_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DockerJobError("Docker tar 镜像 config 无效") from exc
        tag_match = _TEMP_TAG_RE.fullmatch(tag)
        config_section = config_raw.get("config") if isinstance(config_raw, dict) else None
        labels = config_section.get("Labels") if isinstance(config_section, dict) else None
        if (
            hashlib.sha256(config_payload).hexdigest() != digest
            or not isinstance(config_raw, dict)
            or config_raw.get("os") != "linux"
            or config_raw.get("architecture") != "amd64"
            or tag_match is None
            or not isinstance(labels, dict)
            or labels.get(OWNER_LABEL_KEY) != OWNER_LABEL_VALUE
            or labels.get(JOB_LABEL_KEY) != tag_match.group("job")
            or labels.get(BUILD_LABEL_KEY) != tag_match.group("build")
        ):
            raise DockerJobError("Docker tar 镜像 config 身份、架构或所有权标签不一致")

    @staticmethod
    def _validate_triad(paths: ExportPaths, *, build_id: str, image_id: str | None = None) -> dict[str, Any]:
        if not all(_regular_file(path) for path in (paths.tar, paths.checksum, paths.manifest)):
            raise DockerJobError("Docker 导出三件套必须全部是普通文件")
        try:
            if paths.manifest.stat().st_size > _MAX_EXPORT_MANIFEST_BYTES:
                raise DockerJobError("Docker 导出 JSON 超过大小上限")
            raw = json.loads(paths.manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DockerJobError("Docker 导出 JSON 无效") from exc
        size_bytes = raw.get("size_bytes") if isinstance(raw, dict) else None
        image_size_bytes = raw.get("image_size_bytes") if isinstance(raw, dict) else None
        build_time = raw.get("build_time_utc") if isinstance(raw, dict) else None
        if (
            not isinstance(raw, dict)
            or raw.get("schema_version") != 1
            or isinstance(raw.get("schema_version"), bool)
            or raw.get("product") != "bili_workspace"
            or raw.get("version") != PRODUCT_VERSION
            or raw.get("build_id") != build_id
            or raw.get("platform") != DOCKER_PLATFORM
            or isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or size_bytes <= 0
            or isinstance(image_size_bytes, bool)
            or not isinstance(image_size_bytes, int)
            or image_size_bytes < 0
            or not isinstance(build_time, str)
        ):
            raise DockerJobError("Docker 导出 JSON 身份不一致")
        try:
            parsed_time = datetime.fromisoformat(build_time.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DockerJobError("Docker 导出构建时间无效") from exc
        if parsed_time.tzinfo is None or parsed_time.utcoffset() != timezone.utc.utcoffset(None):
            raise DockerJobError("Docker 导出构建时间必须是 UTC")
        recorded_id = raw.get("image_id")
        image_tag = raw.get("image_tag")
        tag_match = _TEMP_TAG_RE.fullmatch(image_tag) if isinstance(image_tag, str) else None
        if (
            not isinstance(recorded_id, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", recorded_id)
            or (image_id is not None and recorded_id != image_id)
            or tag_match is None
            or tag_match.group("version") != PRODUCT_VERSION
            or tag_match.group("build") != build_id
        ):
            raise DockerJobError("Docker 导出镜像 ID 不一致")
        if not paths.tar.is_file() or paths.tar.stat().st_size != size_bytes:
            raise DockerJobError("Docker tar 大小与 JSON 不一致")
        digest = sha256_file(paths.tar)
        if digest != raw.get("sha256"):
            raise DockerJobError("Docker tar SHA-256 与 JSON 不一致")
        try:
            if paths.checksum.stat().st_size > _MAX_CHECKSUM_BYTES:
                raise DockerJobError("Docker SHA-256 文件超过大小上限")
            checksum = paths.checksum.read_text(encoding="ascii").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise DockerJobError("Docker SHA-256 文件不可读") from exc
        if checksum != f"{digest}  {paths.tar.name}":
            raise DockerJobError("Docker SHA-256 文件内容不一致")
        DockerJobs._validate_tar(paths.tar, recorded_id, image_tag)
        return raw

    def _ensure_no_pending_output_recovery(self) -> None:
        if not self._ensure_journal_dir(create=False):
            return
        for journal_path in sorted(self.journal_dir.glob("image-export-*.json")):
            raw = self._read_journal(journal_path)
            if raw.get("state") in _OUTPUT_RECOVERY_STATES:
                raise DockerJobError("存在尚未恢复的 Docker 输出事务，禁止开始新导出")

    def export_image(
        self,
        *,
        source_root: Path,
        output_dir: Path,
        build_id: str,
        overwrite: bool,
        on_output: Callable[[str], None] | None = None,
        preflight: ExportPreflight | None = None,
    ) -> ExportResult:
        if not _BUILD_ID_RE.fullmatch(build_id):
            raise DockerJobError("build_id 无效")
        self._ensure_no_pending_output_recovery()
        checked = self._verify_preflight(
            preflight or self.preflight_export(output_dir, build_id),
            output_dir=output_dir,
            build_id=build_id,
        )
        output_root = checked.output_dir
        paths = checked.paths
        if any(bool(identity["exists"]) for identity in checked.old_files) and not overwrite:
            raise DockerJobError("输出三件套已存在，必须逐次确认覆盖")
        source_candidate = Path(source_root)
        if source_candidate.is_symlink() or _is_reparse_point(source_candidate):
            raise DockerJobError("内置资源根类型无效")
        try:
            resolved_source = source_candidate.resolve(strict=True)
        except OSError as exc:
            raise DockerJobError("内置资源根不存在") from exc
        self.paths.assert_owned_resource_path(resolved_source)
        if not resolved_source.is_dir():
            raise DockerJobError("内置资源根类型无效")
        self._resource_verifier(resolved_source, build_id)
        context_candidate = resolved_source / "docker-context"
        if context_candidate.is_symlink() or _is_reparse_point(context_candidate):
            raise DockerJobError("内置 Docker 构建上下文类型无效")
        context = context_candidate.resolve()
        if not _inside(context, resolved_source):
            raise DockerJobError("内置 Docker 构建上下文越出资源根")
        dockerfile = context / "docker" / "Dockerfile"
        if not _regular_file(dockerfile):
            raise DockerJobError("内置 Docker 构建上下文不完整")

        retained = self._retained
        if retained is not None and retained.build_id == build_id:
            try:
                self._verify_owned_image(retained)
            except DockerJobError:
                retained = None
                self._retained = None
        else:
            retained = None
        if retained is None:
            retained = self._new_retained(build_id)
            self._write_journal(retained, state="building")
            try:
                self.runner.run(
                    [
                        "docker",
                        "build",
                        "--platform",
                        DOCKER_PLATFORM,
                        "--label",
                        f"{OWNER_LABEL_KEY}={OWNER_LABEL_VALUE}",
                        "--label",
                        f"{JOB_LABEL_KEY}={retained.job_id}",
                        "--label",
                        f"{BUILD_LABEL_KEY}={build_id}",
                        "--tag",
                        retained.tag,
                        "--file",
                        str(dockerfile),
                        str(context),
                    ],
                    on_output=on_output,
                )
                self._verify_owned_image(retained)
            except (CommandError, OSError, DockerJobError) as exc:
                self._retained = retained
                detail = redact_sensitive(str(exc).replace("\r", " ").replace("\n", " "))
                detail = " ".join(detail.split())[:1000]
                journal_error: Exception | None = None
                try:
                    self._write_journal(retained, state="failed", error=detail)
                except (OSError, DockerJobError) as write_exc:
                    journal_error = write_exc
                message = detail or "Docker 构建失败"
                if journal_error is not None:
                    message += "；失败 journal 更新失败，已保留原 journal 供恢复"
                raise DockerJobError(message) from exc
            self._retained = retained
            self._write_journal(retained, state="ready")

        image = self._verify_owned_image(retained)
        image_id = str(image["Id"])
        raw_image_size = image.get("Size")
        if (
            isinstance(raw_image_size, bool)
            or not isinstance(raw_image_size, int)
            or raw_image_size < 0
        ):
            raise DockerJobError("临时镜像大小无效")
        image_size = raw_image_size
        temporary, backups = _task_export_paths(paths, retained.job_id)
        for candidate in (
            temporary.tar,
            temporary.checksum,
            temporary.manifest,
            backups.tar,
            backups.checksum,
            backups.manifest,
        ):
            if _path_exists(Path(candidate)):
                raise DockerJobError(f"任务临时路径已存在，拒绝覆盖：{candidate}")
        try:
            self._write_journal(
                retained,
                state="exporting",
                output_dir=str(output_root),
                targets=[str(path) for path in (paths.tar, paths.checksum, paths.manifest)],
                temporary=[
                    str(path)
                    for path in (temporary.tar, temporary.checksum, temporary.manifest)
                ],
                backups=[str(path) for path in (backups.tar, backups.checksum, backups.manifest)],
            )
            self.runner.run(
                ["docker", "image", "save", "--output", str(temporary.tar), retained.tag],
                on_output=on_output,
            )
            if not temporary.tar.is_file() or temporary.tar.stat().st_size <= 0:
                raise DockerJobError("Docker 导出的 tar 文件为空")
            self._validate_tar(temporary.tar, image_id, retained.tag)
            digest = sha256_file(temporary.tar)
            _write_bytes(temporary.checksum, f"{digest}  {paths.tar.name}\n".encode("ascii"))
            export_manifest: dict[str, object] = {
                "schema_version": 1,
                "product": "bili_workspace",
                "version": PRODUCT_VERSION,
                "build_id": build_id,
                "platform": DOCKER_PLATFORM,
                "image_id": image_id,
                "image_tag": retained.tag,
                "image_size_bytes": image_size,
                "size_bytes": temporary.tar.stat().st_size,
                "sha256": digest,
                "build_time_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            _write_bytes(
                temporary.manifest,
                (json.dumps(export_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            )
            self._publish_transaction(
                retained,
                paths,
                temporary,
                backups,
                export_manifest,
                checked.old_files,
            )
            self._write_journal(
                retained,
                state="cleanup-required",
                output_recovered=True,
            )
        except (CommandError, OSError, DockerJobError, tarfile.TarError) as exc:
            self._retained = retained
            try:
                raw = self._read_journal(retained.journal_path)
                if raw.get("state") == "exporting":
                    for candidate in (
                        temporary.tar,
                        temporary.checksum,
                        temporary.manifest,
                    ):
                        _unlink_task_file(candidate)
                    self._write_journal(
                        retained,
                        state="failed",
                        output_recovered=True,
                        error=redact_sensitive(str(exc))[:1000],
                    )
                elif raw.get("state") in _OUTPUT_RECOVERY_STATES:
                    self._write_journal(retained, error=redact_sensitive(str(exc))[:1000])
                else:
                    self._write_journal(
                        retained,
                        state="failed",
                        error=redact_sensitive(str(exc))[:1000],
                    )
            except Exception:
                pass
            raise DockerJobError(str(exc)) from exc
        finally:
            for candidate in (temporary.tar, temporary.checksum, temporary.manifest):
                try:
                    _unlink_task_file(candidate)
                except DockerJobError:
                    pass

        cleanup_warning = ""
        try:
            self._verify_owned_image(retained)
            self.runner.run(["docker", "image", "rm", "--no-prune", retained.tag])
            retained.journal_path.unlink(missing_ok=True)
            self._retained = None
        except (CommandError, OSError, DockerJobError) as exc:
            self._retained = retained
            self._write_journal(retained, state="cleanup-required")
            cleanup_warning = f"产物已完成，但自有临时镜像需要稍后精确清理：{exc}"
        return ExportResult(paths, cleanup_warning)

    def _publish_transaction(
        self,
        retained: RetainedImage,
        targets: ExportPaths,
        temporary: ExportPaths,
        backups: ExportPaths,
        export_manifest: dict[str, object],
        expected_old_files: tuple[
            dict[str, object], dict[str, object], dict[str, object]
        ],
    ) -> None:
        target_list = (targets.tar, targets.checksum, targets.manifest)
        temp_list = (temporary.tar, temporary.checksum, temporary.manifest)
        backup_list = (backups.tar, backups.checksum, backups.manifest)
        if not all(_regular_file(path) for path in temp_list):
            raise DockerJobError("Docker 临时三件套不完整或类型无效")
        current_old_files = tuple(_file_identity(path) for path in target_list)
        if current_old_files != expected_old_files:
            raise DockerJobError("Docker 输出目标在构建期间发生变化，拒绝覆盖")
        old_files = [dict(identity) for identity in expected_old_files]
        had_existing = [bool(identity["exists"]) for identity in old_files]
        self._write_journal(
            retained,
            state="publishing",
            output_dir=str(targets.tar.parent),
            targets=[str(path) for path in target_list],
            temporary=[str(path) for path in temp_list],
            backups=[str(path) for path in backup_list],
            had_existing=had_existing,
            old_files=old_files,
            export_manifest=export_manifest,
        )
        try:
            for target, backup, existed in zip(
                target_list, backup_list, had_existing, strict=True
            ):
                if existed:
                    os.replace(target, backup)
            for backup, identity in zip(backup_list, old_files, strict=True):
                _verify_file_identity(backup, identity)
            for temporary_path, target in zip(temp_list, target_list, strict=True):
                os.replace(temporary_path, target)
            published_manifest = self._validate_triad(
                targets,
                build_id=retained.build_id,
                image_id=str(export_manifest.get("image_id") or ""),
            )
            if published_manifest != export_manifest:
                raise DockerJobError("Docker 已发布三件套与事务清单不一致")
            self._write_journal(retained, state="committed")
        except (OSError, DockerJobError):
            try:
                self._restore_old_outputs(target_list, backup_list, old_files)
                for target, identity in zip(target_list, old_files, strict=True):
                    _verify_file_identity(target, identity)
                self._write_journal(retained, state="failed", output_recovered=True)
            except (OSError, DockerJobError):
                pass
            raise
        for backup in backup_list:
            _unlink_task_file(backup)

    @staticmethod
    def _restore_old_outputs(
        targets: tuple[Path, Path, Path] | list[Path],
        backups: tuple[Path, Path, Path] | list[Path],
        old_files: list[dict[str, object]],
    ) -> None:
        for target, backup, identity in zip(targets, backups, old_files, strict=True):
            existed = bool(identity.get("exists"))
            if _path_exists(backup):
                _verify_file_identity(backup, identity)
                if _path_exists(target):
                    _unlink_task_file(target)
                os.replace(backup, target)
            elif not existed:
                if _path_exists(target):
                    _unlink_task_file(target)
            else:
                _verify_file_identity(target, identity)

    def recover_pending_outputs(self) -> list[str]:
        """恢复中断的三文件发布；不触碰 journal 未精确登记的路径。"""

        if not self._ensure_journal_dir(create=False):
            return []
        messages: list[str] = []
        for journal_path in sorted(self.journal_dir.glob("image-export-*.json")):
            raw = self._read_journal(journal_path)
            state = raw.get("state")
            if state not in _OUTPUT_RECOVERY_STATES:
                continue
            build_id = raw.get("build_id")
            job_id = raw.get("job_id")
            output_value = raw.get("output_dir")
            target_values = raw.get("targets")
            backup_values = raw.get("backups")
            temp_values = raw.get("temporary")
            if (
                not isinstance(build_id, str)
                or not _BUILD_ID_RE.fullmatch(build_id)
                or not isinstance(job_id, str)
                or not _JOB_ID_RE.fullmatch(job_id)
                or not isinstance(output_value, str)
                or not Path(output_value).is_absolute()
                or not isinstance(target_values, list)
                or not isinstance(backup_values, list)
                or not isinstance(temp_values, list)
                or not all(
                    len(values) == 3
                    for values in (
                        target_values,
                        backup_values,
                        temp_values,
                    )
                )
                or not all(
                    isinstance(value, str)
                    for value in target_values + backup_values + temp_values
                )
            ):
                raise DockerJobError(f"无法安全恢复不完整 journal：{journal_path}")
            output_root = self._validate_output_dir(Path(output_value))
            expected = expected_export_paths(output_root, build_id)
            expected_temporary, expected_backups = _task_export_paths(expected, job_id)
            targets = [expected.tar, expected.checksum, expected.manifest]
            backups = [expected_backups.tar, expected_backups.checksum, expected_backups.manifest]
            temporary = [
                expected_temporary.tar,
                expected_temporary.checksum,
                expected_temporary.manifest,
            ]
            declared_groups = (target_values, backup_values, temp_values)
            expected_groups = (targets, backups, temporary)
            if any(
                any(
                    not Path(declared).is_absolute()
                    or Path(declared).resolve(strict=False) != expected_path.resolve(strict=False)
                    for declared, expected_path in zip(declared_group, expected_group, strict=True)
                )
                for declared_group, expected_group in zip(
                    declared_groups, expected_groups, strict=True
                )
            ):
                raise DockerJobError("恢复 journal 的事务路径不符合固定契约")
            if state == "exporting":
                for path in temporary:
                    _unlink_task_file(path)
                raw["state"] = "cleanup-required"
                raw["output_recovered"] = True
                _atomic_json(journal_path, raw)
                messages.append(f"已清理中断的 Docker 临时导出：{output_root}")
                continue

            had_existing = raw.get("had_existing")
            old_files = raw.get("old_files")
            if (
                not isinstance(had_existing, list)
                or not isinstance(old_files, list)
                or len(had_existing) != 3
                or len(old_files) != 3
                or not all(isinstance(value, bool) for value in had_existing)
                or not all(isinstance(value, dict) for value in old_files)
                or not all(isinstance(value.get("exists"), bool) for value in old_files)
                or [bool(value.get("exists")) for value in old_files] != had_existing
            ):
                raise DockerJobError(f"无法安全恢复不完整 journal：{journal_path}")
            try:
                recovered_manifest = self._validate_triad(expected, build_id=build_id)
                if recovered_manifest != raw.get("export_manifest"):
                    raise DockerJobError("Docker 新产物与 journal 身份不一致")
                for path in backups + temporary:
                    _unlink_task_file(path)
                messages.append(f"已确认完成的 Docker 三件套：{expected.tar.parent}")
            except DockerJobError:
                self._restore_old_outputs(targets, backups, old_files)
                for target, identity in zip(targets, old_files, strict=True):
                    _verify_file_identity(target, identity)
                for path in temporary:
                    _unlink_task_file(path)
                messages.append(f"已恢复中断前的 Docker 输出：{expected.tar.parent}")
            raw["state"] = "cleanup-required"
            raw["output_recovered"] = True
            _atomic_json(journal_path, raw)
        return messages

    def cleanup_session_image(self) -> str:
        retained = self._retained
        if retained is None:
            return ""
        try:
            raw = self._read_journal(retained.journal_path)
            self._verify_owned_image(retained, platform=False)
            self.runner.run(["docker", "image", "rm", "--no-prune", retained.tag])
        except (CommandError, OSError, DockerJobError) as exc:
            return f"无法清理本会话自有临时镜像：{exc}"
        self._retained = None
        if raw.get("state") in _OUTPUT_RECOVERY_STATES:
            return "Docker 临时镜像已清理，但输出恢复 journal 已保留到下次启动。"
        retained.journal_path.unlink(missing_ok=True)
        return ""

    def stale_images(self) -> list[RetainedImage]:
        if not self._ensure_journal_dir(create=False):
            return []
        records: list[RetainedImage] = []
        for path in sorted(self.journal_dir.glob("image-export-*.json")):
            try:
                raw = self._read_journal(path)
                job_id = raw["job_id"]
                build_id = raw["build_id"]
                tag = raw["tag"]
                state = raw["state"]
            except (DockerJobError, KeyError, TypeError):
                continue
            if state in _OUTPUT_RECOVERY_STATES:
                continue
            match = _TEMP_TAG_RE.fullmatch(tag) if isinstance(tag, str) else None
            if (
                match is None
                or match.group("job") != job_id
                or match.group("build") != build_id
                or match.group("version") != PRODUCT_VERSION
            ):
                continue
            retained = RetainedImage(job_id, build_id, tag, path)
            try:
                image = self._inspect_image(retained.tag)
                if image is None:
                    _unlink_task_file(path)
                    continue
                self._verify_owned_image(retained, platform=False)
            except (OSError, DockerJobError):
                continue
            records.append(retained)
        return records

    def cleanup_stale_image(self, retained: RetainedImage) -> None:
        if retained.journal_path != self._journal_path(retained.job_id):
            raise DockerJobError("遗留镜像 journal 不属于启动器")
        raw = self._read_journal(retained.journal_path)
        if raw.get("state") in _OUTPUT_RECOVERY_STATES:
            raise DockerJobError("Docker 输出事务尚未恢复，禁止删除其 journal")
        self._verify_owned_image(retained, platform=False)
        try:
            self.runner.run(["docker", "image", "rm", "--no-prune", retained.tag])
        except (CommandError, OSError) as exc:
            raise DockerJobError(str(exc)) from exc
        retained.journal_path.unlink(missing_ok=True)
