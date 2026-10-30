"""控制台页：服务卡片、状态、日志与启停操作。"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, QSize, QThread, Signal
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QBrush, QFont, QLinearGradient,
    QAction, QDesktopServices,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QPushButton, QGridLayout, QPlainTextEdit, QTabWidget, QLineEdit,
    QCheckBox, QFileDialog, QMessageBox, QSystemTrayIcon, QMenu, QScrollArea,
    QSpinBox, QGroupBox, QFormLayout, QSizePolicy, QSpacerItem, QToolButton,
    QListWidget, QListWidgetItem, QSplitter, QProgressBar, QComboBox, QInputDialog,
)

from snowbot.core.config import is_admin
from snowbot.core.paths import APP_NAME, LOG_DIR
from snowbot.core.services import tail_text
from snowbot.ui.widgets import Card, link_button


class ConsoleMixin:
    def _build_console_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(14)

        cards = QHBoxLayout()
        cards.setSpacing(14)

        # AstrBot 卡片
        self.astrbot_card = Card("#3b82f6", "A", "AstrBot", "大模型聊天机器人框架")
        self.astrbot_status_lbl = QLabel("—")
        self.astrbot_status_lbl.setObjectName("value")
        self.astrbot_card.add_row(0, "状态", self.astrbot_status_lbl)

        self.astrbot_link = link_button("http://localhost:6185")
        self.astrbot_link.clicked.connect(
            lambda: self.open_url(f"http://localhost:{self.cfg['dashboard_port']}")
        )
        self.astrbot_card.add_row(1, "WebUI", self.astrbot_link)

        ob = QLabel(f"ws://127.0.0.1:{self.cfg['onebot_port']}/ws")
        ob.setObjectName("value")
        self.astrbot_card.add_row(2, "OneBot", ob)

        self.astrbot_runtime = QLabel("—")
        self.astrbot_runtime.setObjectName("muted")
        self.astrbot_card.add_row(3, "运行时长", self.astrbot_runtime)

        self.btn_astrbot_start = QPushButton("启动")
        self.btn_astrbot_start.setObjectName("primary")
        self.btn_astrbot_start.clicked.connect(self.start_astrbot)
        self.btn_astrbot_stop = QPushButton("停止")
        self.btn_astrbot_stop.setObjectName("danger")
        self.btn_astrbot_stop.clicked.connect(self.stop_astrbot)
        self.btn_astrbot_open = QPushButton("打开面板")
        self.btn_astrbot_open.clicked.connect(
            lambda: self.open_url(f"http://localhost:{self.cfg['dashboard_port']}")
        )
        for b in (self.btn_astrbot_start, self.btn_astrbot_stop, self.btn_astrbot_open):
            self.astrbot_card.buttons.addWidget(b)
        cards.addWidget(self.astrbot_card, 1)

        # NapCat 卡片
        self.napcat_card = Card("#10b981", "N", "NapCat", "QQ 协议端（OneBot v11）")
        self.napcat_status_lbl = QLabel("—")
        self.napcat_status_lbl.setObjectName("value")
        self.napcat_card.add_row(0, "状态", self.napcat_status_lbl)

        self.qq_lbl = QLabel("未登录")
        self.qq_lbl.setObjectName("value")
        self.napcat_card.add_row(1, "QQ 账号", self.qq_lbl)

        self.napcat_link = link_button("http://127.0.0.1:6099")
        self.napcat_link.clicked.connect(
            lambda: self.open_url(f"http://127.0.0.1:{self.cfg['napcat_port']}")
        )
        self.napcat_card.add_row(2, "WebUI", self.napcat_link)

        token_row = QHBoxLayout()
        token_row.setSpacing(8)
        self.token_lbl = QLabel("—")
        self.token_lbl.setObjectName("value")
        self.token_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        token_row.addWidget(self.token_lbl)
        self.btn_token_toggle = QToolButton()
        self.btn_token_toggle.setText("显示")
        self.btn_token_toggle.clicked.connect(self.toggle_token)
        self.btn_token_copy = QToolButton()
        self.btn_token_copy.setText("复制")
        self.btn_token_copy.clicked.connect(self.copy_token)
        token_row.addWidget(self.btn_token_toggle)
        token_row.addWidget(self.btn_token_copy)
        token_row.addStretch(1)
        token_box = QWidget()
        token_box.setLayout(token_row)
        self.napcat_card.add_row(3, "Token", token_box)

        self.conn_lbl = QLabel("未连接")
        self.conn_lbl.setObjectName("value")
        self.napcat_card.add_row(4, "OneBot 连接", self.conn_lbl)

        self.btn_napcat_start = QPushButton("启动")
        self.btn_napcat_start.setObjectName("primary")
        self.btn_napcat_start.clicked.connect(self.start_napcat)
        self.btn_napcat_stop = QPushButton("停止")
        self.btn_napcat_stop.setObjectName("danger")
        self.btn_napcat_stop.clicked.connect(self.stop_napcat)
        self.btn_napcat_open = QPushButton("打开 WebUI")
        self.btn_napcat_open.clicked.connect(
            lambda: self.open_url(f"http://127.0.0.1:{self.cfg['napcat_port']}")
        )
        for b in (self.btn_napcat_start, self.btn_napcat_stop, self.btn_napcat_open):
            self.napcat_card.buttons.addWidget(b)
        cards.addWidget(self.napcat_card, 1)

        layout.addLayout(cards)

        quick = QHBoxLayout()
        quick.setSpacing(10)
        self.btn_start_all = QPushButton("▶  一键启动全部")
        self.btn_start_all.setObjectName("primary")
        self.btn_start_all.setMinimumHeight(38)
        self.btn_start_all.clicked.connect(self.start_all)
        self.btn_stop_all = QPushButton("■  一键停止全部")
        self.btn_stop_all.setObjectName("danger")
        self.btn_stop_all.setMinimumHeight(38)
        self.btn_stop_all.clicked.connect(self.stop_all)
        quick.addWidget(self.btn_start_all)
        quick.addWidget(self.btn_stop_all)
        quick.addStretch(1)
        self.hint_lbl = QLabel("提示：NapCat 启动会拉起 QQ 登录窗口，需管理员权限。")
        self.hint_lbl.setObjectName("muted")
        quick.addWidget(self.hint_lbl)
        layout.addLayout(quick)

        log_head = QHBoxLayout()
        log_title = QLabel("实时日志")
        log_title.setObjectName("cardTitle")
        log_head.addWidget(log_title)
        log_head.addStretch(1)
        auto_lbl = QLabel("自动滚动")
        auto_lbl.setObjectName("muted")
        log_head.addWidget(auto_lbl)
        self.auto_scroll = QCheckBox()
        self.auto_scroll.setChecked(True)
        log_head.addWidget(self.auto_scroll)
        clear_log_btn = QPushButton("清空显示")
        clear_log_btn.setObjectName("ghost")
        clear_log_btn.clicked.connect(self.clear_logs)
        log_head.addWidget(clear_log_btn)
        layout.addLayout(log_head)

        self.log_tabs = QTabWidget()
        self.astrbot_log_view = self._make_log_view()
        self.napcat_log_view = self._make_log_view()
        self.log_tabs.addTab(self.astrbot_log_view, "AstrBot")
        self.log_tabs.addTab(self.napcat_log_view, "NapCat")
        layout.addWidget(self.log_tabs, 1)

        return page

    def _make_log_view(self) -> QPlainTextEdit:
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setMaximumBlockCount(3000)
        view.setPlaceholderText("暂无日志。通过本控制台启动服务后，日志会显示在这里。")
        view.setStyleSheet(
            'font-family: "Cascadia Mono","Consolas","Microsoft YaHei UI"; font-size: 12px;'
        )
        return view

    def refresh_status(self):
        st = self.manager.status()
        self._st = st

        astrbot_up = st["astrbot_up"]
        napcat_up = st["napcat_up"]
        qq_running = st["qq_running"]
        conn = st["onebot_connected"]

        # AstrBot
        if astrbot_up:
            self.astrbot_card.set_status("on", "运行中")
            self.astrbot_status_lbl.setText(f"运行中 · PID {st['astrbot_pid'] or '—'}")
            self.btn_astrbot_start.setEnabled(False)
            self.btn_astrbot_stop.setEnabled(True)
        elif self.manager.procs["astrbot"] and self.manager.procs["astrbot"].poll() is None:
            self.astrbot_card.set_status("starting", "启动中…")
            self.astrbot_status_lbl.setText("启动中，等待端口就绪…")
            self.btn_astrbot_start.setEnabled(False)
            self.btn_astrbot_stop.setEnabled(True)
        else:
            self.astrbot_card.set_status("off", "已停止")
            self.astrbot_status_lbl.setText("未运行")
            self.btn_astrbot_start.setEnabled(True)
            self.btn_astrbot_stop.setEnabled(False)

        # NapCat
        if napcat_up:
            self.napcat_card.set_status("on", "运行中")
            self.napcat_status_lbl.setText(f"运行中 · PID {st['napcat_pid'] or '—'}")
            self.btn_napcat_start.setEnabled(False)
            self.btn_napcat_stop.setEnabled(True)
        elif qq_running:
            self.napcat_card.set_status("starting", "QQ 启动中…")
            self.napcat_status_lbl.setText("QQ 已启动，等待 NapCat 服务…")
            self.btn_napcat_start.setEnabled(False)
            self.btn_napcat_stop.setEnabled(True)
        else:
            self.napcat_card.set_status("off", "已停止")
            self.napcat_status_lbl.setText("未运行")
            self.btn_napcat_start.setEnabled(True)
            self.btn_napcat_stop.setEnabled(False)

        self.qq_lbl.setText(st["qq"] or ("QQ 运行中" if qq_running else "未登录"))
        if conn:
            self.conn_lbl.setText("已连接 AstrBot")
            self.conn_lbl.setStyleSheet("color:#4ade80;")
        elif napcat_up:
            self.conn_lbl.setText("等待连接…")
            self.conn_lbl.setStyleSheet("color:#f59e0b;")
        else:
            self.conn_lbl.setText("未连接")
            self.conn_lbl.setStyleSheet("color:#94a3b8;")

        token = st["token"] or "—"
        self._token = st["token"]
        self.token_lbl.setText(token if self.token_visible else self._mask(token))

        # 运行时长
        self.astrbot_runtime.setText(self._runtime_text(st["astrbot_started_at"], astrbot_up))
        # 地址同步设置（只影响显示）
        self.astrbot_link.setText(f"http://localhost:{self.cfg['dashboard_port']}")
        self.napcat_link.setText(f"http://127.0.0.1:{self.cfg['napcat_port']}")

        # 顶部汇总
        running = int(astrbot_up) + int(napcat_up)
        if running == 2 and conn:
            self.header_pill.setText("● 全部运行中 · 连接正常")
            self.header_pill.setStyleSheet(
                "background:#0f2e1d; color:#4ade80; border:1px solid #14532d;"
                "border-radius:13px; padding:5px 14px; font-weight:600;"
            )
        elif running == 2:
            self.header_pill.setText("● 服务运行中 · 等待连接")
            self.header_pill.setStyleSheet(
                "background:#2d2410; color:#fbbf24; border:1px solid #713f12;"
                "border-radius:13px; padding:5px 14px; font-weight:600;"
            )
        elif running == 1:
            self.header_pill.setText("● 部分运行")
            self.header_pill.setStyleSheet(
                "background:#2d2410; color:#fbbf24; border:1px solid #713f12;"
                "border-radius:13px; padding:5px 14px; font-weight:600;"
            )
        else:
            self.header_pill.setText("● 全部已停止")
            self.header_pill.setStyleSheet(
                "background:#151d31; color:#94a3b8; border:1px solid #24304a;"
                "border-radius:13px; padding:5px 14px; font-weight:600;"
            )

        self.btn_start_all.setEnabled(running < 2)
        self.btn_stop_all.setEnabled(running > 0 or qq_running)
        if self.tray:
            self.tray.setToolTip(
                f"{APP_NAME}\nAstrBot：{'运行中' if astrbot_up else '已停止'}\n"
                f"NapCat：{'运行中' if napcat_up else '已停止'}\n"
                f"OneBot：{'已连接' if conn else '未连接'}"
            )

    def _runtime_text(self, started_at, up: bool) -> str:
        if not up or not started_at:
            return "—"
        secs = int(time.time() - started_at)
        return f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"

    @staticmethod

    def _mask(token: str) -> str:
        if not token or token == "—":
            return token
        return token[:4] + "•" * max(4, len(token) - 4)

    # ---------------- 日志 ----------------

    def refresh_logs(self):
        self._update_log(self.astrbot_log_view, tail_text(self.astrbot_log))
        napcat_file = self.manager.napcat_log_file()
        napcat_text = tail_text(napcat_file) if napcat_file else ""
        if not napcat_text:
            napcat_text = tail_text(LOG_DIR / "napcat_console.log")
        self._update_log(self.napcat_log_view, napcat_text)

    def _update_log(self, view: QPlainTextEdit, text: str):
        if not text:
            return
        if self.last_logs.get(id(view)) == text:
            return
        self.last_logs[id(view)] = text
        bar = view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        view.setPlainText(text)
        if self.auto_scroll.isChecked() or at_bottom:
            bar.setValue(bar.maximum())

    def clear_logs(self):
        self.astrbot_log_view.clear()
        self.napcat_log_view.clear()
        self.last_logs.clear()

    # ---------------- 操作 ----------------

    def start_astrbot(self):
        ok, msg = self.manager.start_astrbot()
        self._toast(msg, ok)
        self.refresh_status()

    def start_napcat(self):
        if not is_admin():
            QMessageBox.warning(
                self,
                "需要管理员权限",
                "启动 NapCat 需要管理员权限，请使用「以管理员身份重启」后重试。",
            )
            return
        ok, msg = self.manager.start_napcat()
        self._toast(msg, ok)
        self.refresh_status()

    def stop_astrbot(self):
        ok, msg = self.manager.stop_astrbot()
        self._toast(msg, ok)
        self.refresh_status()

    def stop_napcat(self):
        if (
            QMessageBox.question(
                self,
                "停止 NapCat",
                "停止 NapCat 会关闭 QQ 登录进程。确定继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        ok, msg = self.manager.stop_napcat()
        self._toast(msg, ok)
        self.refresh_status()

    def start_all(self):
        if not is_admin():
            self._toast("提示：NapCat 需要管理员权限，请先以管理员身份重启", False)
        ok, msg = self.manager.start_all()
        self._toast(msg, ok)
        QTimer.singleShot(600, self.refresh_status)

    def stop_all(self):
        if (
            QMessageBox.question(
                self,
                "停止全部服务",
                "将停止 AstrBot 和 NapCat（包括 QQ），确定？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        ok, msg = self.manager.stop_all()
        self._toast(msg, ok)
        self.refresh_status()

    def toggle_token(self):
        self.token_visible = not self.token_visible
        self.btn_token_toggle.setText("隐藏" if self.token_visible else "显示")
        self.refresh_status()

    def copy_token(self):
        token = getattr(self, "_token", "")
        if token:
            QApplication.clipboard().setText(token)
            self._toast("Token 已复制到剪贴板")
        else:
            self._toast("暂未找到 Token，请先启动一次 NapCat", False)

    def open_url(self, url: str):
        QDesktopServices.openUrl(QUrl(url))

    # ---------------- 设置 ----------------
