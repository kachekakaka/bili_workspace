from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from app.api import ok

router = APIRouter(prefix="/api", tags=["catalog-refinements"])

_UNTAGGED = "__untagged__"


def _session_user_id(request: Request) -> str:
    session = getattr(request.state, "auth_session", None)
    return str(session.get("user_id")) if session else "local"


def _library_list(
    request: Request,
    *,
    page: int,
    page_size: int,
    query: str,
    group_id: str,
    sort: str,
    codec: str,
    min_height: int,
    watched: str,
    tag: str,
) -> dict[str, Any]:
    state = request.app.state.app_state
    store = request.app.state.tag_store
    state.nas.sync_index()
    page = max(1, int(page))
    page_size = min(100, max(1, int(page_size)))
    clauses: list[str] = []
    params: list[Any] = []

    if query.strip():
        needle = f"%{query.strip()}%"
        clauses.append(
            "(m.title LIKE ? OR m.bvid LIKE ? OR m.author LIKE ? OR m.source_key LIKE ?)"
        )
        params += [needle, needle, needle, needle]
    if group_id:
        clauses.append("m.group_id=?")
        params.append(group_id)
    if codec.strip():
        clauses.append("LOWER(m.selected_codec) LIKE ?")
        params.append(f"%{codec.strip().lower()}%")
    if int(min_height or 0) > 0:
        clauses.append("COALESCE(m.selected_height,0)>=?")
        params.append(int(min_height))

    selected_tag = tag.strip()
    if selected_tag == _UNTAGGED:
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM item_tags it "
            "JOIN tag_definitions td ON td.name=it.tag AND td.enabled=1 "
            "WHERE it.source_key=m.source_key)"
        )
    elif selected_tag:
        clauses.append(
            "EXISTS (SELECT 1 FROM item_tags it "
            "JOIN tag_definitions td ON td.name=it.tag AND td.enabled=1 "
            "WHERE it.source_key=m.source_key AND it.tag=? COLLATE NOCASE)"
        )
        params.append(selected_tag)

    watched = watched.strip().lower()
    user_id = _session_user_id(request)
    if watched in {"completed", "in_progress", "watching", "unwatched"}:
        progress_sql = (
            "SELECT 1 FROM watch_progress wp WHERE wp.media_id=m.id AND wp.user_id=? "
        )
        params.append(user_id)
        if watched == "completed":
            clauses.append(f"EXISTS ({progress_sql}AND wp.completed=1)")
        elif watched in {"in_progress", "watching"}:
            clauses.append(
                f"EXISTS ({progress_sql}AND wp.completed=0 AND wp.position_sec>0)"
            )
        else:
            clauses.append(f"NOT EXISTS ({progress_sql}AND wp.position_sec>0)")

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    tag_name_sql = (
        "(SELECT MIN(it.tag) FROM item_tags it "
        "JOIN tag_definitions td ON td.name=it.tag AND td.enabled=1 "
        "WHERE it.source_key=m.source_key)"
    )
    duration_sql = "bili_duration_seconds(m.duration_text)"
    order_sql = {
        "newest": "m.downloaded_at DESC,m.title COLLATE NOCASE ASC",
        "oldest": "m.downloaded_at ASC,m.title COLLATE NOCASE ASC",
        "title": "m.title COLLATE NOCASE ASC",
        "size": "m.total_size DESC,m.title COLLATE NOCASE ASC",
        "recent": "COALESCE(w.updated_at,0) DESC,m.downloaded_at DESC",
        "newest_desc": "m.downloaded_at DESC,m.title COLLATE NOCASE ASC",
        "newest_asc": "m.downloaded_at ASC,m.title COLLATE NOCASE ASC",
        "recent_desc": "COALESCE(w.updated_at,0) DESC,m.downloaded_at DESC",
        "recent_asc": "COALESCE(w.updated_at,0) ASC,m.downloaded_at ASC",
        "title_asc": "m.title COLLATE NOCASE ASC",
        "title_desc": "m.title COLLATE NOCASE DESC",
        "duration_asc": (
            f"CASE WHEN {duration_sql}>0 THEN 0 ELSE 1 END ASC,"
            f"{duration_sql} ASC,m.title COLLATE NOCASE ASC"
        ),
        "duration_desc": f"{duration_sql} DESC,m.title COLLATE NOCASE ASC",
        "size_asc": "m.total_size ASC,m.title COLLATE NOCASE ASC",
        "size_desc": "m.total_size DESC,m.title COLLATE NOCASE ASC",
        "group_asc": (
            "CASE WHEN COALESCE(g.display_name,'')<>'' THEN 0 ELSE 1 END ASC,"
            "g.display_name COLLATE NOCASE ASC,m.title COLLATE NOCASE ASC"
        ),
        "group_desc": (
            "CASE WHEN COALESCE(g.display_name,'')<>'' THEN 0 ELSE 1 END ASC,"
            "g.display_name COLLATE NOCASE DESC,m.title COLLATE NOCASE ASC"
        ),
        "tag_asc": (
            f"CASE WHEN {tag_name_sql} IS NULL THEN 1 ELSE 0 END ASC,"
            f"{tag_name_sql} COLLATE NOCASE ASC,m.title COLLATE NOCASE ASC"
        ),
        "tag_desc": (
            f"CASE WHEN {tag_name_sql} IS NULL THEN 1 ELSE 0 END ASC,"
            f"{tag_name_sql} COLLATE NOCASE DESC,m.title COLLATE NOCASE ASC"
        ),
    }.get(sort, "m.downloaded_at DESC,m.title COLLATE NOCASE ASC")

    total = int(
        (store._one(f"SELECT COUNT(*) AS n FROM media m {where}", tuple(params)) or {}).get(
            "n"
        )
        or 0
    )
    rows = store._all(
        "SELECT m.*,g.display_name AS group_name,g.folder_key AS group_folder,"
        "f.id AS primary_file_id,f.filename AS primary_filename,f.mime_type AS primary_mime,"
        "COALESCE(w.position_sec,0) AS watch_position,COALESCE(w.duration_sec,0) AS watch_duration,"
        "COALESCE(w.completed,0) AS watch_completed FROM media m "
        "LEFT JOIN groups g ON g.id=m.group_id "
        "LEFT JOIN media_files f ON f.media_id=m.id AND f.is_primary=1 "
        "LEFT JOIN watch_progress w ON w.file_id=f.id AND w.user_id=? "
        f"{where} ORDER BY {order_sql} LIMIT ? OFFSET ?",
        tuple([user_id, *params, page_size, (page - 1) * page_size]),
    )
    tags = store.tags_for_keys(str(row["source_key"]) for row in rows)
    for row in rows:
        row["watch_completed"] = bool(row["watch_completed"])
        row["tags"] = tags.get(str(row["source_key"]), [])
    return {
        "items": rows,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": (total + page_size - 1) // page_size if total else 0,
        "filters": {
            "query": query,
            "group_id": group_id,
            "codec": codec,
            "min_height": int(min_height or 0),
            "watched": watched,
            "sort": sort,
            "tag": selected_tag,
        },
    }


@router.get("/enhancements/library")
def refined_library(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(36, ge=1, le=100),
    q: str = Query("", max_length=200),
    group_id: str = Query("", max_length=100),
    sort: str = Query("newest", max_length=30),
    codec: str = Query("", max_length=80),
    min_height: int = Query(0, ge=0, le=4320),
    watched: str = Query("", max_length=30),
    tag: str = Query("", max_length=40),
):
    return ok(
        _library_list(
            request,
            page=page,
            page_size=page_size,
            query=q,
            group_id=group_id,
            sort=sort,
            codec=codec,
            min_height=min_height,
            watched=watched,
            tag=tag,
        )
    )
