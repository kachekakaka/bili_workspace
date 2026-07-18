from __future__ import annotations

import json
from types import SimpleNamespace

from app.task_logs import read_task_log, task_log_path
from app.userdata import UserdataIndexStore, migrate_legacy_database


def test_migrate_legacy_database_and_sidecars(tmp_path):
    config_dir = tmp_path / "config"
    userdata_dir = tmp_path / "userdata"
    config_dir.mkdir()
    legacy = config_dir / "bili_workspace.db"
    legacy.write_bytes(b"sqlite-main")
    (config_dir / "bili_workspace.db-wal").write_bytes(b"sqlite-wal")
    target = userdata_dir / "bili_workspace.db"
    runtime = SimpleNamespace(config_dir=config_dir, database_path=target)

    result = migrate_legacy_database(runtime)

    assert result["migrated"] is True
    assert target.read_bytes() == b"sqlite-main"
    assert (userdata_dir / "bili_workspace.db-wal").read_bytes() == b"sqlite-wal"
    assert not legacy.exists()


def test_userdata_index_migrates_out_of_downloads(tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    legacy = downloads / ".bili_index.json"
    legacy.write_text(json.dumps({"BV1TEST": {"title": "demo"}}), encoding="utf-8")
    target = tmp_path / "userdata" / "indexes" / "library.json"

    store = UserdataIndexStore(downloads, target)

    assert store.path == target.resolve()
    assert store.entries()["BV1TEST"]["title"] == "demo"
    assert target.is_file()
    assert not legacy.exists()


def test_task_log_moves_to_userdata(tmp_path, monkeypatch):
    downloads = tmp_path / "downloads"
    legacy_dir = downloads / ".bili_logs"
    legacy_dir.mkdir(parents=True)
    task_id = "abcdef123456"
    legacy = legacy_dir / f"{task_id}.log"
    legacy.write_text("old log", encoding="utf-8")
    userdata = tmp_path / "userdata"
    monkeypatch.setenv("BILI_USERDATA_DIR", str(userdata))
    monkeypatch.delenv("BILI_DATABASE_PATH", raising=False)

    result = read_task_log(downloads, task_id, tail_chars=None)
    target = task_log_path(downloads, task_id)

    assert result["text"] == "old log"
    assert target == (userdata / "task_logs" / f"{task_id}.log").resolve()
    assert target.is_file()
    assert not legacy.exists()
