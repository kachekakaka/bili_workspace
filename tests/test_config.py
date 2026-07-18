import json

import pytest

from app.config import ConfigStore


def test_download_dir_hot_update(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    new_dir = tmp_env.root / "dl2"
    new_dir.mkdir()
    cfg, restart = store.update({"download_dir": str(new_dir)})
    assert restart is False
    assert cfg.download_path() == new_dir.resolve()


def test_port_change_requires_restart(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    cfg, restart = store.update({"port": 3400})
    assert restart is True
    assert cfg.port == 3400


def test_protected_runtime_fields_and_non_loopback_enables_server_mode(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    with pytest.raises(ValueError, match="不可通过网页修改"):
        store.update({"bbdown_dir": str(tmp_env.root / "missing")})
    lan = ConfigStore(path=tmp_env.config_path, initial={**tmp_env.initial, "host": "0.0.0.0"})
    assert lan.server_mode is True
    assert lan.get().host == "0.0.0.0"


def test_startup_validates_existing_file(tmp_env):
    tmp_env.config_path.write_text(
        json.dumps({**tmp_env.initial, "port": 70000}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="拒绝启动"):
        ConfigStore(path=tmp_env.config_path)


def test_atomic_backup_recovers_corrupt_config(tmp_env):
    store = ConfigStore(path=tmp_env.config_path, initial=tmp_env.initial)
    store.update({"port": 3400})
    store.update({"port": 3401})
    assert tmp_env.config_path.with_suffix(".json.bak").exists()
    tmp_env.config_path.write_text("{broken", encoding="utf-8")
    recovered = ConfigStore(path=tmp_env.config_path)
    assert recovered.get().port == 3400


def test_source_config_allows_missing_third_party_tools(tmp_env):
    empty_tools = tmp_env.root / "empty-tools"
    empty_tools.mkdir()
    store = ConfigStore(
        path=tmp_env.config_path,
        initial={**tmp_env.initial, "bbdown_dir": str(empty_tools)},
    )
    assert store.get().bbdown_path() == empty_tools.resolve()


def test_invalid_bind_hostname_in_json_is_rejected(tmp_path):
    from app.config import ConfigStore

    bbdown = tmp_path / "BBDown_portable"
    bbdown.mkdir()
    with pytest.raises(ValueError, match="host"):
        ConfigStore(
            path=tmp_path / "config.json",
            initial={
                "host": "nas-.home",
                "port": 3398,
                "download_dir": str(tmp_path / "downloads"),
                "bbdown_dir": str(bbdown),
            },
        )
