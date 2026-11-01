"""增强配置页分栏。"""

from __future__ import annotations

from .common import (
    ApiError,
    MEMORY_ID,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    Qt,
    json,
    set_path,
    urllib,
)


class MemoryMixin:
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

        self.mem_result = QLabel("")
        self.mem_result.setWordWrap(True)
        self.mem_result.setObjectName("muted")
        self.mem_result.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        mem_result_row = QHBoxLayout()
        mem_result_row.addWidget(self.mem_result, 1)
        copy_mem = QPushButton("复制")
        copy_mem.setObjectName("ghost")
        copy_mem.clicked.connect(
            lambda: self._copy_result(self.mem_result.text(), "记忆信息")
        )
        mem_result_row.addWidget(copy_mem)
        layout.addLayout(mem_result_row)
        layout.addStretch(1)
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
