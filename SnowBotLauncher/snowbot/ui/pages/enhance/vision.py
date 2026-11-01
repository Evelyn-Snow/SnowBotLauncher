"""增强配置页分栏。"""

from __future__ import annotations

from .common import (
    ApiError,
    Path,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    Qt,
    VISION_PRESETS,
    apply_vision_mode,
    clear_vision_mode,
    json,
    quote,
    urllib,
)


class VisionMixin:
    def _build_vision_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 8, 0, 0)

        group = QGroupBox("视觉模型（让机器人看懂图片 / 表情包）")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)

        self.vision_preset = QComboBox()
        self.vision_preset.addItem("自定义 / 手动填写", None)
        for preset in VISION_PRESETS:
            self.vision_preset.addItem(preset["label"], preset)
        self.vision_preset.currentIndexChanged.connect(self._on_vision_preset)
        self.vision_id = QLineEdit("snowbot-vision")
        self.vision_base = QLineEdit()
        self.vision_base.setPlaceholderText("例如：https://open.bigmodel.cn/api/paas/v4")
        self.vision_key = QLineEdit()
        self.vision_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.vision_key.setPlaceholderText("API Key，仅提交给 AstrBot，不写入启动器配置")
        self.vision_model = QLineEdit()
        self.vision_model.setPlaceholderText("例如：glm-4v-flash / qwen-vl-plus")
        self.vision_status = QLabel("未连接 AstrBot")
        self.vision_status.setObjectName("muted")
        self.vision_status.setWordWrap(True)
        self.chk_vision_context = QCheckBox(
            "让视觉模型直接参与图片轮次（推荐：能同时看到聊天上下文和图片，更自然）"
        )
        self.chk_vision_context.setChecked(True)
        self.chk_vision_context.setToolTip(
            "勾选：图片消息整轮交给视觉模型，它能结合人格设定和最近聊天来理解图片。\n"
            "不勾选：只把图片转成描述交给 DeepSeek，DeepSeek 看不到画面之外的语境。"
        )
        self.chk_vision_tools = QCheckBox(
            "图片轮次保留工具调用（存图、记忆、笔记等）"
        )
        self.chk_vision_tools.setChecked(True)
        self.chk_vision_tools.setToolTip(
            "勾选后，视觉模型在带图片的消息里也能调用工具，例如把图库里的表情存下来。\n"
            "如果所选视觉模型不支持 function calling，可以取消勾选，避免请求报错。"
        )
        self._active_vision_id = ""

        form.addRow("预设", self.vision_preset)
        form.addRow("提供商 ID", self.vision_id)
        form.addRow("API Base", self.vision_base)
        form.addRow("API Key", self.vision_key)
        form.addRow("模型", self.vision_model)
        form.addRow("当前状态", self.vision_status)
        form.addRow("", self.chk_vision_context)
        form.addRow("", self.chk_vision_tools)

        buttons = QHBoxLayout()
        self.btn_vision_save = QPushButton("保存并启用视觉")
        self.btn_vision_save.setObjectName("primary")
        self.btn_vision_save.clicked.connect(self.save_vision_provider)
        self.btn_vision_test = QPushButton("测试连接")
        self.btn_vision_test.setObjectName("ghost")
        self.btn_vision_test.clicked.connect(self.test_vision_provider)
        self.btn_vision_import = QPushButton("导入 JSON…")
        self.btn_vision_import.setObjectName("ghost")
        self.btn_vision_import.clicked.connect(self.import_vision_json)
        self.btn_vision_ollama = QPushButton("检测 Ollama 视觉模型")
        self.btn_vision_ollama.setObjectName("ghost")
        self.btn_vision_ollama.clicked.connect(self.detect_ollama_vision)
        self.btn_vision_disable = QPushButton("关闭视觉模型")
        self.btn_vision_disable.setObjectName("danger")
        self.btn_vision_disable.clicked.connect(self.disable_vision)
        for button in (
            self.btn_vision_save,
            self.btn_vision_test,
            self.btn_vision_import,
            self.btn_vision_ollama,
            self.btn_vision_disable,
        ):
            buttons.addWidget(button)
        buttons.addStretch(1)
        form.addRow("", buttons)

        hint = QLabel(
            "勾选「直接参与图片轮次」时：只有带图片的消息会整轮交给视觉模型，"
            "它能同时看到人格设定、最近聊天和画面，回答更贴近语境；纯文字聊天仍由 DeepSeek 负责。\n"
            "不勾选时退回图片描述模式：视觉模型只把图片转成文字，DeepSeek 再回复，"
            "更省额度，但容易只盯着图片本身。\n"
            "「图片轮次保留工具调用」让视觉模型在带图片的消息里也能存图、用记忆/笔记工具；"
            "如果模型不支持 function calling，可以取消勾选避免报错。\n"
            "支持智谱 GLM-4V / GLM-5.3、阿里云 Qwen-VL、硅基流动、任意 OpenAI 兼容视觉接口，"
            "也可以检测本机 Ollama 已拉取的视觉模型。"
            "API Base 填到 /v4 或 /v1 即可，不要带 /chat/completions；"
            "带完整接口地址时启动器会自动去掉。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        form.addRow("", hint)
        outer.addWidget(group)
        outer.addStretch(1)
        return page

    def _on_vision_preset(self, _index: int):
        preset = self.vision_preset.currentData()
        if not isinstance(preset, dict):
            return
        self.vision_id.setText(str(preset.get("id") or "snowbot-vision"))
        self.vision_base.setText(str(preset.get("base") or ""))
        self.vision_model.setText(str(preset.get("model") or ""))
        if "11434" in self.vision_base.text():
            self.vision_key.setText("ollama")
        elif not self.vision_key.text():
            self.vision_key.clear()

    def _vision_provider(self, pid: str) -> dict | None:
        if not self.client:
            return None
        for provider in self.config.get("provider", []):
            if isinstance(provider, dict) and provider.get("id") == pid:
                return provider
        try:
            result = self.client.request("GET", f"/v1/providers/{quote(pid, safe='')}")
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            provider = data.get("provider") if isinstance(data.get("provider"), dict) else data
            return provider if isinstance(provider, dict) and provider.get("id") == pid else None
        except Exception:
            return None

    def _load_vision_ui(self):
        if not self.client:
            self.vision_status.setText("未连接 AstrBot")
            return
        self.config = self.client.get_profile()
        settings = self.config.get("provider_settings", {})
        caption_id = str(settings.get("default_image_caption_provider_id") or "")
        model_cfg = (
            ((self.config.get("agent_runner") or {}).get("config") or {}).get("model")
            or {}
        )
        fallback_ids = [
            str(item) for item in (model_cfg.get("fallback_provider_ids") or [])
        ]
        context_mode = False
        active_id = caption_id
        if not active_id:
            for fallback_id in fallback_ids:
                candidate = self._vision_provider(fallback_id)
                if not isinstance(candidate, dict):
                    continue
                modalities = candidate.get("modalities")
                if isinstance(modalities, list) and "image" in modalities:
                    active_id = fallback_id
                    context_mode = True
                    break
        if not active_id:
            self._active_vision_id = ""
            self.vision_status.setText("未启用视觉模型；配置后点「保存并启用视觉」")
            return
        provider = self._vision_provider(active_id)
        if not provider:
            self.vision_status.setText(f"视觉模型指向 {active_id}，但当前找不到该提供商")
            return
        self._active_vision_id = active_id
        self.vision_id.setText(active_id)
        self.vision_base.setText(str(provider.get("api_base") or ""))
        self.vision_model.setText(str(provider.get("model") or ""))
        self.chk_vision_context.setChecked(context_mode)
        modalities = provider.get("modalities")
        self.chk_vision_tools.setChecked(
            not isinstance(modalities, list)
            or not modalities
            or "tool_use" in modalities
        )
        if context_mode:
            self.vision_status.setText(f"已启用上下文视觉模型：{active_id}")
        else:
            self.vision_status.setText(f"已启用图片描述模式：{active_id}")

    def _save_provider_v1(self, provider: dict) -> None:
        pid = str(provider["id"])
        existing = self._vision_provider(pid)
        if existing:
            merged = {**existing, **provider}
            result = self.client.request(
                "PUT", f"/v1/providers/{quote(pid, safe='')}", {"config": merged}
            )
        else:
            result = self.client.request("POST", "/v1/providers", {"config": provider})
        if not self.client.ok(result):
            raise ApiError(self.client.message(result))

    @staticmethod
    def _normalize_vision_base(base: str) -> str:
        value = str(base or "").strip().rstrip("/")
        for suffix in ("/chat/completions", "/completions", "/responses"):
            if value.lower().endswith(suffix):
                value = value[: -len(suffix)].rstrip("/")
                break
        return value

    def _test_provider_v1(self, pid: str) -> tuple[bool, str]:
        try:
            result = self.client.request(
                "POST", "/v1/providers/test", {"provider_id": pid}, timeout=90
            )
        except Exception as exc:
            return False, str(exc)
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        status = str(data.get("status") or result.get("status") or "")
        if self.client.ok(result) and status not in ("error", "unavailable", "failed"):
            return True, ""
        return False, str(
            data.get("error") or data.get("message") or self.client.message(result)
        )[:400]

    def save_vision_provider(self):
        if not self._need_client():
            return
        pid = self.vision_id.text().strip() or "snowbot-vision"
        base = self._normalize_vision_base(self.vision_base.text())
        self.vision_base.setText(base)
        key = self.vision_key.text().strip()
        model = self.vision_model.text().strip()
        if not base or not model:
            QMessageBox.warning(self, "信息不完整", "API Base 和模型名称不能为空。")
            return
        existing = self._vision_provider(pid)
        if not key and not existing:
            QMessageBox.warning(self, "缺少 API Key", "新建视觉提供商需要填写 API Key。")
            return
        keys: list[str] = []
        if key:
            keys = [key]
        elif existing:
            old_keys = existing.get("key") or existing.get("api_key") or []
            if isinstance(old_keys, list):
                keys = [str(item) for item in old_keys if str(item).strip()]
            elif str(old_keys).strip():
                keys = [str(old_keys)]
        if not keys:
            QMessageBox.warning(self, "缺少 API Key", "没有可用的 API Key，请重新填写。")
            return
        if not base.startswith(("http://", "https://")):
            QMessageBox.warning(self, "API Base 无效", "API Base 需要以 http:// 或 https:// 开头。")
            return
        modalities = ["text", "image"]
        if self.chk_vision_tools.isChecked():
            modalities.append("tool_use")
        provider = {
            "id": pid,
            "type": "openai_chat_completion",
            "provider": "openai",
            "provider_type": "chat_completion",
            "enable": True,
            "api_base": base,
            # AstrBot 的聊天提供商 key 是列表，不是单个字符串。
            "key": keys,
            "model": model,
            "modalities": modalities,
            "timeout": 60,
            "proxy": "",
        }
        try:
            self._save_provider_v1(provider)
        except Exception as exc:
            QMessageBox.warning(self, "保存视觉提供商失败", str(exc))
            return
        ok, why = self._test_provider_v1(pid)
        if not ok:
            proceed = QMessageBox.question(
                self,
                "视觉模型测试未通过",
                f"提供商已保存，但测试失败：\n{why}\n\n仍然把它设为图片视觉模型吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if proceed != QMessageBox.StandardButton.Yes:
                self.vision_status.setText(f"已保存 {pid}，但未启用：{why}")
                return
        context_mode = self.chk_vision_context.isChecked()
        old_id = str(getattr(self, "_active_vision_id", "") or "")
        profile = self.client.get_profile()
        apply_vision_mode(profile, pid, old_id=old_id, context_mode=context_mode)
        self.client.put_profile(profile)
        self.config = profile
        self._active_vision_id = pid
        self.vision_key.clear()
        if context_mode:
            self.vision_status.setText(f"已启用上下文视觉：{pid}")
        else:
            self.vision_status.setText(f"已启用图片描述模式：{pid}")
        self._set_status(
            f"视觉模型「{pid}」已保存并启用"
            + ("（上下文模式）" if context_mode else "（描述模式）")
            + ("" if ok else "（测试未通过，请检查 Key/模型权限）"),
            ok,
        )

    def test_vision_provider(self):
        if not self._need_client():
            return
        pid = self.vision_id.text().strip()
        if not pid:
            QMessageBox.information(self, "未填写", "请先填写提供商 ID。")
            return
        if not self._vision_provider(pid):
            QMessageBox.information(
                self, "尚未保存", "请先点「保存并启用视觉」，再测试连接。"
            )
            return
        self._set_status(f"正在测试视觉模型 {pid}…")
        ok, why = self._test_provider_v1(pid)
        if ok:
            QMessageBox.information(self, "测试通过", "视觉模型连接正常。")
            self._set_status("视觉模型测试通过", True)
        else:
            QMessageBox.warning(self, "测试失败", why or "提供商不可用")
            self._set_status("视觉模型测试失败", False)

    def import_vision_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视觉提供商 JSON", str(Path.home()), "JSON (*.json)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            if isinstance(data, dict) and isinstance(data.get("config"), dict):
                data = data["config"]
            if not isinstance(data, dict):
                raise ValueError("JSON 顶层必须是对象")
        except Exception as exc:
            QMessageBox.warning(self, "读取失败", str(exc))
            return
        pid = str(data.get("id") or data.get("provider_id") or "snowbot-vision")
        base = self._normalize_vision_base(
            str(data.get("api_base") or data.get("base_url") or "")
        )
        raw_key = data.get("key") or data.get("api_key") or ""
        if isinstance(raw_key, list):
            raw_key = next((item for item in raw_key if str(item).strip()), "")
        key = str(raw_key or "")
        model = str(data.get("model") or "")
        self.vision_id.setText(pid)
        self.vision_base.setText(base)
        self.vision_model.setText(model)
        if key:
            self.vision_key.setText(key)
        self.vision_status.setText("已从 JSON 填入，请点「保存并启用视觉」")
        self._set_status(f"已导入视觉提供商配置：{pid}", True)

    def detect_ollama_vision(self):
        base = self.vision_base.text().strip() or "http://127.0.0.1:11434/v1"
        root = base.rstrip("/")
        if root.endswith("/v1"):
            root = root[:-3]
        try:
            with urllib.request.urlopen(root.rstrip("/") + "/api/tags", timeout=10) as resp:
                data = json.load(resp)
        except Exception as exc:
            QMessageBox.warning(self, "Ollama 不可用", f"连不上本机 Ollama：{exc}")
            return
        vision_models = []
        for model in data.get("models", []):
            if isinstance(model, dict) and "vision" in (model.get("capabilities") or []):
                vision_models.append(str(model.get("name") or ""))
        if not vision_models:
            QMessageBox.information(
                self,
                "没有视觉模型",
                "本机 Ollama 没有已下载的视觉模型。\n\n"
                "可以先在终端执行：\n"
                "ollama pull qwen2.5vl:3b\n\n"
                "然后再点一次检测。",
            )
            return
        model = vision_models[0]
        self.vision_id.setText("snowbot-vision-ollama")
        self.vision_base.setText(root.rstrip("/") + "/v1")
        self.vision_key.setText("ollama")
        self.vision_model.setText(model)
        self.vision_status.setText(f"检测到本机视觉模型：{model}，请保存并启用")
        self._set_status(f"检测到 Ollama 视觉模型：{model}", True)

    def disable_vision(self):
        if not self._need_client():
            return
        pid = self.vision_id.text().strip() or "snowbot-vision"
        old_id = str(getattr(self, "_active_vision_id", "") or "")
        profile = self.client.get_profile()
        clear_vision_mode(profile, pid, old_id)
        self.client.put_profile(profile)
        self.config = profile
        self._active_vision_id = ""
        self.vision_status.setText("已关闭视觉模型；图片消息不再转交视觉模型")
        self._set_status("视觉模型已关闭", True)
