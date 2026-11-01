"""配置包页：列表、变量、预览、应用与备份。"""
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QThread, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QTabWidget,
    QLineEdit,
    QCheckBox,
    QFileDialog,
    QMessageBox,
    QScrollArea,
    QGroupBox,
    QFormLayout,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QProgressBar,
    QComboBox,
    QInputDialog,
)

from snowbot.core.config import astrbot_dashboard_info
from snowbot.core.services import port_listening
from snowbot.core.paths import RESOURCE_DIR
from snowbot.packs import engine as pe


class PackWorker(QThread):
    log_message = Signal(str)
    step_progress = Signal(int, int, str, bool, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, action, pack, values, cfg, run_scripts=False, snapshot=""):
        super().__init__()
        self.action = action
        self.pack = pack
        self.values = values
        self.cfg = cfg
        self.run_scripts = run_scripts
        self.snapshot = snapshot

    def run(self):
        try:
            ctx = pe.build_context(self.pack, self.values, self.cfg, self.log_message.emit)
            if self.action == "preview":
                plan = pe.build_plan(self.pack, ctx)
                self.completed.emit(
                    {
                        "action": "preview",
                        "platform": ctx.platform_id,
                        "provider": ctx.chat_provider_id,
                        "plan": [
                            {
                                "title": item.title,
                                "type": item.step["type"],
                                "script": item.is_script,
                                "when": item.step.get("when", ""),
                            }
                            for item in plan
                        ],
                    }
                )
            elif self.action == "apply":
                result = pe.apply_pack(
                    self.pack,
                    ctx,
                    run_scripts=self.run_scripts,
                    progress=lambda *args: self.step_progress.emit(*args),
                )
                self.completed.emit({"action": "apply", "result": result})
            elif self.action == "restore":
                result = pe.restore_backup(
                    self.snapshot,
                    self.cfg,
                    self.values["base_url"],
                    self.values["astrbot_username"],
                    self.values["astrbot_password"],
                    self.log_message.emit,
                )
                self.completed.emit({"action": "restore", "result": result})
        except Exception as exc:
            self.failed.emit(str(exc))


