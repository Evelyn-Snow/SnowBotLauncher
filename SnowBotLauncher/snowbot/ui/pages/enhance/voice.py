"""增强配置页分栏。"""

from __future__ import annotations

from ....astrbot.seed_audio_patch import patch_seed_audio_source

from .common import (
    ApiError,
    DATA_DIR,
    EDGE_VOICES,
    Path,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    Qt,
    TTS_IDS,
    base64,
    shutil,
    tempfile,
    zip_folder,
)


class VoiceMixin:
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
        self.voice_prob.setValue(0.08)
        top.addWidget(self.voice_prob)
        top.addStretch(1)
        layout.addLayout(top)

        self.voice_stack = QStackedWidget()
        self.voice_stack.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.voice_stack.setMinimumHeight(180)
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
        doubao_layout = QVBoxLayout(doubao_page)
        doubao_layout.setContentsMargins(0, 0, 0, 0)
        doubao_form = QFormLayout()
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
        doubao_layout.addLayout(doubao_form)

        burst_group = QGroupBox("自发语音惯性调度（明确说“语音”仍必发）")
        burst_form = QFormLayout(burst_group)
        burst_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.doubao_burst_prob = QDoubleSpinBox()
        self.doubao_burst_prob.setRange(0.0, 1.0)
        self.doubao_burst_prob.setSingleStep(0.05)
        self.doubao_burst_prob.setDecimals(2)
        self.doubao_burst_prob.setValue(0.4)
        self.doubao_burst_decay = QDoubleSpinBox()
        self.doubao_burst_decay.setRange(0.05, 1.0)
        self.doubao_burst_decay.setSingleStep(0.05)
        self.doubao_burst_decay.setDecimals(2)
        self.doubao_burst_decay.setValue(0.5)
        self.doubao_hourly_max = QSpinBox()
        self.doubao_hourly_max.setRange(0, 999)
        self.doubao_hourly_max.setValue(10)
        self.doubao_hourly_max.setSpecialValueText("不限")
        self.doubao_burst_reset = QSpinBox()
        self.doubao_burst_reset.setRange(60, 3600)
        self.doubao_burst_reset.setValue(600)
        self.doubao_burst_reset.setSuffix(" 秒")
        self.doubao_attempts = QSpinBox()
        self.doubao_attempts.setRange(1, 3)
        self.doubao_attempts.setValue(2)
        burst_form.addRow("刚发过语音后继续语音的概率", self.doubao_burst_prob)
        burst_form.addRow("连发逐条衰减系数", self.doubao_burst_decay)
        burst_form.addRow("每会话每小时语音上限", self.doubao_hourly_max)
        burst_form.addRow("隔多久没语音就清零惯性", self.doubao_burst_reset)
        burst_form.addRow("台词念错时的重试次数（计费）", self.doubao_attempts)
        burst_hint = QLabel(
            "平时按上方“触发概率”掷骰子；刚发过一条语音后改用“连发概率”，"
            "每多连一条再乘一次衰减系数；中间夹一条文字或隔满重置时长就回到触发概率。"
        )
        burst_hint.setWordWrap(True)
        burst_hint.setObjectName("muted")
        doubao_layout.addWidget(burst_group)
        doubao_layout.addWidget(burst_hint)

        self.doubao_plugin_label = QLabel("插件状态：未连接")
        self.doubao_plugin_label.setObjectName("muted")
        install_doubao = QPushButton("从大肥鱼配置包安装豆包语音插件")
        install_doubao.setObjectName("ghost")
        install_doubao.clicked.connect(self.install_doubao_plugin)
        doubao_layout.addWidget(self.doubao_plugin_label)
        doubao_layout.addWidget(install_doubao)
        doubao_layout.addStretch(1)
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

        self.voice_result = QLabel("")
        self.voice_result.setWordWrap(True)
        self.voice_result.setObjectName("muted")
        self.voice_result.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        voice_result_row = QHBoxLayout()
        voice_result_row.addWidget(self.voice_result, 1)
        copy_voice = QPushButton("复制")
        copy_voice.setObjectName("ghost")
        copy_voice.clicked.connect(
            lambda: self._copy_result(self.voice_result.text(), "语音信息")
        )
        voice_result_row.addWidget(copy_voice)
        layout.addLayout(voice_result_row)
        layout.addStretch(1)
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
        self.voice_prob.setValue(float(settings.get("trigger_probability", 0.08)))
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
            self.doubao_burst_prob.setValue(
                float(provider.get("seed_audio_burst_probability") or 0.4)
            )
            self.doubao_burst_decay.setValue(
                float(provider.get("seed_audio_burst_decay") or 0.5)
            )
            self.doubao_hourly_max.setValue(
                int(provider.get("seed_audio_hourly_max") or 0)
            )
            self.doubao_burst_reset.setValue(
                int(float(provider.get("seed_audio_burst_reset_seconds") or 600))
            )
            self.doubao_attempts.setValue(int(provider.get("seed_audio_max_attempts") or 2))
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
                    "seed_audio_whole_reply": True,
                    "seed_audio_reply_probability": prob,
                    "seed_audio_burst_probability": float(self.doubao_burst_prob.value()),
                    "seed_audio_burst_decay": float(self.doubao_burst_decay.value()),
                    "seed_audio_burst_reset_seconds": int(self.doubao_burst_reset.value()),
                    "seed_audio_hourly_max": int(self.doubao_hourly_max.value()),
                    "seed_audio_max_attempts": int(self.doubao_attempts.value()),
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
            # 重新读取配置，避免用连接时的旧快照覆盖刚写入的提供商
            config = self.client.get_profile()
            settings = config.setdefault("provider_tts_settings", {})
            settings.update(
                {
                    "enable": bool(global_enable and ok),
                    "provider_id": provider["id"],
                    "trigger_probability": prob,
                }
            )
            self.client.put_profile(config)
            self.config = config
            return ok, why, provider["id"]

        def done(result):
            ok, why, pid = result
            if ok:
                note = "豆包由插件掷骰子并整条合成，首次回复会等 15~35 秒。" if pid == TTS_IDS["doubao"] else ""
                self.voice_result.setText(f"语音已启用：{pid}。{note}")
                self._set_status(f"语音已保存并测试通过：{pid}", True)
            else:
                hint = self._voice_error_hint(why)
                self.voice_result.setText(
                    f"语音测试未通过：{why}{hint}\n已先把提供商停用，处理后重新保存。"
                )
                self._set_status("语音已保存但测试失败，已停用", False)

        self._run_task(task, done, "正在保存并测试语音…")

    def disable_voice(self):
        if not self._need_client():
            return

        def task():
            config = self.client.get_profile()
            settings = config.setdefault("provider_tts_settings", {})
            settings["enable"] = False
            self.client.put_profile(config)
            self.config = config
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
                main_py.write_text(
                    patch_seed_audio_source(main_py.read_text(encoding="utf-8")),
                    encoding="utf-8",
                )
                self.client.upload_plugin(zip_folder(patched), patched.name + ".zip")
                return self.client.list_plugins()
            finally:
                shutil.rmtree(temp_root, ignore_errors=True)

        def done(plugins):
            self.plugins = plugins
            self.doubao_plugin_label.setText("插件状态：已安装")
            self._set_status("豆包语音插件已安装", True)

        self._run_task(task, done, "正在安装豆包语音插件…")
