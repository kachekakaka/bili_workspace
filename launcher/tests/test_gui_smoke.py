from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox

from bili_workspace_launcher.gui import MainWindow
from bili_workspace_launcher.paths import AppPaths


def test_gui_can_construct_without_starting_products(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow(application, schedule_startup=False, paths=AppPaths(tmp_path / "control"))
    try:
        assert window.windowTitle().startswith("bili_workspace")
        assert window.backend.is_running is False
        assert window.export_button.text().find("三件套") >= 0
    finally:
        window.tray.hide()
        window.close()


def test_gui_stops_own_backend_after_bounded_startup_timeout(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class HangingBackend:
        is_running = True
        process_id = 43210
        port = 3398
        url = "http://127.0.0.1:3398/"

        def health_ready(self, timeout: float) -> bool:
            assert timeout == 0.2
            return False

        def log_tail(self) -> str:
            return "startup log"

        def stop(self, timeout: float) -> bool:
            assert timeout == 0
            self.is_running = False
            self.port = None
            return True

    application = QApplication.instance() or QApplication([])
    window = MainWindow(application, schedule_startup=False, paths=AppPaths(tmp_path / "control"))
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, title, message: messages.append((title, message)),
    )
    window.backend = HangingBackend()  # type: ignore[assignment]
    window._backend_start_deadline = 0
    try:
        window._poll_backend()
        assert window.backend.is_running is False
        assert window._backend_start_deadline is None
        assert window.service_status.text() == "启动超时，已停止"
        assert messages and messages[0][0] == "后端启动超时"
        assert "startup log" in window.log_view.toPlainText()
    finally:
        window.tray.hide()
        window.close()


def test_gui_throttles_health_checks_after_backend_is_ready(tmp_path) -> None:
    class ReadyBackend:
        is_running = True
        process_id = 43210
        port = 3398
        url = "http://127.0.0.1:3398/"

        def __init__(self) -> None:
            self.health_calls = 0

        def health_ready(self, timeout: float) -> bool:
            assert timeout == 0.2
            self.health_calls += 1
            return True

    application = QApplication.instance() or QApplication([])
    window = MainWindow(application, schedule_startup=False, paths=AppPaths(tmp_path / "control"))
    backend = ReadyBackend()
    window.backend = backend  # type: ignore[assignment]
    window._backend_ready = True
    window._next_backend_health_check_at = 0.0
    try:
        window._poll_backend()
        for _ in range(20):
            window._poll_backend()
        assert backend.health_calls == 1
    finally:
        backend.is_running = False
        window.tray.hide()
        window.close()
