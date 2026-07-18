from __future__ import annotations

import hashlib
from email.utils import formatdate
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import Response, StreamingResponse

CHUNK_SIZE = 1024 * 1024


def parse_range(value: str, size: int) -> tuple[int, int]:
    if not value.startswith("bytes=") or "," in value:
        raise ValueError("只支持单个 bytes Range")
    spec = value[6:].strip()
    if "-" not in spec:
        raise ValueError("Range 格式错误")
    left, right = spec.split("-", 1)
    if not left:
        suffix = int(right)
        if suffix <= 0:
            raise ValueError("Range 后缀无效")
        start, end = max(0, size - suffix), size - 1
    else:
        start = int(left)
        end = int(right) if right else size - 1
    if start < 0 or start >= size or end < start:
        raise ValueError("Range 越界")
    return start, min(end, size - 1)


def _disposition(filename: str, attachment: bool) -> str:
    ascii_name = "".join(ch if 32 <= ord(ch) < 127 and ch not in {'"', '\\'} else "_" for ch in filename)
    kind = "attachment" if attachment else "inline"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


def file_response(
    request: Request,
    path: Path,
    *,
    media_type: str,
    filename: str,
    attachment: bool = False,
    allow_range: bool = True,
    on_complete: Callable[[], None] | None = None,
) -> Response:
    path = Path(path)
    stat = path.stat()
    size = stat.st_size
    etag_seed = f"{stat.st_size}:{stat.st_mtime_ns}:{path.name}".encode()
    headers = {
        "Content-Type": media_type or "application/octet-stream",
        "Content-Disposition": _disposition(filename, attachment),
        "ETag": '"' + hashlib.sha256(etag_seed).hexdigest()[:24] + '"',
        "Last-Modified": formatdate(stat.st_mtime, usegmt=True),
        "Accept-Ranges": "bytes" if allow_range else "none",
        "X-Accel-Buffering": "no",
    }
    start, end, status = 0, size - 1, 200
    range_value = request.headers.get("range", "") if allow_range else ""
    if range_value:
        try:
            start, end = parse_range(range_value, size)
        except (ValueError, OverflowError):
            return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
        status = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    length = max(0, end - start + 1)
    headers["Content-Length"] = str(length)
    if not allow_range:
        headers["Cache-Control"] = "private, no-store"
    if request.method == "HEAD":
        return Response(status_code=status, headers=headers)

    def iterator() -> Iterator[bytes]:
        sent = 0
        completed = False
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    sent += len(chunk)
                    remaining -= len(chunk)
                    yield chunk
                completed = sent == length
        finally:
            if completed and on_complete:
                on_complete()

    return StreamingResponse(iterator(), status_code=status, headers=headers)
