"""增强配置页：人格 / 表情包 / 语音 / 记忆。

这四个能力直接操作 AstrBot 后台接口，不依赖配置包脚本；所有修改都通过
AstrBot 的 /api/v1 接口完成，凭据只保留在本次运行的内存中。
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...astrbot.client import ApiError, AstrBotClient, get_path, set_path, zip_folder

from ...core.paths import DATA_DIR
from ...core.services import port_listening
MEME_EXT = "/plug/meme_manager"
EDGE_VOICES = [
    "zh-CN-XiaoyiNeural",
    "zh-CN-XiaoxiaoNeural",
    "zh-CN-YunxiNeural",
    "zh-CN-YunjianNeural",
    "zh-CN-YunxiaNeural",
    "zh-CN-YunyangNeural",
    "zh-CN-liaoning-XiaobeiNeural",
    "zh-CN-shaanxi-XiaoniNeural",
]
TTS_IDS = {"edge": "snowbot-tts-edge", "mimo": "snowbot-tts-mimo", "doubao": "snowbot-tts-doubao"}
MEMORY_ID = "snowbot-memory"


class Worker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as exc:
            self.failed.emit(str(exc))


def _list_from(result: dict, *keys) -> list:
    data = result.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), list):
                return data[key]
    for key in keys:
        if isinstance(result.get(key), list):
            return result[key]
    return []


class EnhanceTab(QWidget):
    def __init__(self, cfg: dict, dashboard: dict | None = None):
        super().__init__()
        self.cfg = cfg
        self.dashboard = dashboard or {}
        self.client: AstrBotClient | None = None
        self.config: dict = {}
        self.personas: list = []
        self.plugins: list = []
        self.meme_config: dict | None = None
        self.living_config: dict | None = None
        self.current_persona_id: str | None = None
        self.worker: Worker | None = None
        self._build_ui()

    # ---------------- 通用 ----------------
    def _plugin_names(self) -> set:
        return {p.get("name") for p in self.plugins if isinstance(p, dict)}

    def _require(self) -> AstrBotClient:
        if not self.client:
            raise ApiError("请先连接 AstrBot")
        return self.client

    def _need_client(self) -> bool:
        if not self.client:
            QMessageBox.information(
                self,
                "请先连接 AstrBot",
                "请先在页面顶部填写 AstrBot 后台密码，并点击「连接 AstrBot」。",
            )
            return False
        return True

    def _need_meme(self) -> bool:
        if not self._need_client():
            return False
        if "meme_manager" not in self._plugin_names():
            QMessageBox.information(
                self,
                "未安装表情包插件",
                "请先在 AstrBot 的插件市场安装并启用 meme_manager，再使用这些按钮。",
            )
            return False
        return True

    def _set_status(self, text: str, ok: bool | None = None):
        self.status.setText(text)
        if ok is True:
            self.status.setStyleSheet("color:#4ade80;")
        elif ok is False:
            self.status.setStyleSheet("color:#fbbf24;")
        else:
            self.status.setObjectName("muted")
            self.status.setStyleSheet("")

    def _set_busy(self, busy: bool):
        self.btn_connect.setEnabled(not busy)
        if busy:
            self._set_status("处理中，请稍候…")

    def _run_task(self, fn, on_done, text: str):
        if self.worker and self.worker.isRunning():
            self._set_status("已有操作正在进行，请稍候…", False)
            return
        self._set_busy(True)
        self._set_status(text)
        worker = Worker(fn)
        worker.done.connect(lambda result: self._task_done(result, on_done))
        worker.failed.connect(self._task_failed)
        worker.finished.connect(lambda: setattr(self, "worker", None))
        self.worker = worker
        worker.start()

    def _task_done(self, result, on_done):
        self._set_busy(False)
        try:
            on_done(result)
        except Exception as exc:
            self._set_status(f"失败：{exc}", False)
            QMessageBox.warning(self, "操作失败", str(exc))

    def _task_failed(self, message: str):
        self._set_busy(False)
        self._set_status(f"失败：{message}", False)
        QMessageBox.warning(self, "操作失败", message)

    # ---------------- 界面 ----------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        port = int(self.dashboard.get("port") or self.cfg.get("dashboard_port", 6185))
        self.url_edit = QLineEdit(f"http://127.0.0.1:{port}")
        self.user_edit = QLineEdit(str(self.dashboard.get("username") or "astrbot"))
        self.pw_edit = QLineEdit()
        self.pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw_edit.setPlaceholderText("后台密码（不保存）")
        self.btn_connect = QPushButton("连接 AstrBot")
        self.btn_connect.setObjectName("primary")
        self.btn_connect.clicked.connect(self.connect_backend)
        self.conn_label = QLabel("未连接")
        self.conn_label.setObjectName("muted")
        bar.addWidget(QLabel("后台"))
        bar.addWidget(self.url_edit, 1)
        bar.addWidget(QLabel("账号"))
        bar.addWidget(self.user_edit, 1)
        bar.addWidget(QLabel("密码"))
        bar.addWidget(self.pw_edit, 1)
        bar.addWidget(self.btn_connect)
        bar.addWidget(self.conn_label)
        outer.addLayout(bar)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_persona_tab(), "人格")
        self.tabs.addTab(self._build_meme_tab(), "表情包")
        self.tabs.addTab(self._build_voice_tab(), "语音")
        self.tabs.addTab(self._build_memory_tab(), "记忆")
        outer.addWidget(self.tabs, 1)

        self.status = QLabel("填写密码并连接 AstrBot 后使用；密码不会保存。")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

    # ---------------- 人格 ----------------
    def _build_persona_tab(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        left = QVBoxLayout()
        left.addWidget(QLabel("人格列表"))
        self.persona_list = QListWidget()
        self.persona_list.currentItemChanged.connect(self._on_persona_selected)
        left.addWidget(self.persona_list, 1)
        row = QHBoxLayout()
        new_btn = QPushButton("新建")
        new_btn.clicked.connect(self.new_persona)
        refresh_btn = QPushButton("刷新")
        refresh_btn.setObjectName("ghost")
        refresh_btn.clicked.connect(self.refresh_personas)
        row.addWidget(new_btn)
        row.addWidget(refresh_btn)
        left.addLayout(row)

        right = QVBoxLayout()
        self.persona_default = QLabel("默认人格：—")
        self.persona_default.setObjectName("muted")
        right.addWidget(self.persona_default)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.persona_id = QLineEdit()
        self.persona_id.setPlaceholderText("例如：小雪")
        self.persona_prompt = QPlainTextEdit()
        self.persona_prompt.setPlaceholderText("人格系统提示词，支持直接粘贴 Markdown 文本")
        self.persona_prompt.setMinimumHeight(240)
        form.addRow("人格 ID", self.persona_id)
        form.addRow("系统提示词", self.persona_prompt)
        right.addLayout(form)

        buttons = QHBoxLayout()
        save_btn = QPushButton("保存人格")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self.save_persona)
        delete_btn = QPushButton("删除")
        delete_btn.setObjectName("danger")
        delete_btn.clicked.connect(self.delete_persona)
        default_btn = QPushButton("设为默认")
        default_btn.clicked.connect(self.set_default_persona)
        import_btn = QPushButton("导入 .md")
        import_btn.setObjectName("ghost")
        import_btn.clicked.connect(self.import_persona_md)
        buttons.addWidget(save_btn)
        buttons.addWidget(delete_btn)
        buttons.addWidget(default_btn)
        buttons.addStretch(1)
        buttons.addWidget(import_btn)
        right.addLayout(buttons)
        right.addStretch(1)

        layout.addLayout(left, 1)
        layout.addLayout(right, 3)
        return page

    def _persona_by_id(self, persona_id: str) -> dict | None:
        for persona in self.personas:
            if isinstance(persona, dict) and persona.get("persona_id") == persona_id:
                return persona
        return None

    def refresh_personas(self):
        if not self._need_client():
            return

        def task():
            personas = self.client.list_personas()
            config = self.client.get_profile()
            return personas, config

        def done(result):
            self.personas, self.config = result
            self._populate_personas()

        self._run_task(task, done, "正在刷新人格…")

    def _populate_personas(self):
        default_id = (
            get_path(self.config, "provider_settings.default_personality")
            or get_path(self.config, "agent_runner.config.persona.persona_id")
            or ""
        )
        self.persona_default.setText(f"默认人格：{default_id or '未设置'}")
        self.persona_list.blockSignals(True)
        self.persona_list.clear()
        for persona in sorted(
            [p for p in self.personas if isinstance(p, dict)],
            key=lambda p: str(p.get("persona_id", "")),
        ):
            pid = str(persona.get("persona_id") or "")
            if not pid:
                continue
            item = QListWidgetItem(pid)
            item.setData(Qt.ItemDataRole.UserRole, pid)
            self.persona_list.addItem(item)
            if pid == default_id:
                item.setForeground(Qt.GlobalColor.green)
        self.persona_list.blockSignals(False)

        target = self.current_persona_id or default_id
        for row in range(self.persona_list.count()):
            if self.persona_list.item(row).data(Qt.ItemDataRole.UserRole) == target:
                self.persona_list.setCurrentRow(row)
                return
        if self.persona_list.count():
            self.persona_list.setCurrentRow(0)

    def _on_persona_selected(self, current, _previous=None):
        if not current:
            return
        pid = current.data(Qt.ItemDataRole.UserRole)
        persona = self._persona_by_id(pid)
        if not persona:
            return
        self.current_persona_id = pid
        self.persona_id.setText(pid)
        self.persona_id.setReadOnly(True)
        self.persona_prompt.setPlainText(str(persona.get("system_prompt") or ""))

    def new_persona(self):
        self.current_persona_id = None
        self.persona_id.setReadOnly(False)
        self.persona_id.clear()
        self.persona_prompt.clear()
        self.persona_id.setFocus()

    def import_persona_md(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择人格 Markdown", str(Path.home()), "Markdown (*.md *.txt)"
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8-sig")
        except Exception as exc:
            QMessageBox.warning(self, "读取失败", str(exc))
            return
        self.persona_prompt.setPlainText(text)
        if not self.persona_id.text().strip():
            self.persona_id.setText(Path(path).stem)

    def save_persona(self):
        if not self._need_client():
            return
        pid = self.persona_id.text().strip()
        prompt = self.persona_prompt.toPlainText().strip()
        if not pid or not prompt:
            QMessageBox.warning(self, "缺少内容", "人格 ID 和系统提示词都不能为空。")
            return

        def task():
            self.client.upsert_persona(pid, prompt)
            return self.client.list_personas(), self.client.get_profile()

        def done(result):
            self.personas, self.config = result
            self.current_persona_id = pid
            self._populate_personas()
            self._set_status(f"人格「{pid}」已保存", True)

        self._run_task(task, done, f"正在保存人格「{pid}」…")

    def delete_persona(self):
        if not self._need_client():
            return
        pid = self.current_persona_id
        if not pid:
            QMessageBox.information(self, "未选择", "请先在左侧选择一个人格。")
            return
        if (
            QMessageBox.question(
                self,
                "删除人格",
                f"确定删除人格「{pid}」？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return

        def task():
            ok = self.client.delete_persona(pid)
            if not ok:
                raise ApiError("删除失败，可能该人格正在被使用")
            return self.client.list_personas()

        def done(personas):
            self.personas = personas
            self.current_persona_id = None
            self.new_persona()
            self._populate_personas()
            self._set_status(f"人格「{pid}」已删除", True)

        self._run_task(task, done, f"正在删除人格「{pid}」…")

    def set_default_persona(self):
        if not self._need_client():
            return
        pid = self.persona_id.text().strip()
        if not pid:
            QMessageBox.warning(self, "未选择", "请先选择或填写人格 ID。")
            return

        def task():
            set_path(self.config, "provider_settings.default_personality", pid)
            if "agent_runner" in self.config:
                set_path(self.config, "agent_runner.config.persona.persona_id", pid)
            self.client.put_profile(self.config)
            return pid

        def done(result):
            self.persona_default.setText(f"默认人格：{result}")
            self._set_status(f"已把「{result}」设为默认人格", True)

        self._run_task(task, done, f"正在设置默认人格「{pid}」…")

    # ---------------- 表情包 ----------------
    def _build_meme_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        self.meme_plugin_label = QLabel("插件状态：未连接")
        self.meme_plugin_label.setObjectName("muted")
        layout.addWidget(self.meme_plugin_label)

        accel = QHBoxLayout()
        accel.addWidget(QLabel("GitHub 加速地址"))
        self.meme_accel = QLineEdit()
        self.meme_accel.setPlaceholderText("例如 https://gh-proxy.org/，留空表示直连")
        accel.addWidget(self.meme_accel, 1)
        save_accel = QPushButton("保存加速地址")
        save_accel.clicked.connect(self.save_meme_accel)
        accel.addWidget(save_accel)
        layout.addLayout(accel)

        actions = QHBoxLayout()
        fetch = QPushButton("拉取资源广场索引")
        fetch.clicked.connect(self.fetch_meme_index)
        refresh = QPushButton("刷新已安装")
        refresh.setObjectName("ghost")
        refresh.clicked.connect(self.refresh_meme_packs)
        actions.addWidget(fetch)
        actions.addWidget(refresh)
        actions.addStretch(1)
        layout.addLayout(actions)

        install_row = QHBoxLayout()
        install_row.addWidget(QLabel("套装 ID"))
        self.meme_pack_id = QLineEdit()
        self.meme_pack_id.setPlaceholderText("从资源广场复制的 pack_id，例如 blue-fat-fish-meme-pack")
        install_row.addWidget(self.meme_pack_id, 1)
        self.meme_set_default = QCheckBox("安装后设为默认")
        install_row.addWidget(self.meme_set_default)
        install = QPushButton("下载并安装")
        install.setObjectName("primary")
        install.clicked.connect(self.install_meme_pack)
        install_row.addWidget(install)
        layout.addLayout(install_row)

        self.meme_list = QListWidget()
        layout.addWidget(self.meme_list, 1)

        bottom = QHBoxLayout()
        set_default = QPushButton("设为默认")
        set_default.clicked.connect(self.set_selected_meme_default)
        multi = QPushButton("同时使用勾选的套装")
        multi.clicked.connect(self.apply_meme_multi)
        bottom.addWidget(set_default)
        bottom.addWidget(multi)
        bottom.addStretch(1)
        layout.addLayout(bottom)

        self.meme_status = QLabel("表情包功能依赖 meme_manager 插件。")
        self.meme_status.setObjectName("muted")
        self.meme_status.setWordWrap(True)
        layout.addWidget(self.meme_status)
        return page

    def _load_meme_ui(self):
        names = self._plugin_names()
        installed = "meme_manager" in names
        self.meme_plugin_label.setText(
            "插件状态：已安装" if installed else "插件状态：未安装（请先在 AstrBot 插件市场安装 meme_manager）"
        )
        if installed and self.meme_config:
            self.meme_accel.setText(
                str(get_path(self.meme_config, "community.github_accelerator_url") or "")
            )
        if installed:
            QTimer.singleShot(300, self.refresh_meme_packs)

    def _meme_data(self, key: str) -> list:
        result = self.client.request("GET", f"{MEME_EXT}/{key}")
        if not self.client.ok(result):
            raise ApiError(self.client.message(result))
        return _list_from(result, key, "packs", "rules", "items")

    def refresh_meme_packs(self):
        if not self._need_meme():
            return

        def task():
            packs = self._meme_data("packs")
            rules = self._meme_data("settings/rules")
            return packs, rules

        def done(result):
            packs, rules = result
            default = next(
                (r for r in rules if isinstance(r, dict) and r.get("scope") == "default"), {}
            )
            ids = default.get("pack_ids") or (
                [default.get("pack_id")] if default.get("pack_id") else []
            )
            self.meme_list.clear()
            for pack in packs:
                if not isinstance(pack, dict):
                    continue
                pid = str(pack.get("pack_id") or pack.get("id") or pack.get("name") or "")
                if not pid:
                    continue
                name = str(pack.get("name") or pack.get("title") or pid)
                count = pack.get("count") or pack.get("image_count")
                label = f"{name}    ({pid})"
                if count:
                    label += f"    {count} 张"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, pid)
                item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                item.setCheckState(
                    Qt.CheckState.Checked if pid in ids else Qt.CheckState.Unchecked
                )
                self.meme_list.addItem(item)
            self.meme_status.setText(f"已安装 {self.meme_list.count()} 套表情包；勾选后可同时使用。")
            self._set_status(f"表情包：已安装 {self.meme_list.count()} 套", True)

        self._run_task(task, done, "正在读取表情包列表…")

    def fetch_meme_index(self):
        if not self._need_meme():
            return

        def task():
            result = self.client.request(
                "POST", f"{MEME_EXT}/community/index/fetch", body={}, timeout=120
            )
            if not self.client.ok(result):
                raise ApiError(self.client.message(result))
            return self._meme_data("packs"), self._meme_data("settings/rules")

        def done(result):
            packs, rules = result
            self.meme_status.setText(f"资源广场索引已刷新，已安装 {len(packs)} 套。")
            self.refresh_meme_packs()

        self._run_task(task, done, "正在拉取表情包资源广场索引…")

    def save_meme_accel(self):
        if not self._need_meme():
            return
        url = self.meme_accel.text().strip()

        def task():
            config = self.meme_config or self.client.get_plugin_config("meme_manager")
            set_path(config, "community.github_accelerator_url", url)
            self.client.put_plugin_config("meme_manager", config)
            return config

        def done(config):
            self.meme_config = config
            self._set_status("表情包 GitHub 加速地址已保存", True)

        self._run_task(task, done, "正在保存加速地址…")

    def install_meme_pack(self):
        if not self._need_meme():
            return
        pack_id = self.meme_pack_id.text().strip()
        if not pack_id:
            QMessageBox.warning(self, "缺少套装 ID", "请填写要安装的 pack_id。")
            return
        set_default = self.meme_set_default.isChecked()

        def task():
            result = self.client.request(
                "POST",
                f"{MEME_EXT}/community/install",
                body={"pack_id": pack_id, "set_as_default": set_default},
                timeout=900,
            )
            if not self.client.ok(result):
                raise ApiError(self.client.message(result))
            return pack_id

        def done(result):
            self._set_status(f"表情包「{result}」安装完成", True)
            self.refresh_meme_packs()

        self._run_task(task, done, f"正在下载表情包「{pack_id}」…")

    def set_selected_meme_default(self):
        if not self._need_meme():
            return
        item = self.meme_list.currentItem()
        if not item:
            QMessageBox.information(self, "未选择", "请先选中一套表情包。")
            return
        pid = item.data(Qt.ItemDataRole.UserRole)

        def task():
            result = self.client.request(
                "POST", f"{MEME_EXT}/packs/default", body={"pack_id": pid}
            )
            if not self.client.ok(result):
                raise ApiError(self.client.message(result))

        def done(_result):
            self._set_status(f"已把「{pid}」设为默认表情包", True)
            self.refresh_meme_packs()

        self._run_task(task, done, f"正在设置默认表情包「{pid}」…")

    def apply_meme_multi(self):
        if not self._need_meme():
            return
        ids = []
        for row in range(self.meme_list.count()):
            item = self.meme_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                ids.append(item.data(Qt.ItemDataRole.UserRole))
        if not ids:
            QMessageBox.information(self, "未勾选", "请至少勾选一套表情包。")
            return

        def task():
            result = self.client.request("GET", f"{MEME_EXT}/settings/rules")
            if not self.client.ok(result):
                raise ApiError(self.client.message(result))
            rules = _list_from(result, "rules", "items")
            keep = [r for r in rules if isinstance(r, dict) and r.get("scope") != "default"]
            current = next(
                (r for r in rules if isinstance(r, dict) and r.get("scope") == "default"), {}
            )
            rule = {
                "id": current.get("id") or "default",
                "scope": "default",
                "pack_id": ids[0],
                "pack_ids": ids,
            }
            saved = self.client.request(
                "POST", f"{MEME_EXT}/settings/rules", body={"rules": keep + [rule]}
            )
            if not self.client.ok(saved):
                raise ApiError(self.client.message(saved))

        def done(_result):
            self._set_status(f"已设置为同时使用 {len(ids)} 套表情包", True)
            self.refresh_meme_packs()

        self._run_task(task, done, "正在应用表情包规则…")

    # ---------------- 语音 ----------------
    def _build_voice_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.addWidget(QLabel("语音方案"))
        self.voice_mode = QComboBox()
        for label, value in (
            ("关闭", "off"),
            ("Edge TTS（免费）", "edge"),
            ("小米 MiMo 克隆音", "mimo"),
            ("豆包 Seed Audio", "doubao"),
        ):
            self.voice_mode.addItem(label, value)
        top.addWidget(self.voice_mode)
        top.addSpacing(16)
        top.addWidget(QLabel("触发概率"))
        self.voice_prob = QDoubleSpinBox()
        self.voice_prob.setRange(0.0, 1.0)
        self.voice_prob.setSingleStep(0.05)
        self.voice_prob.setDecimals(2)
        self.voice_prob.setValue(0.33)
        top.addWidget(self.voice_prob)
        top.addStretch(1)
        layout.addLayout(top)

        self.voice_stack = QStackedWidget()
        off_page = QWidget()
        off_layout = QVBoxLayout(off_page)
        off_layout.addWidget(QLabel("语音已关闭。"))
        off_layout.addStretch(1)
        self.voice_stack.addWidget(off_page)

        edge_page = QWidget()
        edge_form = QFormLayout(edge_page)
        self.edge_voice = QComboBox()
        self.edge_voice.setEditable(True)
        self.edge_voice.addItems(EDGE_VOICES)
        edge_form.addRow("声音", self.edge_voice)
        install_edge = QPushButton("安装/更新 Edge 依赖（edge-tts、pyffmpeg）")
        install_edge.setObjectName("ghost")
        install_edge.clicked.connect(self.install_edge_deps)
        edge_form.addRow("", install_edge)
        self.voice_stack.addWidget(edge_page)

        mimo_page = QWidget()
        mimo_form = QFormLayout(mimo_page)
        self.mimo_base = QLineEdit("https://api.xiaomimimo.com/v1")
        self.mimo_key = QLineEdit()
        self.mimo_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.mimo_model = QLineEdit("mimo-v2.5-tts-voiceclone")
        ref_row = QWidget()
        ref_layout = QHBoxLayout(ref_row)
        ref_layout.setContentsMargins(0, 0, 0, 0)
        self.mimo_ref = QLineEdit()
        self.mimo_ref.setPlaceholderText("5~10 秒、只有一个人说话的录音")
        browse = QPushButton("浏览…")
        browse.setObjectName("ghost")
        browse.clicked.connect(self.browse_mimo_ref)
        ref_layout.addWidget(self.mimo_ref, 1)
        ref_layout.addWidget(browse)
        mimo_form.addRow("API 地址", self.mimo_base)
        mimo_form.addRow("API Key", self.mimo_key)
        mimo_form.addRow("模型", self.mimo_model)
        mimo_form.addRow("参考音频", ref_row)
        self.voice_stack.addWidget(mimo_page)

        doubao_page = QWidget()
        doubao_form = QFormLayout(doubao_page)
        self.doubao_appid = QLineEdit()
        self.doubao_token = QLineEdit()
        self.doubao_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.doubao_base = QLineEdit("https://openspeech.bytedance.com/api/v3/tts/create")
        self.doubao_model = QLineEdit("seed-audio-1.0")
        self.doubao_persona = QLineEdit(
            "一个憨萌软糯的小女生，声音甜甜的、有点奶，十几岁的感觉"
        )
        self.doubao_prompt = QLineEdit(
            "{persona}，在QQ上给好朋友发语音，语气轻快自然，只说引号里的这句话，一字不差：“{text}”"
        )
        doubao_form.addRow("APP ID", self.doubao_appid)
        doubao_form.addRow("Access Token", self.doubao_token)
        doubao_form.addRow("API 地址", self.doubao_base)
        doubao_form.addRow("模型", self.doubao_model)
        doubao_form.addRow("声音描述", self.doubao_persona)
        doubao_form.addRow("提示词模板", self.doubao_prompt)
        self.doubao_plugin_label = QLabel("插件状态：未连接")
        self.doubao_plugin_label.setObjectName("muted")
        install_doubao = QPushButton("从大肥鱼配置包安装豆包语音插件")
        install_doubao.setObjectName("ghost")
        install_doubao.clicked.connect(self.install_doubao_plugin)
        doubao_form.addRow("", self.doubao_plugin_label)
        doubao_form.addRow("", install_doubao)
        self.voice_stack.addWidget(doubao_page)
        layout.addWidget(self.voice_stack)

        buttons = QHBoxLayout()
        save = QPushButton("测试并保存语音")
        save.setObjectName("primary")
        save.clicked.connect(self.save_voice)
        disable = QPushButton("关闭语音")
        disable.setObjectName("danger")
        disable.clicked.connect(self.disable_voice)
        buttons.addWidget(save)
        buttons.addWidget(disable)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)

        self.voice_result = QLabel("")
        self.voice_result.setWordWrap(True)
        self.voice_result.setObjectName("muted")
        layout.addWidget(self.voice_result)
        self.voice_mode.currentIndexChanged.connect(
            lambda index: self.voice_stack.setCurrentIndex(index)
        )
        return page

    def browse_mimo_ref(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择参考音频", str(Path.home()), "音频 (*.mp3 *.wav *.m4a)"
        )
        if path:
            self.mimo_ref.setText(path)

    def _load_voice_ui(self):
        settings = self.config.get("provider_tts_settings") or {}
        self.voice_prob.setValue(float(settings.get("trigger_probability", 0.33)))
        provider_id = str(settings.get("provider_id") or "")
        provider = next(
            (
                p
                for p in self.config.get("provider", [])
                if isinstance(p, dict) and p.get("id") == provider_id
            ),
            None,
        )
        if not provider:
            self.voice_mode.setCurrentIndex(0)
            return
        ptype = provider.get("type") or ""
        if ptype == "edge_tts":
            self.voice_mode.setCurrentIndex(1)
            self.edge_voice.setCurrentText(str(provider.get("voice") or EDGE_VOICES[0]))
        elif ptype == "mimo_tts_api":
            self.voice_mode.setCurrentIndex(2)
            self.mimo_base.setText(str(provider.get("api_base") or ""))
            self.mimo_model.setText(str(provider.get("model") or ""))
        elif ptype == "seed_audio_tts":
            self.voice_mode.setCurrentIndex(3)
            self.doubao_base.setText(str(provider.get("api_base") or ""))
            self.doubao_model.setText(str(provider.get("model") or ""))
            self.doubao_persona.setText(str(provider.get("seed_audio_persona") or ""))
            self.doubao_prompt.setText(str(provider.get("seed_audio_prompt_template") or ""))
            self.doubao_plugin_label.setText(
                "插件状态：已安装"
                if "astrbot_plugin_seed_audio_tts" in self._plugin_names()
                or "seed_audio_tts" in self._plugin_names()
                else "插件状态：未安装"
            )

    def _voice_provider(self):
        mode = self.voice_mode.currentData()
        prob = float(self.voice_prob.value())
        if mode == "edge":
            voice = self.edge_voice.currentText().strip() or EDGE_VOICES[0]
            return (
                {
                    "id": TTS_IDS["edge"],
                    "type": "edge_tts",
                    "provider": "microsoft",
                    "provider_type": "text_to_speech",
                    "enable": True,
                    "voice": voice,
                    "rate": "+0%",
                    "volume": "+0%",
                    "pitch": "+0Hz",
                    "timeout": 20,
                    "proxy": "",
                },
                True,
            )
        if mode == "mimo":
            key = self.mimo_key.text().strip()
            ref = self.mimo_ref.text().strip()
            if not key or not ref or not Path(ref).exists():
                raise ApiError("MiMo 需要 API Key 和存在的参考音频")
            suffix = Path(ref).suffix.lower().lstrip(".") or "mp3"
            mime = {"mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4"}.get(
                suffix, "audio/mpeg"
            )
            data_uri = (
                f"data:{mime};base64,"
                + base64.b64encode(Path(ref).read_bytes()).decode()
            )
            return (
                {
                    "id": TTS_IDS["mimo"],
                    "type": "mimo_tts_api",
                    "provider": "mimo",
                    "provider_type": "text_to_speech",
                    "enable": True,
                    "api_key": key,
                    "api_base": self.mimo_base.text().strip(),
                    "model": self.mimo_model.text().strip(),
                    "mimo-tts-voice": data_uri,
                    "mimo-tts-format": "wav",
                    "mimo-tts-style-prompt": "",
                    "mimo-tts-dialect": "",
                    "mimo-tts-seed-text": "",
                    "timeout": 30,
                    "proxy": "",
                },
                True,
            )
        if mode == "doubao":
            names = self._plugin_names()
            if "astrbot_plugin_seed_audio_tts" not in names and "seed_audio_tts" not in names:
                raise ApiError("豆包语音需要先安装 astrbot_plugin_seed_audio_tts 插件")
            appid = self.doubao_appid.text().strip()
            token = self.doubao_token.text().strip()
            if not appid or not token:
                raise ApiError("豆包语音需要 APP ID 和 Access Token")
            return (
                {
                    "id": TTS_IDS["doubao"],
                    "type": "seed_audio_tts",
                    "provider": "volcengine",
                    "provider_type": "text_to_speech",
                    "enable": True,
                    "app_id": appid,
                    "access_key": token,
                    "credentials_file": "",
                    "api_base": self.doubao_base.text().strip(),
                    "resource_id": "seed-audio-1.0",
                    "model": self.doubao_model.text().strip(),
                    "seed_audio_persona": self.doubao_persona.text().strip(),
                    "seed_audio_prompt_template": self.doubao_prompt.text().strip(),
                    "seed_audio_format": "mp3",
                    "seed_audio_sample_rate": 24000,
                    "seed_audio_max_attempts": 2,
                    "seed_audio_whole_reply": True,
                    "seed_audio_reply_probability": prob,
                    "timeout": 60,
                },
                False,
            )
        return None, False

    def save_voice(self):
        if not self._need_client():
            return
        mode = self.voice_mode.currentData()
        if mode == "off":
            self.disable_voice()
            return
        try:
            provider, global_enable = self._voice_provider()
        except Exception as exc:
            QMessageBox.warning(self, "配置不完整", str(exc))
            return
        prob = float(self.voice_prob.value())

        def task():
            self.client.upsert_provider(provider)
            ok, why = self.client.test_provider(provider["id"])
            if not ok:
                provider["enable"] = False
                self.client.upsert_provider(provider)
            settings = self.config.setdefault("provider_tts_settings", {})
            settings.update(
                {
                    "enable": bool(global_enable and ok),
                    "provider_id": provider["id"],
                    "trigger_probability": prob,
                }
            )
            self.client.put_profile(self.config)
            return ok, why, provider["id"]

        def done(result):
            ok, why, pid = result
            if ok:
                note = "豆包由插件掷骰子并整条合成，首次回复会等 15~35 秒。" if pid == TTS_IDS["doubao"] else ""
                self.voice_result.setText(f"语音已启用：{pid}。{note}")
                self._set_status(f"语音已保存并测试通过：{pid}", True)
            else:
                self.voice_result.setText(f"语音测试未通过：{why}\n已先把提供商停用，处理后重新保存。")
                self._set_status("语音已保存但测试失败，已停用", False)

        self._run_task(task, done, "正在保存并测试语音…")

    def disable_voice(self):
        if not self._need_client():
            return

        def task():
            settings = self.config.setdefault("provider_tts_settings", {})
            settings["enable"] = False
            self.client.put_profile(self.config)
            return True

        def done(_result):
            self.voice_result.setText("语音已关闭。")
            self._set_status("语音已关闭", True)

        self._run_task(task, done, "正在关闭语音…")

    def install_edge_deps(self):
        if not self._need_client():
            return

        def task():
            for package in ("edge-tts==7.3.1", "pyffmpeg==2.5.2.3.2"):
                self.client.install_pip(package)
            return True

        def done(_result):
            self.voice_result.setText("Edge 依赖已安装/更新。")
            self._set_status("Edge 依赖安装完成", True)

        self._run_task(task, done, "正在安装 Edge 语音依赖…")

    def install_doubao_plugin(self):
        if not self._need_client():
            return
        candidates = list((DATA_DIR / "packs").glob("*/plugins/astrbot_plugin_seed_audio_tts"))
        source = next(
            (p for p in candidates if (p / "metadata.yaml").exists()), None
        )
        if not source:
            QMessageBox.information(
                self,
                "找不到插件",
                "没有在配置包目录里找到 astrbot_plugin_seed_audio_tts。\n"
                "请先导入大肥鱼配置包，或手动安装该插件。",
            )
            return

        def task():
            temp_root = Path(tempfile.mkdtemp(prefix="seed-audio-"))
            try:
                patched = temp_root / source.name
                shutil.copytree(source, patched)
                main_py = patched / "main.py"
                text = main_py.read_text(encoding="utf-8")
                old = (
                    "from astrbot.core.utils.astrbot_path import "
                    "get_astrbot_temp_path"
                )
                if old in text:
                    compat = """from astrbot.core.utils.astrbot_path import get_astrbot_data_path


