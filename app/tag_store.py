from __future__ import annotations

import time
from typing import Any, Iterable

from app.config_files import ensure_json_from_default
from app.database import Database
from app.paths import defaults_dir

class TagStore:
    """Tag definitions and assignments on the shared application database."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.runtime = database.runtime
        self.path = database.path
        self.config_path = self.runtime.config_dir / "tags.json"
        self.default_config_path = defaults_dir() / "tags.json.default"
        self.reload_definitions()

    def reload_definitions(self) -> list[dict[str, Any]]:
        data, _ = ensure_json_from_default(self.default_config_path, self.config_path)
        raw_tags = data.get("tags") or []
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, item in enumerate(raw_tags):
            if isinstance(item, str):
                item = {"name": item}
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()[:40]
            folded = name.casefold()
            if not name or folded in seen:
                continue
            seen.add(folded)
            color = str(item.get("color") or "#64748b").strip()[:32]
            if not color.startswith("#"):
                color = "#64748b"
            normalized.append(
                {
                    "name": name,
                    "color": color,
                    "enabled": bool(item.get("enabled", True)),
                    "sort_order": index,
                }
            )
        now = time.time()
        with self.database.transaction() as connection:
            for item in normalized:
                connection.execute(
                    "INSERT INTO tag_definitions(name,color,sort_order,enabled,updated_at) "
                    "VALUES(?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
                    "color=excluded.color,sort_order=excluded.sort_order,"
                    "enabled=excluded.enabled,updated_at=excluded.updated_at",
                    (
                        item["name"],
                        item["color"],
                        item["sort_order"],
                        1 if item["enabled"] else 0,
                        now,
                    ),
                )
            if normalized:
                placeholders = ",".join("?" for _ in normalized)
                connection.execute(
                    f"UPDATE tag_definitions SET enabled=0,updated_at=? "
                    f"WHERE name NOT IN ({placeholders})",
                    (now, *(item["name"] for item in normalized)),
                )
        return self.definitions(include_disabled=True)

    def definitions(self, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        where = "" if include_disabled else "WHERE enabled=1"
        rows = self.database.all(
            f"SELECT name,color,sort_order,enabled FROM tag_definitions {where} "
            "ORDER BY sort_order,name COLLATE NOCASE"
        )
        for row in rows:
            row["enabled"] = bool(row["enabled"])
        return rows

    def _valid_names(self) -> dict[str, str]:
        return {
            str(row["name"]).casefold(): str(row["name"])
            for row in self.definitions()
        }

    def set_tags(self, source_key: str, tags: Iterable[str]) -> list[str]:
        source_key = str(source_key or "").strip()[:256]
        if not source_key:
            raise ValueError("作品标识不能为空")
        valid = self._valid_names()
        selected: list[str] = []
        seen: set[str] = set()
        for raw in tags:
            folded = str(raw or "").strip().casefold()
            canonical = valid.get(folded)
            if canonical and folded not in seen:
                seen.add(folded)
                selected.append(canonical)
        now = time.time()
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM item_tags WHERE source_key=?", (source_key,))
            connection.executemany(
                "INSERT INTO item_tags(source_key,tag,created_at) VALUES(?,?,?)",
                [(source_key, tag, now) for tag in selected],
            )
        return selected

    def add_tag(self, source_key: str, tag: str) -> list[str]:
        current = self.tags_for_keys([source_key]).get(source_key, [])
        return self.set_tags(source_key, [*current, tag])

    def clear_tags(self, source_key: str) -> None:
        source_key = str(source_key or "").strip()[:256]
        if not source_key:
            raise ValueError("作品标识不能为空")
        self.database.execute("DELETE FROM item_tags WHERE source_key=?", (source_key,))

    def tags_for_keys(self, keys: Iterable[str]) -> dict[str, list[str]]:
        values = [str(key or "").strip() for key in keys if str(key or "").strip()]
        values = list(dict.fromkeys(values))[:500]
        result = {key: [] for key in values}
        if not values:
            return result
        placeholders = ",".join("?" for _ in values)
        rows = self.database.all(
            "SELECT it.source_key,it.tag FROM item_tags it "
            "JOIN tag_definitions td ON td.name=it.tag AND td.enabled=1 "
            f"WHERE it.source_key IN ({placeholders}) "
            "ORDER BY td.sort_order,td.name COLLATE NOCASE",
            tuple(values),
        )
        for row in rows:
            result.setdefault(str(row["source_key"]), []).append(str(row["tag"]))
        return result