class PacksMixin:
    def _build_packs_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel("配置包")
        title.setObjectName("cardTitle")
        hint = QLabel("清单驱动 · 变量自定义 · 计划预览 · 备份还原 · 兼容旧版配置包")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        top.addWidget(title)
        top.addWidget(hint, 1)
        self.btn_import_pack = QPushButton("导入配置包…")
        self.btn_import_pack.clicked.connect(self.import_pack_dialog)
        self.btn_refresh_packs = QPushButton("刷新")
        self.btn_refresh_packs.setObjectName("ghost")
        self.btn_refresh_packs.clicked.connect(lambda: self.refresh_packs())
        self.btn_open_packs = QPushButton("打开目录")
        self.btn_open_packs.setObjectName("ghost")
        self.btn_open_packs.clicked.connect(self.open_packs_dir)
        top.addWidget(self.btn_import_pack)
        top.addWidget(self.btn_refresh_packs)
        top.addWidget(self.btn_open_packs)
        layout.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left.setMinimumWidth(190)
        left.setMaximumWidth(320)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.pack_list = QListWidget()
        self.pack_list.currentItemChanged.connect(self._on_pack_selected)
        left_layout.addWidget(self.pack_list)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self.pack_title = QLabel("选择一个配置包")
        self.pack_title.setObjectName("cardTitle")
        self.pack_meta = QLabel("")
        self.pack_meta.setObjectName("muted")
        self.pack_meta.setWordWrap(True)
        self.pack_desc = QLabel("")
        self.pack_desc.setWordWrap(True)
        self.pack_desc.setObjectName("value")
        right_layout.addWidget(self.pack_title)
        right_layout.addWidget(self.pack_meta)
        right_layout.addWidget(self.pack_desc)

        vars_scroll = QScrollArea()
        vars_scroll.setWidgetResizable(True)
        vars_host = QWidget()
        vars_layout = QVBoxLayout(vars_host)
        vars_layout.setContentsMargins(2, 2, 10, 2)
        vars_layout.setSpacing(10)

        vars_group = QGroupBox("变量")
        self.vars_form = QFormLayout(vars_group)
        self.vars_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.vars_form.setSpacing(8)

        conn_group = QGroupBox("AstrBot 连接")
        conn_form = QFormLayout(conn_group)
        conn_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        conn_form.setSpacing(8)
        self.pack_url = QLineEdit()
        self.pack_user = QLineEdit()
        self.pack_password = QLineEdit()
        self.pack_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.pack_password.setPlaceholderText("AstrBot 后台密码，仅本次使用，不保存")
        self.chk_run_scripts = QCheckBox("允许运行包内脚本（高风险，仅对信任的配置包勾选）")
        conn_form.addRow("后台地址", self.pack_url)
        conn_form.addRow("账号", self.pack_user)
        conn_form.addRow("密码", self.pack_password)
        conn_form.addRow("", self.chk_run_scripts)
        vars_layout.addWidget(conn_group)
        vars_layout.addWidget(vars_group)
        vars_layout.addStretch(1)
        vars_scroll.setWidget(vars_host)

        self.pack_steps = QPlainTextEdit()
        self.pack_steps.setReadOnly(True)
        self.pack_steps.setPlaceholderText("点击「预览计划」从 AstrBot 读取当前状态并生成步骤清单")
        plan_host = QWidget()
        plan_host_layout = QVBoxLayout(plan_host)
        plan_host_layout.setContentsMargins(2, 2, 10, 2)
        plan_host_layout.addWidget(self.pack_steps)

        self.pack_detail_tabs = QTabWidget()
        self.pack_detail_tabs.addTab(vars_scroll, "变量与连接")
        self.pack_detail_tabs.addTab(plan_host, "执行计划")

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.btn_preview_pack = QPushButton("预览计划")
        self.btn_preview_pack.clicked.connect(self.preview_pack)
        self.btn_apply_pack = QPushButton("应用配置")
        self.btn_apply_pack.setObjectName("primary")
        self.btn_apply_pack.clicked.connect(self.apply_pack)
        self.btn_restore_pack = QPushButton("还原备份…")
        self.btn_restore_pack.setObjectName("danger")
        self.btn_restore_pack.clicked.connect(self.restore_backup_dialog)
        self.btn_dup_pack = QPushButton("另存副本")
        self.btn_dup_pack.setObjectName("ghost")
        self.btn_dup_pack.clicked.connect(self.duplicate_pack)
        self.btn_export_pack = QPushButton("导出")
        self.btn_export_pack.setObjectName("ghost")
        self.btn_export_pack.clicked.connect(self.export_pack_dialog)
        actions.addWidget(self.btn_preview_pack)
        actions.addWidget(self.btn_apply_pack)
        actions.addWidget(self.btn_restore_pack)
        actions.addStretch(1)
        actions.addWidget(self.btn_dup_pack)
        actions.addWidget(self.btn_export_pack)

        self.pack_progress = QProgressBar()
        self.pack_progress.setVisible(False)
        self.pack_progress.setTextVisible(True)

        log_group = QGroupBox("执行日志")
        log_layout = QVBoxLayout(log_group)
        self.pack_log = QPlainTextEdit()
        self.pack_log.setReadOnly(True)
        self.pack_log.setFixedHeight(118)
        self.pack_log.setStyleSheet(
            'font-family: "Cascadia Mono","Consolas","Microsoft YaHei UI"; font-size: 12px;'
        )
        log_layout.addWidget(self.pack_log)

        right_layout.addLayout(actions)
        right_layout.addWidget(self.pack_progress)
        right_layout.addWidget(self.pack_detail_tabs, 1)
        right_layout.addWidget(log_group)
        splitter.addWidget(right)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 700])
        splitter.setMinimumHeight(420)
        self.pack_detail_tabs.setMinimumHeight(200)
        layout.addWidget(splitter, 1)

        return page

    def _backend_reachable(self, url: str) -> bool:
        from urllib.parse import urlsplit

        parts = urlsplit(url)
        if parts.hostname in ("127.0.0.1", "localhost"):
            port = parts.port or int(self.cfg.get("dashboard_port", 6185))
            if not port_listening(port):
                QMessageBox.information(
                    self,
                    "AstrBot 未运行",
                    "AstrBot 面板端口还没有就绪。\n"
                    "请先在「控制台」页启动 AstrBot，等待约 20~30 秒后再试。",
                )
                return False
        return True

    def _ensure_examples(self):
        examples = RESOURCE_DIR / "examples"
        if not examples.is_dir():
            return
        try:
            existing = [p for p in pe.PACKS_DIR.iterdir() if p.is_dir() and (p / "pack.json").exists()]
            if existing:
                return
            for src in examples.iterdir():
                if src.is_dir() and (src / "pack.json").exists():
                    shutil.copytree(src, pe.PACKS_DIR / src.name, dirs_exist_ok=True)
        except Exception:
            pass

    def refresh_packs(self, select_id: str | None = None):
        self._ensure_examples()
        packs = pe.list_packs(pe.PACKS_DIR)
        self.packs = {p["id"]: p for p in packs}
        current = select_id or (self.current_pack or {}).get("id")
        self.pack_list.blockSignals(True)
        self.pack_list.clear()
        for pack in packs:
            label = f"{pack.get('name', pack['id'])}   v{pack.get('version', '?')}"
            if pack.get("_error"):
                label += "   ⚠"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, pack["id"])
            if pack.get("description"):
                item.setToolTip(str(pack["description"]))
            self.pack_list.addItem(item)
        self.pack_list.blockSignals(False)

        target_id = current if current in self.packs else (packs[0]["id"] if packs else None)
        if target_id:
            for row in range(self.pack_list.count()):
                item = self.pack_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == target_id:
                    self.pack_list.setCurrentItem(item)
                    break
        else:
            self.current_pack = None
            self.pack_title.setText("还没有配置包")
            self.pack_meta.setText("点击「导入配置包…」选择文件夹或 zip")
            self.pack_desc.setText("")

    def _on_pack_selected(self, current, _previous=None):
        if not current:
            return
        pack_id = current.data(Qt.ItemDataRole.UserRole)
        pack = getattr(self, "packs", {}).get(pack_id)
        if not pack:
            return
        self.current_pack = pack
        if pack.get("_error"):
            self.pack_title.setText(f"{pack.get('name', pack_id)}（加载失败）")
            self.pack_meta.setText("")
            self.pack_desc.setText(str(pack["_error"]))
            self.pack_steps.setPlainText("")
            self._clear_vars_form()
            self.pack_log.clear()
            return
        self._populate_pack_detail(pack)

    def _clear_vars_form(self):
        while self.vars_form.count():
            item = self.vars_form.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.var_widgets = {}

    def _populate_pack_detail(self, pack: dict):
        self.pack_title.setText(pack.get("name", pack["id"]))
        meta = [f"v{pack.get('version', '?')}"]
        if pack.get("author"):
            meta.append(str(pack["author"]))
        if pack.get("tags"):
            meta.append(" · ".join(str(t) for t in pack["tags"]))
        self.pack_meta.setText("　·　".join(meta))
        self.pack_desc.setText(str(pack.get("description", "")))

        lines = []
        display_values = {**pe.variable_defaults(pack), **pe.load_preset(pack)}
        for index, step in enumerate(pack.get("steps", []), 1):
            kind = step.get("type")
            target = (
                step.get("id")
                or (step.get("provider") or {}).get("id")
                or step.get("plugin")
                or step.get("name")
                or step.get("market_id")
                or step.get("path")
                or step.get("tool")
                or ""
            )
            target = pe.fill(target, display_values)
            when = f"    条件：{step['when']}" if step.get("when") else ""
            lines.append(f"{index}. {kind}  {target}{when}")
        self.pack_steps.setPlainText("\n".join(lines))

        self._clear_vars_form()
        preset = pe.load_preset(pack)
        defaults = pe.variable_defaults(pack)
        hidden = {"base_url", "astrbot_username", "astrbot_password"}
        for var in pack.get("variables", []):
            key = var["key"]
            if key in hidden:
                continue
            label = var.get("label", key) + (" *" if var.get("required") else "")
            widget = self._make_var_widget(var, preset.get(key, defaults.get(key, "")))
            self.vars_form.addRow(label, widget)
            if var.get("description"):
                desc = QLabel(str(var["description"]))
                desc.setObjectName("muted")
                desc.setWordWrap(True)
                self.vars_form.addRow("", desc)
            self.var_widgets[key] = (var, widget)

        url_default = (
            str(preset.get("base_url") or defaults.get("base_url") or "")
            or f"http://127.0.0.1:{self.cfg['dashboard_port']}"
        )
        self.pack_url.setText(url_default)
        dashboard = astrbot_dashboard_info(self.cfg)
        self.pack_user.setText(
            str(preset.get("astrbot_username") or dashboard.get("username") or "astrbot")
        )
        self.pack_password.clear()
        self.chk_run_scripts.setChecked(False)
        self.pack_progress.setVisible(False)
        self.pack_log.clear()
        has_scripts = any(s.get("type") == "script" for s in pack.get("steps", []))
        if has_scripts:
            self.pack_log.appendPlainText(
                "提示：此配置包含脚本步骤，应用前需要勾选「允许运行包内脚本」。"
            )

    def _make_var_widget(self, var: dict, value):
        kind = var.get("type", "text")
        if kind == "select":
            combo = QComboBox()
            for option in var.get("options", []):
                if isinstance(option, dict):
                    combo.addItem(str(option.get("label", option.get("value"))), option.get("value"))
                else:
                    combo.addItem(str(option), option)
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
            return combo
        if kind == "bool":
            box = QCheckBox()
            box.setChecked(bool(value))
            return box
        if kind == "multiline":
            edit = QPlainTextEdit()
            edit.setFixedHeight(76)
            edit.setPlainText(str(value or ""))
            return edit
        edit = QLineEdit(str(value or ""))
        if kind == "password" or var.get("secret"):
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        if var.get("placeholder"):
            edit.setPlaceholderText(str(var["placeholder"]))
        return edit

    def _collect_pack_values(self) -> dict:
        values = {}
        for key, (var, widget) in self.var_widgets.items():
            if isinstance(widget, QComboBox):
                values[key] = widget.currentData()
            elif isinstance(widget, QCheckBox):
                values[key] = widget.isChecked()
            elif isinstance(widget, QPlainTextEdit):
                values[key] = widget.toPlainText()
            else:
                values[key] = widget.text().strip()
        url = self.pack_url.text().strip() or f"http://127.0.0.1:{self.cfg['dashboard_port']}"
        if not url.startswith("http"):
            url = "http://" + url
        values["base_url"] = url.rstrip("/")
        values["astrbot_username"] = self.pack_user.text().strip() or "astrbot"
        values["astrbot_password"] = self.pack_password.text()
        return values

    def _append_pack_log(self, text: str):
        self.pack_log.appendPlainText(text)
        bar = self.pack_log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _set_pack_busy(self, busy: bool):
        for button in (
            self.btn_preview_pack,
            self.btn_apply_pack,
            self.btn_restore_pack,
            self.btn_dup_pack,
            self.btn_export_pack,
            self.btn_import_pack,
            self.btn_refresh_packs,
        ):
            button.setEnabled(not busy)
        self.pack_list.setEnabled(not busy)
        self.pack_progress.setVisible(busy)
        if busy:
            self.pack_progress.setRange(0, 0)

    def _start_pack_worker(self, action: str, pack: dict, values: dict, run_scripts=False, snapshot=""):
        if self.pack_worker and self.pack_worker.isRunning():
            return
        self._last_pack_values = values
        self._set_pack_busy(True)
        self.pack_log.clear()
        worker = PackWorker(action, pack, values, self.cfg, run_scripts, snapshot)
        worker.log_message.connect(self._append_pack_log)
        worker.step_progress.connect(self._on_pack_progress)
        worker.completed.connect(self._on_pack_done)
        worker.failed.connect(self._on_pack_failed)
        worker.finished.connect(lambda: setattr(self, "pack_worker", None))
        self.pack_worker = worker
        worker.start()

    def _on_pack_progress(self, index: int, total: int, title: str, ok: bool, message: str):
        self.pack_progress.setRange(0, total)
        self.pack_progress.setValue(index)
        self.pack_progress.setFormat(f"%v/%m  {title}" if message != "running" else f"%v/%m  {title}")
        if ok:
            self._append_pack_log(f"✔ {title}" + (f"：{message}" if message else ""))
        elif message and message != "running":
            self._append_pack_log(f"✘ {title}：{message}")

    def _on_pack_done(self, data: dict):
        self._set_pack_busy(False)
        self.pack_progress.setVisible(False)
        action = data.get("action")
        if action == "preview":
            plan = data.get("plan", [])
            lines = [
                f"AstrBot 平台：{data.get('platform') or '未找到'}",
                f"对话模型：{data.get('provider') or '未配置'}",
                f"共 {len(plan)} 个步骤：",
            ]
            for index, item in enumerate(plan, 1):
                flag = " [脚本]" if item.get("script") else ""
                lines.append(f"  {index}. {item.get('title')}{flag}")
            text = "\n".join(lines)
            self.pack_steps.setPlainText(text)
            self._append_pack_log(text)
            QMessageBox.information(self, "预览完成", f"计划共 {len(plan)} 个步骤，详情见右侧。")
        elif action == "apply":
            result = data.get("result")
            ok_count = sum(1 for item in result.results if item.ok)
            total = len(result.results)
            self._append_pack_log(f"\n完成：{ok_count}/{total} 步成功")
            if result.backup:
                self._append_pack_log(f"备份：{result.backup}")
            if result.error:
                self._append_pack_log(f"错误：{result.error}")
            if result.ok:
                pe.save_preset(self.current_pack, getattr(self, "_last_pack_values", {}))
                QMessageBox.information(
                    self,
                    "应用完成",
                    f"配置包已应用（{ok_count}/{total} 步成功）。\n备份：{result.backup}",
                )
            else:
                QMessageBox.warning(
                    self,
                    "部分步骤失败",
                    f"{ok_count}/{total} 步成功。\n{result.error or '请查看执行日志与备份。'}",
                )
        elif action == "restore":
            result = data.get("result")
            if result.ok:
                QMessageBox.information(self, "还原完成", "已按备份还原 AstrBot 配置。")
            else:
                QMessageBox.warning(self, "还原失败", result.error or "请查看日志。")

    def _on_pack_failed(self, message: str):
        self._set_pack_busy(False)
        self.pack_progress.setVisible(False)
        self._append_pack_log(f"失败：{message}")
        QMessageBox.warning(self, "操作失败", message)

    def preview_pack(self):
        pack = self.current_pack
        if not pack or pack.get("_error"):
            return
        try:
            values = pe.resolve_variables(pack, self._collect_pack_values())
        except Exception as exc:
            QMessageBox.warning(self, "变量有误", str(exc))
            return
        if not values.get("astrbot_password"):
            QMessageBox.warning(self, "缺少密码", "请填写 AstrBot 后台密码。")
            return
        if not self._backend_reachable(values["base_url"]):
            return
        self._append_pack_log("正在登录 AstrBot 并生成计划…")
        self._start_pack_worker("preview", pack, values)

    def apply_pack(self):
        pack = self.current_pack
        if not pack or pack.get("_error"):
            return
        try:
            values = pe.resolve_variables(pack, self._collect_pack_values())
        except Exception as exc:
            QMessageBox.warning(self, "变量有误", str(exc))
            return
        if not values.get("astrbot_password"):
            QMessageBox.warning(self, "缺少密码", "请填写 AstrBot 后台密码。")
            return
        if not self._backend_reachable(values["base_url"]):
            return
        has_scripts = any(step.get("type") == "script" for step in pack.get("steps", []))
        if has_scripts and not self.chk_run_scripts.isChecked():
            QMessageBox.warning(
                self,
                "需要确认脚本",
                "此配置包包含脚本步骤。\n请先确认来源可信，并勾选「允许运行包内脚本」。",
            )
            return
        note = (
            "\n此配置包会运行包内脚本，请确认来源可信。"
            if has_scripts
            else ""
        )
        if (
            QMessageBox.question(
                self,
                "应用配置包",
                f"将应用「{pack.get('name', pack['id'])}」。\n"
                f"应用前会自动备份 AstrBot 配置，可随时还原。{note}\n\n确定继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._append_pack_log("开始应用配置包…")
        self._start_pack_worker(
            "apply", pack, values, run_scripts=self.chk_run_scripts.isChecked()
        )

    def restore_backup_dialog(self):
        backups = pe.list_backups()
        if not backups:
            QMessageBox.information(self, "没有备份", "还没有可用的备份。应用一次配置包后会自动生成。")
            return
        labels = [
            f"{item['created']}　{item['pack'].get('name', '')}　({item['name']})"
            for item in backups
        ]
        choice, ok = QInputDialog.getItem(
            self, "还原备份", "选择要还原的备份：", labels, 0, False
        )
        if not ok:
            return
        index = labels.index(choice)
        values = self._collect_pack_values()
        if not values.get("astrbot_password"):
            QMessageBox.warning(self, "缺少密码", "请填写 AstrBot 后台密码。")
            return
        if not self._backend_reachable(values["base_url"]):
            return
        if (
            QMessageBox.question(
                self,
                "确认还原",
                "将用备份覆盖 AstrBot 的全局配置、人格与插件配置。\n确定继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._append_pack_log(f"开始还原备份：{backups[index]['name']}")
        self._start_pack_worker(
            "restore", self.current_pack, values, snapshot=backups[index]["path"]
        )

    def import_pack_dialog(self):
        path = QFileDialog.getExistingDirectory(
            self, "选择配置包文件夹（取消后可选择 zip）", str(Path.home())
        )
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "选择配置包 zip", str(Path.home()), "配置包 (*.zip)"
            )
        if not path:
            return
        try:
            pack = pe.import_pack(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        legacy = "legacy" in (pack.get("tags") or [])
        self.refresh_packs(select_id=pack["id"])
        QMessageBox.information(
            self,
            "导入成功",
            f"已导入「{pack.get('name', pack['id'])}」。"
            + ("\n检测到旧版配置包，已自动转换为脚本步骤；应用前请勾选允许运行脚本。" if legacy else ""),
        )

    def export_pack_dialog(self):
        pack = self.current_pack
        if not pack or pack.get("_error"):
            return
        default = str(Path.home() / f"{pack['id']}.zip")
        path, _ = QFileDialog.getSaveFileName(self, "导出配置包", default, "配置包 (*.zip)")
        if not path:
            return
        try:
            pe.export_pack(pack, Path(path))
            QMessageBox.information(self, "导出成功", f"已导出到：\n{path}")
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))

    def duplicate_pack(self):
        pack = self.current_pack
        if not pack or pack.get("_error"):
            return
        try:
            new_pack = pe.duplicate_pack(pack)
            self.refresh_packs(select_id=new_pack["id"])
            QMessageBox.information(self, "已创建副本", "现在可以修改副本的 pack.json 或变量。")
        except Exception as exc:
            QMessageBox.warning(self, "创建副本失败", str(exc))

    def open_packs_dir(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(pe.PACKS_DIR)))

    # ---------------- 托盘 ----------------
