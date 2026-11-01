"""增强配置页的存储路径分栏。

记忆文件（Obsidian）和图片图库的目录由各自插件配置控制；这里提供统一入口，
避免用户去 AstrBot 插件配置里逐个找。修改路径不会自动搬移旧文件。
"""

from __future__ import annotations

from .common import (
    Path,
    QCheckBox,
    QDesktopServices,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
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

        # 图库收藏与清理参数
        lib_group = QGroupBox("图库收藏与清理")
        lib_form = QFormLayout(lib_group)
        lib_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        lib_form.setSpacing(9)
        self.spin_lib_max_items = QSpinBox()
        self.spin_lib_max_items.setRange(10, 5000)
        self.spin_lib_max_items.setValue(300)
        self.spin_lib_max_items.setSuffix(" 张")
        self.spin_lib_retention = QSpinBox()
        self.spin_lib_retention.setRange(1, 3650)
        self.spin_lib_retention.setValue(180)
        self.spin_lib_retention.setSuffix(" 天")
        self.spin_lib_min_uses = QSpinBox()
        self.spin_lib_min_uses.setRange(0, 100)
        self.spin_lib_min_uses.setValue(2)
        self.spin_lib_cleanup = QSpinBox()
        self.spin_lib_cleanup.setRange(1, 168)
        self.spin_lib_cleanup.setValue(6)
        self.spin_lib_cleanup.setSuffix(" 小时")
        lib_form.addRow("图库容量上限", self.spin_lib_max_items)
        lib_form.addRow("保留天数", self.spin_lib_retention)
        lib_form.addRow("低频清理阈值（使用次数低于）", self.spin_lib_min_uses)
        lib_form.addRow("清理检查间隔", self.spin_lib_cleanup)
        self.chk_auto_save = QCheckBox("自动收藏喜欢的图片/表情包")
        self.spin_auto_save_prob = QSpinBox()
        self.spin_auto_save_prob.setRange(0, 100)
        self.spin_auto_save_prob.setValue(100)
        self.spin_auto_save_prob.setSuffix(" %")
        self.spin_auto_save_interval = QSpinBox()
        self.spin_auto_save_interval.setRange(0, 1440)
        self.spin_auto_save_interval.setValue(45)
        self.spin_auto_save_interval.setSuffix(" 分钟")
        self.spin_auto_save_daily = QSpinBox()
        self.spin_auto_save_daily.setRange(1, 100)
        self.spin_auto_save_daily.setValue(8)
        self.chk_allow_member_save = QCheckBox("允许其他人的图也存进图库")
        self.chk_auto_save_groups = QCheckBox("群里也自动收藏")
        lib_form.addRow(self.chk_auto_save)
        lib_form.addRow("收藏概率", self.spin_auto_save_prob)
        lib_form.addRow("两次收藏最小间隔", self.spin_auto_save_interval)
        lib_form.addRow("每天收藏上限", self.spin_auto_save_daily)
        lib_form.addRow(self.chk_allow_member_save)
        lib_form.addRow(self.chk_auto_save_groups)
        layout.addWidget(lib_group)

        # 自动日记参数
        diary_group = QGroupBox("自动日记")
        diary_form = QFormLayout(diary_group)
        diary_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        diary_form.setSpacing(9)
        self.chk_auto_diary = QCheckBox("自动写日记")
        self.spin_diary_interval = QSpinBox()
        self.spin_diary_interval.setRange(30, 1440)
        self.spin_diary_interval.setValue(120)
        self.spin_diary_interval.setSuffix(" 分钟")
        self.spin_diary_daily = QSpinBox()
        self.spin_diary_daily.setRange(1, 20)
        self.spin_diary_daily.setValue(3)
        self.spin_diary_exchanges = QSpinBox()
        self.spin_diary_exchanges.setRange(1, 50)
        self.spin_diary_exchanges.setValue(3)
        self.spin_diary_chars = QSpinBox()
        self.spin_diary_chars.setRange(40, 300)
        self.spin_diary_chars.setValue(120)
        self.spin_diary_chars.setSuffix(" 字")
        self.diary_quiet_edit = QLineEdit()
        self.diary_quiet_edit.setPlaceholderText("免打扰时段，例如 0-7")
        self.chk_diary_groups = QCheckBox("参考群聊消息")
        self.chk_diary_other_private = QCheckBox("参考其他人的私聊")
        self.spin_diary_weight_owner = QSpinBox()
        self.spin_diary_weight_owner.setRange(0, 10)
        self.spin_diary_weight_owner.setValue(3)
        self.spin_diary_weight_group = QSpinBox()
        self.spin_diary_weight_group.setRange(0, 10)
        self.spin_diary_weight_group.setValue(2)
        self.spin_diary_weight_other = QSpinBox()
        self.spin_diary_weight_other.setRange(0, 10)
        self.spin_diary_weight_other.setValue(1)
        diary_form.addRow(self.chk_auto_diary)
        diary_form.addRow("两次日记最小间隔", self.spin_diary_interval)
        diary_form.addRow("每天日记上限", self.spin_diary_daily)
        diary_form.addRow("至少聊多少轮才写", self.spin_diary_exchanges)
        diary_form.addRow("日记字数上限", self.spin_diary_chars)
        diary_form.addRow("免打扰时段", self.diary_quiet_edit)
        diary_form.addRow(self.chk_diary_groups)
        diary_form.addRow(self.chk_diary_other_private)
        weight_row = QHBoxLayout()
        weight_row.addWidget(QLabel("素材侧重：所有者"))
        weight_row.addWidget(self.spin_diary_weight_owner)
        weight_row.addWidget(QLabel("群聊"))
        weight_row.addWidget(self.spin_diary_weight_group)
        weight_row.addWidget(QLabel("其他人"))
        weight_row.addWidget(self.spin_diary_weight_other)
        weight_row.addStretch(1)
        diary_form.addRow(weight_row)
        layout.addWidget(diary_group)

        buttons = QHBoxLayout()
        save = QPushButton("保存存储与参数")
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
            for widget in (
                self.spin_lib_max_items,
                self.spin_lib_retention,
                self.spin_lib_min_uses,
                self.spin_lib_cleanup,
                self.chk_auto_save,
                self.spin_auto_save_prob,
                self.spin_auto_save_interval,
                self.spin_auto_save_daily,
                self.chk_allow_member_save,
                self.chk_auto_save_groups,
            ):
                widget.setEnabled(False)
        else:
            self.library_path_edit.setEnabled(True)
            self.library_path_edit.setText(str(imagebox.get("library_path") or ""))
            self.library_status.setText("已读取图库插件配置")
            self.spin_lib_max_items.setValue(int(imagebox.get("max_items") or 300))
            self.spin_lib_retention.setValue(int(imagebox.get("retention_days") or 180))
            self.spin_lib_min_uses.setValue(int(imagebox.get("min_uses") or 2))
            self.spin_lib_cleanup.setValue(
                int(imagebox.get("cleanup_interval_hours") or 6)
            )
            self.chk_auto_save.setChecked(bool(imagebox.get("auto_save_enabled", True)))
            self.spin_auto_save_prob.setValue(
                int(imagebox.get("auto_save_probability") or 100)
            )
            self.spin_auto_save_interval.setValue(
                int(imagebox.get("auto_save_min_interval_minutes") or 45)
            )
            self.spin_auto_save_daily.setValue(
                int(imagebox.get("auto_save_max_per_day") or 8)
            )
            self.chk_allow_member_save.setChecked(
                bool(imagebox.get("allow_member_save", False))
            )
            self.chk_auto_save_groups.setChecked(
                bool(imagebox.get("auto_save_in_groups", False))
            )
        if obsidian is None:
            for widget in (
                self.chk_auto_diary,
                self.spin_diary_interval,
                self.spin_diary_daily,
                self.spin_diary_exchanges,
                self.spin_diary_chars,
                self.diary_quiet_edit,
                self.chk_diary_groups,
                self.chk_diary_other_private,
                self.spin_diary_weight_owner,
                self.spin_diary_weight_group,
                self.spin_diary_weight_other,
            ):
                widget.setEnabled(False)
        else:
            self.chk_auto_diary.setChecked(
                bool(obsidian.get("auto_diary_enabled", True))
            )
            self.spin_diary_interval.setValue(
                int(obsidian.get("auto_diary_min_interval_minutes") or 120)
            )
            self.spin_diary_daily.setValue(
                int(obsidian.get("auto_diary_max_per_day") or 3)
            )
            self.spin_diary_exchanges.setValue(
                int(obsidian.get("auto_diary_min_exchanges") or 3)
            )
            self.spin_diary_chars.setValue(int(obsidian.get("auto_diary_max_chars") or 120))
            self.diary_quiet_edit.setText(str(obsidian.get("auto_diary_quiet_hours") or "0-7"))
            self.chk_diary_groups.setChecked(
                bool(obsidian.get("auto_diary_include_groups", True))
            )
            self.chk_diary_other_private.setChecked(
                bool(obsidian.get("auto_diary_include_other_private", True))
            )
            self.spin_diary_weight_owner.setValue(
                int(obsidian.get("auto_diary_owner_weight") or 3)
            )
            self.spin_diary_weight_group.setValue(
                int(obsidian.get("auto_diary_group_weight") or 2)
            )
            self.spin_diary_weight_other.setValue(
                int(obsidian.get("auto_diary_other_weight") or 1)
            )
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
        updates: dict[str, dict] = {}
        try:
            if self.vault_path_edit.isEnabled():
                updates.setdefault(OBSIDIAN_PLUGIN, {})[
                    "vault_path"
                ] = str(self._prepare_storage_path(self.vault_path_edit.text()))
            if self.library_path_edit.isEnabled():
                updates.setdefault(IMAGEBOX_PLUGIN, {})[
                    "library_path"
                ] = str(self._prepare_storage_path(self.library_path_edit.text()))
        except Exception as exc:
            QMessageBox.warning(self, "路径无效", str(exc))
            return
        if self.chk_auto_save.isEnabled():
            updates.setdefault(IMAGEBOX_PLUGIN, {}).update(
                {
                    "max_items": int(self.spin_lib_max_items.value()),
                    "retention_days": int(self.spin_lib_retention.value()),
                    "min_uses": int(self.spin_lib_min_uses.value()),
                    "cleanup_interval_hours": int(self.spin_lib_cleanup.value()),
                    "auto_save_enabled": self.chk_auto_save.isChecked(),
                    "auto_save_probability": int(self.spin_auto_save_prob.value()),
                    "auto_save_min_interval_minutes": int(
                        self.spin_auto_save_interval.value()
                    ),
                    "auto_save_max_per_day": int(self.spin_auto_save_daily.value()),
                    "allow_member_save": self.chk_allow_member_save.isChecked(),
                    "auto_save_in_groups": self.chk_auto_save_groups.isChecked(),
                }
            )
        if self.chk_auto_diary.isEnabled():
            updates.setdefault(OBSIDIAN_PLUGIN, {}).update(
                {
                    "auto_diary_enabled": self.chk_auto_diary.isChecked(),
                    "auto_diary_min_interval_minutes": int(
                        self.spin_diary_interval.value()
                    ),
                    "auto_diary_max_per_day": int(self.spin_diary_daily.value()),
                    "auto_diary_min_exchanges": int(self.spin_diary_exchanges.value()),
                    "auto_diary_max_chars": int(self.spin_diary_chars.value()),
                    "auto_diary_quiet_hours": self.diary_quiet_edit.text().strip() or "0-7",
                    "auto_diary_include_groups": self.chk_diary_groups.isChecked(),
                    "auto_diary_include_other_private": self.chk_diary_other_private.isChecked(),
                    "auto_diary_owner_weight": int(self.spin_diary_weight_owner.value()),
                    "auto_diary_group_weight": int(self.spin_diary_weight_group.value()),
                    "auto_diary_other_weight": int(self.spin_diary_weight_other.value()),
                }
            )
        if not updates:
            QMessageBox.information(self, "没有可保存的设置", "请先安装对应插件并连接 AstrBot。")
            return

        def task():
            for plugin, changes in updates.items():
                conf = self.client.get_plugin_config(plugin)
                conf.update(changes)
                self.client.put_plugin_config(plugin, conf)
                self.client.reload_plugin(plugin)
            return list(updates)

        def done(changed):
            self._set_status(f"已保存存储与参数：{'、'.join(changed)}", True)
            self._load_storage_ui()

        self._run_task(task, done, "正在保存存储与参数…")

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
