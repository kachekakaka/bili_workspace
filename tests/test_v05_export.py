from __future__ import annotations

import asyncio
from pathlib import Path

from starlette.requests import Request

from app.media_stream import CHUNK_SIZE, file_response
from tests.conftest import wait_terminal


def _request(method: str = "GET") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": "/download",
            "raw_path": b"/download",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("test", 80),
        }
    )


def test_device_export_full_transfer_cleans_temporary_artifacts(client):
    response = client.post(
        "/api/download",
        json={
            "items": [{"bvid": "BV0000000510", "title": "导出到当前设备"}],
            "destination": "device",
            "min_height": 1080,
        },
    )
    assert response.status_code == 200
    task_id = response.json()["data"][0]["id"]
    task = wait_terminal(client.state_ref.export_queue, task_id)
    assert task["status"] == "success"

    prepared = client.post(f"/api/exports/{task_id}/prepare")
    assert prepared.status_code == 200
    record = client.state_ref.nas.export_record(task_id)
    package = client.state_ref.nas.export_root / record["relative_path"]
    assert package.is_file()

    downloaded = client.get(f"/api/exports/{task_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.content == b"video"
    assert downloaded.headers["accept-ranges"] == "none"
    assert downloaded.headers["cache-control"] == "private, no-store"

    final = client.state_ref.nas.export_record(task_id)
    assert final["state"] == "downloaded"
    assert not package.exists()
    assert client.state_ref.export_index.get("BV0000000510") is None
    assert client.get(f"/api/exports/{task_id}/download").status_code == 410


def test_active_device_export_blocks_duplicate_until_cleaned(client):
    body = {
        "bvids": ["BV0000000511"],
        "destination": "device",
        "min_height": 1080,
    }
    first = client.post("/api/download", json=body)
    task_id = first.json()["data"][0]["id"]
    wait_terminal(client.state_ref.export_queue, task_id)
    duplicate = client.post("/api/download", json=body)
    assert duplicate.status_code == 409

    assert client.delete(f"/api/exports/{task_id}").status_code == 200
    replacement = client.post("/api/download", json=body)
    assert replacement.status_code == 200


def test_interrupted_stream_does_not_call_cleanup(tmp_path: Path):
    path = tmp_path / "large.bin"
    path.write_bytes(b"x" * (CHUNK_SIZE * 2 + 17))
    calls: list[str] = []
    response = file_response(
        _request(),
        path,
        media_type="application/octet-stream",
        filename="large.bin",
        attachment=True,
        allow_range=False,
        on_complete=lambda: calls.append("done"),
    )

    async def consume_one_chunk() -> None:
        iterator = response.body_iterator
        chunk = await anext(iterator)
        assert len(chunk) == CHUNK_SIZE
        await iterator.aclose()

    asyncio.run(consume_one_chunk())
    assert calls == []
    assert path.is_file()


def test_complete_stream_calls_cleanup_once_and_head_never_calls_it(tmp_path: Path):
    path = tmp_path / "small.bin"
    path.write_bytes(b"abcdef")
    calls: list[str] = []
    response = file_response(
        _request(),
        path,
        media_type="application/octet-stream",
        filename="small.bin",
        attachment=True,
        allow_range=False,
        on_complete=lambda: calls.append("done"),
    )

    async def consume_all() -> bytes:
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        return b"".join(chunks)

    assert asyncio.run(consume_all()) == b"abcdef"
    assert calls == ["done"]

    head = file_response(
        _request("HEAD"),
        path,
        media_type="application/octet-stream",
        filename="small.bin",
        attachment=True,
        allow_range=False,
        on_complete=lambda: calls.append("head"),
    )
    assert head.status_code == 200
    assert calls == ["done"]