def get_astrbot_temp_path():
    path = os.path.join(get_astrbot_data_path(), "temp")
    os.makedirs(path, exist_ok=True)
    return path"""
                    text = text.replace(old, compat)
                    main_py.write_text(text, encoding="utf-8")
                self.client.upload_plugin(zip_folder(patched), patched.name + ".zip")
                return self.client.list_plugins()
            finally:
                shutil.rmtree(temp_root, ignore_errors=True)

        def done(plugins):
            self.plugins = plugins
            self.doubao_plugin_label.setText("插件状态：已安装")
            self._set_status("豆包语音插件已安装", True)

        self._run_task(task, done, "正在安装豆包语音插件…")

    # ---------------- 记忆 ----------------
    def _build_memory_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.addWidget(QLabel("记忆方案"))
        self.mem_mode = QComboBox()
        for label, value in (
            ("关闭", "off"),
            ("本机 Ollama（免费）", "ollama"),
            ("硅基流动", "siliconflow"),
            ("自定义 OpenAI 兼容", "custom"),
        ):
            self.mem_mode.addItem(label, value)
        top.addWidget(self.mem_mode)
        top.addStretch(1)
        self.mem_plugin_label = QLabel("插件状态：未连接")
        self.mem_plugin_label.setObjectName("muted")
        top.addWidget(self.mem_plugin_label)
        layout.addLayout(top)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.mem_base = QLineEdit()
        self.mem_key = QLineEdit()
        self.mem_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.mem_model = QLineEdit()
        self.mem_dims = QSpinBox()
        self.mem_dims.setRange(64, 8192)
        self.mem_dims.setValue(1024)
        form.addRow("Embedding 地址", self.mem_base)
        form.addRow("API Key", self.mem_key)
        form.addRow("模型", self.mem_model)
        form.addRow("向量维度", self.mem_dims)
        layout.addLayout(form)

        row = QHBoxLayout()
        check_ollama = QPushButton("检查本机 Ollama")
        check_ollama.setObjectName("ghost")
        check_ollama.clicked.connect(self.check_ollama)
        install_lm = QPushButton("安装长期记忆插件")
        install_lm.setObjectName("ghost")
        install_lm.clicked.connect(self.install_livingmemory)
        row.addWidget(check_ollama)
        row.addWidget(install_lm)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QHBoxLayout()
        save = QPushButton("测试并保存记忆")
        save.setObjectName("primary")
        save.clicked.connect(self.save_memory)
        disable = QPushButton("关闭记忆")
        disable.setObjectName("danger")
        disable.clicked.connect(self.disable_memory)
        buttons.addWidget(save)
        buttons.addWidget(disable)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)

        self.mem_result = QLabel("")
        self.mem_result.setWordWrap(True)
        self.mem_result.setObjectName("muted")
        layout.addWidget(self.mem_result)
        self.mem_mode.currentIndexChanged.connect(self._on_mem_mode)
        return page

    def _on_mem_mode(self):
        mode = self.mem_mode.currentData()
        if mode == "ollama":
            self.mem_base.setText("http://127.0.0.1:11434/v1")
            self.mem_key.setText("ollama")
            self.mem_model.setText("bge-m3")
        elif mode == "siliconflow":
            self.mem_base.setText("https://api.siliconflow.cn/v1")
            self.mem_key.clear()
            self.mem_model.setText("BAAI/bge-m3")
        elif mode == "custom":
            pass
        self.mem_key.setEnabled(mode != "off")
        self.mem_base.setEnabled(mode != "off")
        self.mem_model.setEnabled(mode != "off")
        self.mem_dims.setEnabled(mode != "off")

    def _load_memory_ui(self):
        names = self._plugin_names()
        has_lm = "astrbot_plugin_livingmemory" in names
        self.mem_plugin_label.setText(
            "长期记忆插件：已安装" if has_lm else "长期记忆插件：未安装"
        )
        provider = next(
            (
                p
                for p in self.config.get("provider", [])
                if isinstance(p, dict)
                and p.get("provider_type") == "embedding"
                and p.get("enable", True)
            ),
            None,
        )
        if not provider:
            self.mem_mode.setCurrentIndex(0)
            return
        base = str(provider.get("embedding_api_base") or "")
        self.mem_base.setText(base)
        self.mem_key.setText(str(provider.get("embedding_api_key") or ""))
        self.mem_model.setText(str(provider.get("embedding_model") or ""))
        dims = provider.get("embedding_dimensions")
        if isinstance(dims, int) and dims > 0:
            self.mem_dims.setValue(dims)
        if "11434" in base or "ollama" in str(provider.get("id", "")).lower():
            self.mem_mode.setCurrentIndex(1)
        elif "siliconflow" in base:
            self.mem_mode.setCurrentIndex(2)
        else:
            self.mem_mode.setCurrentIndex(3)
        self._on_mem_mode()

    def check_ollama(self):
        def task():
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:11434/api/tags", timeout=6
                ) as resp:
                    data = json.load(resp)
                return [m.get("name", "") for m in data.get("models", [])]
            except Exception as exc:
                raise ApiError(f"连不上本机 Ollama：{exc}") from exc

        def done(models):
            target = self.mem_model.text().strip() or "bge-m3"
            found = any(str(name).split(":")[0] == target for name in models)
            self.mem_result.setText(
                ("Ollama 已有模型：" + "、".join(models)) if models else "Ollama 没有已下载模型"
            )
            self._set_status(
                f"Ollama 正常，{'已找到' if found else '未找到'} {target}",
                True if found else False,
            )

        self._run_task(task, done, "正在检查本机 Ollama…")

    def install_livingmemory(self):
        if not self._need_client():
            return

        def task():
            self.client.install_market_plugin("lxfight/astrbot_plugin_livingmemory")
            return self.client.list_plugins()

        def done(plugins):
            self.plugins = plugins
            self.mem_plugin_label.setText("长期记忆插件：已安装")
            self._set_status("长期记忆插件已安装", True)

        self._run_task(task, done, "正在从插件市场安装长期记忆插件…")

    def save_memory(self):
        if not self._need_client():
            return
        mode = self.mem_mode.currentData()
        if mode == "off":
            self.disable_memory()
            return
        base = self.mem_base.text().strip()
        key = self.mem_key.text().strip()
        model = self.mem_model.text().strip()
        if not base or not model or not key:
            QMessageBox.warning(self, "配置不完整", "Embedding 地址、Key、模型都要填写。")
            return
        dims = self.mem_dims.value()
        provider = {
            "id": MEMORY_ID,
            "type": "openai_embedding",
            "provider": "openai",
            "provider_type": "embedding",
            "enable": True,
            "embedding_api_key": key,
            "embedding_api_base": base,
            "embedding_model": model,
            "embedding_dimensions": dims,
            "embedding_dimensions_mode": "auto",
            "timeout": 20,
            "proxy": "",
        }
        has_lm = "astrbot_plugin_livingmemory" in self._plugin_names()

        def task():
            self.client.upsert_provider(provider)
            ok, why = self.client.test_provider(MEMORY_ID)
            if not ok:
                provider["enable"] = False
                self.client.upsert_provider(provider)
            if has_lm:
                conf = self.client.get_plugin_config("astrbot_plugin_livingmemory")
                set_path(conf, "provider_settings.embedding_provider_id", MEMORY_ID)
                self.client.put_plugin_config("astrbot_plugin_livingmemory", conf)
                self.client.set_plugin_enabled("astrbot_plugin_livingmemory", ok)
            return ok, why, has_lm

        def done(result):
            ok, why, has_lm = result
            if ok:
                tip = "" if has_lm else "（未安装长期记忆插件，仅创建了向量提供商）"
                self.mem_result.setText(f"记忆已启用：{MEMORY_ID}。{tip}")
                self._set_status("记忆已保存并测试通过", True)
            else:
                self.mem_result.setText(f"记忆测试未通过：{why}\n提供商与插件已先停用。")
                self._set_status("记忆已保存但测试失败，已停用", False)

        self._run_task(task, done, "正在保存并测试记忆…")

    def disable_memory(self):
        if not self._need_client():
            return
        has_lm = "astrbot_plugin_livingmemory" in self._plugin_names()

        def task():
            if has_lm:
                self.client.set_plugin_enabled("astrbot_plugin_livingmemory", False)
            provider = self.client.get_provider(MEMORY_ID)
            if provider:
                provider["enable"] = False
                self.client.upsert_provider(provider)
            return True

        def done(_result):
            self.mem_result.setText("记忆已关闭。")
            self._set_status("记忆已关闭", True)

        self._run_task(task, done, "正在关闭记忆…")

    # ---------------- 连接 ----------------
    def connect_backend(self):
        url = self.url_edit.text().strip()
        user = self.user_edit.text().strip() or "astrbot"
        password = self.pw_edit.text()
        if not url or not password:
            QMessageBox.warning(self, "缺少信息", "请填写 AstrBot 后台地址和密码。")
            return
        if not url.startswith("http"):
            url = "http://" + url
        url = url.rstrip("/")
        host = urlsplit(url).hostname
        if host in ("127.0.0.1", "localhost"):
            port = urlsplit(url).port or int(self.cfg.get("dashboard_port", 6185))
            if not port_listening(port):
                QMessageBox.information(
                    self,
                    "AstrBot 未运行",
                    "AstrBot 面板端口还没有就绪。\n"
                    "请先在「控制台」页点击「一键启动全部」，等待约 20~30 秒后再连接。",
                )
                return

        def task():
            client = AstrBotClient(url)
            if not client.login(user, password):
                raise ApiError("登录失败：检查后台地址、账号和密码")
            config = client.get_profile()
            personas = client.list_personas()
            plugins = client.list_plugins()
            names = {p.get("name") for p in plugins if isinstance(p, dict)}
            meme_config = None
            living_config = None
            if "meme_manager" in names:
                try:
                    meme_config = client.get_plugin_config("meme_manager")
                except Exception:
                    pass
            if "astrbot_plugin_livingmemory" in names:
                try:
                    living_config = client.get_plugin_config("astrbot_plugin_livingmemory")
                except Exception:
                    pass
            return client, config, personas, plugins, meme_config, living_config

        def done(result):
            (
                self.client,
                self.config,
                self.personas,
                self.plugins,
                self.meme_config,
                self.living_config,
            ) = result
            platforms = [
                p.get("id")
                for p in self.config.get("platform", [])
                if isinstance(p, dict) and p.get("type") == "aiocqhttp"
            ]
            self.conn_label.setText("已连接")
            self.conn_label.setToolTip("平台：" + (platforms[0] if platforms else "未找到"))
            self.conn_label.setStyleSheet("color:#4ade80;")
            self.pw_edit.clear()
            self._populate_personas()
            self._load_meme_ui()
            self._load_voice_ui()
            self._load_memory_ui()
            self._set_status(
                "已连接 AstrBot，平台：" + (platforms[0] if platforms else "未找到"), True
            )

        self._run_task(task, done, "正在连接 AstrBot…")
