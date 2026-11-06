"""控制台页：服务卡片、状态、日志与启停操作。"""
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QSystemTrayIcon,
    QApplication,
    QSizePolicy,
    QSplitter,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QTabWidget,
    QCheckBox,
    QMessageBox,
    QToolButton,
)

from snowbot.core.config import is_admin
from snowbot.core.paths import APP_NAME, LOG_DIR
from snowbot.core.services import tail_text
from snowbot.ui.theme import MUTED_COLOR, OK_COLOR, PILL_IDLE, PILL_OK, PILL_WARN, WARN_COLOR, pill_style
from snowbot.ui.widgets import Card, link_button, scroll_page

# 协议端卡片身份：(图标字母, 主色)
QQ_CARD_BRANDS = {
    "snowluma": ("S", "#0ea5e9"),
    "napcat": ("N", "#10b981"),
}


class ConsoleMixin:
    def _build_console_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(14)

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(12)

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

        self.ob_lbl = QLabel(f"ws://127.0.0.1:{self.cfg['onebot_port']}/ws")
        self.ob_lbl.setObjectName("value")
        self.ob_lbl.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.ob_lbl.setToolTip(f"ws://127.0.0.1:{self.cfg['onebot_port']}/ws")
        self.astrbot_card.add_row(2, "OneBot", self.ob_lbl)

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

        # NapCat / SnowLuma 卡片
        snowluma = str(self.cfg.get("qq_backend") or "napcat") == "snowluma"
        letter, accent = QQ_CARD_BRANDS["snowluma" if snowluma else "napcat"]
        qq_name = "SnowLuma" if snowluma else "NapCat"
        self.napcat_card = Card(accent, letter, qq_name, "QQ 协议端（OneBot v11）")
        self.napcat_status_lbl = QLabel("—")
        self.napcat_status_lbl.setObjectName("value")
        self.napcat_card.add_row(0, "状态", self.napcat_status_lbl)

        self.qq_lbl = QLabel("未登录")
        self.qq_lbl.setObjectName("value")
        self.napcat_card.add_row(1, "QQ 账号", self.qq_lbl)

        self.napcat_link = link_button("http://127.0.0.1:6099")
        self.napcat_link.clicked.connect(self._open_qq_webui)
        self.napcat_card.add_row(2, "WebUI", self.napcat_link)

        token_row = QHBoxLayout()
        token_row.setSpacing(8)
        self.token_lbl = QLabel("—")
        self.token_lbl.setObjectName("value")
        self.token_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.token_lbl.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
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
        self.btn_napcat_open.clicked.connect(self._open_qq_webui)
        for b in (self.btn_napcat_start, self.btn_napcat_stop, self.btn_napcat_open):
            self.napcat_card.buttons.addWidget(b)
        cards.addWidget(self.napcat_card, 1)

        cards_host = QWidget()
        cards_host_layout = QVBoxLayout(cards_host)
        cards_host_layout.setContentsMargins(0, 0, 0, 0)
        cards_host_layout.addLayout(cards)
        cards_host_layout.addStretch(1)
        top_layout.addWidget(scroll_page(cards_host, 150), 1)

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
        self.hint_lbl = QLabel("提示：启动 QQ 协议端会拉起 QQ 登录窗口，需管理员权限。")
        self.hint_lbl.setObjectName("muted")
        self.hint_lbl.setWordWrap(True)
        quick.addWidget(self.hint_lbl, 1)
        top_layout.addLayout(quick)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(top)
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(8)
        bottom.setMinimumHeight(200)

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
        bottom_layout.addLayout(log_head)

        self.log_tabs = QTabWidget()
        self.log_tabs.setMinimumHeight(180)
        self.log_tabs.tabBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.astrbot_log_view = self._make_log_view()
        self.napcat_log_view = self._make_log_view()
        self.log_tabs.addTab(self.astrbot_log_view, "AstrBot")
        self.log_tabs.addTab(self.napcat_log_view, qq_name)
        bottom_layout.addWidget(self.log_tabs, 1)
        splitter.addWidget(bottom)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([360, 210])
        layout.addWidget(splitter, 1)

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

        astrbot_up = st["astrbot_up"]
        napcat_up = st["napcat_up"]
        qq_running = st["qq_running"]
        conn = st["onebot_connected"]
        backend = st.get("qq_backend", "napcat")
        backend_label = st.get("qq_label", "NapCat")
        webui = st.get("qq_webui") or f"http://127.0.0.1:{self.cfg['napcat_port']}"
        self.napcat_card.title_label.setText(backend_label)
        self.napcat_card.sub_label.setText("QQ 协议端（OneBot v11）")
        letter, accent = QQ_CARD_BRANDS.get(backend, QQ_CARD_BRANDS["napcat"])
        self.napcat_card.set_icon(letter, accent)

        self._check_qq_health(st, conn, napcat_up)

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

        # QQ 协议端（NapCat / SnowLuma）
        if napcat_up:
            self.napcat_card.set_status("on", "运行中")
            self.napcat_status_lbl.setText(f"运行中 · PID {st['napcat_pid'] or '—'}")
            self.btn_napcat_start.setEnabled(False)
            self.btn_napcat_stop.setEnabled(True)
        elif qq_running:
            self.napcat_card.set_status("starting", "QQ 启动中…")
            self.napcat_status_lbl.setText(f"QQ 已启动，等待 {backend_label} 服务…")
            self.btn_napcat_start.setEnabled(False)
            self.btn_napcat_stop.setEnabled(True)
        else:
            self.napcat_card.set_status("off", "已停止")
            self.napcat_status_lbl.setText("未运行")
            self.btn_napcat_start.setEnabled(True)
            self.btn_napcat_stop.setEnabled(False)

        self.qq_lbl.setText(st["qq"] or ("QQ 运行中" if qq_running else "未登录"))
        if backend == "snowluma":
            if qq_running and not conn:
                self.qq_lbl.setText(f"等待扫码登录（{backend_label} WebUI）")
        elif health_qr := getattr(self, "health", None):
            try:
                if qq_running and health_qr.qrcode_waiting():
                    self.qq_lbl.setText("等待扫码登录（NapCat WebUI 或 cache\\qrcode.png）")
            except Exception:
                pass
        if conn:
            self.conn_lbl.setText("已连接 AstrBot")
            self.conn_lbl.setStyleSheet(f"color:{OK_COLOR};")
        elif napcat_up:
            self.conn_lbl.setText("等待连接…")
            self.conn_lbl.setStyleSheet(f"color:{WARN_COLOR};")
        else:
            self.conn_lbl.setText("未连接")
            self.conn_lbl.setStyleSheet(f"color:{MUTED_COLOR};")

        token = st["token"] or "—"
        self._token = st["token"]
        self.token_lbl.setText(token if self.token_visible else self._mask(token))
        is_napcat = backend == "napcat"
        self.btn_token_toggle.setEnabled(is_napcat and bool(st["token"]))
        self.btn_token_copy.setEnabled(is_napcat and bool(st["token"]))
        # 运行时长
        self.astrbot_runtime.setText(self._runtime_text(st["astrbot_started_at"], astrbot_up))
        # 地址同步设置（只影响显示）
        self.astrbot_link.setText(f"http://localhost:{self.cfg['dashboard_port']}")
        self.napcat_link.setText(webui)
        self.ob_lbl.setText(f"ws://127.0.0.1:{self.cfg['onebot_port']}/ws")

        # 顶部汇总
        running = int(astrbot_up) + int(napcat_up)
        if running == 2 and conn:
            self.header_pill.setText("● 全部运行中 · 连接正常")
            self.header_pill.setStyleSheet(pill_style(PILL_OK))
        elif running == 2:
            self.header_pill.setText("● 服务运行中 · 等待连接")
            self.header_pill.setStyleSheet(pill_style(PILL_WARN))
        elif running == 1:
            self.header_pill.setText("● 部分运行")
            self.header_pill.setStyleSheet(pill_style(PILL_WARN))
        else:
            self.header_pill.setText("● 全部已停止")
            self.header_pill.setStyleSheet(pill_style(PILL_IDLE))

        self.btn_start_all.setEnabled(running < 2)
        self.btn_stop_all.setEnabled(running > 0 or qq_running)
        if self.tray:
            self.tray.setToolTip(
                f"{APP_NAME}\nAstrBot：{'运行中' if astrbot_up else '已停止'}\n"
                f"NapCat：{'运行中' if napcat_up else '已停止'}\n"
                f"OneBot：{'已连接' if conn else '未连接'}"
            )

    def _check_qq_health(self, st: dict, conn: bool, napcat_up: bool) -> None:
        """QQ 掉线监控：进程还在但连接断了才告警，并记录事件时间线。"""
        health = getattr(self, "health", None)
        if health is None:
            return
        # NapCat / SnowLuma 在跑，或 QQ 进程在跑，都算"应当在线"
        process_alive = bool(napcat_up or st.get("qq_running"))
        backend = st.get("qq_backend", "napcat")
        backend_label = st.get("qq_label", "NapCat")
        events = health.update(
            connected=conn,
            napcat_running=process_alive,
            qq_version=self._qq_version(),
            offline_marker=health.napcat_offline_marker() if backend == "napcat" else None,
        )
        for event in events:
            etype = event.get("type")
            detail = str(event.get("detail") or "")
            if etype == "offline":
                count = health.offline_count_today()
                self._notify(
                    f"QQ 掉线{('（今日第 %d 次）' % count) if count else ''}",
                    detail + f"\n需要到 {backend_label} WebUI 重新扫码登录。",
                    warning=True,
                )
            elif etype == "online":
                self._notify("QQ 已恢复在线", detail, warning=False)
            elif etype == "version_change":
                self._notify(
                    "QQ 版本变化（可能自动更新）",
                    detail + f"\nQQ 更新后 {backend_label} 可能需要同步升级，否则容易掉线。",
                    warning=True,
                )
        # 状态行显示今日掉线次数
        last = health.last_offline
        if last and hasattr(self, "conn_lbl"):
            count = health.offline_count_today()
            if count and not conn:
                stamp = time.strftime("%H:%M", time.localtime(float(last.get("time", 0))))
                self.conn_lbl.setText(f"QQ 已离线（今日 {count} 次，上次 {stamp}）")

    def _qq_version(self) -> str:
        """读 QQ 主程序版本号；读不到返回空串。"""
        try:
            exe = Path(str(self.cfg.get("qq_exe") or r"C:\Program Files\Tencent\QQNT\QQ.exe"))
            if not exe.exists():
                return ""
            return str(exe.stat().st_size)
        except Exception:
            return ""

    def _notify(self, title: str, body: str, warning: bool = True) -> None:
        """托盘气泡 + 状态提示（窗口隐藏时也能看到）。"""
        try:
            if self.tray:
                icon = (
                    QSystemTrayIcon.MessageIcon.Warning
                    if warning
                    else QSystemTrayIcon.MessageIcon.Information
                )
                self.tray.showMessage(f"{APP_NAME} · {title}", body, icon, 8000)
        except Exception:
            pass
        try:
            toast = getattr(self, "_toast", None)
            if callable(toast):
                toast(f"{title}：{body.splitlines()[0]}", not warning)
        except Exception:
            pass

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
        snowluma = self.manager.qq_backend() == "snowluma"
        self.log_tabs.setTabText(1, "SnowLuma" if snowluma else "NapCat")
        if snowluma:
            qq_text = tail_text(self.manager.snowluma_log_file())
        else:
            napcat_file = self.manager.napcat_log_file()
            qq_text = tail_text(napcat_file) if napcat_file else ""
            if not qq_text:
                qq_text = tail_text(LOG_DIR / "napcat_console.log")
        self._update_log(self.napcat_log_view, qq_text)

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
                f"启动 {self.manager.qq_backend_label()} 需要管理员权限，"
                "请使用「以管理员身份重启」后重试。",
            )
            return
        ok, msg = self.manager.start_qq()
        self._toast(msg, ok)
        self.refresh_status()

    def stop_astrbot(self):
        ok, msg = self.manager.stop_astrbot()
        self._toast(msg, ok)
        self.refresh_status()

    def stop_napcat(self):
        label = self.manager.qq_backend_label()
        if (
            QMessageBox.question(
                self,
                f"停止 {label}",
                f"停止 {label} 会关闭 QQ 登录进程。确定继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        ok, msg = self.manager.stop_qq()
        self._toast(msg, ok)
        self.refresh_status()

    def _open_qq_webui(self):
        st = self.manager.status()
        url = st.get("qq_webui") or f"http://127.0.0.1:{self.cfg['napcat_port']}"
        self.open_url(url)

    def start_all(self):
        if not is_admin():
            self._toast(
                f"提示：{self.manager.qq_backend_label()} 需要管理员权限，请先以管理员身份重启",
                False,
            )
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
