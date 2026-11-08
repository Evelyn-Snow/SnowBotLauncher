"""设置页：路径、端口、托盘与开机自启。"""
import ctypes
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QGroupBox,
    QFormLayout,
)

from snowbot.core.config import (
    astrbot_dashboard_info,
    default_config,
    discover_astrbot,
    discover_napcat_dir,
    launcher_command,
    save_config,
)
from snowbot.core.paths import APP_DIR, AUTOSTART_TASK
from snowbot.core.single_instance import acquire_single_instance, release_single_instance


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
        self.python_exe = QLineEdit(self.cfg["python_exe"])
        form.addRow("AstrBot 目录", self._path_row(self.dir_astrbot, dir_mode=True))
        form.addRow("Python 解释器", self._path_row(self.python_exe, dir_mode=False))
        detect_btn = QPushButton("自动检测官方启动器实例")
        detect_btn.setObjectName("ghost")
        detect_btn.clicked.connect(self.detect_paths)
        form.addRow("", detect_btn)
        path_hint = QLabel(
            "官方 AstrBot Launcher 的实例位于 %USERPROFILE%\\.astrbot_launcher\\instances；"
            "检测会优先选择带有 core/main.py 和 venv/Scripts/python.exe 的实例。"
        )
        path_hint.setWordWrap(True)
        path_hint.setObjectName("muted")
        form.addRow("", path_hint)
        layout.addWidget(paths)

        qq_box = QGroupBox("QQ 协议端")
        qform = QFormLayout(qq_box)
        self._qq_form = qform
        self._qq_rows = {}
        qform.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        qform.setSpacing(10)
        self.qq_backend = QComboBox()
        self.qq_backend.addItem("NapCat（内置流程）", "napcat")
        self.qq_backend.addItem("SnowLuma（外部安装）", "snowluma")
        current_backend = str(self.cfg.get("qq_backend") or "napcat")
        self.qq_backend.setCurrentIndex(
            1 if current_backend == "snowluma" else 0
        )
        self.dir_napcat = QLineEdit(self.cfg["napcat_dir"])
        self.port_napcat = QSpinBox()
        self.port_napcat.setRange(1, 65535)
        self.port_napcat.setValue(int(self.cfg["napcat_port"]))
        self.dir_snowluma = QLineEdit(str(self.cfg.get("snowluma_dir") or ""))
        self.port_snowluma = QSpinBox()
        self.port_snowluma.setRange(1, 65535)
        self.port_snowluma.setValue(int(self.cfg.get("snowluma_webui_port") or 5099))
        self.node_exe = QLineEdit(str(self.cfg.get("node_exe") or ""))
        self.node_exe.setPlaceholderText("留空自动查找 node")
        self.qq_exe = QLineEdit(str(self.cfg.get("qq_exe") or ""))
        qform.addRow("使用协议端", self.qq_backend)
        self._qq_rows["napcat_dir"] = qform.rowCount()
        qform.addRow("NapCat 目录", self._path_row(self.dir_napcat, dir_mode=True))
        self._qq_rows["napcat_port"] = qform.rowCount()
        qform.addRow("NapCat WebUI 端口", self.port_napcat)
        self._qq_rows["snowluma_dir"] = qform.rowCount()
        qform.addRow("SnowLuma 目录", self._path_row(self.dir_snowluma, dir_mode=True))
        self._qq_rows["snowluma_port"] = qform.rowCount()
        qform.addRow("SnowLuma WebUI 端口", self.port_snowluma)
        self._qq_rows["node"] = qform.rowCount()
        qform.addRow("Node.js", self._path_row(self.node_exe, dir_mode=False))
        qform.addRow("QQ 程序", self._path_row(self.qq_exe, dir_mode=False))
        self.qq_hint = QLabel()
        self.qq_hint.setWordWrap(True)
        self.qq_hint.setObjectName("muted")
        qform.addRow("", self.qq_hint)
        layout.addWidget(qq_box)

        ports = QGroupBox("端口设置")
        pform = QFormLayout(ports)
        pform.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        pform.setSpacing(10)
        self.port_dash = QSpinBox()
        self.port_ob = QSpinBox()
        for sp in (self.port_dash, self.port_ob):
            sp.setRange(1, 65535)
        self.port_dash.setValue(int(self.cfg["dashboard_port"]))
        self.port_ob.setValue(int(self.cfg["onebot_port"]))
        pform.addRow("AstrBot 面板端口", self.port_dash)
        pform.addRow("OneBot WS 端口", self.port_ob)
        port_hint = QLabel(
            "这里的端口用于状态检测与跳转。若要与实际服务一致，请同步修改 AstrBot 的 "
            "cmd_config.json 和协议端的网络配置。"
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
        self.chk_quick_login = QCheckBox(
            "启动 NapCat 时自动使用已保存 QQ 账号快速登录（避免每次扫码）"
        )
        self.chk_quick_login.setChecked(bool(self.cfg.get("napcat_quick_login", True)))
        bform.addWidget(self.chk_close_tray)
        bform.addWidget(self.chk_start_min)
        bform.addWidget(self.chk_autostart)
        bform.addWidget(self.chk_auto_services)
        bform.addWidget(self.chk_quick_login)

        code_row = QHBoxLayout()
        code_row.setSpacing(8)
        code_lbl = QLabel("熟人暗号")
        self.intro_code = QLineEdit(str(self.cfg.get("intro_code") or ""))
        self.intro_code.setPlaceholderText("新朋友说出即通过身份验证")
        self.intro_code.setMinimumWidth(160)
        code_hint = QLabel("小雪会用它核实「哥哥介绍来的朋友」；连接 AstrBot 后保存自动同步给画像插件")
        code_hint.setObjectName("muted")
        code_hint.setWordWrap(True)
        code_row.addWidget(code_lbl)
        code_row.addWidget(self.intro_code, 1)
        bform.addLayout(code_row)
        bform.addWidget(code_hint)
        layout.addWidget(behavior)

        maintenance = QGroupBox("维护")
        self.napcat_maint_box = maintenance
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

        self.qq_backend.currentIndexChanged.connect(self._update_backend_visibility)
        self._update_backend_visibility()

        scroll.setWidget(host)
        outer.addWidget(scroll)
        return page

    def _update_backend_visibility(self, *_args):
        """按所选协议端显示对应路径/端口，避免两套配置同时铺在页面上。"""
        snow = str(self.qq_backend.currentData() or "napcat") == "snowluma"
        self._qq_form.setRowVisible(self._qq_rows["napcat_dir"], not snow)
        self._qq_form.setRowVisible(self._qq_rows["napcat_port"], not snow)
        self._qq_form.setRowVisible(self._qq_rows["snowluma_dir"], snow)
        self._qq_form.setRowVisible(self._qq_rows["snowluma_port"], snow)
        self._qq_form.setRowVisible(self._qq_rows["node"], snow)
        self.chk_quick_login.setVisible(not snow)
        self.napcat_maint_box.setVisible(not snow)
        text = (
            "SnowLuma 需要你先从官方 Releases 解压到本机目录（启动器不分发它），"
            "并自行用手机扫码登录一次；Node.js 留空时自动查找。"
            if snow
            else "NapCat 由启动器内置流程启动，目录需包含 launcher.bat；"
            "已保存账号时默认走快速登录，避免每次扫码。"
        )
        self.qq_hint.setText(
            text + " OneBot 反向连到 AstrBot 的 6199，平台 ID 保持 napcat 以保留会话。"
        )

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

    def detect_paths(self):
        found = discover_astrbot()
        napcat = discover_napcat_dir()
        if not found:
            QMessageBox.warning(
                self,
                "未找到 AstrBot 实例",
                "没有找到可用的 AstrBot 实例。\n"
                "请确认官方启动器已创建实例，或手动选择包含 main.py 的 core 目录和 venv Python。",
            )
            return
        self.dir_astrbot.setText(found.get("astrbot_dir", ""))
        self.python_exe.setText(found.get("python_exe", ""))
        if found.get("dashboard_port"):
            self.port_dash.setValue(int(found["dashboard_port"]))
        if (napcat / "launcher.bat").is_file():
            self.dir_napcat.setText(str(napcat))
        self._toast("已检测到 AstrBot 实例，点击「保存设置」生效")

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
                "napcat_quick_login": self.chk_quick_login.isChecked(),
                "qq_backend": str(self.qq_backend.currentData() or "napcat"),
                "snowluma_dir": self.dir_snowluma.text().strip(),
                "snowluma_webui_port": int(self.port_snowluma.value()),
                "node_exe": self.node_exe.text().strip(),
                "qq_exe": self.qq_exe.text().strip(),
                "intro_code": self.intro_code.text().strip(),
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
        # 让增强配置页和 QQ 健康监控立刻用上新端口/日志目录，而不是等重启。
        enhance = getattr(self, "enhance", None)
        if enhance is not None:
            info = astrbot_dashboard_info(self.cfg)
            enhance.dashboard = info
            port = int(info.get("port") or self.cfg.get("dashboard_port") or 6185)
            enhance.url_edit.setText(f"http://127.0.0.1:{port}")
        health = getattr(self, "health", None)
        if health is not None:
            health.napcat_log_dir = Path(
                str(self.cfg.get("napcat_dir") or "")
            ) / "logs"
        self._toast("设置已保存")
        self._sync_intro_code()
        self.refresh_status()

    def _sync_intro_code(self):
        """已连接 AstrBot 时把熟人暗号同步给画像插件；未连接只存本地。"""
        enhance = getattr(self, "enhance", None)
        client = getattr(enhance, "client", None) if enhance else None
        if client is None:
            self._toast("暗号已保存，连接 AstrBot 后自动同步", ok=True)
            return
        try:
            config = client.get_plugin_config("astrbot_plugin_snow_profile")
            if str(config.get("intro_code") or "") == self.cfg.get("intro_code", ""):
                return
            config["intro_code"] = self.cfg.get("intro_code", "")
            client.put_plugin_config("astrbot_plugin_snow_profile", config)
            self._toast("暗号已同步到小雪的画像插件", ok=True)
        except Exception as exc:
            self._toast(f"暗号同步失败：{str(exc)[:80]}", ok=False)

    def reset_settings(self):
        defaults = default_config()
        self.dir_astrbot.setText(defaults["astrbot_dir"])
        self.dir_napcat.setText(defaults["napcat_dir"])
        self.python_exe.setText(defaults["python_exe"])
        self.port_dash.setValue(defaults["dashboard_port"])
        self.port_ob.setValue(defaults["onebot_port"])
        self.port_napcat.setValue(defaults["napcat_port"])
        self.chk_close_tray.setChecked(defaults["close_to_tray"])
        self.chk_start_min.setChecked(defaults["start_minimized"])
        self.chk_auto_services.setChecked(False)
        self.chk_quick_login.setChecked(defaults.get("napcat_quick_login", True))
        idx = self.qq_backend.findData(defaults.get("qq_backend", "napcat"))
        if idx >= 0:
            self.qq_backend.setCurrentIndex(idx)
        self.dir_snowluma.setText(defaults.get("snowluma_dir", r"C:\SnowLuma"))
        self.port_snowluma.setValue(int(defaults.get("snowluma_webui_port", 5099)))
        self.node_exe.setText(defaults.get("node_exe", ""))
        self.qq_exe.setText(
            defaults.get("qq_exe", r"C:\Program Files\Tencent\QQNT\QQ.exe")
        )
        self.chk_autostart.setChecked(False)
        self._update_backend_visibility()
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
        # 先释放单实例锁，否则新进程会在旧进程退出前被锁挡住。
        release_single_instance()
        try:
            params = subprocess.list2cmdline(cmd[1:]) if len(cmd) > 1 else ""
            r = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", cmd[0], params, str(APP_DIR), 1
            )
            if r > 32:
                self.quit_app()
            else:
                acquire_single_instance()
                QMessageBox.warning(
                    self, "提权重启失败", f"ShellExecuteW 返回 {r}，控制台将继续运行。"
                )
        except Exception as e:
            acquire_single_instance()
            QMessageBox.warning(self, "提权重启失败", str(e))
