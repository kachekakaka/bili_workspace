"""只记录允许的公开响应，并生成确定性的完整结构 fixture 候选。"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.metadata import VIEW_URL
from app.search import (
    CREATOR_PROFILE_URL,
    CREATOR_SUBMISSIONS_URL,
    NAV_URL,
    SEARCH_URL,
)
from tools.bilibili_live.contracts import LiveInconclusiveError, is_reparse


_PUBLIC_KINDS = {
    SEARCH_URL: "creator-search",
    CREATOR_PROFILE_URL: "creator-profile",
    CREATOR_SUBMISSIONS_URL: "creator-submissions",
    VIEW_URL: "video-detail",
}
_MAX_RAW_RESPONSE_BYTES = 16 * 1024 * 1024
_URL_KEYS = {
    "avatar",
    "cover",
    "face",
    "img_url",
    "pic",
    "profile_url",
    "sub_url",
    "upic",
    "url",
}
_TEXT_KEYS = {
    "author",
    "bio",
    "desc",
    "description",
    "message",
    "msg",
    "name",
    "sign",
    "title",
    "uname",
}
_TIME_KEYS = {
    "created",
    "created_at",
    "ctime",
    "mtime",
    "pubdate",
    "timestamp",
}
_ALLOWED_SANITIZED_STRINGS = {
    "",
    "0",
    "01:00",
    "BV1TEST00001",
    "https://example.invalid/public",
    "https://i0.hdslb.com/bfs/archive/bili-workspace-test.jpg",
    "pubdate",
    "text",
    "creator-search",
    "creator-profile",
    "creator-submissions",
    "video-detail",
}


def _write_json_exclusive(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    with path.open("xb") as stream:
        stream.write(encoded)


class RecordingClient:
    """httpx.Client 的窄包装；永不记录请求、header、Cookie、NAV 或响应 header。"""

    def __init__(self, raw_root: Path, client: httpx.Client | None = None) -> None:
        self.raw_root = Path(raw_root)
        if self.raw_root.exists():
            if (
                not self.raw_root.is_dir()
                or self.raw_root.is_symlink()
                or is_reparse(self.raw_root)
                or any(self.raw_root.iterdir())
            ):
                raise LiveInconclusiveError("公开响应目录必须是全新普通目录")
        else:
            self.raw_root.mkdir(parents=True)
        self._client = client or httpx.Client(timeout=20.0, trust_env=False)
        self._owns_client = client is None
        self._records: list[dict[str, str]] = []
        self._payloads: list[tuple[str, Any]] = []

    @property
    def records(self) -> tuple[dict[str, str], ...]:
        return tuple(dict(item) for item in self._records)

    def last_payload(self, kind: str) -> Any:
        for record_kind, payload in reversed(self._payloads):
            if record_kind == kind:
                return payload
        raise LiveInconclusiveError(f"尚未记录 {kind} 公开响应")

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        response = self._client.get(url, **kwargs)
        canonical = f"{urlsplit(str(url)).scheme}://{urlsplit(str(url)).netloc}{urlsplit(str(url)).path}"
        kind = _PUBLIC_KINDS.get(canonical)
        if canonical == NAV_URL or kind is None:
            return response
        try:
            payload = response.json()
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise LiveInconclusiveError("允许记录的公开响应不是 JSON") from exc
        if len(encoded) > _MAX_RAW_RESPONSE_BYTES:
            raise LiveInconclusiveError("允许记录的公开响应超过大小上限")
        index = len(self._records) + 1
        filename = f"{index:03d}-{kind}.json"
        _write_json_exclusive(self.raw_root / filename, payload)
        self._records.append({"kind": kind, "file": filename})
        self._payloads.append((kind, payload))
        return response

    def write_index(self) -> Path:
        index_path = self.raw_root / "index.json"
        _write_json_exclusive(
            index_path,
            {
                "schema_version": 1,
                "records": self._records,
            },
        )
        return index_path

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "RecordingClient":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()


def _string_placeholder(key: str) -> str:
    lowered = key.casefold()
    if lowered in {"bvid", "bv_id"} or lowered.endswith("_bvid"):
        return "BV1TEST00001"
    if lowered in {"duration", "length"}:
        return "01:00"
    if lowered == "order":
        return "pubdate"
    if lowered in _URL_KEYS or lowered.endswith("_url"):
        if lowered in {"avatar", "cover", "face", "pic", "upic"}:
            return "https://i0.hdslb.com/bfs/archive/bili-workspace-test.jpg"
        return "https://example.invalid/public"
    if lowered in _TEXT_KEYS:
        return "text"
    if lowered in {"code"}:
        return "0"
    return "text"


def sanitize_public_json(value: Any, *, key: str = "") -> Any:
    """保留完整键、嵌套、类型、null 与不同数组元素结构。"""

    if value is None:
        return None
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        lowered = key.casefold()
        if lowered == "code":
            return 0
        if lowered in _TIME_KEYS or lowered.endswith(("_at", "_time")):
            return 1_700_000_000
        if lowered in {"duration", "length"}:
            return 60
        if lowered in {"mid", "uid", "owner_mid"} or lowered.endswith("_uid"):
            return 10001
        return 1
    if isinstance(value, float):
        return 1.0
    if isinstance(value, str):
        if not value:
            return ""
        return _string_placeholder(key)
    if isinstance(value, dict):
        return {
            str(child_key): sanitize_public_json(child_value, key=str(child_key))
            for child_key, child_value in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        variants: dict[str, Any] = {}
        for item in value:
            sanitized = sanitize_public_json(item, key=key)
            token = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            variants.setdefault(token, sanitized)
        return [variants[token] for token in sorted(variants)]
    raise LiveInconclusiveError(f"公开响应包含不支持的 JSON 类型: {type(value).__name__}")


def _assert_sanitized_value(value: Any) -> None:
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if value not in _ALLOWED_SANITIZED_STRINGS:
            raise LiveInconclusiveError("fixture 候选包含非确定性字符串")
        return
    if isinstance(value, list):
        for item in value:
            _assert_sanitized_value(item)
        return
    if isinstance(value, dict):
        for child in value.values():
            _assert_sanitized_value(child)
        return
    raise LiveInconclusiveError("fixture 候选包含非 JSON 值")


def _collect_sensitive_tokens(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for child in value.values():
            result.update(_collect_sensitive_tokens(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_collect_sensitive_tokens(child))
    elif isinstance(value, str):
        text = value.strip()
        if (
            len(text) >= 8
            or (len(text) >= 2 and any(ord(character) > 127 for character in text))
            or text.startswith(("BV", "http://", "https://"))
        ):
            result.add(text)
    elif isinstance(value, int) and not isinstance(value, bool) and abs(value) >= 10_000:
        result.add(str(value))
    return result


def _assert_no_forbidden_keys(value: Any, forbidden_strings: set[str]) -> None:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            if any(token and token in key for token in forbidden_strings):
                raise LiveInconclusiveError("fixture 候选字段名包含真实动态值")
            _assert_no_forbidden_keys(child, forbidden_strings)
    elif isinstance(value, list):
        for child in value:
            _assert_no_forbidden_keys(child, forbidden_strings)


def _read_json_file(path: Path, *, max_bytes: int = _MAX_RAW_RESPONSE_BYTES) -> Any:
    if (
        not path.is_file()
        or path.is_symlink()
        or is_reparse(path)
        or path.stat().st_size > max_bytes
    ):
        raise LiveInconclusiveError("公开响应文件类型或大小无效")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveInconclusiveError("公开响应文件不是有效 UTF-8 JSON") from exc


def load_raw_records(raw_root: Path) -> list[tuple[str, Any]]:
    root = Path(raw_root)
    if not root.is_dir() or root.is_symlink() or is_reparse(root):
        raise LiveInconclusiveError("公开响应目录类型无效")
    index = _read_json_file(root / "index.json", max_bytes=1024 * 1024)
    records = index.get("records") if isinstance(index, dict) else None
    if (
        not isinstance(index, dict)
        or type(index.get("schema_version")) is not int
        or index.get("schema_version") != 1
        or not isinstance(records, list)
    ):
        raise LiveInconclusiveError("公开响应索引无效")
    expected_files = {"index.json"}
    result: list[tuple[str, Any]] = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {"kind", "file"}:
            raise LiveInconclusiveError("公开响应索引条目无效")
        kind = record.get("kind")
        filename = record.get("file")
        if kind not in set(_PUBLIC_KINDS.values()) or not isinstance(filename, str):
            raise LiveInconclusiveError("公开响应索引身份无效")
        if Path(filename).name != filename or not filename.endswith(f"-{kind}.json"):
            raise LiveInconclusiveError("公开响应索引路径无效")
        if filename in expected_files:
            raise LiveInconclusiveError("公开响应索引路径重复")
        expected_files.add(filename)
        result.append((kind, _read_json_file(root / filename)))
    actual_files = {path.name for path in root.iterdir()}
    if actual_files != expected_files:
        raise LiveInconclusiveError("公开响应目录与索引不一致")
    return result


def build_structural_candidates(
    raw_root: Path,
    *,
    forbidden_strings: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for kind, payload in load_raw_records(raw_root):
        sanitized = sanitize_public_json(payload)
        _assert_sanitized_value(sanitized)
        forbidden = _collect_sensitive_tokens(payload)
        forbidden.update(forbidden_strings or set())
        _assert_no_forbidden_keys(sanitized, forbidden)
        token = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        grouped.setdefault(kind, {})[token] = sanitized
    return {
        kind: {
            "schema_version": 1,
            "kind": kind,
            "variants": [variants[token] for token in sorted(variants)],
        }
        for kind, variants in sorted(grouped.items())
    }


def compare_and_write_candidates(
    raw_root: Path,
    tracked_root: Path,
    candidate_root: Path,
    *,
    forbidden_strings: set[str] | None = None,
) -> list[str]:
    candidates = build_structural_candidates(
        raw_root,
        forbidden_strings=forbidden_strings,
    )
    drift: list[str] = []
    pending: dict[str, dict[str, Any]] = {}
    for kind, payload in candidates.items():
        tracked_path = Path(tracked_root) / f"{kind}.json"
        if tracked_path.exists():
            tracked = _read_json_file(tracked_path)
            _assert_sanitized_value(tracked)
        else:
            tracked = None
        if tracked != payload:
            drift.append(kind)
            pending[kind] = payload
    if drift:
        root = Path(candidate_root)
        if root.exists() and (
            not root.is_dir() or root.is_symlink() or is_reparse(root) or any(root.iterdir())
        ):
            raise LiveInconclusiveError("fixture 候选目录必须是全新普通目录")
        root.mkdir(parents=True, exist_ok=True)
        for kind, payload in pending.items():
            _write_json_exclusive(root / f"{kind}.json", payload)
        _write_json_exclusive(
            root / "index.json",
            {"schema_version": 1, "drift": drift},
        )
    return drift


def validate_candidate_directory(
    candidate_root: Path,
    *,
    forbidden_strings: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    root = Path(candidate_root)
    if not root.is_dir() or root.is_symlink() or is_reparse(root):
        raise LiveInconclusiveError("fixture 候选目录类型无效")
    index = _read_json_file(root / "index.json", max_bytes=1024 * 1024)
    drift = index.get("drift") if isinstance(index, dict) else None
    if (
        not isinstance(index, dict)
        or type(index.get("schema_version")) is not int
        or index.get("schema_version") != 1
        or not isinstance(drift, list)
        or not drift
    ):
        raise LiveInconclusiveError("fixture 候选索引无效")
    if any(
        not isinstance(kind, str) or kind not in set(_PUBLIC_KINDS.values())
        for kind in drift
    ) or len(set(drift)) != len(drift):
        raise LiveInconclusiveError("fixture 候选索引包含无效类型")
    expected = {"index.json"}
    result: dict[str, dict[str, Any]] = {}
    for kind in drift:
        path = root / f"{kind}.json"
        payload = _read_json_file(path)
        if (
            not isinstance(payload, dict)
            or type(payload.get("schema_version")) is not int
            or payload.get("schema_version") != 1
            or payload.get("kind") != kind
            or not isinstance(payload.get("variants"), list)
        ):
            raise LiveInconclusiveError("fixture 候选结构无效")
        _assert_sanitized_value(payload)
        _assert_no_forbidden_keys(payload, forbidden_strings or set())
        expected.add(path.name)
        result[kind] = payload
    if {path.name for path in root.iterdir()} != expected:
        raise LiveInconclusiveError("fixture 候选文件集合与索引不一致")
    return result


def validate_candidate_matches_raw(
    raw_root: Path,
    candidate_root: Path,
    *,
    forbidden_strings: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    candidates = validate_candidate_directory(
        candidate_root,
        forbidden_strings=forbidden_strings,
    )
    rebuilt = build_structural_candidates(
        raw_root,
        forbidden_strings=forbidden_strings,
    )
    if any(rebuilt.get(kind) != payload for kind, payload in candidates.items()):
        raise LiveInconclusiveError("fixture 候选与同一 run 的公开响应不一致")
    return candidates


def refresh_tracked_fixtures(candidate_root: Path, tracked_root: Path) -> list[Path]:
    """显式维护入口调用；普通真测绝不调用本函数。"""

    candidates = validate_candidate_directory(candidate_root)
    destination_root = Path(tracked_root)
    if destination_root.is_symlink() or is_reparse(destination_root):
        raise LiveInconclusiveError("跟踪 fixture 目录类型无效")
    destination_root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for kind, payload in candidates.items():
        destination = destination_root / f"{kind}.json"
        if destination.is_symlink() or is_reparse(destination) or (
            destination.exists() and not destination.is_file()
        ):
            raise LiveInconclusiveError("跟踪 fixture 目标类型无效")
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        encoded = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        try:
            with temporary.open("xb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        written.append(destination)
    return written
