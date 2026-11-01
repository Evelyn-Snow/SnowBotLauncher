"""增强配置页的「作息与接话」分栏。

管理 snow_sleep（作息守卫）与 snow_continuity（连续对话接话）两个插件的
行为参数；写入插件配置并在保存后自动重载。插件未安装时对应分组禁用。
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

SLEEP_PLUGIN = "astrbot_plugin_snow_sleep"
CONTINUITY_PLUGIN = "astrbot_plugin_snow_continuity"


class BehaviorMixin:
    def _build_behavior_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        intro = QLabel(
            "作息决定机器人几点休息、几点上线；接话决定追问和戳一戳后的消息"
            "是否必回。网页测试台不受作息影响。"
        )
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        layout.addWidget(intro)

        # 作息（snow_sleep）
        sleep_group = QGroupBox("作息")
        sleep_form = QFormLayout(sleep_group)
        sleep_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        sleep_form.setSpacing(9)
        self.chk_sleep_enabled = QCheckBox("启用作息")
        self.chk_sleep_enabled.setToolTip("关闭后全天候在线。")
        self.sleep_start_edit = QLineEdit()
        self.sleep_start_edit.setPlaceholderText("HH:MM，例如 00:00")
        self.wake_time_edit = QLineEdit()
        self.wake_time_edit.setPlaceholderText("HH:MM，例如 07:00")
        self.chk_allow_commands = QCheckBox("休息时放行 / 命令")
        self.chk_allow_commands.setToolTip("以 / 或！开头的消息在休息时间也能执行。")
        self.chk_include_webchat = QCheckBox("网页测试台也休息")
        self.chk_include_webchat.setToolTip("默认豁免网页测试台，方便白天调试。")
        self.chk_suppress_memory = QCheckBox("休息时暂停记忆捕获")
        self.chk_suppress_memory.setToolTip(
            "开启后休息时间的群聊/私聊不再写进 LivingMemory 记忆数据库。"
        )
        sleep_form.addRow(self.chk_sleep_enabled)
        sleep_form.addRow("休息开始", self.sleep_start_edit)
        sleep_form.addRow("睡醒时间", self.wake_time_edit)
        sleep_form.addRow(self.chk_allow_commands)
        sleep_form.addRow(self.chk_include_webchat)
        sleep_form.addRow(self.chk_suppress_memory)
        layout.addWidget(sleep_group)

        # 连续对话接话（snow_continuity）
        cont_group = QGroupBox("连续对话接话")
        cont_form = QFormLayout(cont_group)
        cont_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        cont_form.setSpacing(9)
        self.cont_markers_edit = QLineEdit()
        self.cont_markers_edit.setPlaceholderText("逗号分隔，例如：你,您,在吗")
        self.spin_attention = QDoubleSpinBox()
        self.spin_attention.setRange(0.0, 1.0)
        self.spin_attention.setSingleStep(0.05)
        self.spin_attention.setDecimals(2)
        self.spin_poke_window = QSpinBox()
        self.spin_poke_window.setRange(60, 1800)
        self.spin_poke_window.setSuffix(" 秒")
        self.spin_poke_window.setValue(120)
        self.spin_boost_prob = QDoubleSpinBox()
        self.spin_boost_prob.setRange(0.5, 0.98)
        self.spin_boost_prob.setSingleStep(0.02)
        self.spin_boost_prob.setDecimals(2)
        self.spin_boost_prob.setValue(0.98)
        self.spin_boost_duration = QSpinBox()
        self.spin_boost_duration.setRange(30, 1800)
        self.spin_boost_duration.setSuffix(" 秒")
        self.spin_boost_duration.setValue(120)
        self.spin_interaction_window = QSpinBox()
        self.spin_interaction_window.setRange(30, 3600)
        self.spin_interaction_window.setSuffix(" 秒")
        self.spin_interaction_window.setValue(600)
        cont_form.addRow("呼唤标记词", self.cont_markers_edit)
        cont_form.addRow("注意力达标阈值", self.spin_attention)
        cont_form.addRow("戳一戳有效窗口", self.spin_poke_window)
        cont_form.addRow("命中后必回概率", self.spin_boost_prob)
        cont_form.addRow("必回持续时间", self.spin_boost_duration)
        cont_form.addRow("连续对话互动窗口", self.spin_interaction_window)
        cont_hint = QLabel(
            "标记词/戳一戳/互动窗口内判定为“正在和我说话”，按必回概率回复，"
            "不再被读空气概率吞掉。"
        )
        cont_hint.setWordWrap(True)
        cont_hint.setObjectName("muted")
        layout.addWidget(cont_group)
        layout.addWidget(cont_hint)

        buttons = QHBoxLayout()
        self.btn_behavior_save = QPushButton("保存作息与接话")
        self.btn_behavior_save.setObjectName("primary")
        self.btn_behavior_save.clicked.connect(self.save_behavior_settings)
        buttons.addWidget(self.btn_behavior_save)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)

        self.behavior_result = QLabel("")
        self.behavior_result.setWordWrap(True)
        self.behavior_result.setObjectName("muted")
        self.behavior_result.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        result_row = QHBoxLayout()
        result_row.addWidget(self.behavior_result, 1)
        copy_behavior = QPushButton("复制")
        copy_behavior.setObjectName("ghost")
        copy_behavior.clicked.connect(
            lambda: self._copy_result(self.behavior_result.text(), "作息与接话")
        )
        result_row.addWidget(copy_behavior)
        layout.addLayout(result_row)
        return page

    def _load_behavior_ui(self):
        if not self.client:
            return
        sleep = self._plugin_config_or_none(SLEEP_PLUGIN)
        if sleep is None:
            for widget in (
                self.chk_sleep_enabled,
                self.sleep_start_edit,
                self.wake_time_edit,
                self.chk_allow_commands,
                self.chk_include_webchat,
                self.chk_suppress_memory,
            ):
                widget.setEnabled(False)
        else:
            self.chk_sleep_enabled.setChecked(bool(sleep.get("enabled", True)))
            self.sleep_start_edit.setText(str(sleep.get("sleep_start") or "00:00"))
            self.wake_time_edit.setText(str(sleep.get("wake_time") or "07:00"))
            self.chk_allow_commands.setChecked(bool(sleep.get("allow_commands", True)))
            self.chk_include_webchat.setChecked(bool(sleep.get("include_webchat", False)))
            self.chk_suppress_memory.setChecked(
                bool(sleep.get("suppress_memory_capture", True))
            )
        cont = self._plugin_config_or_none(CONTINUITY_PLUGIN)
        if cont is None:
            for widget in (
                self.cont_markers_edit,
                self.spin_attention,
                self.spin_poke_window,
                self.spin_boost_prob,
                self.spin_boost_duration,
                self.spin_interaction_window,
            ):
                widget.setEnabled(False)
            self.behavior_result.setText(
                "未安装作息或接话插件，对应分组不可用。" if sleep is None else ""
            )
        else:
            self.cont_markers_edit.setText(str(cont.get("markers") or "你,您,在吗"))
            self.spin_attention.setValue(float(cont.get("attention_threshold") or 0.3))
            self.spin_poke_window.setValue(int(cont.get("poke_window_seconds") or 120))
            self.spin_boost_prob.setValue(float(cont.get("boost_probability") or 0.98))
            self.spin_boost_duration.setValue(
                int(cont.get("boost_duration_seconds") or 120)
            )
            self.spin_interaction_window.setValue(
                int(cont.get("interaction_window_seconds") or 600)
            )
            if sleep is not None:
                self.behavior_result.setText("已读取作息与接话配置。")

    def save_behavior_settings(self):
        if not self._need_client():
            return
        sleep_installed = SLEEP_PLUGIN in self._plugin_names()
        cont_installed = CONTINUITY_PLUGIN in self._plugin_names()
        sleep_values = {
            "enabled": self.chk_sleep_enabled.isChecked(),
            "sleep_start": self.sleep_start_edit.text().strip(),
            "wake_time": self.wake_time_edit.text().strip(),
            "allow_commands": self.chk_allow_commands.isChecked(),
            "include_webchat": self.chk_include_webchat.isChecked(),
            "suppress_memory_capture": self.chk_suppress_memory.isChecked(),
        }
        cont_values = {
            "markers": self.cont_markers_edit.text().strip(),
            "attention_threshold": round(self.spin_attention.value(), 2),
            "poke_window_seconds": int(self.spin_poke_window.value()),
            "boost_probability": round(self.spin_boost_prob.value(), 2),
            "boost_duration_seconds": int(self.spin_boost_duration.value()),
            "interaction_window_seconds": int(self.spin_interaction_window.value()),
        }
        for name in ("sleep_start", "wake_time"):
            value = sleep_values[name]
            if sleep_installed and not self._valid_hhmm(value):
                QMessageBox.warning(
                    self, "时间无效", f"「{value or '空'}」不是有效的 HH:MM 时间。"
                )
                return

        def task():
            changed = []
            if sleep_installed:
                conf = self.client.get_plugin_config(SLEEP_PLUGIN)
                conf.update(sleep_values)
                self.client.put_plugin_config(SLEEP_PLUGIN, conf)
                self.client.reload_plugin(SLEEP_PLUGIN)
                changed.append("作息")
            if cont_installed:
                conf = self.client.get_plugin_config(CONTINUITY_PLUGIN)
                conf.update(cont_values)
                self.client.put_plugin_config(CONTINUITY_PLUGIN, conf)
                self.client.reload_plugin(CONTINUITY_PLUGIN)
                changed.append("接话")
            return changed

        def done(changed):
            self.behavior_result.setText(
                f"已保存：作息 {sleep_values['sleep_start']}~{sleep_values['wake_time']}，"
                f"必回概率 {cont_values['boost_probability']:.0%}。"
            )
            self._set_status(
                f"作息与接话已保存并重载：{'、'.join(changed) or '（无已安装插件）'}",
                True,
            )
            self._load_behavior_ui()

        self._run_task(task, done, "正在保存作息与接话…")

    @staticmethod
    def _valid_hhmm(text: str) -> bool:
        parts = text.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            return False
        hour, minute = int(parts[0]), int(parts[1])
        return 0 <= hour <= 23 and 0 <= minute <= 59
