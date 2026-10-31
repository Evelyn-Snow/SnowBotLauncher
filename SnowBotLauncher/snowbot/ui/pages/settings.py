"""设置页：路径、端口、托盘与开机自启。"""
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

from snowbot.core.config import DEFAULT_CONFIG, launcher_command, save_config
from snowbot.core.paths import AUTOSTART_TASK


class SettingsMixin:
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

        maintenance = QGroupBox("维护")
        m_layout = QVBoxLayout(maintenance)
        mirror_hint = QLabel(
            "NapCat 插件商店打不开时，可注入国内可用的 GitHub 加速镜像；"
            "修改后需要重启 NapCat 才会生效。"
        )
        mirror_hint.setWordWrap(True)
        mirror_hint.setObjectName("muted")
        fix_mirror_btn = QPushButton("修复 NapCat 插件商店镜像")
        fix_mirror_btn.clicked.connect(self.fix_napcat_plugin_store)
        m_layout.addWidget(mirror_hint)
        m_layout.addWidget(fix_mirror_btn)
        layout.addWidget(maintenance)

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

    def fix_napcat_plugin_store(self):
        from snowbot.core.napcat_fix import patch_napcat_mirror

        path = self.dir_napcat.text().strip() or self.cfg.get("napcat_dir", "")
        ok, message = patch_napcat_mirror(path)
        if ok:
            QMessageBox.information(self, "修复完成", message)
        else:
            QMessageBox.warning(self, "修复失败", message)

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
