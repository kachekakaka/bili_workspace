from __future__ import annotations

import argparse
import hashlib
import json
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

ROOT = Path(__file__).resolve().parent.parent
VERSION = "0.5.6"
PYTHON_VERSION = "3.13.14"
PYTHON_EMBED_NAME = f"python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{PYTHON_EMBED_NAME}"
PYTHON_EMBED_SHA256 = "90b4e5b9898b72d744650524bff92377c367f44bd5fbd09e3148656c080ad907"

BBDOWN_NAME = "BBDown_1.6.3_20240814_win-x64.zip"
BBDOWN_URL = f"https://github.com/nilaoda/BBDown/releases/download/1.6.3/{BBDOWN_NAME}"
BBDOWN_SHA256 = "40f1e2af0d4e74df765c6f93d2e931f9bea201d5168d0bc62dc35a54b7e0ec02"

FFMPEG_WHEEL_NAME = "imageio_ffmpeg-0.6.0-py3-none-win_amd64.whl"
FFMPEG_WHEEL_URL = (
    "https://files.pythonhosted.org/packages/2c/c6/"
    "fa760e12a2483469e2bf5058c5faff664acf66cadb4df2ad6205b016a73d/"
    + FFMPEG_WHEEL_NAME
)
FFMPEG_WHEEL_SHA256 = "02fa47c83703c37df6bfe4896aab339013f62bf02c5ebf2dce6da56af04ffc0a"
FFMPEG_MEMBER = "imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe"

