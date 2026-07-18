def test_status_ok_and_paths_are_sanitized(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["bbdown_ready"] is True
    assert data["ffmpeg_ready"] is True
    assert data["logged_in"] is True
    assert "cookie_path" not in data
    assert not data["bbdown_file"].startswith("/")


def test_docs_disabled_and_host_guard(client):
    assert client.get("/docs").status_code == 404
    response = client.get("/api/status", headers={"host": "evil.example"})
    assert response.status_code == 400
