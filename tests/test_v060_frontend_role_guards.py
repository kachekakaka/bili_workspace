from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_normal_user_frontend_scope_is_device_only() -> None:
    main = (ROOT / "web" / "assets" / "app" / "main.mjs").read_text(encoding="utf-8")
    routes = (
        ROOT / "web" / "assets" / "app" / "core" / "route-policy.mjs"
    ).read_text(encoding="utf-8")
    download = (
        ROOT / "web" / "assets" / "app" / "pages" / "download.mjs"
    ).read_text(encoding="utf-8")
    index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

    assert "const USER_NAV = Object.freeze([['download', '↓', '下载'], ['tasks', '≡', '任务']]);" in main
    assert "export const USER_ROUTES = Object.freeze(['download', 'tasks']);" in routes
    assert "return normalizeRole(role) === 'admin' ? 'dashboard' : 'download';" in routes
    assert "const normalUser = !context.session.isAdmin();" in download
    assert "const destination = normalUser ? 'device'" in download
    assert "force: normalUser ? false" in download
    assert "group_id: destination === 'library'" in download
    assert "group: ''" in download
    assert "下载完成后导出到当前设备，不会进入管理员媒体库。" in download
    assert 'id="userMenuRoot"' in index
    assert 'id="userMenuButton"' in index
