import os
import sys
import json
import time
import shutil
import socket
import ctypes
import subprocess
import threading
from pathlib import Path
from datetime import datetime

import psutil
from PySide6.QtCore import Qt, QTimer, QUrl, QSize
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QBrush, QFont, QLinearGradient,
    QAction, QDesktopServices,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QPushButton, QGridLayout, QPlainTextEdit, QTabWidget, QLineEdit,
    QCheckBox, QFileDialog, QMessageBox, QSystemTrayIcon, QMenu, QScrollArea,
    QSpinBox, QGroupBox, QFormLayout, QSizePolicy, QSpacerItem, QToolButton,
)

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "launcher_config.json"
LOG_DIR = APP_DIR / "logs"
APP_NAME = "QQ 机器人控制台"
APP_VERSION = "1.0.0"
AUTOSTART_TASK = "QQBotLauncher"

DEFAULT_CONFIG = {
    "astrbot_dir": r"C:\Users\Administrator\AstrBot",
    "napcat_dir": r"C:\NapCat\NapCat.Shell",
    "python_exe": r"C:\Users\Administrator\AstrBot\.venv\Scripts\python.exe",
    "dashboard_port": 6185,
    "onebot_port": 6199,
    "napcat_port": 6099,
    "close_to_tray": True,
    "start_minimized": False,
    "autostart": False,
    "autostart_services": False,
}


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        if CONFIG_PATH.exists():
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except Exception:
        pass
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def launcher_command() -> list:
    """返回启动控制台自身的命令（兼容 PyInstaller 冻结后的 exe）。"""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    return [str(pythonw), str(APP_DIR / "app.py")]


def list_tcp_connections():
    try:
        return psutil.net_connections(kind="tcp")
    except Exception:
        return []


def port_listening(port: int, conns=None) -> bool:
    conns = conns if conns is not None else list_tcp_connections()
    for c in conns:
        try:
            if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port:
                return True
        except Exception:
            continue
    if conns:
        return False
    # 后备方案：psutil 不可用时直接尝试连接
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def listening_pid(port: int, conns=None):
    conns = conns if conns is not None else list_tcp_connections()
    for c in conns:
        try:
            if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port:
                return c.pid
        except Exception:
            continue
    return None


def onebot_connected(port: int, conns=None) -> bool:
    conns = conns if conns is not None else list_tcp_connections()
    for c in conns:
        try:
            if c.status != psutil.CONN_ESTABLISHED:
                continue
            if (c.laddr and c.laddr.port == port) or (c.raddr and c.raddr.port == port):
                return True
        except Exception:
            continue
    return False


def qq_processes():
    result = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if (p.info["name"] or "").lower() == "qq.exe":
                result.append(p)
        except Exception:
            continue
    return result


def kill_tree(pid: int, timeout: float = 6.0) -> None:
    if not pid:
        return
    try:
        proc = psutil.Process(pid)
        procs = proc.children(recursive=True)
        procs.append(proc)
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        _, alive = psutil.wait_procs(procs, timeout=timeout)
        for p in alive:
            try:
                p.kill()
            except Exception:
                pass
    except psutil.NoSuchProcess:
        pass
    except Exception:
        pass


def tail_text(path: Path, max_bytes: int = 80000, max_lines: int = 700) -> str:
    try:
        if not path or not path.exists():
            return ""
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read()
        text = data.decode("utf-8", "replace")
        return "\n".join(text.splitlines()[-max_lines:])
    except Exception:
        return ""