CHUNK_SIZE = 1024 * 1024
MAX_PACK_BYTES = 100 * 1024 * 1024
FIXED_ZIP_TIME = (2026, 7, 18, 0, 0, 0)
USER_AGENT = f"bili-workspace/{VERSION} integrated-runtime-builder"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, expected_sha256: str, destination: Path, retries: int = 5) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and sha256_file(destination) == expected_sha256:
        return destination
    destination.unlink(missing_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        partial = destination.with_suffix(destination.suffix + ".part")
        partial.unlink(missing_ok=True)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            print(f"Downloading {destination.name} ({attempt}/{retries})")
            with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
                while chunk := response.read(CHUNK_SIZE):
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            actual = sha256_file(partial)
            if actual != expected_sha256:
                raise ValueError(
                    f"SHA-256 mismatch for {destination.name}: {actual}; expected {expected_sha256}"
                )
            os.replace(partial, destination)
            return destination
        except (OSError, urllib.error.URLError, ValueError) as exc:
            last_error = exc
            partial.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(attempt * 3)
    raise RuntimeError(f"Unable to download {destination.name}: {last_error}") from last_error


def safe_member(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    raw_parts = normalized.split("/")
    member = PurePosixPath(normalized)
    if (
        not member.parts
        or member.is_absolute()
        or any(part in {"", ".", ".."} for part in raw_parts)
    ):
        raise ValueError(f"Unsafe archive path: {name}")
    if member.parts[0].endswith(":"):
        raise ValueError(f"Windows absolute archive path: {name}")
    return member


def is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def safe_extract(archive_path: Path, destination: Path) -> None:
    seen: set[str] = set()
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            member = safe_member(info.filename)
            name = member.as_posix()
            if name in seen:
                raise ValueError(f"Duplicate archive path: {name}")
            if is_zip_symlink(info):
                raise ValueError(f"Archive symlink is not allowed: {name}")
            seen.add(name)
            target = destination.joinpath(*member.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=CHUNK_SIZE)


def find_unique(root: Path, basename: str) -> Path:
    matches = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.name.lower() == basename.lower()
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {basename}; found {len(matches)}")
    return matches[0]


def clean_python_tree(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir() and path.name in {"__pycache__", ".pytest_cache"}:
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_file() and path.suffix in {".pyc", ".pyo"}:
            path.unlink(missing_ok=True)


def write_internal_manifest(root: Path) -> None:
    rows: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "runtime_manifest.sha256":
            continue
        rel = path.relative_to(root).as_posix()
        rows.append(f"{sha256_file(path)}  {rel}")
    (root / "runtime_manifest.sha256").write_text(
        "\n".join(rows) + "\n", encoding="utf-8"
    )


def deterministic_zip(source: Path, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        temporary,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        allowZip64=True,
    ) as archive:
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(rel, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info,
                path.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    if temporary.stat().st_size >= MAX_PACK_BYTES:
        raise ValueError(
            f"{destination.name} is {temporary.stat().st_size} bytes and exceeds the regular Git limit"
        )
    os.replace(temporary, destination)


def build_python_pack(cache: Path, build: Path, output: Path) -> Path:
    embed = download(PYTHON_EMBED_URL, PYTHON_EMBED_SHA256, cache / PYTHON_EMBED_NAME)
    python_root = build / "python"
    safe_extract(embed, python_root)

    pth = python_root / "python313._pth"
    if not pth.is_file():
        raise RuntimeError("Python embeddable package does not contain python313._pth")
    pth.write_text(
        "python313.zip\n.\nLib/site-packages\n../..\nimport site\n",
        encoding="utf-8",
        newline="\r\n",
    )

    site_packages = python_root / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--no-compile",
            "--target",
            str(site_packages),
            "-r",
            str(ROOT / "requirements" / "dev.lock"),
        ],
        check=True,
    )
    clean_python_tree(python_root)
    (python_root / "BILI_RUNTIME.txt").write_text(
        json.dumps(
            {
                "bili_workspace_version": VERSION,
                "python_version": PYTHON_VERSION,
                "python_embed_sha256": PYTHON_EMBED_SHA256,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    write_internal_manifest(python_root)
    deterministic_zip(python_root, output)

    portable_python = python_root / "python.exe"
    subprocess.run(
        [
            str(portable_python),
            "-c",
            "import fastapi,httpx,pydantic,pytest,ruff,starlette,uvicorn; print('portable python ok')",
        ],
        cwd=ROOT,
        check=True,
    )
    return output


def build_media_pack(cache: Path, build: Path, output: Path) -> Path:
    bbdown_archive = download(BBDOWN_URL, BBDOWN_SHA256, cache / BBDOWN_NAME)
    ffmpeg_wheel = download(
        FFMPEG_WHEEL_URL, FFMPEG_WHEEL_SHA256, cache / FFMPEG_WHEEL_NAME
    )

    bb_extract = build / "bbdown-upstream"
    ff_extract = build / "ffmpeg-upstream"
    safe_extract(bbdown_archive, bb_extract)
    safe_extract(ffmpeg_wheel, ff_extract)

    root = build / "media"
    bbdown_target = root / "BBDown_portable" / "BBDown.exe"
    ffmpeg_target = root / "BBDown_portable" / "ffmpeg" / "bin" / "ffmpeg.exe"
    bbdown_target.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(find_unique(bb_extract, "BBDown.exe"), bbdown_target)

    ffmpeg_source = ff_extract.joinpath(*PurePosixPath(FFMPEG_MEMBER).parts)
    if not ffmpeg_source.is_file():
        raise RuntimeError(f"FFmpeg wheel member is missing: {FFMPEG_MEMBER}")
    shutil.copy2(ffmpeg_source, ffmpeg_target)

    for name in ("BBDown.LICENSE.txt", "FFmpeg.LICENSE.txt"):
        source = ROOT / "LICENSES" / name
        destination = root / "LICENSES" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    shutil.copy2(
        ROOT / "LICENSES" / "BBDown.LICENSE.txt",
        root / "BBDown_portable" / "BBDown.LICENSE.txt",
    )
    ff_license = root / "BBDown_portable" / "ffmpeg" / "LICENSE.txt"
    ff_license.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "LICENSES" / "FFmpeg.LICENSE.txt", ff_license)

    checksums = root / "BBDown_portable" / "checksums.sha256"
    checksums.write_text(
        f"{sha256_file(bbdown_target)}  BBDown.exe\n"
        f"{sha256_file(ffmpeg_target)}  ffmpeg/bin/ffmpeg.exe\n",
        encoding="utf-8",
    )
    (root / "BILI_RUNTIME.txt").write_text(
        json.dumps(
            {
                "bili_workspace_version": VERSION,
                "bbdown_source": {"url": BBDOWN_URL, "sha256": BBDOWN_SHA256},
                "ffmpeg_source": {
                    "url": FFMPEG_WHEEL_URL,
                    "sha256": FFMPEG_WHEEL_SHA256,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    write_internal_manifest(root)
    deterministic_zip(root, output)

    subprocess.run(
        [str(bbdown_target), "--help"], check=True, capture_output=True, timeout=60
    )
    result = subprocess.run(
        [str(ffmpeg_target), "-hide_banner", "-version"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if "ffmpeg version" not in (result.stdout + result.stderr).lower():
        raise RuntimeError("FFmpeg smoke output did not contain version information")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build repository-integrated Windows runtime packs"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "vendor" / "windows"
    )
    parser.add_argument(
        "--cache", type=Path, default=ROOT / ".tmp" / "runtime-builder-cache"
    )
    args = parser.parse_args(argv)

    if os.name != "nt":
        raise SystemExit("This builder must run on a Windows x64 host")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bili-runtime-build-") as temporary_name:
        build = Path(temporary_name)
        python_pack = build_python_pack(
            args.cache.resolve(), build, output / "python-runtime.pack"
        )
        media_pack = build_media_pack(
            args.cache.resolve(), build, output / "media-runtime.pack"
        )

    manifest = {
        "schema_version": 1,
        "bili_workspace_version": VERSION,
        "platform": "windows-x64",
        "python_version": PYTHON_VERSION,
        "packs": {
            "python": {
                "path": "vendor/windows/python-runtime.pack",
                "sha256": sha256_file(python_pack),
                "size": python_pack.stat().st_size,
            },
            "media": {
                "path": "vendor/windows/media-runtime.pack",
                "sha256": sha256_file(media_pack),
                "size": media_pack.stat().st_size,
            },
        },
        "sources": {
            "python_embed": {
                "url": PYTHON_EMBED_URL,
                "sha256": PYTHON_EMBED_SHA256,
            },
            "bbdown": {"url": BBDOWN_URL, "sha256": BBDOWN_SHA256},
            "ffmpeg_wheel": {
                "url": FFMPEG_WHEEL_URL,
                "sha256": FFMPEG_WHEEL_SHA256,
            },
        },
    }
    manifest_path = output / "runtime-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
