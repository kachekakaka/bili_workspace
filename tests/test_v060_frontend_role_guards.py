from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_normal_user_frontend_scope_is_device_only() -> None:
    app = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

    assert "const USER_NAV = [['download','↓','下载'], ['tasks','≡','任务']]" in app
    assert ": ['download','tasks']);" in app
    assert "function defaultPage() { return isAdmin() ? 'dashboard' : 'download'; }" in app
    assert "destination:'device'" in app
    assert "force:false,group_id:'',group:''" in app
    assert "下载完成后导出到当前设备，不会进入管理员媒体库。" in app
    assert 'id="userMenuRoot"' in index
    assert 'id="userMenuButton"' in index
