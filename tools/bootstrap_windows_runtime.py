from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from app.io_utils import atomic_write_text
from app.paths import ROOT

RUNTIME_VERSION = "0.5.4"
RUNTIME_FILENAME = f"bili_workspace_v{RUNTIME_VERSION}_windows_runtime.zip"
RUNTIME_URL = (
    "https://github.com/kachekakaka/bili_workspace/releases/download/"
    f"v{RUNTIME_VERSION}/{RUNTIME_FILENAME}"
)
RUNTIME_SHA256 = "e084d898d3c7405488380bb4bda8cd11786158bf2af5e974cf455abf1615f8c4"
CHUNK_SIZE = 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
USER_AGENT = f"bili-workspace/{RUNTIME_VERSION} windows-runtime-bootstrap"
ALLOWED_PREFIXES = ("BBDown_portable/", "wheelhouse/", "LICENSES/")
EXPECTED_TOOL_HASHES = {
    "BBDown.exe": "eb8b985af07c4757fa695204283208aee879bf79f6462a1d161e3a55b5a19cb1",
    "ffmpeg/bin/ffmpeg.exe": "a25942892c8e5180c2998f9936f56e914cece03708b93e8d54f38d23304dcf8c",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/")
    member = PurePosixPath(normalized)
    if member.is_absolute() or not member.parts or ".." in member.parts:
        raise ValueError(f"运行包包含不安全路径: {value}")
    if member.parts[0].endswith(":"):
        raise ValueError(f"运行包包含 Windows 绝对路径: {value}")
    if value == "runtime_manifest.sha256":
        return member
    if not any(value.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        raise ValueError(f"运行包包含未允许路径: {value}")
    return member


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def _download(url: str, destination: Path, *, timeout: int = 90) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response, destination.open("wb") as output:
        total_raw = response.headers.get("Content-Length", "")
        total = int(total_raw) if total_raw.isdigit() else 0
        received = 0
        last_report = 0.0
        while True:
            chunk = response.read(CHUNK_SIZE)
            if not chunk:
                break
            output.write(chunk)
            received += len(chunk)
            now = time.monotonic()
            if now - last_report >= 1.0:
                if total:
                    print(f"  downloaded {received / 1024**2:.1f}/{total / 1024**2:.1f} MiB")
                else:
                    print(f"  downloaded {received / 1024**2:.1f} MiB")
                last_report = now
        output.flush()
        os.fsync(output.fileno())


def download_verified(destination: Path, *, retries: int = 3) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        partial = destination.with_name(destination.name + ".part")
        partial.unlink(missing_ok=True)
        try:
            print(f"Downloading Windows runtime package ({attempt}/{retries})...")
            _download(RUNTIME_URL, partial)
            actual = sha256_file(partial)
            if actual.lower() != RUNTIME_SHA256:
                raise ValueError(
                    f"runtime package SHA-256 mismatch: {actual}; expected {RUNTIME_SHA256}"
                )
            os.replace(partial, destination)
            return destination
        except (OSError, urllib.error.URLError, ValueError) as exc:
            last_error = exc
            partial.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Windows runtime download failed: {last_error}") from last_error


def _parse_manifest(text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            digest, name = line.split(None, 1)
        except ValueError as exc:
            raise ValueError(f"运行包清单第 {line_number} 行格式错误") from exc
        name = name.strip().replace("\\", "/")
        _safe_member(name)
        if len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
            raise ValueError(f"运行包清单第 {line_number} 行哈希无效")
        if name in rows:
            raise ValueError(f"运行包清单包含重复路径: {name}")
        rows[name] = digest.lower()
    if not rows:
        raise ValueError("运行包清单为空")
    return rows


def verify_archive(archive_path: Path) -> dict[str, str]:
    actual_archive = sha256_file(archive_path)
    if actual_archive.lower() != RUNTIME_SHA256:
        raise ValueError(
            f"运行包 SHA-256 不匹配: {actual_archive}; 期望 {RUNTIME_SHA256}"
        )

    with zipfile.ZipFile(archive_path) as archive:
        infos: dict[str, zipfile.ZipInfo] = {}
        total = 0
        for info in archive.infolist():
            if info.is_dir():
                continue
            member = _safe_member(info.filename)
            name = member.as_posix()
            if _is_zip_symlink(info):
                raise ValueError(f"运行包不允许符号链接: {name}")
            if name in infos:
                raise ValueError(f"运行包包含重复路径: {name}")
            total += info.file_size
            if total > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("运行包解压后大小超过安全限制")
            infos[name] = info

        manifest_info = infos.get("runtime_manifest.sha256")
        if manifest_info is None:
            raise ValueError("运行包缺少 runtime_manifest.sha256")
        manifest = _parse_manifest(archive.read(manifest_info).decode("utf-8"))
        payload_names = set(infos) - {"runtime_manifest.sha256"}
        if payload_names != set(manifest):
            missing = sorted(set(manifest) - payload_names)
            extra = sorted(payload_names - set(manifest))
            raise ValueError(f"运行包清单与文件不一致; 缺少={missing}; 多余={extra}")

        for name, expected in manifest.items():
            digest = hashlib.sha256()
            with archive.open(infos[name]) as handle:
                for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
                    digest.update(chunk)
            actual = digest.hexdigest()
            if actual != expected:
                raise ValueError(f"运行包内部文件哈希不匹配: {name}")
        return manifest


def _atomic_copy(source, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise ValueError(f"目标不允许是符号链接: {destination}")
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output:
            shutil.copyfileobj(source, output, length=CHUNK_SIZE)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def install_archive(archive_path: Path, *, overwrite: bool) -> list[Path]:
    manifest = verify_archive(archive_path)
    installed: list[Path] = []
    with zipfile.ZipFile(archive_path) as archive:
        infos = {PurePosixPath(info.filename.replace("\\", "/")).as_posix(): info for info in archive.infolist()}
        for name in sorted(manifest):
            destination = ROOT / Path(*PurePosixPath(name).parts)
            if destination.exists() and not overwrite:
                if destination.is_file() and not destination.is_symlink():
                    if sha256_file(destination) == manifest[name]:
                        continue
            with archive.open(infos[name]) as source:
                _atomic_copy(source, destination)
            installed.append(destination)

    manifest_target = ROOT / ".windows_runtime_manifest.sha256"
    atomic_write_text(
        manifest_target,
        "\n".join(f"{digest}  {name}" for name, digest in sorted(manifest.items())) + "\n",
        backup=False,
    )
    write_tool_manifest()
    return installed


def write_tool_manifest() -> Path:
    tool_root = ROOT / "BBDown_portable"
    rows: list[str] = []
    for relative_text, expected in EXPECTED_TOOL_HASHES.items():
        relative = Path(relative_text)
        target = tool_root / relative
        if not target.is_file() or target.is_symlink():
            raise RuntimeError(f"工具文件缺失或类型异常: {target}")
        actual = sha256_file(target)
        if actual != expected:
            raise RuntimeError(
                f"工具文件 SHA-256 不匹配: {relative.as_posix()}; {actual}; 期望 {expected}"
            )
        rows.append(f"{actual}  {relative.as_posix()}")
    manifest = tool_root / "checksums.sha256"
    atomic_write_text(manifest, "\n".join(rows) + "\n", backup=False)
    return manifest


def runtime_present() -> bool:
    tool_root = ROOT / "BBDown_portable"
    for relative, expected in EXPECTED_TOOL_HASHES.items():
        path = tool_root / relative
        if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
            return False
    return len(list((ROOT / "wheelhouse").glob("*.whl"))) >= 23


def _smoke() -> None:
    commands = (
        ([str(ROOT / "BBDown_portable" / "BBDown.exe"), "--help"], "BBDown"),
        (
            [str(ROOT / "BBDown_portable" / "ffmpeg" / "bin" / "ffmpeg.exe"), "-hide_banner", "-version"],
            "ffmpeg version",
        ),
    )
    for command, expected in commands:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0 or expected.lower() not in output.lower():
            raise RuntimeError(
                f"工具冒烟测试失败: {' '.join(command)}\n退出码: {result.returncode}\n{output[-1500:]}"
            )


def choose_archive(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    env_path = os.getenv("BILI_WINDOWS_RUNTIME_ARCHIVE", "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()
    local = ROOT / RUNTIME_FILENAME
    if local.is_file():
        return local
    cached = ROOT / ".tmp" / "runtime-downloads" / RUNTIME_FILENAME
    if cached.is_file() and sha256_file(cached).lower() == RUNTIME_SHA256:
        return cached
    cached.unlink(missing_ok=True)
    return download_verified(cached)


def ensure_windows_runtime(
    *,
    archive: Path | None = None,
    force: bool = False,
    smoke: bool = True,
    force_platform: bool = False,
) -> list[Path]:
    if os.name != "nt" and not force_platform:
        print("[skip] Non-Windows host; Docker installs Linux runtime tools during image build.")
        return []
    if runtime_present() and not force:
        write_tool_manifest()
        print("[ok] Existing Windows runtime and wheelhouse will be reused.")
        if smoke and os.name == "nt":
            _smoke()
        return []

    archive_path = choose_archive(archive)
    if not archive_path.is_file():
        raise RuntimeError(f"Windows 运行包不存在: {archive_path}")
    installed = install_archive(archive_path, overwrite=force)
    print(f"[ok] Installed/verified {len(installed)} Windows runtime files.")
    if smoke and os.name == "nt":
        _smoke()
        print("[ok] BBDown and FFmpeg smoke tests passed.")
    return installed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the verified bili_workspace Windows runtime")
    parser.add_argument("--archive", type=Path, help="Use a local runtime ZIP instead of GitHub Release")
    parser.add_argument("--force", action="store_true", help="Overwrite existing runtime files")
    parser.add_argument("--no-smoke", action="store_true", help="Skip executable smoke tests")
    parser.add_argument("--force-platform", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if os.getenv("BILI_SKIP_RUNTIME_DOWNLOAD", "").strip().lower() in {"1", "true", "yes", "on"}:
        print("[skip] BILI_SKIP_RUNTIME_DOWNLOAD is enabled.")
        return 0
    try:
        ensure_windows_runtime(
            archive=args.archive,
            force=args.force,
            smoke=not args.no_smoke,
            force_platform=args.force_platform,
        )
    except Exception as exc:  # noqa: BLE001 - command-line boundary
        print(f"[error] Windows runtime initialization failed: {exc}", file=sys.stderr)
        print(
            f"Place {RUNTIME_FILENAME} beside setup.bat, copy BBDown_portable/wheelhouse "
            "from a verified full package, or set BILI_SKIP_RUNTIME_DOWNLOAD=1 for media-library-only setup.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
