"""增强配置页的群聊分栏。

集中管理群聊概率引擎（GCP）、戳一戳、@空消息回询和群聊记忆捕获；
写入的是 AstrBot 与插件的运行配置，保存后自动重载插件。
"""

from __future__ import annotations

from .common import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    Qt,
)
from ....core.group_config import (
    build_scoped_groups,
    is_scope_enabled,
    parse_group_ids,
    scope_group_text,
)

GCP_PLUGIN = "astrbot_plugin_group_chat_plus"
LIVING_PLUGIN = "astrbot_plugin_livingmemory"


class GroupMixin:
    def _build_group_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        intro = QLabel(
            "群聊互动的总开关和频率都在这里。@机器人、回复机器人的消息始终会回复，"
            "不受下面的概率影响。"
        )
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        layout.addWidget(intro)

        # 概率引擎
        engine_group = QGroupBox("读空气（不 @ 也接话）")
        engine_form = QFormLayout(engine_group)
        engine_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        engine_form.setSpacing(9)

        self.chk_read_air = QCheckBox("启用读空气")
        self.chk_read_air.setToolTip(
            "关闭后机器人只响应 @、回复和指令，不在群里自主接话。\n"
            "开启后按下面的概率在群里参与闲聊。"
        )
        self.group_ids_edit = QLineEdit()
        self.group_ids_edit.setPlaceholderText("留空 = 所有群；多个群号用逗号分隔，例如 123456,234567")
        self.spin_initial = QDoubleSpinBox()
        self.spin_initial.setRange(0.0, 1.0)
        self.spin_initial.setSingleStep(0.01)
        self.spin_initial.setDecimals(2)
        self.spin_after = QDoubleSpinBox()
        self.spin_after.setRange(0.0, 1.0)
        self.spin_after.setSingleStep(0.05)
        self.spin_after.setDecimals(2)
        self.spin_duration = QSpinBox()
        self.spin_duration.setRange(10, 3600)
        self.spin_duration.setSuffix(" 秒")
        self.spin_duration.setValue(120)
        engine_form.addRow(self.chk_read_air)
        engine_form.addRow("生效群", self.group_ids_edit)
        engine_form.addRow("接话概率", self.spin_initial)
        engine_form.addRow("连聊概率", self.spin_after)
        engine_form.addRow("连聊持续", self.spin_duration)
        layout.addWidget(engine_group)

        # 戳一戳
        poke_group = QGroupBox("戳一戳")
        poke_form = QFormLayout(poke_group)
        poke_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        poke_form.setSpacing(9)
        self.chk_poke = QCheckBox("响应戳一戳")
        self.chk_poke.setToolTip(
            "生效范围与上面填写的群号一致；关闭后任何群都不响应戳一戳。"
        )
        self.spin_reverse = QDoubleSpinBox()
        self.spin_reverse.setRange(0.0, 1.0)
        self.spin_reverse.setSingleStep(0.05)
        self.spin_reverse.setDecimals(2)
        poke_form.addRow(self.chk_poke)
        poke_form.addRow("反戳概率", self.spin_reverse)
        layout.addWidget(poke_group)

        # 平台行为与记忆
        misc_group = QGroupBox("平台行为与记忆")
        misc_form = QFormLayout(misc_group)
        misc_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        misc_form.setSpacing(9)
        self.chk_empty_mention = QCheckBox("@机器人但没说话时，回话询问")
        self.chk_full_capture = QCheckBox("记录机器人未参与的群聊消息")
        self.chk_full_capture.setToolTip(
            "开启后 LivingMemory 会把群里所有消息写进记忆数据库，\n"
            "数据库增长和总结开销都会明显上升；关闭时只记录机器人回复过的内容。"
        )
        misc_form.addRow(self.chk_empty_mention)
        misc_form.addRow(self.chk_full_capture)
        layout.addWidget(misc_group)

        buttons = QHBoxLayout()
        self.btn_group_save = QPushButton("保存群聊设置")
        self.btn_group_save.setObjectName("primary")
        self.btn_group_save.clicked.connect(self.save_group_settings)
        buttons.addWidget(self.btn_group_save)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)

        self.group_result = QLabel("")
        self.group_result.setWordWrap(True)
        self.group_result.setObjectName("muted")
        self.group_result.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        result_row = QHBoxLayout()
        result_row.addWidget(self.group_result, 1)
        copy_group = QPushButton("复制")
        copy_group.setObjectName("ghost")
        copy_group.clicked.connect(
            lambda: self._copy_result(self.group_result.text(), "群聊设置")
        )
        result_row.addWidget(copy_group)
        layout.addLayout(result_row)
        return page

    def _load_group_ui(self):
        if not self.client:
            return
        gcp = self._plugin_config_or_none(GCP_PLUGIN)
        if gcp is None:
            for widget in (
                self.chk_read_air,
                self.group_ids_edit,
                self.spin_initial,
                self.spin_after,
                self.spin_duration,
                self.chk_poke,
                self.spin_reverse,
            ):
                widget.setEnabled(False)
            self.group_result.setText("未安装群聊增强插件（group_chat_plus），概率设置不可用。")
        else:
            self.chk_read_air.setEnabled(True)
            self.chk_read_air.setChecked(is_scope_enabled(gcp.get("enabled_groups")))
            self.group_ids_edit.setEnabled(True)
            self.group_ids_edit.setText(scope_group_text(gcp.get("enabled_groups")))
            self.spin_initial.setEnabled(True)
            self.spin_initial.setValue(float(gcp.get("initial_probability") or 0))
            self.spin_after.setEnabled(True)
            self.spin_after.setValue(float(gcp.get("after_reply_probability") or 0))
            self.spin_duration.setEnabled(True)
            self.spin_duration.setValue(int(gcp.get("probability_duration") or 120))
            self.chk_poke.setEnabled(True)
            self.chk_poke.setChecked(is_scope_enabled(gcp.get("poke_enabled_groups")))
            self.spin_reverse.setEnabled(True)
            self.spin_reverse.setValue(
                float(gcp.get("poke_reverse_on_poke_probability") or 0)
            )
            self.group_result.setText("已读取群聊增强插件配置。")
        living = self._plugin_config_or_none(LIVING_PLUGIN)
        if living is None:
            self.chk_full_capture.setEnabled(False)
        else:
            self.chk_full_capture.setEnabled(True)
            self.chk_full_capture.setChecked(
                bool(
                    (living.get("session_manager") or {}).get(
                        "enable_full_group_capture"
                    )
                )
            )
        platform = (self.config.get("platform_settings") or {})
        self.chk_empty_mention.setChecked(
            bool(platform.get("empty_mention_waiting_need_reply"))
        )

    def save_group_settings(self):
        if not self._need_client():
            return
        # 在进入后台线程前取齐所有控件值，避免跨线程访问 Qt 控件。
        read_air = self.chk_read_air.isChecked()
        ids = parse_group_ids(self.group_ids_edit.text())
        invalid = self.group_ids_edit.text().strip() and not ids
        poke = self.chk_poke.isChecked()
        initial = round(self.spin_initial.value(), 2)
        after = round(self.spin_after.value(), 2)
        duration = int(self.spin_duration.value())
        reverse = round(self.spin_reverse.value(), 2)
        empty_mention = self.chk_empty_mention.isChecked()
        full_capture = self.chk_full_capture.isChecked()
        full_capture_available = self.chk_full_capture.isEnabled()
        gcp_installed = GCP_PLUGIN in self._plugin_names()
        if gcp_installed and invalid:
            QMessageBox.warning(
                self,
                "群号无效",
                "生效群只能填数字群号，多个用逗号分隔；留空表示所有群。",
            )
            return

        def task():
            changed = []
            if gcp_installed:
                gcp = self.client.get_plugin_config(GCP_PLUGIN)
                gcp["enabled_groups"] = build_scoped_groups(read_air, ids)
                gcp["poke_enabled_groups"] = build_scoped_groups(poke, ids)
                gcp["initial_probability"] = initial
                gcp["after_reply_probability"] = after
                gcp["probability_duration"] = duration
                gcp["poke_reverse_on_poke_probability"] = reverse
                self.client.put_plugin_config(GCP_PLUGIN, gcp)
                self.client.reload_plugin(GCP_PLUGIN)
                changed.append("群聊增强")
            if full_capture_available:
                living = self.client.get_plugin_config(LIVING_PLUGIN)
                living.setdefault("session_manager", {})[
                    "enable_full_group_capture"
                ] = full_capture
                self.client.put_plugin_config(LIVING_PLUGIN, living)
                self.client.reload_plugin(LIVING_PLUGIN)
                changed.append("群聊记忆")
            profile = self.client.get_profile()
            profile.setdefault("platform_settings", {})[
                "empty_mention_waiting_need_reply"
            ] = empty_mention
            self.client.put_profile(profile)
            self.config = profile
            return changed, ids

        def done(result):
            changed, ids = result
            scope = "所有群" if not ids else f"{len(ids)} 个群"
            state = "启用" if read_air else "停用"
            self.group_result.setText(
                f"已保存：读空气{state}（{scope}），反戳 {reverse:.0%}，"
                f"@空消息{'回话' if empty_mention else '不回话'}。"
            )
            self._set_status(f"群聊设置已保存并重载：{'、'.join(changed) or '平台设置'}", True)
            self._load_group_ui()

        self._run_task(task, done, "正在保存群聊设置…")
