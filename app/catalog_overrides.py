from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

import app.search as search_module
from app.api import _decorate_search_items, _user_id, err, ok
from app.search import SearchError, search_videos

router = APIRouter(prefix="/api", tags=["catalog-overrides"])

_TERM_SPLIT_RE = re.compile(r"[\s,，;；|/\\()（）\[\]{}<>《》]+")
_MODE_ALIASES = {
    "all": "all",
    "precise": "all",
    "exact": "all",
    "精准": "all",
    "any": "any",
    "fuzzy": "any",
    "模糊": "any",
    "raw": "raw",
    "original": "raw",
    "原始": "raw",
}
_MODE_LABELS = {
    "all": "精准搜索（标题匹配全部词）",
    "any": "模糊搜索（标题匹配任一词）",
    "raw": "原始搜索（B站直接结果）",
}
ShortText = Annotated[str, StringConstraints(max_length=300)]


class CatalogDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_ids: list[ShortText] = Field(default_factory=list, min_length=1, max_length=100)
    delete_files: bool = True
    # Kept only so older frontends that submitted mark_tag continue to work.
    # Deleted-work history now uses a dedicated tombstone table, not a visible tag.
    mark_tag: Annotated[str, StringConstraints(max_length=40)] = ""


def parse_title_search_terms(value: str, *, limit: int = 6) -> list[str]:
    """Split a query into stable terms used only to filter returned titles."""
    terms: list[str] = []
    seen: set[str] = set()
    for part in _TERM_SPLIT_RE.split(str(value or "").strip()):
        term = part.strip()
        folded = term.casefold()
        if not term or folded in seen:
            continue
        seen.add(folded)
        terms.append(term[:50])
        if len(terms) >= limit:
            break
    return terms


def _canonical_mode(value: str) -> str:
    return _MODE_ALIASES.get(str(value or "").strip().casefold(), "raw")


def _purge_original_search_cache(query: str, order: str, page: int) -> None:
    cache = getattr(search_module, "_SEARCH_CACHE", None)
    lock = getattr(search_module, "_CACHE_LOCK", None)
    if not isinstance(cache, dict) or lock is None:
        return
    wanted = query.casefold()
    with lock:
        for key in list(cache):
            if (
                isinstance(key, tuple)
                and len(key) >= 3
                and str(key[0]).casefold() == wanted
                and str(key[1]) == order
                and int(key[2]) == page
            ):
                cache.pop(key, None)


def _title_matches(item: dict[str, Any], terms: list[str], mode: str) -> bool:
    if mode == "raw" or not terms:
        return True
    title = str(item.get("title") or "").casefold()
    matches = [term.casefold() in title for term in terms]
    return all(matches) if mode == "all" else any(matches)


def search_videos_title_mode(
    query: str,
    *,
    mode: str,
    order: str,
    page: int,
    bbdown_dir,
    fresh: bool = False,
) -> dict[str, Any]:
    """Call Bilibili once with the original query, then filter returned titles."""
    query = str(query or "").strip()
    if not query:
        raise SearchError("请输入关键词")
    canonical_mode = _canonical_mode(mode)
    terms = parse_title_search_terms(query)
    if canonical_mode != "raw" and not terms:
        raise SearchError("没有可用于标题筛选的关键词")
    if fresh:
        _purge_original_search_cache(query, order, page)

    source = search_videos(
        query,
        order=order,
        page=page,
        bbdown_dir=bbdown_dir,
    )
    candidates = [dict(item) for item in source.get("items") or []]
    items = [item for item in candidates if _title_matches(item, terms, canonical_mode)]
    result = dict(source)
    result.update(
        {
            "keyword": query,
            "normalized_keyword": " ".join(terms)
            if canonical_mode != "raw"
            else query,
            "items": items,
            "candidate_on_page": len(candidates),
            "filtered_on_page": len(items),
            "candidate_total": int(source.get("total") or len(candidates)),
            "search_mode": canonical_mode,
            "search_mode_label": _MODE_LABELS[canonical_mode],
            "query_terms": terms,
            "source_queries": [query],
            "source_count": 1,
        }
    )
    return result


def _decorate_deleted_state(request: Request, data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("items") or []
    keys = [str(item.get("bvid") or "").strip() for item in items]
    keys = [key for key in keys if key]
    store = request.app.state.deletion_store
    tombstones = store.for_keys(keys)
    restored: list[str] = []
    for item in items:
        key = str(item.get("bvid") or "").strip()
        status = str(item.get("local_status") or "")
        if status == "downloaded":
            if key in tombstones:
                restored.append(key)
            continue
        if status in {"queued", "running"}:
            continue
        deleted = tombstones.get(key)
        if deleted:
            item.update(
                local_status="deleted",
                local_status_label="已删除",
                deleted_at=deleted.get("deleted_at"),
                deleted_record=True,
            )
    if restored:
        store.clear(restored)
    return data


@router.get("/search")
def catalog_search(
    request: Request,
    q: str = Query(default="", max_length=100),
    order: str = Query(default="totalrank", max_length=32),
    page: int = Query(default=1, ge=1, le=1000),
    mode: str = Query(default="raw", max_length=20),
    fresh: bool = Query(default=False),
):
    state = request.app.state.app_state
    cfg = state.config_store.get()
    try:
        data = search_videos_title_mode(
            q,
            mode=mode,
            order=order,
            page=page,
            bbdown_dir=cfg.bbdown_path(),
            fresh=fresh,
        )
        data = _decorate_search_items(state, data)
        data = _decorate_deleted_state(request, data)
    except SearchError as exc:
        return err(str(exc))
    except Exception as exc:  # noqa: BLE001
        return err(f"搜索失败: {exc}", 502)
    return ok(data)


def _delete_one(request: Request, media_id: str, delete_files: bool) -> dict[str, Any]:
    state = request.app.state.app_state
    media = state.nas.media_detail(media_id, _user_id(request))
    if not media:
        raise KeyError("作品不存在")
    source_key = str(media.get("source_key") or "")
    result = state.nas.delete_media(media_id, delete_files)
    tombstone = request.app.state.deletion_store.record(
        media, files_deleted=bool(delete_files)
    )
    # Tags belong to visible/current library entries. The tombstone is the only
    # record retained after deletion, so a future explicit re-download starts clean.
    try:
        request.app.state.tag_store.set_tags(source_key, [])
    except (OSError, ValueError):
        pass
    return {
        **result,
        "media_id": media_id,
        "source_key": source_key,
        "deleted_recorded": True,
        "deleted_at": tombstone["deleted_at"],
    }


@router.post("/enhancements/library/delete")
def catalog_batch_delete(request: Request, body: CatalogDeleteRequest):
    deleted: list[str] = []
    records: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for media_id in list(dict.fromkeys(body.media_ids)):
        try:
            record = _delete_one(request, media_id, body.delete_files)
            deleted.append(media_id)
            records.append(record)
        except KeyError as exc:
            errors[media_id] = str(exc)
        except Exception as exc:  # noqa: BLE001 - batch should continue
            errors[media_id] = str(exc)
    return ok(
        {
            "deleted": deleted,
            "deleted_records": records,
            "errors": errors,
            "files_deleted": body.delete_files,
            "deleted_recorded": True,
            "marked_tag": "",
        },
        total=len(deleted),
    )


@router.delete("/library/{media_id}")
def catalog_delete_media(
    request: Request,
    media_id: str,
    delete_files: bool = Query(default=False),
):
    try:
        return ok(_delete_one(request, media_id, delete_files))
    except KeyError as exc:
        return err(str(exc), 404)
    except (OSError, ValueError) as exc:
        return err(str(exc), 409)
