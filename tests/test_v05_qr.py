from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.qr_login import QrLoginManager


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.cookies = httpx.Cookies()
        self.closed = False

    def get(self, *args, **kwargs):
        del args, kwargs
        return FakeResponse(self.responses.pop(0))

    def close(self):
        self.closed = True


def test_qr_login_persists_cookie_only_on_server(tmp_path: Path):
    fake = FakeClient(
        [
            {
                "code": 0,
                "data": {"url": "https://example.invalid/qr", "qrcode_key": "key"},
            },
            {
                "code": 0,
                "data": {
                    "code": 0,
                    "message": "ok",
                    "url": "https://example.invalid/success?SESSDATA=sess&bili_jct=csrf&DedeUserID=123",
                },
            },
        ]
    )
    manager = QrLoginManager(lambda: tmp_path)
    manager._client = lambda: fake
    try:
        created = manager.create()
        assert created["login_url"] == "https://example.invalid/qr"
        result = manager.poll(created["id"])
        assert result["status"] == "success"
        assert "SESSDATA" not in result
        data = (tmp_path / "BBDown.data").read_text(encoding="utf-8")
        assert "SESSDATA=sess" in data
        assert "bili_jct=csrf" in data
        assert manager.logout() is True
        assert not (tmp_path / "BBDown.data").exists()
    finally:
        manager.stop()


def test_qr_poll_rejects_response_without_status_code(tmp_path: Path):
    fake = FakeClient(
        [
            {"code": 0, "data": {"url": "https://example.invalid/qr", "qrcode_key": "key"}},
            {"code": 0, "data": {"message": "missing"}},
        ]
    )
    manager = QrLoginManager(lambda: tmp_path)
    manager._client = lambda: fake
    try:
        session = manager.create()
        with pytest.raises(RuntimeError, match="缺少状态码"):
            manager.poll(session["id"])
    finally:
        manager.stop()


def test_qr_login_rejects_cookie_file_injection(tmp_path: Path):
    fake = FakeClient(
        [
            {"code": 0, "data": {"url": "https://example.invalid/qr", "qrcode_key": "key"}},
            {
                "code": 0,
                "data": {
                    "code": 0,
                    "message": "ok",
                    "url": "https://example.invalid/success?SESSDATA=x%3By&bili_jct=csrf",
                },
            },
        ]
    )
    manager = QrLoginManager(lambda: tmp_path)
    manager._client = lambda: fake
    try:
        session = manager.create()
        with pytest.raises(RuntimeError, match="格式异常"):
            manager.poll(session["id"])
        assert not (tmp_path / "BBDown.data").exists()
    finally:
        manager.stop()
