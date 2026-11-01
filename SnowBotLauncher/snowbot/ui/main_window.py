"""主窗口：组装各页面、托盘与全局状态。"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QPushButton,
    QTabWidget,
    QMessageBox,
    QSystemTrayIcon,
    QMenu,
)

from snowbot.core.config import astrbot_dashboard_info, is_admin, load_config, save_config
from snowbot.core.paths import APP_NAME, APP_VERSION, CONFIG_PATH, LOG_DIR
from snowbot.core.services import ServiceManager
from snowbot.ui.pages.about import AboutMixin
from snowbot.ui.pages.console import ConsoleMixin
from snowbot.ui.pages.enhance import EnhanceTab
from snowbot.ui.pages.packs import PacksMixin
from snowbot.ui.pages.settings import SettingsMixin
from snowbot.ui.theme import make_app_icon
from snowbot.ui.widgets import scroll_page


class LauncherWindow(
    ConsoleMixin, PacksMixin, SettingsMixin, AboutMixin, QMainWindow
):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        if not CONFIG_PATH.exists():
            save_config(self.cfg)
        self.manager = ServiceManager(self.cfg)
        self.tray = None
        self.last_logs = {}
        self.token_visible = False
        self.astrbot_log = LOG_DIR / "astrbot.log"
        self.current_pack = None
        self.var_widgets = {}
        self.pack_worker = None

        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setWindowIcon(make_app_icon())
        self.resize(1060, 760)
        self.setMinimumSize(860, 520)

        self._build_ui()
        self._build_tray()

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start(2000)

        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self.refresh_logs)
        self.log_timer.start(1200)

        self.refresh_packs()
        self.refresh_status()
        if self.cfg.get("start_minimized"):
            QTimer.singleShot(600, self.hide_to_tray)
        if self.cfg.get("autostart_services"):
            QTimer.singleShot(1500, self.start_all)

    # ---------------- UI ----------------

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 20, 24, 16)
        outer.setSpacing(14)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel(APP_NAME)
        title.setObjectName("title")
        sub = QLabel("AstrBot + NapCat 统一启停 / 配置包 / 增强配置 / 后台挂起")
        sub.setObjectName("subtitle")
        titles.addWidget(title)
        titles.addWidget(sub)
        header.addLayout(titles)
        header.addStretch(1)

        self.header_pill = QLabel("检测中…")
        self.header_pill.setObjectName("pill")
        header.addWidget(self.header_pill, 0, Qt.AlignmentFlag.AlignVCenter)

        suspend_btn = QPushButton("后台挂起")
        suspend_btn.setObjectName("ghost")
        suspend_btn.setToolTip("隐藏窗口，服务继续运行；可从系统托盘恢复")
        suspend_btn.clicked.connect(self.hide_to_tray)
        header.addWidget(suspend_btn)

        refresh_btn = QPushButton("刷新状态")
        refresh_btn.setObjectName("ghost")
        refresh_btn.clicked.connect(self.refresh_status)
        header.addWidget(refresh_btn)
        outer.addLayout(header)

        if not is_admin():
            banner = QFrame()
            banner.setObjectName("banner")
            bl = QHBoxLayout(banner)
            bl.setContentsMargins(14, 8, 14, 8)
            warn = QLabel("当前未以管理员权限运行，NapCat 可能无法启动。")
            warn.setObjectName("warnText")
            bl.addWidget(warn)
            bl.addStretch(1)
            ele = QPushButton("以管理员身份重启")
            ele.clicked.connect(self.relaunch_admin)
            bl.addWidget(ele)
            outer.addWidget(banner)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        self.tabs.addTab(self._build_console_tab(), "控制台")
        self.tabs.addTab(scroll_page(self._build_packs_tab()), "配置包")
        self.tabs.addTab(EnhanceTab(self.cfg, astrbot_dashboard_info(self.cfg)), "增强配置")
        self.tabs.addTab(self._build_settings_tab(), "设置")
        self.tabs.addTab(self._build_about_tab(), "使用说明")

        footer = QHBoxLayout()
        self.footer_label = QLabel(f"配置：{CONFIG_PATH}")
        self.footer_label.setObjectName("muted")
        footer.addWidget(self.footer_label)
        footer.addStretch(1)
        ver = QLabel(f"v{APP_VERSION}")
        ver.setObjectName("muted")
        footer.addWidget(ver)
        outer.addLayout(footer)

    def _build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(make_app_icon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()

        show_action = QAction("显示控制台", self)
        show_action.triggered.connect(self.show_from_tray)
        start_action = QAction("一键启动全部", self)
        start_action.triggered.connect(self.start_all)
        stop_action = QAction("一键停止全部", self)
        stop_action.triggered.connect(self.stop_all)
        quit_action = QAction("退出（服务继续运行）", self)
        quit_action.triggered.connect(self.quit_app)
        quit_stop_action = QAction("退出并停止服务", self)
        quit_stop_action.triggered.connect(self.quit_and_stop)

        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(start_action)
        menu.addAction(stop_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        menu.addAction(quit_stop_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.show_from_tray()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick
            else None
        )
        self.tray.show()

    def hide_to_tray(self):
        self.hide()
        if self.tray:
            self.tray.showMessage(
                APP_NAME,
                "已挂起到托盘，服务继续在后台运行。双击托盘图标可恢复窗口。",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )

    def show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _stop_workers(self):
        workers = [getattr(self, "pack_worker", None)]
        for enhance in self.findChildren(EnhanceTab):
            workers.append(getattr(enhance, "worker", None))
        for worker in workers:
            if worker and worker.isRunning():
                worker.terminate()
                worker.wait(1500)

    def quit_app(self):
        self.status_timer.stop()
        self.log_timer.stop()
        self._stop_workers()
        if self.tray:
            self.tray.hide()
        QApplication.quit()

    def quit_and_stop(self):
        if (
            QMessageBox.question(
                self,
                "退出并停止服务",
                "将停止 AstrBot 和 NapCat（包括 QQ），确定退出？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.manager.stop_all()
        self.quit_app()

    def closeEvent(self, event):
        if self.cfg.get("close_to_tray", True):
            event.ignore()
            self.hide_to_tray()
        else:
            event.ignore()
            if (
                QMessageBox.question(
                    self,
                    "退出控制台",
                    "服务将继续在后台运行，仅退出控制台。确定？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                == QMessageBox.StandardButton.Yes
            ):
                self.quit_app()

    # ---------------- 状态刷新 ----------------

    def _toast(self, msg: str, ok: bool = True):
        self.hint_lbl.setText(("✔ " if ok else "⚠ ") + msg)
        self.hint_lbl.setStyleSheet(
            "color:#4ade80;" if ok else "color:#fbbf24;"
        )
        if self.tray and self.isHidden():
            self.tray.showMessage(
                APP_NAME,
                msg,
                QSystemTrayIcon.MessageIcon.Information if ok else QSystemTrayIcon.MessageIcon.Warning,
                3000,
            )
