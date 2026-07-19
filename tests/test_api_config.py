from pathlib import Path


def test_get_put_config(client, tmp_env):
    response = client.get("/api/config")
    assert response.json()["ok"] is True
    assert set(response.json()["protected_fields"]) == {"host", "bbdown_dir"}

    new_dir = tmp_env.root / "new_dl"
    new_dir.mkdir()
    response = client.put("/api/config", json={"download_dir": str(new_dir)})
    body = response.json()
    assert body["ok"] is True
    assert body["restart_required"] is False

    response = client.put("/api/config", json={"port": 3401})
    body = response.json()
    assert body["ok"] is True
    assert body["restart_required"] is True


def test_executable_directory_is_not_web_editable(client, tmp_env):
    attacker = tmp_env.root / "attacker"
    attacker.mkdir()
    (attacker / "BBDown.exe").write_text("harmless", encoding="utf-8")
    response = client.put("/api/config", json={"bbdown_dir": str(attacker)})
    assert response.status_code == 422
    assert client.state_ref.config_store.get().bbdown_path() == tmp_env.bbdown_dir.resolve()


def test_download_dir_change_blocked_while_active(tmp_env):
    import threading
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.state import AppState
    from tests.conftest import StaticCookieChecker, authenticate_local_admin

    started = threading.Event()
    release = threading.Event()

    def runner(argv, **kwargs):
        del kwargs
        started.set()
        release.wait(timeout=3)
        work = Path(argv[argv.index("--work-dir") + 1])
        (work / "demo.mp4").write_bytes(b"x")
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    state = AppState.create(
        config_path=tmp_env.config_path,
        initial_config=tmp_env.initial,
        runner=runner,
        cookie_checker=StaticCookieChecker(),
    )
    with TestClient(create_app(state), base_url="http://127.0.0.1") as test_client:
        authenticate_local_admin(test_client)
        task = test_client.post("/api/download", json={"bvids": ["BV0000000001"]}).json()["data"][0]
        assert started.wait(timeout=2)
        response = test_client.put(
            "/api/config", json={"download_dir": str(tmp_env.root / "other")}
        )
        assert response.status_code == 409
        release.set()
        deadline = __import__("time").time() + 3
        while __import__("time").time() < deadline:
            if test_client.get(f"/api/tasks/{task['id']}").json()["data"]["status"] == "success":
                break
            __import__("time").sleep(0.02)
    state.queue.stop()