class ServiceManager:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.procs = {"astrbot": None, "napcat": None}
        self.started_at = {"astrbot": None, "napcat": None}
        self.log_files = {}
        LOG_DIR.mkdir(exist_ok=True)

    # ---------- 状态 ----------
    def status(self) -> dict:
        conns = list_tcp_connections()
        dash = int(self.cfg["dashboard_port"])
        ob = int(self.cfg["onebot_port"])
        nc = int(self.cfg["napcat_port"])

        astrbot_up = port_listening(dash, conns)
        napcat_up = port_listening(nc, conns)
        qqs = qq_processes()

        return {
            "astrbot_up": astrbot_up,
            "astrbot_pid": listening_pid(dash, conns),
            "napcat_up": napcat_up,
            "napcat_pid": listening_pid(nc, conns),
            "qq_running": bool(qqs),
            "qq_pids": [p.pid for p in qqs],
            "onebot_connected": onebot_connected(ob, conns),
            "token": self.napcat_token(),
            "qq": self.napcat_account(),
            "astrbot_started_at": self.started_at.get("astrbot"),
            "napcat_started_at": self.started_at.get("napcat"),
        }

    # ---------- 信息读取 ----------
    def napcat_token(self) -> str:
        p = Path(self.cfg["napcat_dir"]) / "config" / "webui.json"
        try:
            return json.loads(p.read_text(encoding="utf-8")).get("token", "")
        except Exception:
            return ""

    def napcat_account(self) -> str:
        cfgdir = Path(self.cfg["napcat_dir"]) / "config"
        try:
            for f in cfgdir.glob("onebot11_*.json"):
                num = f.stem.replace("onebot11_", "")
                if num.isdigit():
                    return num
        except Exception:
            pass
        return ""

    def napcat_log_file(self):
        logs = list((Path(self.cfg["napcat_dir"]) / "logs").glob("*.log"))
        if not logs:
            return None
        return max(logs, key=lambda p: p.stat().st_mtime)

    # ---------- 启动 ----------
    def start_astrbot(self):
        cfg = self.cfg
        if port_listening(int(cfg["dashboard_port"])):
            return False, "AstrBot 已在运行"
        py = Path(cfg["python_exe"])
        d = Path(cfg["astrbot_dir"])
        if not py.exists():
            return False, f"Python 解释器不存在：{py}"
        if not (d / "main.py").exists():
            return False, f"AstrBot 目录无效：{d}"

        LOG_DIR.mkdir(exist_ok=True)
        log_path = LOG_DIR / "astrbot.log"
        log_f = open(log_path, "ab", buffering=0)
        log_f.write(
            f"\n===== {now_str()} 启动 AstrBot =====\n".encode("utf-8")
        )
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        try:
            p = subprocess.Popen(
                [str(py), "main.py"],
                cwd=str(d),
                stdout=log_f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW
                | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        except Exception as e:
            log_f.close()
            return False, f"启动失败：{e}"
        finally:
            try:
                log_f.close()
            except Exception:
                pass

        self.procs["astrbot"] = p
        self.started_at["astrbot"] = time.time()
        self.log_files["astrbot"] = log_path
        return True, "AstrBot 启动中…"

    def _prepare_napcat_file_log(self):
        cfgdir = Path(self.cfg["napcat_dir"]) / "config"
        for name in ["napcat.json", *[f"napcat_{n}.json" for n in self._napcat_uins()]]:
            p = cfgdir / name
            if not p.exists():
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                data["fileLog"] = True
                data["consoleLog"] = True
                p.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception:
                pass

    def _napcat_uins(self):
        cfgdir = Path(self.cfg["napcat_dir"]) / "config"
        uins = []
        try:
            for f in cfgdir.glob("napcat_*.json"):
                num = f.stem.replace("napcat_", "")
                if num.isdigit() and not f.stem.startswith("napcat_protocol"):
                    uins.append(num)
        except Exception:
            pass
        return uins

    def start_napcat(self):
        cfg = self.cfg
        if port_listening(int(cfg["napcat_port"])) or qq_processes():
            return False, "NapCat / QQ 已在运行"
        d = Path(cfg["napcat_dir"])
        if not (d / "launcher.bat").exists():
            return False, f"NapCat 目录无效：{d}"

        self._prepare_napcat_file_log()
        LOG_DIR.mkdir(exist_ok=True)
        log_path = LOG_DIR / "napcat_console.log"
        log_f = open(log_path, "ab", buffering=0)
        log_f.write(f"\n===== {now_str()} 启动 NapCat =====\n".encode("utf-8"))
        try:
            p = subprocess.Popen(
                ["cmd", "/c", "launcher.bat"],
                cwd=str(d),
                stdout=log_f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as e:
            log_f.close()
            return False, f"启动失败：{e}"
        finally:
            try:
                log_f.close()
            except Exception:
                pass

        self.procs["napcat"] = p
        self.started_at["napcat"] = time.time()
        return True, "NapCat 启动中，QQ 登录窗口即将出现…"

    # ---------- 停止 ----------
    def stop_astrbot(self):
        pid = listening_pid(int(self.cfg["dashboard_port"]))
        p = self.procs.get("astrbot")
        if not pid and p and p.poll() is None:
            pid = p.pid
        if not pid:
            return False, "AstrBot 未在运行"
        kill_tree(int(pid))
        self.started_at["astrbot"] = None
        return True, "AstrBot 已停止"

    def stop_napcat(self):
        stopped = False
        for p in qq_processes():
            try:
                p.kill()
                stopped = True
            except Exception:
                pass
        # 关闭可能残留的引导进程
        for p in psutil.process_iter(["pid", "name"]):
            try:
                if (p.info["name"] or "").lower() == "napcatwinbootmain.exe":
                    p.kill()
                    stopped = True
            except Exception:
                continue
        pid = listening_pid(int(self.cfg["napcat_port"]))
        if pid:
            kill_tree(int(pid))
            stopped = True
        p = self.procs.get("napcat")
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
            stopped = True
        self.started_at["napcat"] = None
        return (True, "NapCat / QQ 已停止") if stopped else (False, "NapCat / QQ 未在运行")

    def start_all(self):
        msgs = []
        ok1, m1 = self.start_astrbot()
        msgs.append(m1)
        ok2, m2 = self.start_napcat()
        msgs.append(m2)
        return ok1 or ok2, "；".join(msgs)

    def stop_all(self):
        msgs = []
        ok1, m1 = self.stop_astrbot()
        msgs.append(m1)
        ok2, m2 = self.stop_napcat()
        msgs.append(m2)
        return ok1 or ok2, "；".join(msgs)


def make_app_icon() -> QIcon:
    pm = QPixmap(128, 128)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, 128, 128)
    grad.setColorAt(0, QColor("#3b82f6"))
    grad.setColorAt(1, QColor("#8b5cf6"))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(8, 8, 112, 112, 30, 30)
    p.setPen(QColor("white"))
    p.setFont(QFont("Segoe UI", 58, QFont.Weight.Bold))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "Q")
    p.end()
    return QIcon(pm)


