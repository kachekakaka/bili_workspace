from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.constants import MAX_BATCH_ITEMS, MAX_INPUT_LENGTH
from app.grouping import MAX_GROUP_LENGTH
from app.quality import ALLOWED_MIN_HEIGHTS

InputText = Annotated[str, StringConstraints(max_length=MAX_INPUT_LENGTH * 2)]
ShortText = Annotated[str, StringConstraints(max_length=300)]
MetaText = Annotated[str, StringConstraints(max_length=2048)]
GroupText = Annotated[str, StringConstraints(max_length=MAX_GROUP_LENGTH * 2)]
QualityText = Annotated[str, StringConstraints(max_length=120)]


class DownloadItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bvid: InputText | None = None
    url: InputText | None = None
    title: ShortText = ""
    cover: MetaText = ""
    author: ShortText = ""
    pubdate: int | None = Field(default=None, ge=0, le=9_999_999_999)
    duration: Annotated[str, StringConstraints(max_length=32)] = ""
    play: int | None = Field(default=None, ge=0)
    preferred_quality: QualityText = ""

    @model_validator(mode="after")
    def validate_target(self) -> "DownloadItem":
        if not str(self.bvid or "").strip() and not str(self.url or "").strip():
            raise ValueError("作品元数据必须包含 bvid 或 url")
        return self

    def display_metadata(self) -> dict[str, Any]:
        return {
            "title": self.title.strip(),
            "cover": self.cover.strip(),
            "author": self.author.strip(),
            "pubdate": self.pubdate,
            "duration": self.duration.strip(),
            "play": self.play,
            "preferred_quality": self.preferred_quality.strip(),
        }


class DownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    urls: list[InputText] = Field(default_factory=list, max_length=MAX_BATCH_ITEMS)
    bvids: list[InputText] = Field(default_factory=list, max_length=MAX_BATCH_ITEMS)
    items: list[DownloadItem] = Field(default_factory=list, max_length=MAX_BATCH_ITEMS)
    force: bool = False
    group: GroupText = ""
    group_id: ShortText = ""
    destination: Literal["library", "device"] = "library"
    min_height: int | None = None

    @model_validator(mode="after")
    def validate_request(self) -> "DownloadRequest":
        if len(self.urls) + len(self.bvids) + len(self.items) > MAX_BATCH_ITEMS:
            raise ValueError(f"单次最多提交 {MAX_BATCH_ITEMS} 项")
        if self.min_height is not None and self.min_height not in ALLOWED_MIN_HEIGHTS:
            allowed = ", ".join(str(item) for item in sorted(ALLOWED_MIN_HEIGHTS))
            raise ValueError(f"最低清晰度只支持: {allowed}")
        return self


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: DownloadItem
    min_height: int | None = None
    preferred_quality: QualityText = ""

    @model_validator(mode="after")
    def validate_quality(self) -> "PreviewRequest":
        if self.min_height is not None and self.min_height not in ALLOWED_MIN_HEIGHTS:
            allowed = ", ".join(str(item) for item in sorted(ALLOWED_MIN_HEIGHTS))
            raise ValueError(f"最低清晰度只支持: {allowed}")
        return self


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force: bool = False


class ConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    port: int | None = Field(default=None, ge=1, le=65535)
    download_dir: InputText | None = None
    poll_hint_ms: int | None = Field(default=None, ge=200, le=60_000)
    download_timeout_sec: int | None = Field(default=None, ge=30, le=86_400)
    dfn_priority: Annotated[str, StringConstraints(max_length=256)] | None = None
    encoding_priority: Annotated[str, StringConstraints(max_length=256)] | None = None
    default_group: GroupText | None = None
    default_min_height: int | None = None

    @model_validator(mode="after")
    def validate_quality(self) -> "ConfigUpdate":
        if self.default_min_height is not None and self.default_min_height not in ALLOWED_MIN_HEIGHTS:
            allowed = ", ".join(str(item) for item in sorted(ALLOWED_MIN_HEIGHTS))
            raise ValueError(f"默认最低清晰度只支持: {allowed}")
        return self

    def as_patch(self) -> dict[str, Any]:
        return {key: value for key, value in self.model_dump().items() if value is not None}

class AuthSetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: Annotated[str, StringConstraints(min_length=3, max_length=64)]
    password: Annotated[str, StringConstraints(min_length=10, max_length=256)]
    bootstrap_token: Annotated[str, StringConstraints(min_length=8, max_length=256)]


class AuthLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class AuthPasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    new_password: Annotated[str, StringConstraints(min_length=10, max_length=256)]


class GroupCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: GroupText


class GroupRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: GroupText


class GroupMergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: ShortText


class MediaMoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_id: ShortText


class WatchProgressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_id: ShortText
    position_sec: float = Field(ge=0, le=10_000_000)
    duration_sec: float = Field(ge=0, le=10_000_000)


class CompatibleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_id: ShortText
