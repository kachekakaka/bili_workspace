from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.database import Database
from app.deletion_store import DeletionStore
from app.runtime import RuntimeSettings
from app.tag_store import TagStore


def _runtime(root: Path) -> RuntimeSettings:
    for name in ("config", "media", "cache", "tmp", "bbdown", "userdata"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return RuntimeSettings(
        mode="local",
        config_dir=root / "config",
        media_dir=root / "media",
        cache_dir=root / "cache",
        temp_dir=root / "tmp",
        database_path=root / "userdata" / "bili_workspace.db",
        bbdown_dir=root / "bbdown",
        host="127.0.0.1",
        port=3398,
        public_base_url="",
        trusted_hosts=("127.0.0.1", "localhost", "testserver"),
        trusted_proxy_ips=("127.0.0.1",),
        allow_ip_hosts=False,
        auth_required=True,
        cookie_secure=False,
        hsts_enabled=False,
        export_ttl_sec=86400,
        min_free_bytes=0,
        download_concurrency=1,
        transcode_threads=0,
    )


def test_existing_v4_database_migrates_to_v5_with_backup(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    with sqlite3.connect(runtime.database_path) as connection:
        connection.execute("CREATE TABLE marker(value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker(value) VALUES('keep')")
        connection.execute("PRAGMA user_version=4")
        connection.commit()

    database = Database(runtime)
    try:
        assert database.migration_backup_path is not None
        assert database.migration_backup_path.is_file()
        assert database.one("PRAGMA user_version") == {"user_version": 5}
        tables = {
            str(row["name"])
            for row in database.all("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "tag_definitions",
            "item_tags",
            "deleted_media",
            "task_records",
            "device_download_history",
        } <= tables
        assert database.one("SELECT value FROM marker") == {"value": "keep"}
    finally:
        database.close()


def test_outer_transaction_rolls_back_tag_and_deletion_store_together(
    tmp_path: Path,
) -> None:
    database = Database(_runtime(tmp_path))
    tags = TagStore(database)
    deletions = DeletionStore(database)
    source_key = "BVTRANSACTION1"
    tags.set_tags(source_key, ["夯"])

    try:
        with pytest.raises(RuntimeError, match="rollback"):
            with database.transaction():
                tags.set_tags(source_key, [])
                deletions.record(
                    {"source_key": source_key, "title": "事务回滚"},
                    files_deleted=True,
                )
                raise RuntimeError("rollback")

        assert tags.tags_for_keys([source_key])[source_key] == ["夯"]
        assert deletions.for_keys([source_key]) == {}

        with database.transaction():
            tags.clear_tags(source_key)
            deletions.record(
                {"source_key": source_key, "title": "事务提交"},
                files_deleted=False,
            )
        assert tags.tags_for_keys([source_key])[source_key] == []
        assert deletions.for_keys([source_key])[source_key]["files_deleted"] is False
    finally:
        database.close()