class Card(QFrame):
    def __init__(self, accent: str, letter: str, title: str, subtitle: str):
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(12)
        icon = QLabel(letter)
        icon.setFixedSize(44, 44)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {accent}, stop:1 #8b5cf6);"
            "border-radius: 12px; color: white; font-size: 21px; font-weight: 700;"
        )
        head.addWidget(icon)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
        self.sub_label = QLabel(subtitle)
        self.sub_label.setObjectName("muted")
        titles.addWidget(self.title_label)
        titles.addWidget(self.sub_label)
        head.addLayout(titles)
        head.addStretch(1)

        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet("color:#64748b; font-size: 14px;")
        self.status_text = QLabel("已停止")
        self.status_text.setObjectName("muted")
        head.addWidget(self.status_dot)
        head.addWidget(self.status_text)
        layout.addLayout(head)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(9)
        layout.addLayout(self.grid)

        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(8)
        self.buttons.addStretch(1)
        layout.addLayout(self.buttons)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def add_row(self, row: int, name: str, widget: QWidget):
        label = QLabel(name)
        label.setObjectName("muted")
        self.grid.addWidget(label, row, 0, Qt.AlignmentFlag.AlignTop)
        self.grid.addWidget(widget, row, 1)
        self.grid.setColumnStretch(1, 1)

    def set_status(self, kind: str, text: str):
        colors = {
            "on": "#22c55e",
            "starting": "#f59e0b",
            "off": "#64748b",
            "error": "#ef4444",
        }
        self.status_dot.setStyleSheet(
            f"color:{colors.get(kind, '#64748b')}; font-size: 14px;"
        )
        self.status_text.setText(text)
        self.status_text.setObjectName("value" if kind == "on" else "muted")
        self.status_text.style().unpolish(self.status_text)
        self.status_text.style().polish(self.status_text)


