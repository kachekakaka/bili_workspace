"""PySide6 启动器界面、托盘生命周期与显式安全配置。"""

from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from app.task_logs import redact_sensitive

from .backend_process import BackendProcessError, BackendProcessManager
from .constants import (
    APP_NAME,
    BACKEND_READY_HEALTH_INTERVAL_SECONDS,
    BACKEND_START_TIMEOUT_SECONDS,
)
from .docker_jobs import DockerJobError, DockerJobs, ExportResult
from .paths import (
    AppPaths,
    DataRootError,
    DataRootLayout,
    DataRootLock,
    DataRootLockError,
    DataRootManager,
)
from .ports import is_port_available, recommend_available_port
from .resources import ResourceError, ResourceManager, ResourceManifest
from .settings import (
    LauncherSettings,
    NetworkSettings,
    RuntimeEnvStore,
    SettingsError,
    SettingsStore,
)
from .version import PRODUCT_VERSION


class FunctionWorker(QThread):
    output = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, function: Callable[[Callable[[str], None]], Any]) -> None:
        super().__init__()
        self.function = function

    def run(self) -> None:
        try:
            result = self.function(self.output.emit)
        except Exception as exc:  # GUI 边界必须把后台异常带回主线程
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(result)


class MainWindow(QMainWindow):
    def __init__(
        self,
        application: QApplication,
        *,
        schedule_startup: bool = True,
        paths: AppPaths | None = None,
    ) -> None:
        super().__init__()
        self.application = application
        self.paths = paths or AppPaths.from_executable()
        self.paths.ensure_control_directories()
        self.settings_store = SettingsStore(self.paths)
        self.data_roots: DataRootManager | None = None
        self.resources = ResourceManager(self.paths)
        self.backend = BackendProcessManager(self.paths)
        self.docker_jobs = DockerJobs(self.paths)
        self.settings: LauncherSettings | None = None
        self.layout: DataRootLayout | None = None
        self.network: NetworkSettings | None = None
        self.resource_root: Path | None = None
        self.resource_manifest: ResourceManifest | None = None
        self._data_lock: DataRootLock | None = None
        self._worker: FunctionWorker | None = None
        self._allow_close = False
        self._backend_ready = False
        self._backend_start_deadline: float | None = None
        self._next_backend_health_check_at = 0.0
        self._docker_recovery_blocked = False
        self._tray_available = False

        self.setWindowTitle(f"{APP_NAME} Windows 启动器 {PRODUCT_VERSION}")
        self.resize(920, 760)
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self._build_ui()
        self._build_tray()
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(500)
        self.status_timer.timeout.connect(self._poll_backend)
        self.status_timer.start()
        if schedule_startup:
            QTimer.singleShot(0, self._bootstrap)

    def _build_ui(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)

        service_group = QGroupBox("Web 后台服务")
        service_layout = QVBoxLayout(service_group)
        self.service_status = QLabel("尚未选择数据根")
        self.service_url = QLabel("")
        self.data_path = QLabel("未选择")
        self.data_path.setWordWrap(True)
        service_layout.addWidget(self.service_status)
        service_layout.addWidget(self.service_url)
        service_layout.addWidget(QLabel("数据根："))
        service_layout.addWidget(self.data_path)
        service_buttons = QHBoxLayout()
        self.start_button = QPushButton("启动服务")
        self.stop_button = QPushButton("停止服务")
        self.open_web_button = QPushButton("打开 Web")
        self.data_button = QPushButton("选择数据根")
        self.start_button.clicked.connect(self.start_backend)
        self.stop_button.clicked.connect(self.stop_backend)
        self.open_web_button.clicked.connect(self.open_web)
        self.data_button.clicked.connect(self.change_data_root)
        for button in (self.start_button, self.stop_button, self.open_web_button, self.data_button):
            service_buttons.addWidget(button)
        service_layout.addLayout(service_buttons)
        layout.addWidget(service_group)

        network_group = QGroupBox("监听与安全配置（保存在数据根）")
        network_form = QFormLayout(network_group)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("本机模式", "local")
        self.mode_combo.addItem("局域网服务器模式", "server")
        self.host_edit = QLineEdit()
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.trusted_hosts_edit = QLineEdit()
        self.trusted_proxies_edit = QLineEdit()
        self.public_url_edit = QLineEdit()
        self.allow_ip_hosts_check = QCheckBox("允许通过明确 IP Host 访问")
        self.secure_cookie_check = QCheckBox("启用 Secure Cookie")
        self.hsts_check = QCheckBox("启用 HSTS（要求已验证 HTTPS）")
        self.save_network_button = QPushButton("保存网络与安全配置")
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.save_network_button.clicked.connect(lambda _checked=False: self.save_network())
        network_form.addRow("运行模式", self.mode_combo)
        network_form.addRow("监听地址", self.host_edit)
        network_form.addRow("端口", self.port_spin)
        network_form.addRow("可信 Host（逗号分隔）", self.trusted_hosts_edit)
        network_form.addRow("可信代理 IP/CIDR（逗号分隔）", self.trusted_proxies_edit)
        network_form.addRow("公开 URL", self.public_url_edit)
        network_form.addRow("IP Host", self.allow_ip_hosts_check)
        network_form.addRow("Cookie", self.secure_cookie_check)
        network_form.addRow("HSTS", self.hsts_check)
        network_note = QLabel(
            "局域网直连使用 HTTP；需要传输加密时，请经反向代理配置 HTTPS、"
            "Secure Cookie 与 HSTS。"
        )
        network_note.setWordWrap(True)
        network_form.addRow("提示", network_note)
        network_form.addRow("", self.save_network_button)
        layout.addWidget(network_group)

        export_group = QGroupBox("构建并导出 Docker 镜像（固定 linux/amd64）")
        export_layout = QHBoxLayout(export_group)
        self.export_button = QPushButton("选择目录并导出三件套")
        self.export_button.clicked.connect(self.choose_docker_export)
        self.build_identity = QLabel("构建身份尚未加载")
        export_layout.addWidget(self.export_button)
        export_layout.addWidget(self.build_identity, stretch=1)
        layout.addWidget(export_group)

        log_group = QGroupBox("当前启动器会话日志（不显示秘密值）")
        log_layout = QVBoxLayout(log_group)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(1000)
        log_layout.addWidget(self.log_view)
        layout.addWidget(log_group, stretch=1)

        footer = QHBoxLayout()
        about_button = QPushButton("关于与许可")
        exit_button = QPushButton("退出程序")
        about_button.clicked.connect(self.show_about)
        exit_button.clicked.connect(self.explicit_exit)
        footer.addStretch(1)
        footer.addWidget(about_button)
        footer.addWidget(exit_button)
        layout.addLayout(footer)
        self.setCentralWidget(root)
        self._update_controls()

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        self.tray.setContextMenu(menu)
        show_action = menu.addAction("打开启动器")
        open_web_action = menu.addAction("打开 Web")
        menu.addSeparator()
        exit_action = menu.addAction("退出程序")
        show_action.triggered.connect(self._restore_window)
        open_web_action.triggered.connect(self.open_web)
        exit_action.triggered.connect(self.explicit_exit)
        self.tray.activated.connect(self._tray_activated)
        self.tray.setToolTip(f"{APP_NAME} {PRODUCT_VERSION}")
        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        if self._tray_available:
            self.tray.show()

    def _bootstrap(self) -> None:
        for message in self.backend.recover_stale_sessions():
            self.append_log(message)
        try:
            for message in self.docker_jobs.recover_pending_outputs():
                self.append_log(message)
        except DockerJobError as exc:
            QMessageBox.critical(self, "Docker 输出恢复失败", str(exc))
            self.append_log(f"Docker 输出恢复失败：{exc}")
            self._docker_recovery_blocked = True
        try:
            settings = self.settings_store.load()
        except SettingsError as exc:
            QMessageBox.critical(
                self,
                "launcher.json 无效",
                f"{exc}\n\n原文件未被覆盖。请关闭启动器，修复或删除该文件后重试。",
            )
            self.service_status.setText("launcher.json 无效，服务未启动")
            return
        try:
            self.resource_root, self.resource_manifest = self.resources.ensure_extracted()
        except ResourceError as exc:
            QMessageBox.critical(self, "内置资源错误", str(exc))
            self.service_status.setText("内置资源无效，服务未启动")
            self._update_controls()
            return
        self.data_roots = DataRootManager(
            self.paths,
            self.resource_root / "docker-context" / "app" / "defaults",
        )
        self.build_identity.setText(
            f"版本 {PRODUCT_VERSION} · build {self.resource_manifest.build_id} · linux/amd64"
        )
        if settings is None:
            if not self._select_data_root("首次启动：选择仓库外数据根（取消则不启动）"):
                self.service_status.setText("未选择数据根，服务未启动")
                return
        else:
            self.settings = settings
            if not self._prepare_data_root(Path(settings.data_root), persist=False):
                if not self._select_data_root("已记住的数据根不可用，请重新选择（取消则不启动）"):
                    return
        self._update_controls()
        QTimer.singleShot(100, self.start_backend)
        QTimer.singleShot(1200, self._check_stale_images)

    def _select_data_root(self, title: str) -> bool:
        initial = self.settings.data_root if self.settings else str(self.paths.base_dir.parent)
        selected = QFileDialog.getExistingDirectory(self, title, initial)
        if not selected:
            self.append_log("用户取消数据根选择；后端未启动。")
            return False
        return self._prepare_data_root(Path(selected), persist=True)

    def _prepare_data_root(self, selected: Path, *, persist: bool) -> bool:
        if self.data_roots is None:
            QMessageBox.critical(self, "内置资源未就绪", "请先完成启动器资源校验。")
            return False
        candidate_lock: DataRootLock | None = None
        acquired_new_lock = False
        try:
            preview_layout = self.data_roots.resolve_layout(selected)
            if (
                self._data_lock is not None
                and self._data_lock.acquired
                and self._data_lock.layout.root == preview_layout.root
            ):
                candidate_lock = self._data_lock
            else:
                candidate_lock = DataRootLock(preview_layout)
                candidate_lock.acquire()
                acquired_new_lock = True
            layout = self.data_roots.prepare_locked(preview_layout.root, candidate_lock)
            network = RuntimeEnvStore(layout.runtime_env_file).load()
        except (DataRootError, DataRootLockError, SettingsError) as exc:
            if acquired_new_lock and candidate_lock is not None:
                candidate_lock.release()
            QMessageBox.critical(self, "数据根无效", str(exc))
            self.append_log(f"数据根拒绝：{exc}")
            return False
        recent = self.settings.recent_export_dir if self.settings else ""
        settings = LauncherSettings.create(layout.root, recent)
        if persist or self.settings is None:
            try:
                self.settings_store.save(settings)
            except (OSError, SettingsError) as exc:
                if acquired_new_lock and candidate_lock is not None:
                    candidate_lock.release()
                QMessageBox.critical(self, "launcher.json 保存失败", str(exc))
                return False
        old_lock = self._data_lock
        self.settings = settings
        self.layout = layout
        self.network = network
        self._data_lock = candidate_lock
        if old_lock is not None and old_lock is not candidate_lock:
            try:
                old_lock.release()
            except Exception as exc:
                self.append_log(f"旧数据根锁释放异常：{exc}")
        self.data_path.setText(str(layout.root))
        self._apply_network(network)
        self.service_status.setText("数据根已就绪，服务未启动")
        self.append_log(f"数据根已验证：{layout.root}")
        self._update_controls()
        return True

    def change_data_root(self) -> None:
        if self.backend.is_running:
            QMessageBox.information(self, "服务运行中", "请先停止服务再选择其他数据根。")
            return
        self._select_data_root("选择仓库外数据根")

    def _apply_network(self, network: NetworkSettings) -> None:
        index = self.mode_combo.findData(network.mode)
        self.mode_combo.setCurrentIndex(max(0, index))
        self.host_edit.setText(network.host)
        self.port_spin.setValue(network.port)
        self.trusted_hosts_edit.setText(",".join(network.trusted_hosts))
        self.trusted_proxies_edit.setText(",".join(network.trusted_proxy_ips))
        self.public_url_edit.setText(network.public_base_url)
        self.allow_ip_hosts_check.setChecked(network.allow_ip_hosts)
        self.secure_cookie_check.setChecked(network.cookie_secure)
        self.hsts_check.setChecked(network.hsts_enabled)

    def _network_from_widgets(self) -> NetworkSettings:
        return NetworkSettings(
            mode=str(self.mode_combo.currentData()),
            host=self.host_edit.text(),
            port=self.port_spin.value(),
            trusted_hosts=tuple(self.trusted_hosts_edit.text().split(",")),
            trusted_proxy_ips=tuple(self.trusted_proxies_edit.text().split(",")),
            public_base_url=self.public_url_edit.text(),
            allow_ip_hosts=self.allow_ip_hosts_check.isChecked(),
            cookie_secure=self.secure_cookie_check.isChecked(),
            hsts_enabled=self.hsts_check.isChecked(),
        ).validated()

    def _mode_changed(self, _index: int = -1) -> None:
        mode = str(self.mode_combo.currentData())
        if mode == "local":
            self.host_edit.setText("127.0.0.1")
            self.allow_ip_hosts_check.setChecked(False)
        elif self.host_edit.text().strip().lower() in {"", "127.0.0.1", "localhost", "::1", "[::1]"}:
            self.host_edit.setText("0.0.0.0")
            self.allow_ip_hosts_check.setChecked(True)

    def save_network(self, *, show_success: bool = True) -> bool:
        if self.backend.is_running:
            QMessageBox.information(self, "服务运行中", "请先停止服务再修改网络配置。")
            return False
        if self.layout is None:
            QMessageBox.information(self, "尚未选择数据根", "请先选择数据根。")
            return False
        try:
            network = self._network_from_widgets()
            RuntimeEnvStore(self.layout.runtime_env_file).save(network)
        except (OSError, SettingsError) as exc:
            QMessageBox.critical(self, "网络配置无效", str(exc))
            return False
        self.network = network
        self._apply_network(network)
        self.append_log(f"网络配置已保存：{network.mode} {network.host}:{network.port}")
        if show_success:
            QMessageBox.information(self, "已保存", "网络与安全配置已保存到当前数据根。")
        return True

    def start_backend(self) -> None:
        if self.backend.is_running:
            return
        if self.layout is None or self.resource_root is None or self.resource_manifest is None:
            QMessageBox.information(self, "启动条件未满足", "请先选择数据根并通过内置资源校验。")
            return
        if not self.save_network(show_success=False):
            return
        assert self.network is not None
        network = self.network
        if not is_port_available(network.port, network.host):
            recommended = recommend_available_port(
                network.port,
                checker=lambda port: is_port_available(port, network.host),
            )
            if recommended is None:
                QMessageBox.critical(self, "端口冲突", f"端口 {network.port} 已占用，且没有找到可用端口。")
                return
            answer = QMessageBox.question(
                self,
                "端口冲突",
                f"{network.host}:{network.port} 已被其他进程占用。\n"
                f"建议改用 {recommended}；是否确认写入当前数据根？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.append_log("用户未确认推荐端口；没有停止其他进程，也没有启动后端。")
                return
            self.port_spin.setValue(recommended)
            if not self.save_network(show_success=False):
                return
            network = self.network
            assert network is not None
        try:
            self.backend.start(
                layout=self.layout,
                network=network,
                resource_root=self.resource_root,
                build_id=self.resource_manifest.build_id,
                data_lock=self._data_lock,
            )
        except (BackendProcessError, DataRootLockError, OSError) as exc:
            QMessageBox.critical(self, "后端启动失败", str(exc))
            return
        self._backend_ready = False
        self._backend_start_deadline = time.monotonic() + BACKEND_START_TIMEOUT_SECONDS
        self._next_backend_health_check_at = 0.0
        self.service_status.setText("正在启动……")
        self.service_url.setText(self.backend.url or "")
        self.append_log(
            f"已创建自有后端子进程（PID {self.backend.process_id}，监听 {self.backend.bind_description}）。"
        )
        self._update_controls()

    def _poll_backend(self) -> None:
        if self.backend.is_running:
            now = time.monotonic()
            if self._backend_ready and now < self._next_backend_health_check_at:
                ready = True
            else:
                ready = self.backend.health_ready(timeout=0.2)
                self._next_backend_health_check_at = (
                    now + BACKEND_READY_HEALTH_INTERVAL_SECONDS if ready else 0.0
                )
            if ready and not self._backend_ready:
                self.append_log(f"Web 服务已就绪：{self.backend.url}")
            if ready:
                self._backend_start_deadline = None
            elif (
                self._backend_start_deadline is not None
                and time.monotonic() >= self._backend_start_deadline
            ):
                details = self.backend.log_tail()
                try:
                    forced = self.backend.stop(timeout=0)
                except (BackendProcessError, OSError) as exc:
                    self.append_log(f"后端启动超时，停止失败：{exc}")
                    message = f"后端未在时限内通过健康检查，且停止失败：{exc}"
                    stopped = False
                else:
                    suffix = "；已终止自有子进程" if forced else "；自有子进程已停止"
                    message = "后端未在时限内通过健康检查" + suffix
                    stopped = True
                self._backend_start_deadline = None
                self._backend_ready = False
                self.service_status.setText("启动超时，已停止" if stopped else "启动超时，停止失败")
                if stopped:
                    self.service_url.setText("")
                self.append_log(message + "。\n" + details)
                QMessageBox.critical(self, "后端启动超时", message)
                self._update_controls()
                return
            self._backend_ready = ready
            self.service_status.setText("运行中" if ready else "正在启动……")
            self.service_url.setText(self.backend.url or "")
        elif self.backend.process_id is None and self.backend.port is not None:
            details = self.backend.log_tail()
            self.append_log("后端子进程已退出。\n" + details)
            try:
                self.backend.stop(timeout=0)
            except (BackendProcessError, OSError) as exc:
                self.append_log(f"后端已退出，但会话清理失败：{exc}")
            self._backend_start_deadline = None
            self._backend_ready = False
            self._next_backend_health_check_at = 0.0
            self.service_status.setText("已停止")
        self._update_controls()

    def stop_backend(self) -> None:
        if not self.backend.is_running and self.backend.port is None:
            return
        details = self.backend.log_tail()
        try:
            forced = self.backend.stop()
        except (BackendProcessError, OSError) as exc:
            QMessageBox.warning(self, "后端停止失败", str(exc))
            return
        self._backend_start_deadline = None
        self._backend_ready = False
        self._next_backend_health_check_at = 0.0
        self.service_status.setText("已停止")
        self.append_log("后端已停止。" + ("（优雅停止超时，只终止了自有子进程）" if forced else ""))
        if "ERROR" in details:
            self.append_log(details)
        self._update_controls()

    def open_web(self) -> None:
        url = self.backend.url
        if not url or not self._backend_ready:
            QMessageBox.information(self, "Web 未就绪", "请先启动服务并等待健康检查通过。")
            return
        QDesktopServices.openUrl(QUrl(url))

    def choose_docker_export(self) -> None:
        if self._worker is not None:
            return
        if self._docker_recovery_blocked:
            QMessageBox.critical(
                self,
                "Docker 导出已阻止",
                "存在未能安全恢复的 Docker 输出事务。请先处理启动日志中的 journal 错误。",
            )
            return
        if self.resource_root is None or self.resource_manifest is None:
            QMessageBox.information(self, "内置资源未就绪", "请先完成启动器资源校验。")
            return
        if not self.docker_jobs.docker_available():
            QMessageBox.critical(self, "Docker 不可用", "导出需要本机正在运行的 Docker Desktop/Engine。")
            return
        initial = self.settings.recent_export_dir if self.settings else ""
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择 Docker 三件套输出目录（不能位于 Git 仓库或 EXE 控制根）",
            initial or str(Path.home()),
        )
        if not selected:
            return
        output_dir = Path(selected)
        try:
            preflight = self.docker_jobs.preflight_export(
                output_dir,
                self.resource_manifest.build_id,
            )
        except DockerJobError as exc:
            QMessageBox.critical(self, "Docker 输出目录无效", str(exc))
            return
        paths = preflight.paths
        path_identities = tuple(
            zip(
                (paths.tar, paths.checksum, paths.manifest),
                preflight.old_files,
                strict=True,
            )
        )
        existing = [item for item in path_identities if bool(item[1]["exists"])]
        overwrite = False
        if existing:
            details = "\n".join(
                f"{path}（{identity['size']} 字节，SHA-256 {identity['sha256']}）"
                for path, identity in existing
            )
            old_build = preflight.old_build_id or "无法从现有 JSON 验证"
            answer = QMessageBox.question(
                self,
                "确认覆盖固定三件套",
                f"以下目标已存在：\n{details}\n\n"
                f"现有交付 build：{old_build}\n"
                f"新产物版本 {PRODUCT_VERSION}，build {self.resource_manifest.build_id}，linux/amd64。\n"
                "是否仅对本次任务确认覆盖？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        if self.settings is not None:
            self.settings = replace(self.settings, recent_export_dir=str(output_dir.resolve()))
            try:
                self.settings_store.save(self.settings)
            except (OSError, SettingsError) as exc:
                QMessageBox.warning(self, "最近目录保存失败", str(exc))

        def job(output: Callable[[str], None]) -> ExportResult:
            assert self.resource_root is not None and self.resource_manifest is not None
            return self.docker_jobs.export_image(
                source_root=self.resource_root,
                output_dir=output_dir,
                build_id=self.resource_manifest.build_id,
                overwrite=overwrite,
                on_output=output,
                preflight=preflight,
            )

        self._start_job("Docker amd64 构建并导出", job)

    def _start_job(
        self,
        label: str,
        function: Callable[[Callable[[str], None]], Any],
        *,
        success_handler: Callable[[Any], None] | None = None,
    ) -> None:
        if self._worker is not None:
            QMessageBox.information(self, "已有任务", "请等待当前任务完成。")
            return
        self.append_log(f"{label}：开始。")
        worker = FunctionWorker(function)
        self._worker = worker
        self._update_controls()
        worker.output.connect(self.append_log)

        def succeeded(result: object) -> None:
            self.append_log(f"{label}：完成。")
            if success_handler:
                success_handler(result)
            elif isinstance(result, ExportResult):
                message = (
                    f"已输出：\n{result.paths.tar}\n{result.paths.checksum}\n{result.paths.manifest}"
                )
                if result.cleanup_warning:
                    message += f"\n\n{result.cleanup_warning}"
                QMessageBox.information(self, "导出完成", message)
            self._finish_job()

        def failed(message: str) -> None:
            safe_message = redact_sensitive(message)
            self.append_log(f"{label}：失败：{safe_message}")
            QMessageBox.critical(self, f"{label}失败", safe_message)
            self._finish_job()

        worker.succeeded.connect(succeeded)
        worker.failed.connect(failed)
        worker.start()

    def _finish_job(self) -> None:
        worker = self._worker
        self._worker = None
        self._update_controls()
        if worker is not None:
            worker.deleteLater()

    def _check_stale_images(self) -> None:
        if (
            self._docker_recovery_blocked
            or self._worker is not None
            or not self.docker_jobs.docker_available()
        ):
            return
        try:
            stale = self.docker_jobs.stale_images()
        except DockerJobError as exc:
            self.append_log(f"遗留临时镜像检查失败：{exc}")
            return
        if not stale:
            return
        answer = QMessageBox.question(
            self,
            "发现启动器自有遗留镜像",
            f"发现 {len(stale)} 个同时具有有效 journal 与所有权标签的临时镜像。\n"
            "是否逐个重新核验并精确删除？不会清理其他镜像、缓存或卷。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def job(output: Callable[[str], None]) -> int:
            for retained in stale:
                self.docker_jobs.cleanup_stale_image(retained)
                output(f"已删除自有临时标签：{retained.tag}")
            return len(stale)

        self._start_job("遗留自有镜像清理", job)

    def _update_controls(self) -> None:
        running = self.backend.is_running
        ready = self.layout is not None and self.resource_root is not None
        self.start_button.setEnabled(ready and not running)
        self.stop_button.setEnabled(running)
        self.open_web_button.setEnabled(running and self._backend_ready)
        self.data_button.setEnabled(not running and self.data_roots is not None)
        network_enabled = self.layout is not None and not running
        for widget in (
            self.mode_combo,
            self.host_edit,
            self.port_spin,
            self.trusted_hosts_edit,
            self.trusted_proxies_edit,
            self.public_url_edit,
            self.allow_ip_hosts_check,
            self.secure_cookie_check,
            self.hsts_check,
            self.save_network_button,
        ):
            widget.setEnabled(network_enabled)
        self.export_button.setEnabled(
            self.resource_root is not None
            and self._worker is None
            and not self._docker_recovery_blocked
        )

    def append_log(self, message: str) -> None:
        if message:
            self.log_view.appendPlainText(redact_sensitive(message))

    def show_about(self) -> None:
        try:
            if self.resource_root is None:
                raise OSError("verified resources are not ready")
            text = (self.resource_root / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
        except OSError:
            text = "第三方许可告知文件不可用。"
        build = self.resource_manifest.build_id if self.resource_manifest else "unknown"
        QMessageBox.information(
            self,
            f"关于 {APP_NAME}",
            f"{APP_NAME} Windows 启动器 {PRODUCT_VERSION}\nbuild {build}\n\n{text[:6000]}",
        )

    def _restore_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self._restore_window()

    def explicit_exit(self) -> None:
        if self._worker is not None:
            QMessageBox.information(self, "任务进行中", "请等待当前构建任务结束后再退出。")
            return
        warning = self.docker_jobs.cleanup_session_image()
        if warning:
            QMessageBox.warning(self, "临时镜像清理未完成", warning)
        self.stop_backend()
        self._allow_close = True
        self.tray.hide()
        self.application.quit()

    def shutdown_for_session_end(self) -> None:
        try:
            self.backend.stop()
        except Exception:
            pass
        if self._data_lock is not None:
            try:
                self._data_lock.release()
            except Exception:
                pass
            self._data_lock = None
        self._allow_close = True

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_close:
            event.accept()
            return
        event.ignore()
        if not self._tray_available:
            self.showMinimized()
            self.append_log("系统托盘不可用；窗口已最小化，后台服务继续运行。")
            return
        self.hide()
        if self.tray.isVisible():
            self.tray.showMessage(
                APP_NAME,
                "启动器已缩到系统托盘，后台服务继续运行。",
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )


def run_gui() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setApplicationVersion(PRODUCT_VERSION)
    application.setQuitOnLastWindowClosed(False)
    try:
        window = MainWindow(application)
    except (OSError, ValueError) as exc:
        QMessageBox.critical(
            None,
            "EXE 所在目录不可写或不安全",
            f"无法在 EXE 同级使用 launcher.json、resources 和 work：\n{exc}\n\n"
            "请把 EXE 移到当前用户可写的普通目录后重试。",
        )
        return 1
    window.show()
    application.aboutToQuit.connect(window.shutdown_for_session_end)
    if hasattr(application, "commitDataRequest"):
        application.commitDataRequest.connect(lambda _manager: window.shutdown_for_session_end())
    return application.exec()
