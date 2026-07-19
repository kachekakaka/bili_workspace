from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api import _user_id, err, ok

router = APIRouter(prefix="/api", tags=["catalog-overrides"])

ShortText = Annotated[str, StringConstraints(max_length=300)]


class CatalogDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_ids: list[ShortText] = Field(default_factory=list, min_length=1, max_length=100)
    delete_files: bool = True
    # Kept only so older frontends that submitted mark_tag continue to work.
    # Deleted-work history now uses a dedicated tombstone table, not a visible tag.
    mark_tag: Annotated[str, StringConstraints(max_length=40)] = ""


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
