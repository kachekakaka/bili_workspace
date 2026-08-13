"""内置源码与 Windows 工具的哈希验证和版本化展开。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .paths import AppPaths, _is_reparse_point
from .version import PRODUCT_VERSION

_MARKER_NAME = ".bili-launcher-resource.json"
_MAX_MANIFEST_BYTES = 32 * 1024 * 1024
_MAX_MARKER_BYTES = 64 * 1024
_MAX_RESOURCE_ENTRIES = 50_000
_WINDOWS_RESERVED_BASENAMES = {
    "aux",
    "con",
    "conin$",
    "conout$",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


class ResourceError(RuntimeError):
    """内置资源缺失、被篡改或不能安全展开。"""


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink() or _is_reparse_point(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_manifest_path(relative: str) -> PurePosixPath:
    raw_parts = relative.split("/")
    pure = PurePosixPath(relative)
    if (
        "\\" in relative
        or not pure.parts
        or pure.is_absolute()
        or pure.as_posix() != relative
        or relative == _MARKER_NAME
        or any(
            part in {"", ".", ".."}
            or len(part) > 255
            or part != part.rstrip(" .")
            or ":" in part
            or any(ord(character) < 32 for character in part)
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_BASENAMES
            for part in raw_parts
        )
    ):
        raise ResourceError(f"内置资源路径越界或不适用于 Windows：{relative!r}")
    return pure


def default_bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "resources"
    override = os.getenv("BILI_LAUNCHER_RESOURCE_BUNDLE", "").strip()
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2] / "build" / "bili-launcher-resources"


@dataclass(frozen=True, slots=True)
class ResourceFile:
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class ResourceManifest:
    product_version: str
    build_id: str
    files: dict[str, ResourceFile]
    digest: str


class ResourceManager:
    def __init__(self, paths: AppPaths, bundle_root: Path | None = None) -> None:
        self.paths = paths
        self.bundle_root = (bundle_root or default_bundle_root()).resolve()
        self.source_dir = self.bundle_root / "source"
        self.manifest_path = self.bundle_root / "manifest.json"

    def load_manifest(self) -> ResourceManifest:
        try:
            if self.manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
                raise ResourceError("内置资源清单超过大小上限")
            payload = self.manifest_path.read_bytes()
            raw = json.loads(payload.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResourceError(f"无法读取内置资源清单：{self.manifest_path}") from exc
        if (
            not isinstance(raw, dict)
            or isinstance(raw.get("schema_version"), bool)
            or raw.get("schema_version") != 1
        ):
            raise ResourceError("内置资源清单 schema_version 无效")
        if raw.get("product_version") != PRODUCT_VERSION:
            raise ResourceError("内置资源与启动器产品版本不一致")
        build_id = raw.get("build_id")
        if not isinstance(build_id, str) or len(build_id) != 12 or any(
            character not in "0123456789abcdef" for character in build_id
        ):
            raise ResourceError("内置资源 build_id 无效")
        raw_files = raw.get("files")
        if not isinstance(raw_files, dict) or not raw_files:
            raise ResourceError("内置资源清单缺少 files")
        if len(raw_files) > _MAX_RESOURCE_ENTRIES:
            raise ResourceError("内置资源清单文件数量超过上限")
        files: dict[str, ResourceFile] = {}
        folded_paths: set[str] = set()
        for relative, entry in raw_files.items():
            if not isinstance(relative, str) or not isinstance(entry, dict):
                raise ResourceError("内置资源清单条目类型无效")
            pure = _safe_manifest_path(relative)
            folded = pure.as_posix().casefold()
            if folded in folded_paths:
                raise ResourceError(f"内置资源路径在 Windows 上冲突：{relative!r}")
            folded_paths.add(folded)
            digest = entry.get("sha256")
            size = entry.get("size")
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
                or isinstance(size, bool)
                or not isinstance(size, int)
                or size < 0
            ):
                raise ResourceError(f"内置资源摘要或大小无效：{relative}")
            files[pure.as_posix()] = ResourceFile(digest, size)
        return ResourceManifest(
            product_version=PRODUCT_VERSION,
            build_id=build_id,
            files=files,
            digest=hashlib.sha256(payload).hexdigest(),
        )

    @staticmethod
    def _tree_entries(root: Path) -> list[tuple[Path, bool]]:
        entries: list[tuple[Path, bool]] = []

        def walk(directory: Path) -> None:
            try:
                with os.scandir(directory) as scanned:
                    children = sorted(scanned, key=lambda entry: entry.name.casefold())
            except OSError as exc:
                raise ResourceError(f"无法扫描资源目录：{directory}") from exc
            for child in children:
                path = Path(child.path)
                if child.is_symlink() or _is_reparse_point(path):
                    raise ResourceError(f"资源目录包含符号链接或重解析点：{path}")
                try:
                    is_directory = child.is_dir(follow_symlinks=False)
                    is_file = child.is_file(follow_symlinks=False)
                except OSError as exc:
                    raise ResourceError(f"无法读取资源路径类型：{path}") from exc
                if is_directory:
                    entries.append((path, True))
                    walk(path)
                elif is_file:
                    entries.append((path, False))
                else:
                    raise ResourceError(f"资源目录包含不支持的文件类型：{path}")
                if len(entries) > _MAX_RESOURCE_ENTRIES * 2:
                    raise ResourceError("资源目录条目数量超过上限")

        walk(root)
        return entries

    def verify_tree(self, root: Path, manifest: ResourceManifest) -> None:
        if not root.is_dir() or root.is_symlink() or _is_reparse_point(root):
            raise ResourceError(f"资源目录不存在或类型无效：{root}")
        entries = self._tree_entries(root)
        marker = root / _MARKER_NAME
        actual = {
            path.relative_to(root).as_posix()
            for path, is_directory in entries
            if not is_directory and path != marker
        }
        expected = set(manifest.files)
        if actual != expected:
            raise ResourceError(
                f"资源文件集合不一致：缺失 {sorted(expected - actual)[:3]}；"
                f"多出 {sorted(actual - expected)[:3]}"
            )
        for relative, entry in manifest.files.items():
            path = root.joinpath(*PurePosixPath(relative).parts)
            if (
                not path.is_file()
                or path.is_symlink()
                or _is_reparse_point(path)
                or path.stat().st_size != entry.size
                or sha256_file(path) != entry.sha256
            ):
                raise ResourceError(f"资源摘要或大小不一致：{relative}")

    def verify_embedded_bundle(self) -> ResourceManifest:
        manifest = self.load_manifest()
        self.verify_tree(self.source_dir, manifest)
        return manifest

    def _copy_verified_tree(self, destination: Path) -> None:
        destination.mkdir(parents=False, exist_ok=False)
        for source, is_directory in self._tree_entries(self.source_dir):
            target = destination / source.relative_to(self.source_dir)
            if is_directory:
                target.mkdir(parents=False, exist_ok=False)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

    def _marker_matches(self, target: Path, manifest: ResourceManifest) -> bool:
        marker = target / _MARKER_NAME
        if (
            not marker.is_file()
            or marker.is_symlink()
            or _is_reparse_point(marker)
        ):
            return False
        try:
            if marker.stat().st_size > _MAX_MARKER_BYTES:
                return False
            raw = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False
        return (
            isinstance(raw, dict)
            and not isinstance(raw.get("schema_version"), bool)
            and raw
            == {
                "schema_version": 1,
                "build_id": manifest.build_id,
                "manifest_digest": manifest.digest,
            }
        )

    def ensure_extracted(self) -> tuple[Path, ResourceManifest]:
        manifest = self.verify_embedded_bundle()
        self.paths.ensure_control_directories()
        target = self.paths.resources_dir / manifest.build_id
        self.paths.assert_owned_resource_path(target)
        if _path_exists(target):
            if target.is_symlink() or _is_reparse_point(target) or not target.is_dir():
                raise ResourceError(f"拒绝替换类型无效的资源目录：{target}")
            try:
                if self._marker_matches(target, manifest):
                    self.verify_tree(target, manifest)
                    return target, manifest
            except ResourceError:
                pass
        temporary = self.paths.resources_dir / f".{manifest.build_id}.tmp-{uuid.uuid4().hex}"
        backup = self.paths.resources_dir / f".{manifest.build_id}.bak-{uuid.uuid4().hex}"
        self.paths.assert_owned_resource_path(temporary)
        self.paths.assert_owned_resource_path(backup)
        if _path_exists(temporary) or _path_exists(backup):
            raise ResourceError("随机资源事务路径已存在，拒绝继续")
        replaced_existing = False
        published = False
        try:
            self._copy_verified_tree(temporary)
            self.verify_tree(temporary, manifest)
            (temporary / _MARKER_NAME).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "build_id": manifest.build_id,
                        "manifest_digest": manifest.digest,
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            if _path_exists(target):
                self.paths.assert_owned_resource_path(target)
                if target.is_symlink() or _is_reparse_point(target) or not target.is_dir():
                    raise ResourceError(f"拒绝替换类型无效的资源目录：{target}")
                os.replace(target, backup)
                replaced_existing = True
            os.replace(temporary, target)
            published = True
            self.verify_tree(target, manifest)
        except (OSError, shutil.Error, ResourceError) as exc:
            rollback_error: Exception | None = None
            try:
                if published and _path_exists(target):
                    os.replace(target, temporary)
                if replaced_existing and _path_exists(backup):
                    os.replace(backup, target)
            except OSError as rollback_exc:
                rollback_error = rollback_exc
            if rollback_error is not None:
                raise ResourceError(
                    f"无法展开内置资源到 {target}，且旧资源回滚失败：{rollback_error}"
                ) from exc
            raise ResourceError(f"无法展开内置资源到 {target}") from exc
        else:
            if _path_exists(backup):
                if backup.is_symlink() or _is_reparse_point(backup) or not backup.is_dir():
                    raise ResourceError(f"资源备份路径类型无效：{backup}")
                shutil.rmtree(backup)
        finally:
            if _path_exists(temporary):
                self.paths.assert_owned_resource_path(temporary)
                if temporary.is_symlink() or _is_reparse_point(temporary) or not temporary.is_dir():
                    raise ResourceError(f"资源临时路径类型无效：{temporary}")
                shutil.rmtree(temporary)
        return target, manifest