def link_button(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("link")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


class LauncherWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        if not CONFIG_PATH.exists():
            save_config(self.cfg)
        self.manager = ServiceManager(self.cfg)
        self.tray = None
        self.quitting = False
        self.last_logs = {}
        self.token_visible = False
        self.astrbot_log = LOG_DIR / "astrbot.log"

        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setWindowIcon(make_app_icon())
        self.resize(1060, 760)
        self.setMinimumSize(920, 660)

        self._build_ui()
        self._build_tray()

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start(2000)

        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self.refresh_logs)
        self.log_timer.start(1200)

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
        sub = QLabel("AstrBot + NapCat 统一启停 / 状态监控 / 一键挂起")
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

    def _build_settings_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 8, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(4, 4, 8, 8)
        layout.setSpacing(16)

        paths = QGroupBox("路径设置")
        form = QFormLayout(paths)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)
        self.dir_astrbot = QLineEdit(self.cfg["astrbot_dir"])
        self.dir_napcat = QLineEdit(self.cfg["napcat_dir"])
        self.python_exe = QLineEdit(self.cfg["python_exe"])
        form.addRow("AstrBot 目录", self._path_row(self.dir_astrbot, dir_mode=True))
        form.addRow("NapCat 目录", self._path_row(self.dir_napcat, dir_mode=True))
        form.addRow("Python 解释器", self._path_row(self.python_exe, dir_mode=False))
        layout.addWidget(paths)

        ports = QGroupBox("端口设置")
        pform = QFormLayout(ports)
        pform.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        pform.setSpacing(10)
        self.port_dash = QSpinBox()
        self.port_ob = QSpinBox()
        self.port_napcat = QSpinBox()
        for sp in (self.port_dash, self.port_ob, self.port_napcat):
            sp.setRange(1, 65535)
        self.port_dash.setValue(int(self.cfg["dashboard_port"]))
        self.port_ob.setValue(int(self.cfg["onebot_port"]))
        self.port_napcat.setValue(int(self.cfg["napcat_port"]))
        pform.addRow("AstrBot 面板端口", self.port_dash)
        pform.addRow("OneBot WS 端口", self.port_ob)
        pform.addRow("NapCat WebUI 端口", self.port_napcat)
        port_hint = QLabel(
            "这里的端口用于状态检测与跳转。若要与实际服务一致，请同步修改 AstrBot 的 "
            "cmd_config.json 和 NapCat 的网络配置。"
        )
        port_hint.setWordWrap(True)
        port_hint.setObjectName("muted")
        pform.addRow("", port_hint)
        layout.addWidget(ports)

        behavior = QGroupBox("行为设置")
        bform = QVBoxLayout(behavior)
        self.chk_close_tray = QCheckBox("关闭窗口时最小化到系统托盘（后台挂起）")
        self.chk_close_tray.setChecked(bool(self.cfg["close_to_tray"]))
        self.chk_start_min = QCheckBox("启动控制台时最小化到托盘")
        self.chk_start_min.setChecked(bool(self.cfg["start_minimized"]))
        self.chk_autostart = QCheckBox("开机自动启动控制台（计划任务，免 UAC 弹窗）")
        self.chk_autostart.setChecked(self.autostart_enabled())
        self.chk_auto_services = QCheckBox("启动控制台后自动启动全部服务")
        self.chk_auto_services.setChecked(bool(self.cfg.get("autostart_services", False)))
        bform.addWidget(self.chk_close_tray)
        bform.addWidget(self.chk_start_min)
        bform.addWidget(self.chk_autostart)
        bform.addWidget(self.chk_auto_services)
        layout.addWidget(behavior)

        btns = QHBoxLayout()
        save_btn = QPushButton("保存设置")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self.save_settings)
        reload_btn = QPushButton("恢复默认")
        reload_btn.setObjectName("ghost")
        reload_btn.clicked.connect(self.reset_settings)
        btns.addWidget(save_btn)
        btns.addWidget(reload_btn)
        btns.addStretch(1)
        layout.addLayout(btns)
        layout.addStretch(1)

        scroll.setWidget(host)
        outer.addWidget(scroll)
        return page

    def _path_row(self, line: QLineEdit, dir_mode: bool) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        h.addWidget(line, 1)
        btn = QPushButton("浏览…")
        btn.setObjectName("ghost")

        def browse():
            if dir_mode:
                path = QFileDialog.getExistingDirectory(self, "选择目录", line.text())
            else:
                path, _ = QFileDialog.getOpenFileName(
                    self, "选择可执行文件", line.text(), "可执行文件 (*.exe)"
                )
            if path:
                line.setText(path)

        btn.clicked.connect(browse)
        h.addWidget(btn)
        return w

    def _build_about_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 12, 8, 8)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setStyleSheet(
            'font-family: "Microsoft YaHei UI"; font-size: 13px; color:#cbd5e1;'
            "background: #0a1020; border: 1px solid #1c2740; border-radius: 12px;"
        )
        text.setPlainText(
            f"""QQ 机器人控制台 v{APP_VERSION}

一、日常使用
  1. 点击「一键启动全部」：先启动 AstrBot（约 5~10 秒），随后拉起 NapCat 与 QQ。
  2. 首次或掉线时，在弹出的 QQ 窗口扫码登录；NapCat 会自动连接 AstrBot。
  3. 点击「打开面板」进入 AstrBot WebUI 配置大模型、插件等。
  4. 关闭窗口默认挂起到系统托盘，服务继续在后台运行。

二、地址与账号
  AstrBot WebUI   http://localhost:{self.cfg['dashboard_port']}
  AstrBot 账号    默认 astrbot / astrbot（建议登录后修改）
  NapCat WebUI    http://127.0.0.1:{self.cfg['napcat_port']}
  NapCat Token    自动读取 config/webui.json，可在控制台复制
  OneBot 地址     ws://127.0.0.1:{self.cfg['onebot_port']}/ws（NapCat 作为 WS 客户端连接）

三、后台与自启
  · 「后台挂起」或关闭窗口：隐藏到托盘，服务不中断。
  · 托盘菜单可启动/停止全部、恢复窗口、退出。
  · 设置页可开启开机自启（写入 Windows 计划任务，登录后自动运行且免 UAC）。
  · 还可开启「启动控制台后自动启动全部服务」，配合开机自启即可无人值守挂机。
  · 退出控制台不会自动停止服务；如需停止请用「停止全部」或托盘菜单。

四、常见问题
  · NapCat 启动失败：确认以管理员身份运行；检查 QQ 是否已安装。
  · 面板打不开：查看下方 AstrBot 日志是否报错，检查端口是否被占用。
  · 机器人不回复：AstrBot 中尚未配置大模型服务商，或未设为默认。
  · 日志：AstrBot → 本程序 logs/astrbot.log；NapCat → NapCat.Shell/logs/*.log

五、目录
  控制台  {APP_DIR}
  AstrBot {self.cfg['astrbot_dir']}
  NapCat  {self.cfg['napcat_dir']}
"""
        )
        layout.addWidget(text)
        return page

    # ---------------- 托盘 ----------------
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

    def quit_app(self):
        self.quitting = True
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
    def save_settings(self):
        self.cfg.update(
            {
                "astrbot_dir": self.dir_astrbot.text().strip(),
                "napcat_dir": self.dir_napcat.text().strip(),
                "python_exe": self.python_exe.text().strip(),
                "dashboard_port": self.port_dash.value(),
                "onebot_port": self.port_ob.value(),
                "napcat_port": self.port_napcat.value(),
                "close_to_tray": self.chk_close_tray.isChecked(),
                "start_minimized": self.chk_start_min.isChecked(),
                "autostart_services": self.chk_auto_services.isChecked(),
            }
        )
        want_autostart = self.chk_autostart.isChecked()
        if want_autostart and not self.autostart_enabled():
            ok, msg = self.set_autostart(True)
            if not ok:
                QMessageBox.warning(self, "设置开机自启失败", msg)
                self.chk_autostart.setChecked(False)
        elif not want_autostart and self.autostart_enabled():
            ok, msg = self.set_autostart(False)
            if not ok:
                QMessageBox.warning(self, "关闭开机自启失败", msg)

        save_config(self.cfg)
        self.manager.cfg = self.cfg
        self._toast("设置已保存")
        self.refresh_status()

    def reset_settings(self):
        self.dir_astrbot.setText(DEFAULT_CONFIG["astrbot_dir"])
        self.dir_napcat.setText(DEFAULT_CONFIG["napcat_dir"])
        self.python_exe.setText(DEFAULT_CONFIG["python_exe"])
        self.port_dash.setValue(DEFAULT_CONFIG["dashboard_port"])
        self.port_ob.setValue(DEFAULT_CONFIG["onebot_port"])
        self.port_napcat.setValue(DEFAULT_CONFIG["napcat_port"])
        self.chk_close_tray.setChecked(DEFAULT_CONFIG["close_to_tray"])
        self.chk_start_min.setChecked(DEFAULT_CONFIG["start_minimized"])
        self.chk_auto_services.setChecked(False)
        self._toast("已恢复默认值，点击「保存设置」生效")

    def autostart_enabled(self) -> bool:
        try:
            r = subprocess.run(
                ["schtasks", "/Query", "/TN", AUTOSTART_TASK],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return r.returncode == 0
        except Exception:
            return False

    def set_autostart(self, enable: bool):
        cmd = subprocess.list2cmdline(launcher_command())
        try:
            if enable:
                r = subprocess.run(
                    [
                        "schtasks", "/Create", "/TN", AUTOSTART_TASK,
                        "/SC", "ONLOGON", "/RL", "HIGHEST", "/TR", cmd, "/F",
                    ],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                r = subprocess.run(
                    ["schtasks", "/Delete", "/TN", AUTOSTART_TASK, "/F"],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            if r.returncode != 0:
                return False, r.stderr.decode("gbk", "ignore") or r.stdout.decode("gbk", "ignore")
            return True, "OK"
        except Exception as e:
            return False, str(e)

    def relaunch_admin(self):
        cmd = launcher_command()
        try:
            params = subprocess.list2cmdline(cmd[1:]) if len(cmd) > 1 else ""
            r = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", cmd[0], params, str(APP_DIR), 1
            )
            if r > 32:
                self.quit_app()
        except Exception as e:
            QMessageBox.warning(self, "提权重启失败", str(e))


QSS = """
* { font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 13px; color: #e5e7eb; }
QWidget#root, QMainWindow { background: #0b1020; }
QFrame#card { background: #121a2d; border: 1px solid #22304a; border-radius: 14px; }
QFrame#banner { background: #2a2110; border: 1px solid #6b5214; border-radius: 10px; }
QLabel#warnText { color: #fbbf24; }
QLabel#title { font-size: 22px; font-weight: 700; color: #f8fafc; }
QLabel#subtitle { color: #8b97b0; font-size: 12px; }
QLabel#cardTitle { font-size: 17px; font-weight: 600; color: #f1f5f9; }
QLabel#muted { color: #94a3b8; font-size: 12px; }
QLabel#pill { background:#151d31; color:#94a3b8; border:1px solid #24304a; border-radius:13px; padding:5px 14px; font-weight:600; }
QLabel#value { color: #e2e8f0; }
QPushButton { background: #1b2539; border: 1px solid #2a3a55; padding: 7px 14px; border-radius: 8px; }
QPushButton:hover { background: #243149; border-color: #3a4d6e; }
QPushButton:pressed { background: #162033; }
QPushButton#primary { background: #2563eb; border: 1px solid #2563eb; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #3b82f6; border-color: #3b82f6; }
QPushButton#primary:disabled { background: #16233d; border-color: #24304a; color: #5b6b85; }
QPushButton#danger { background: #3a1c27; border: 1px solid #6b2237; color: #fca5a5; }
QPushButton#danger:hover { background: #4a2233; }
QPushButton#danger:disabled { background: #1a1a24; border-color: #2b2b38; color: #6b5b63; }
QPushButton#ghost { background: transparent; border: 1px solid #2a3a55; color: #cbd5e1; }
QPushButton#ghost:hover { background: #182238; }
QPushButton#link { background: transparent; border: none; color: #7dd3fc; padding: 0; text-align: left; }
QPushButton#link:hover { color: #bae6fd; text-decoration: underline; }
QPushButton:disabled { color: #64748b; background: #141c2e; border-color: #1f2b44; }
QToolButton { background: #162033; border: 1px solid #26354f; border-radius: 6px; padding: 2px 8px; color: #cbd5e1; }
QToolButton:hover { background: #1e2c44; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; color: #94a3b8; padding: 8px 18px; margin-right: 6px; border-radius: 8px; }
QTabBar::tab:selected { background: #1b2740; color: #e2e8f0; }
QTabBar::tab:hover { color: #e2e8f0; }
QPlainTextEdit { background: #070b16; border: 1px solid #1c2740; border-radius: 10px; color: #a7f3d0; }
QLineEdit, QSpinBox { background: #0e1526; border: 1px solid #24304a; border-radius: 8px; padding: 6px 10px; color: #e2e8f0; }
QLineEdit:focus, QSpinBox:focus { border-color: #3b82f6; }
QCheckBox { spacing: 8px; color: #cbd5e1; }
QGroupBox { border: 1px solid #1f2b44; border-radius: 12px; margin-top: 18px; padding: 16px 14px 12px 14px; font-weight: 600; color: #cbd5e1; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; color: #cbd5e1; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QMenu { background: #121a2d; border: 1px solid #22304a; padding: 6px; }
QMenu::item { padding: 7px 24px; border-radius: 6px; }
QMenu::item:selected { background: #1e3a8a; }
"""


def acquire_single_instance():
    """用文件锁保证只有一个控制台实例；返回保持引用的文件对象。"""
    try:
        import msvcrt

        lock_path = APP_DIR / "launcher.lock"
        fh = open(lock_path, "w")
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        return fh
    except OSError:
        QMessageBox.information(
            None,
            APP_NAME,
            "控制台已经在运行。\n如果窗口被挂起到了系统托盘，请双击托盘图标恢复。",
        )
        return None
    except Exception:
        return True


def main():
    if hasattr(Qt, "HighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(make_app_icon())
    app.setStyleSheet(QSS)
    app.setQuitOnLastWindowClosed(False)

    lock_handle = acquire_single_instance()
    if lock_handle is None:
        sys.exit(0)

    win = LauncherWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
