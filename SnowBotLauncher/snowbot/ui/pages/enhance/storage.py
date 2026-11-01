"""增强配置页的存储路径分栏。

记忆文件（Obsidian）和图片图库的目录由各自插件配置控制；这里提供统一入口，
避免用户去 AstrBot 插件配置里逐个找。修改路径不会自动搬移旧文件。
"""

from __future__ import annotations

from .common import (
    Path,
    QDesktopServices,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QUrl,
    QVBoxLayout,
    QWidget,
    Qt,
    os,
)

OBSIDIAN_PLUGIN = "astrbot_plugin_obsidian_notes"
IMAGEBOX_PLUGIN = "astrbot_plugin_snow_imagebox"


class StorageMixin:
    def _build_storage_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        intro = QLabel(
            "统一管理长期记忆和图片图库的存放位置。路径可以放在任意磁盘；"
            "修改后新文件写入新目录，旧文件不会自动搬移。"
        )
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        layout.addWidget(intro)

        # 记忆文件（Obsidian）
        memory_group = QGroupBox("记忆文件目录（日记 / 笔记 / 长期资料）")
        memory_form = QFormLayout(memory_group)
        memory_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.vault_path_edit = QLineEdit()
        self.vault_path_edit.setPlaceholderText("例如：C:\\Users\\你\\Documents\\BotMemory")
        self.vault_status = QLabel("未连接 AstrBot")
        self.vault_status.setObjectName("muted")
        self.vault_status.setWordWrap(True)
        vault_row = QHBoxLayout()
        vault_browse = QPushButton("浏览…")
        vault_browse.setObjectName("ghost")
        vault_browse.clicked.connect(self.browse_vault_path)
        vault_open = QPushButton("打开目录")
        vault_open.setObjectName("ghost")
        vault_open.clicked.connect(lambda: self.open_storage_path(self.vault_path_edit.text()))
        vault_row.addWidget(vault_browse)
        vault_row.addWidget(vault_open)
        vault_row.addStretch(1)
        memory_form.addRow("记忆目录", self.vault_path_edit)
        memory_form.addRow("", vault_row)
        memory_form.addRow("当前状态", self.vault_status)
        layout.addWidget(memory_group)

        # 图片图库
        image_group = QGroupBox("图片图库目录（聊天图片 / 表情包）")
        image_form = QFormLayout(image_group)
        image_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.library_path_edit = QLineEdit()
        self.library_path_edit.setPlaceholderText("例如：C:\\Users\\你\\Documents\\BotMemory\\表情包")
        self.library_status = QLabel("未连接 AstrBot")
        self.library_status.setObjectName("muted")
        self.library_status.setWordWrap(True)
        image_row = QHBoxLayout()
        image_browse = QPushButton("浏览…")
        image_browse.setObjectName("ghost")
        image_browse.clicked.connect(self.browse_library_path)
        image_open = QPushButton("打开目录")
        image_open.setObjectName("ghost")
        image_open.clicked.connect(
            lambda: self.open_storage_path(self.library_path_edit.text())
        )
        image_row.addWidget(image_browse)
        image_row.addWidget(image_open)
        image_row.addStretch(1)
        image_form.addRow("图库目录", self.library_path_edit)
        image_form.addRow("", image_row)
        image_form.addRow("当前状态", self.library_status)
        layout.addWidget(image_group)

        # 语义记忆数据库（由 LivingMemory 管理）
        semantic_group = QGroupBox("语义记忆数据库（LivingMemory）")
        semantic_form = QFormLayout(semantic_group)
        semantic_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.semantic_path_label = QLabel("未连接 AstrBot")
        self.semantic_path_label.setWordWrap(True)
        self.semantic_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        semantic_open = QPushButton("打开目录")
        semantic_open.setObjectName("ghost")
        semantic_open.clicked.connect(self.open_semantic_dir)
        semantic_form.addRow("数据目录", self.semantic_path_label)
        semantic_form.addRow("", semantic_open)
        semantic_note = QLabel(
            "语义记忆数据库由 LivingMemory 插件管理，包含 SQLite、索引和备份；"
            "这里只负责定位，避免在插件运行时直接移动数据库。"
        )
        semantic_note.setWordWrap(True)
        semantic_note.setObjectName("muted")
        semantic_form.addRow("", semantic_note)
        layout.addWidget(semantic_group)

        buttons = QHBoxLayout()
        save = QPushButton("保存存储路径")
        save.setObjectName("primary")
        save.clicked.connect(self.save_storage_paths)
        buttons.addWidget(save)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return page

    def _plugin_config_or_none(self, name: str) -> dict | None:
        if name not in self._plugin_names():
            return None
        try:
            return self.client.get_plugin_config(name)
        except Exception:
            return None

    def _load_storage_ui(self):
        if not self.client:
            return
        obsidian = self._plugin_config_or_none(OBSIDIAN_PLUGIN)
        imagebox = self._plugin_config_or_none(IMAGEBOX_PLUGIN)
        if obsidian is None:
            self.vault_path_edit.setEnabled(False)
            self.vault_status.setText("未安装 Obsidian 笔记插件，暂不可设置")
        else:
            self.vault_path_edit.setEnabled(True)
            self.vault_path_edit.setText(str(obsidian.get("vault_path") or ""))
            self.vault_status.setText("已读取 Obsidian 插件配置")
        if imagebox is None:
            self.library_path_edit.setEnabled(False)
            self.library_status.setText("未安装图库插件，暂不可设置")
        else:
            self.library_path_edit.setEnabled(True)
            self.library_path_edit.setText(str(imagebox.get("library_path") or ""))
            self.library_status.setText("已读取图库插件配置")
        base = Path(str(self.cfg.get("astrbot_dir") or ""))
        semantic = base / "data" / "plugin_data" / "astrbot_plugin_livingmemory"
        self.semantic_path_label.setText(str(semantic) if str(base) else "未找到 AstrBot 目录")

    def browse_vault_path(self):
        start = self.vault_path_edit.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "选择记忆文件目录", start)
        if path:
            self.vault_path_edit.setText(path)

    def browse_library_path(self):
        start = self.library_path_edit.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "选择图片图库目录", start)
        if path:
            self.library_path_edit.setText(path)

    @staticmethod
    def _prepare_storage_path(raw: str) -> Path:
        text = str(raw or "").strip()
        if not text:
            raise ValueError("路径不能为空")
        path = Path(os.path.expandvars(text)).expanduser()
        if not path.is_absolute():
            raise ValueError("请填写绝对路径")
        path = path.resolve()
        path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            raise ValueError("路径不是目录")
        return path

    def save_storage_paths(self):
        if not self._need_client():
            return
        targets: list[tuple[str, str, Path]] = []
        try:
            if self.vault_path_edit.isEnabled():
                targets.append(
                    (
                        OBSIDIAN_PLUGIN,
                        "vault_path",
                        self._prepare_storage_path(self.vault_path_edit.text()),
                    )
                )
            if self.library_path_edit.isEnabled():
                targets.append(
                    (
                        IMAGEBOX_PLUGIN,
                        "library_path",
                        self._prepare_storage_path(self.library_path_edit.text()),
                    )
                )
        except Exception as exc:
            QMessageBox.warning(self, "路径无效", str(exc))
            return
        if not targets:
            QMessageBox.information(self, "没有可保存的路径", "请先安装对应插件并连接 AstrBot。")
            return

        def task():
            changed = []
            for plugin, key, path in targets:
                conf = self.client.get_plugin_config(plugin)
                conf[key] = str(path)
                self.client.put_plugin_config(plugin, conf)
                self.client.reload_plugin(plugin)
                changed.append(plugin)
            return changed

        def done(changed):
            self._set_status(f"已保存存储路径：{'、'.join(changed)}", True)
            self._load_storage_ui()

        self._run_task(task, done, "正在保存存储路径…")

    def open_storage_path(self, raw: str):
        text = str(raw or "").strip()
        if not text:
            QMessageBox.information(self, "路径为空", "请先填写或选择一个目录。")
            return
        path = Path(os.path.expandvars(text)).expanduser()
        if not path.exists():
            QMessageBox.information(self, "目录不存在", f"目录还不存在：\n{path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_semantic_dir(self):
        text = self.semantic_path_label.text().strip()
        if not text or text == "未找到 AstrBot 目录":
            QMessageBox.information(self, "路径未知", "请先连接 AstrBot 或检查 AstrBot 目录设置。")
            return
        path = Path(text)
        if not path.exists():
            QMessageBox.information(self, "目录不存在", f"还没有语义记忆数据：\n{path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
