"""增强配置页的搜索分栏。

联网搜索由 AstrBot 内置工具链承担（provider_settings.web_search + 搜索源
Key）；搜索礼仪插件控制触发频率和表述。这里提供统一入口，避免去 WebUI
逐项找配置。
"""

from __future__ import annotations

from .common import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    Qt,
)

MANNERS_PLUGIN = "astrbot_plugin_search_manners"

SEARCH_PROVIDERS = [
    ("deepseek", "DeepSeek 搜索（可先试聊天同款 Key）"),
    ("tavily", "Tavily（免费额度 1000 次/月）"),
    ("bocha", "博查（中文效果好，按次付费）"),
    ("baidu_ai_search", "百度 AI 搜索（需千帆 Key）"),
    ("brave", "Brave Search"),
    ("exa", "Exa"),
    ("firecrawl", "Firecrawl"),
    ("anysearch", "AnySearch"),
    ("serpapi", "SerpAPI"),
]
# 百度的 Key 在 AstrBot 里是独立字符串字段，其余都是列表。
KEY_FIELDS = {name: f"websearch_{name}_key" for name, _ in SEARCH_PROVIDERS}
KEY_FIELDS["baidu_ai_search"] = "websearch_baidu_app_builder_key"


class SearchMixin:
    def _build_search_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        intro = QLabel(
            "遇到没把握的问题时可以联网查证。用户明确说「搜索 / 查一下」必定联网；"
            "平时自发搜索保持低频，并会先表明不太清楚再引用网上内容。"
        )
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        layout.addWidget(intro)

        provider_group = QGroupBox("搜索源（AstrBot 内置工具）")
        provider_form = QFormLayout(provider_group)
        provider_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        provider_form.setSpacing(9)
        self.chk_web_search = QCheckBox("启用联网搜索")
        self.combo_search_provider = QComboBox()
        for name, label in SEARCH_PROVIDERS:
            self.combo_search_provider.addItem(label, name)
        self.search_key = QLineEdit()
        self.search_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.search_key.setPlaceholderText("API Key，仅提交给 AstrBot，不写入启动器配置")
        self.search_status = QLabel("未连接 AstrBot")
        self.search_status.setObjectName("muted")
        self.search_status.setWordWrap(True)
        provider_form.addRow(self.chk_web_search)
        provider_form.addRow("搜索源", self.combo_search_provider)
        provider_form.addRow("API Key", self.search_key)
        provider_form.addRow("当前状态", self.search_status)
        layout.addWidget(provider_group)

        manners_group = QGroupBox("自发搜索频率（搜索礼仪插件）")
        manners_form = QFormLayout(manners_group)
        manners_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        manners_form.setSpacing(9)
        self.chk_manners = QCheckBox("启用搜索礼仪（低频自发 + 注明来源）")
        self.spin_search_interval = QSpinBox()
        self.spin_search_interval.setRange(0, 720)
        self.spin_search_interval.setSuffix(" 分钟")
        self.spin_search_interval.setValue(30)
        self.spin_search_daily = QSpinBox()
        self.spin_search_daily.setRange(0, 50)
        self.spin_search_daily.setValue(5)
        manners_form.addRow(self.chk_manners)
        manners_form.addRow("自发搜索最小间隔", self.spin_search_interval)
        manners_form.addRow("自发搜索每天上限", self.spin_search_daily)
        manners_hint = QLabel(
            "自发搜索指模型自己决定去查的情况；用户明确要求搜索不受这些限制。"
            "被频率挡住时机器人会直接回答并坦率说不确定。"
        )
        manners_hint.setWordWrap(True)
        manners_hint.setObjectName("muted")
        manners_form.addRow("", manners_hint)
        layout.addWidget(manners_group)

        buttons = QHBoxLayout()
        self.btn_search_save = QPushButton("保存搜索设置")
        self.btn_search_save.setObjectName("primary")
        self.btn_search_save.clicked.connect(self.save_search_settings)
        buttons.addWidget(self.btn_search_save)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)

        self.search_result = QLabel("")
        self.search_result.setWordWrap(True)
        self.search_result.setObjectName("muted")
        layout.addWidget(self.search_result)
        return page

    def _load_search_ui(self):
        if not self.client:
            return
        settings = self.config.get("provider_settings", {})
        self.chk_web_search.setChecked(bool(settings.get("web_search")))
        provider = str(settings.get("websearch_provider") or "deepseek")
        index = self.combo_search_provider.findData(provider)
        self.combo_search_provider.setCurrentIndex(index if index >= 0 else 0)
        key_field = KEY_FIELDS.get(provider, "websearch_deepseek_key")
        configured = bool(settings.get(key_field))
        self.search_key.setPlaceholderText(
            "已配置（留空保持不变）" if configured else "API Key，仅提交给 AstrBot，不写入启动器配置"
        )
        manners = self._plugin_config_or_none(MANNERS_PLUGIN)
        if manners is None:
            for widget in (
                self.chk_manners,
                self.spin_search_interval,
                self.spin_search_daily,
            ):
                widget.setEnabled(False)
            self.search_result.setText("未安装搜索礼仪插件，频率限制不可用；其余设置仍可保存。")
        else:
            self.chk_manners.setEnabled(True)
            self.chk_manners.setChecked(bool(manners.get("enabled", True)))
            self.spin_search_interval.setEnabled(True)
            self.spin_search_interval.setValue(int(manners.get("min_interval_minutes") or 30))
            self.spin_search_daily.setEnabled(True)
            self.spin_search_daily.setValue(int(manners.get("max_per_day") or 5))
            if not self.search_result.text():
                self.search_result.setText("已读取搜索礼仪插件配置。")
        self.search_status.setText(
            "已启用联网搜索" if settings.get("web_search") else "未启用联网搜索"
        )

    def save_search_settings(self):
        if not self._need_client():
            return
        # 进入后台线程前取齐控件值，避免跨线程访问 Qt 控件。
        enable = self.chk_web_search.isChecked()
        provider = str(self.combo_search_provider.currentData() or "deepseek")
        key = self.search_key.text().strip()
        manners_on = self.chk_manners.isChecked()
        interval = int(self.spin_search_interval.value())
        daily = int(self.spin_search_daily.value())
        manners_available = self.chk_manners.isEnabled()
        key_field = KEY_FIELDS.get(provider, "websearch_deepseek_key")

        def task():
            changed = []
            profile = self.client.get_profile()
            settings = profile.setdefault("provider_settings", {})
            settings["web_search"] = enable
            settings["websearch_provider"] = provider
            if key:
                if provider == "baidu_ai_search":
                    settings[key_field] = key
                else:
                    settings[key_field] = [key]
            self.client.put_profile(profile)
            self.config = profile
            changed.append("搜索源")
            if manners_available:
                manners = self.client.get_plugin_config(MANNERS_PLUGIN)
                manners["enabled"] = manners_on
                manners["min_interval_minutes"] = interval
                manners["max_per_day"] = daily
                self.client.put_plugin_config(MANNERS_PLUGIN, manners)
                self.client.reload_plugin(MANNERS_PLUGIN)
                changed.append("搜索礼仪")
            return changed, enable

        def done(result):
            changed, enable = result
            self.search_status.setText(
                "已启用联网搜索" if enable else "未启用联网搜索"
            )
            self.search_result.setText(
                f"已保存：{'、'.join(changed)}。"
                + ("保存后在对话里说「搜索一下……」即可验证。" if enable else "")
            )
            self._set_status("搜索设置已保存", True)
            self.search_key.clear()
            self._load_search_ui()

        self._run_task(task, done, "正在保存搜索设置…")
