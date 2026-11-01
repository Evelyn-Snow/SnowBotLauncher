"""增强配置页分栏。"""

from __future__ import annotations

from .common import (
    ApiError,
    PERSONAS_DIR,
    Path,
    QCheckBox,
    QComboBox,
    QDesktopServices,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QUrl,
    QVBoxLayout,
    QWidget,
    Qt,
    get_path,
    import_persona_file,
    list_persona_files,
    read_persona_file,
    render_persona,
    safe_stem,
    save_config,
    set_path,
    write_persona_file,
)


class PersonaMixin:
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

        file_group = QGroupBox("人格文件与识别")
        file_grid = QGridLayout(file_group)
        file_grid.setHorizontalSpacing(8)
        file_grid.setVerticalSpacing(7)
        file_grid.addWidget(QLabel("Markdown 文件"), 0, 0)
        self.persona_file_combo = QComboBox()
        self.persona_file_combo.setMinimumWidth(220)
        self.persona_file_combo.currentIndexChanged.connect(
            self._on_persona_file_selected
        )
        file_grid.addWidget(self.persona_file_combo, 0, 1, 1, 4)
        open_dir_btn = QPushButton("打开目录")
        open_dir_btn.setObjectName("ghost")
        open_dir_btn.clicked.connect(self.open_persona_dir)
        file_grid.addWidget(open_dir_btn, 0, 5)

        file_buttons = QHBoxLayout()
        file_buttons.setSpacing(6)
        self.btn_import_persona = QPushButton("导入 .md…")
        self.btn_import_persona.clicked.connect(self.import_persona_md)
        self.btn_open_persona = QPushButton("打开编辑")
        self.btn_open_persona.setObjectName("ghost")
        self.btn_open_persona.clicked.connect(self.open_persona_file)
        self.btn_reload_persona = QPushButton("重新加载")
        self.btn_reload_persona.setObjectName("ghost")
        self.btn_reload_persona.clicked.connect(self.reload_persona_file)
        self.btn_save_persona_md = QPushButton("保存 .md")
        self.btn_save_persona_md.setObjectName("ghost")
        self.btn_save_persona_md.clicked.connect(self.save_current_persona_file)
        self.btn_save_persona_as = QPushButton("另存为…")
        self.btn_save_persona_as.setObjectName("ghost")
        self.btn_save_persona_as.clicked.connect(self.save_persona_file_as)
        for btn in (
            self.btn_import_persona,
            self.btn_open_persona,
            self.btn_reload_persona,
            self.btn_save_persona_md,
            self.btn_save_persona_as,
        ):
            file_buttons.addWidget(btn)
        file_buttons.addStretch(1)
        file_grid.addLayout(file_buttons, 1, 0, 1, 6)

        self.owner_edit = QLineEdit(str(self.cfg.get("owner_qq") or ""))
        self.owner_edit.setPlaceholderText("例如：123456789")
        self.owner_name_edit = QLineEdit(str(self.cfg.get("owner_name") or "你"))
        self.owner_name_edit.setPlaceholderText("你 / 所有者")
        self.bot_name_edit = QLineEdit(str(self.cfg.get("bot_name") or "助手"))
        owner_row = QHBoxLayout()
        owner_row.setSpacing(6)
        owner_row.addWidget(QLabel("所有者 QQ"))
        owner_row.addWidget(self.owner_edit, 2)
        owner_row.addWidget(QLabel("称呼"))
        owner_row.addWidget(self.owner_name_edit, 1)
        owner_row.addWidget(QLabel("机器人称呼"))
        owner_row.addWidget(self.bot_name_edit, 1)
        file_grid.addLayout(owner_row, 2, 0, 1, 6)

        self.chk_sync_owner = QCheckBox(
            "保存时同步所有者识别（管理员 / 主动聊天 / 签名会话）"
        )
        self.chk_sync_owner.setChecked(True)
        file_grid.addWidget(self.chk_sync_owner, 3, 0, 1, 4)
        preview_vars_btn = QPushButton("预览变量")
        preview_vars_btn.setObjectName("ghost")
        preview_vars_btn.clicked.connect(self.preview_persona_variables)
        file_grid.addWidget(preview_vars_btn, 3, 4, 1, 2)
        file_hint = QLabel(
            "支持 {OWNER_QQ}、{OWNER_NAME}、{BOT_NAME} 占位符；保存人格时自动替换。"
            "外部编辑后点「重新加载」即可。"
        )
        file_hint.setWordWrap(True)
        file_hint.setObjectName("muted")
        file_grid.addWidget(file_hint, 4, 0, 1, 6)
        right.addWidget(file_group)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.persona_id = QLineEdit()
        self.persona_id.setPlaceholderText("例如：助手")
        self.persona_prompt = QPlainTextEdit()
        self.persona_prompt.setPlaceholderText(
            "人格系统提示词，可直接粘贴 Markdown；支持 {OWNER_QQ} 等占位符"
        )
        self.persona_prompt.setMinimumHeight(170)
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
        buttons.addWidget(save_btn)
        buttons.addWidget(delete_btn)
        buttons.addWidget(default_btn)
        buttons.addStretch(1)
        right.addLayout(buttons)
        right.addStretch(1)

        layout.addLayout(left, 1)
        layout.addLayout(right, 3)
        return page

    # ---------------- 人格文件与身份变量 ----------------
    def _persona_variables(self) -> dict:
        owner = self.owner_edit.text().strip()
        owner_name = self.owner_name_edit.text().strip() or "你"
        bot_name = self.bot_name_edit.text().strip() or "助手"
        return {
            "OWNER_QQ": owner,
            "OWNER_NAME": owner_name,
            "BOT_NAME": bot_name,
            # 兼容 dafeiyu / 示例配置包里常见的写法。
            "OWNER": owner,
            "PERSONA_NAME": bot_name,
            "NAME": bot_name,
        }

    def _rendered_persona_text(self, text: str) -> str:
        return render_persona(text, self._persona_variables())

    def _refresh_persona_files(self, select: Path | None = None):
        current = select or self.persona_file
        files = list_persona_files(PERSONAS_DIR)
        self.persona_file_combo.blockSignals(True)
        self.persona_file_combo.clear()
        self.persona_file_combo.addItem("（不关联文件）", "")
        selected = 0
        for path in files:
            self.persona_file_combo.addItem(path.name, str(path))
            if current and path.resolve() == Path(current).resolve():
                selected = self.persona_file_combo.count() - 1
        self.persona_file_combo.setCurrentIndex(selected)
        self.persona_file_combo.blockSignals(False)

    def _on_persona_file_selected(self, _index: int):
        value = self.persona_file_combo.currentData()
        if not value:
            self.persona_file = None
            self._persona_file_mtime = None
            self.persona_id.setReadOnly(False)
            return
        self._load_persona_file(Path(str(value)))

    def _load_persona_file(self, path: Path, status: bool = True):
        path = Path(path)
        try:
            text = read_persona_file(path)
        except Exception as exc:
            QMessageBox.warning(self, "读取失败", str(exc))
            return
        self.persona_file = path
        self._persona_file_mtime = path.stat().st_mtime
        self.current_persona_id = path.stem
        self.persona_id.setText(path.stem)
        self.persona_id.setReadOnly(True)
        self.persona_prompt.setPlainText(text)
        self.persona_file_combo.blockSignals(True)
        for index in range(self.persona_file_combo.count()):
            if self.persona_file_combo.itemData(index) == str(path):
                self.persona_file_combo.setCurrentIndex(index)
                break
        self.persona_file_combo.blockSignals(False)
        if status:
            self._set_status(f"已加载人格文件：{path.name}；修改后点「重新加载」", True)

    def _detach_persona_file(self):
        self.persona_file = None
        self._persona_file_mtime = None
        self.persona_file_combo.blockSignals(True)
        self.persona_file_combo.setCurrentIndex(0)
        self.persona_file_combo.blockSignals(False)

    def _load_owner_from_profile(self):
        if self.owner_edit.text().strip():
            return
        admins = self.config.get("admins_id") or []
        for admin in admins:
            value = str(admin).strip()
            if value.isdigit():
                self.owner_edit.setText(value)
                self.cfg["owner_qq"] = value
                try:
                    save_config(self.cfg)
                except Exception:
                    pass
                return

    def import_persona_md(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择人格 Markdown", str(Path.home()), "Markdown (*.md *.txt)"
        )
        if not path:
            return
        source = Path(path)
        target = PERSONAS_DIR / f"{safe_stem(source.stem)}.md"
        if target.exists() and target.resolve() != source.resolve():
            if (
                QMessageBox.question(
                    self,
                    "覆盖人格文件",
                    f"人格库中已有「{target.name}」，要覆盖吗？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                != QMessageBox.StandardButton.Yes
            ):
                return
        try:
            if target.resolve() != source.resolve():
                target = import_persona_file(source, PERSONAS_DIR, overwrite=True)
            else:
                target = source
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        self._refresh_persona_files(target)
        self._load_persona_file(target)
        self._set_status(f"已导入人格文件：{target.name}", True)

    def open_persona_file(self):
        if not self.persona_file:
            QMessageBox.information(
                self, "未关联文件", "请先导入 .md，或点「另存为…」把人格保存成文件。"
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.persona_file)))
        self._set_status("已用系统默认编辑器打开；改完点「重新加载」", True)

    def reload_persona_file(self):
        if not self.persona_file:
            QMessageBox.information(self, "未关联文件", "请先从下拉框选择一个人格 .md。")
            return
        self._load_persona_file(self.persona_file)

    def save_current_persona_file(self):
        if not self.persona_file:
            self.save_persona_file_as()
            return
        try:
            write_persona_file(self.persona_file, self.persona_prompt.toPlainText())
            self._persona_file_mtime = self.persona_file.stat().st_mtime
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self._set_status(f"已写入 {self.persona_file.name}", True)

    def save_persona_file_as(self):
        default_name = f"{self.persona_id.text().strip() or 'persona'}.md"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "人格另存为 Markdown",
            str(PERSONAS_DIR / default_name),
            "Markdown (*.md)",
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() not in {".md", ".txt"}:
            target = target.with_suffix(".md")
        try:
            write_persona_file(target, self.persona_prompt.toPlainText())
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.persona_file = target
        self._persona_file_mtime = target.stat().st_mtime
        self.persona_id.setText(target.stem)
        self.persona_id.setReadOnly(True)
        self._refresh_persona_files(target)
        self._set_status(f"已保存人格文件：{target.name}", True)

    def open_persona_dir(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(PERSONAS_DIR)))

    def preview_persona_variables(self):
        text = self.persona_prompt.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "没有内容", "请先填写或导入人格提示词。")
            return
        rendered = self._rendered_persona_text(text)
        if len(rendered) > 4000:
            rendered = rendered[:4000] + "\n…"
        QMessageBox.information(self, "变量预览（保存时使用）", rendered)

    def _sync_owner_recognition(self, owner: str, previous_owner: str) -> list[str]:
        warnings: list[str] = []
        try:
            profile = self.client.get_profile()
            admins = [str(x) for x in (profile.get("admins_id") or [])]
            if previous_owner and previous_owner != owner:
                admins = [x for x in admins if x != previous_owner]
            if owner not in admins:
                admins.append(owner)
            profile["admins_id"] = admins
            self.client.put_profile(profile)

            platforms = [
                p
                for p in profile.get("platform", [])
                if isinstance(p, dict) and p.get("type") == "aiocqhttp"
            ]
            platform_id = platforms[0].get("id") if platforms else "napcat"
            session = f"{platform_id}:FriendMessage:{owner}"
            for plugin in (
                "astrbot_plugin_proactive_chat",
                "astrbot_plugin_dafeiyu_signature",
            ):
                try:
                    conf = self.client.get_plugin_config(plugin)
                except Exception:
                    continue
                if plugin == "astrbot_plugin_proactive_chat":
                    set_path(conf, "friend_settings.session_list", [session])
                else:
                    set_path(conf, "owner_session", session)
                try:
                    self.client.put_plugin_config(plugin, conf)
                except Exception as exc:
                    warnings.append(f"{plugin} 同步失败：{exc}")
            # 空间/资料插件在初始化时读取 admins_id，换所有者后重载一次。
            for plugin in ("astrbot_plugin_qzone", "astrbot_plugin_qqprofile"):
                try:
                    self.client.reload_plugin(plugin)
                except Exception:
                    pass
        except Exception as exc:
            warnings.append(f"所有者识别同步失败：{exc}")
        return warnings

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
            self._set_status(f"人格已刷新：{len(self.personas)} 个", True)

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
        self._detach_persona_file()
        self.persona_id.setText(pid)
        self.persona_id.setReadOnly(True)
        self.persona_prompt.setPlainText(str(persona.get("system_prompt") or ""))

    def new_persona(self):
        self.current_persona_id = None
        self._detach_persona_file()
        self.persona_id.setReadOnly(False)
        self.persona_id.clear()
        self.persona_prompt.clear()
        self.persona_id.setFocus()

    def save_persona(self):
        if not self._need_client():
            return
        pid = self.persona_id.text().strip()
        raw = self.persona_prompt.toPlainText().strip()
        if not pid or not raw:
            QMessageBox.warning(self, "缺少内容", "人格 ID 和系统提示词都不能为空。")
            return
        owner = self.owner_edit.text().strip()
        previous_owner = str(self.cfg.get("owner_qq") or "").strip()
        if owner and not owner.isdigit():
            QMessageBox.warning(self, "所有者 QQ 格式不对", "所有者 QQ 只能填写数字。")
            return
        if self.persona_file and self._persona_file_mtime is not None:
            try:
                if abs(self.persona_file.stat().st_mtime - self._persona_file_mtime) > 1e-6:
                    QMessageBox.warning(
                        self,
                        "文件已被外部修改",
                        "这个 .md 在外部编辑过。请先点「重新加载」，确认内容后再保存。",
                    )
                    return
            except Exception:
                pass
        if previous_owner and owner and previous_owner != owner and previous_owner in raw:
            raw = raw.replace(previous_owner, owner)
            self.persona_prompt.setPlainText(raw)
        prompt = self._rendered_persona_text(raw)
        if "{OWNER_QQ}" in prompt:
            QMessageBox.warning(
                self, "缺少所有者 QQ", "人格里使用了 {OWNER_QQ}，请先填写所有者 QQ。"
            )
            return

        self.cfg["owner_qq"] = owner
        self.cfg["owner_name"] = self.owner_name_edit.text().strip() or "你"
        self.cfg["bot_name"] = self.bot_name_edit.text().strip() or "助手"
        save_config(self.cfg)
        saved_file = self.persona_file
        if saved_file:
            try:
                write_persona_file(saved_file, raw)
                self._persona_file_mtime = saved_file.stat().st_mtime
            except Exception as exc:
                QMessageBox.warning(self, "写入人格文件失败", str(exc))
                return
        sync_owner = bool(self.chk_sync_owner.isChecked() and owner)

        def task():
            warnings = (
                self._sync_owner_recognition(owner, previous_owner)
                if sync_owner
                else []
            )
            self.client.upsert_persona(pid, prompt)
            return self.client.list_personas(), self.client.get_profile(), warnings

        def done(result):
            self.personas, self.config, warnings = result
            self.current_persona_id = pid
            self._populate_personas()
            if saved_file:
                self._load_persona_file(saved_file, status=False)
            message = f"人格「{pid}」已保存"
            if sync_owner:
                message += "，所有者识别已同步"
            if warnings:
                message += "；" + "；".join(warnings)
            self._set_status(message, not warnings)

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
            config = self.client.get_profile()
            set_path(config, "provider_settings.default_personality", pid)
            if "agent_runner" in config:
                set_path(config, "agent_runner.config.persona.persona_id", pid)
            self.client.put_profile(config)
            self.config = config
            return pid

        def done(result):
            self.persona_default.setText(f"默认人格：{result}")
            self._set_status(f"已把「{result}」设为默认人格", True)

        self._run_task(task, done, f"正在设置默认人格「{pid}」…")
