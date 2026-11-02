"""安装第三方豆包语音插件（astrbot_plugin_seed_audio_tts）时打的补丁。

补丁内容（纯文本替换，方便单测）：
1. 兼容 AstrBot 4.x：get_astrbot_temp_path 已移除，改用 data/temp。
2. 用户明确要求语音（“语音/读出来/说给我听/用声音”）时跳过概率，必定合成语音。
3. 自发语音用“惯性”调度（借鉴 MaiBot 的意愿/状态思路，代替固定冷却）：
   - 基础概率用 seed_audio_reply_probability；
   - 刚发过一条语音时改用更高的惯性概率 seed_audio_burst_probability，
     每连一条乘以 seed_audio_burst_decay 衰减——偶尔连着两三句很自然，
     但不会一直语音；
   - 中间夹了一条文字就打断惯性，回到基础概率；
   - 超过 BURST_RESET_SECONDS 没发过语音，惯性清零；
   - 每小时自发语音上限 seed_audio_hourly_max，兜底控制成本。
"""

from __future__ import annotations

TEMP_PATH_OLD = "from astrbot.core.utils.astrbot_path import get_astrbot_temp_path"
TEMP_PATH_NEW = """from astrbot.core.utils.astrbot_path import get_astrbot_data_path


def get_astrbot_temp_path():
    path = os.path.join(get_astrbot_data_path(), "temp")
    os.makedirs(path, exist_ok=True)
    return path"""

DECORATOR_MARKER = "    @filter.on_decorating_result(priority=-1000)"
COOLDOWN_SECONDS = 600

CLASS_LINE = "class SeedAudioTTSPlugin(Star):\n"
CLASS_STATE = (
    "    # 自发语音的“惯性”：刚发过语音时继续语音的概率更高，逐条衰减；文字会打断。\n"
    "    BURST_RESET_SECONDS = 600  # 隔这么久没发过语音，惯性清零回到基础概率\n"
)

INIT_LINE = "        self._warned_double = False\n"
INIT_STATE = (
    "        self._streak: dict[str, int] = {}\n"
    "        self._voice_log: dict[str, list[float]] = {}\n"
)

PROB_LINE = '        self.reply_probability = float(0.33 if prob in (None, "") else prob)\n'
PROB_STATE = """        burst = c.get("seed_audio_burst_probability")
        self.burst_probability = float(0.4 if burst in (None, "") else burst)
        decay = c.get("seed_audio_burst_decay")
        self.burst_decay = float(0.5 if decay in (None, "") else decay)
        reset = c.get("seed_audio_burst_reset_seconds")
        self.burst_reset_seconds = float(600 if reset in (None, "") else reset)
        hmax = c.get("seed_audio_hourly_max")
        self.hourly_max = 10 if hmax in (None, "") else max(0, int(hmax))
"""

TMPL_LINE = '        "seed_audio_reply_probability": 0.33,\n'
TMPL_STATE = (
    '        "seed_audio_burst_probability": 0.4,\n'
    '        "seed_audio_burst_decay": 0.5,\n'
    '        "seed_audio_burst_reset_seconds": 600,\n'
    '        "seed_audio_hourly_max": 10,\n'
    '        "seed_audio_speech_rate": 30,\n'
    '        "seed_audio_reference_audio": "",\n'
)

# 补丁 5：语速与参考音频。
# audio_config 支持 speech_rate（-50~100，100≈2.0x，0=原速）；
# references 用纯 base64 的 audio_data，并在 text_prompt 里用 @Audio1 引用。
# 参考音频在配置里存「本地路径」，插件读取时才转 base64，避免配置被撑爆。
SPEED_STATE = """        rate = c.get("seed_audio_speech_rate")
        self.speech_rate = int(0 if rate in (None, "") else rate)
        self.reference_path = str(c.get("seed_audio_reference_audio") or "").strip()
"""

AUDIO_CONFIG_OLD = """            "audio_config": {
                "format": self.fmt,
                "sample_rate": self.sample_rate,
                "enable_subtitle": True,
            },
"""
AUDIO_CONFIG_NEW = """            "audio_config": {
                "format": self.fmt,
                "sample_rate": self.sample_rate,
                "enable_subtitle": True,
                "speech_rate": max(-50, min(100, int(getattr(self, "speech_rate", 0) or 0))),
            },
"""

REFERENCE_BLOCK = """        ref_path = str(getattr(self, "reference_path", "") or "").strip()
        if ref_path:
            try:
                if os.path.isfile(ref_path) and os.path.getsize(ref_path) <= 10 * 1024 * 1024:
                    with open(ref_path, "rb") as _f:
                        body["references"] = [
                            {"audio_data": base64.b64encode(_f.read()).decode()}
                        ]
            except Exception as _exc:
                logger.info(f"[SeedAudio] 参考音频读取失败，按纯文本合成：{_exc}")
"""

PROMPT_REF_NOTE = "用 @Audio1 的音色、语速和说话风格模仿；"

# 补丁 4：台词校验从「逐字全等」放宽到「相似度达标即接受」。
# 原逻辑念错一个字就整次重试，每次重试都计费（实测重试率 38%，多花约 1/3 的钱）；
# 语音里轻微的"的/了/啊"差异听不出来，相似度 ≥ 0.9 就当作念对了。
MATCH_OLD = "            match = _norm(heard) == target\n"
MATCH_NEW = """            match = _norm(heard) == target
            if not match and heard:
                # 放宽：念错少量字也算通过，避免整次重试重复计费
                ratio = difflib.SequenceMatcher(None, _norm(heard), target).ratio()
                match = ratio >= 0.9
"""

DIFFLIB_LINE = "import base64\n"
DIFFLIB_NEW = "import base64\nimport difflib\n"

DICE_OLD = "\n".join([
    "        if random.random() > prov.reply_probability:",
    "            return",
])
DICE_NEW = "\n".join([
    '        umo = str(getattr(event, "unified_msg_origin", "") or "")',
    "        force_voice = any(",
    '            k in str(event.message_str or "") for k in self.VOICE_REQUEST_KEYWORDS',
    "        )",
    "        if not force_voice:",
    "            blocked = self._voice_blocked_reason(prov, umo)",
    "            if blocked:",
    '                logger.info(f"[SeedAudio] {blocked}，保持文字")',
    "                return",
])

CHAIN_LINE = "        result.chain = new_chain\n"

HELPERS = [
    "    def _voice_blocked_reason(self, prov, umo: str) -> str:",
    '        """决定这条回复要不要保持文字：返回原因（空串表示可以发语音）。"""',
    "        now = time.time()",
    "        times = [t for t in (self._voice_log.get(umo) or []) if now - t < 3600]",
    "        self._voice_log[umo] = times",
    "        if prov.hourly_max and len(times) >= prov.hourly_max:",
    '            return f"一小时内自发语音已到 {prov.hourly_max} 条上限"',
    "        streak = self._streak.get(umo, 0)",
    "        reset = getattr(prov, \"burst_reset_seconds\", self.BURST_RESET_SECONDS)",
    "        if streak and now - (times[-1] if times else 0.0) < reset:",
    "            p = prov.burst_probability * (prov.burst_decay ** (streak - 1))",
    "            if random.random() > p:",
    "                self._streak[umo] = 0",
    '                return "语音惯性骰子未中"',
    '            return ""',
    "        if random.random() > prov.reply_probability:",
    "            self._streak[umo] = 0",
    '            return "骰子未中"',
    '        return ""',
    "",
    "    def _note_voice(self, umo: str) -> None:",
    "        if not umo:",
    "            return",
    "        now = time.time()",
    "        self._voice_log.setdefault(umo, []).append(now)",
    "        if len(self._voice_log) > 50:",
    "            oldest = min(self._voice_log, key=lambda k: self._voice_log[k][-1])",
    "            self._voice_log.pop(oldest, None)",
    "        self._streak[umo] = self._streak.get(umo, 0) + 1",
    "        if len(self._streak) > 50:",
    "            self._streak.pop(next(iter(self._streak)))",
    "",
]

FORCE_VOICE_LINES = [
    "    # 用户明确要求语音时跳过概率，必定转语音",
    '    VOICE_REQUEST_KEYWORDS = ("语音", "读出来", "说给我听", "用声音")',
    "",
    "    @filter.on_llm_request()",
    "    async def hint_voice_flow(self, event: AstrMessageEvent, req):",
    '        """用户提到语音时，告诉模型正常回复即可，系统会自动转语音。"""',
    '        text = str(event.message_str or "")',
    "        if not any(k in text for k in self.VOICE_REQUEST_KEYWORDS):",
    "            return",
    "        if self._whole_reply_provider() is None:",
    '            logger.info("[SeedAudio] 提示未注入：找不到整条语音提供商")',
    "            return",
    '        logger.info("[SeedAudio] 已注入[语音说明]提示")',
    '        req.system_prompt = (req.system_prompt or "") + (',
    '            "\\n\\n[语音说明] 语音功能已配置完成且正常工作。用户正在要求语音消息。"',
    '            "系统会自动把你的整条回复转成语音发送；不要尝试用任何工具发送语音或音频文件，"',
    '            "不要提及语音配置状态或表示语音不可用。这段说明不要在回复中提到。"',
    "        )",
    "",
]

# 装饰器提前返回时补一行日志，方便排查“为什么没转语音”。
DIAGNOSTICS = [
    (
        "\n".join([
            "        result = event.get_result()",
            "        if result is None or not result.chain or not result.is_llm_result():",
            "            return",
        ]),
        "\n".join([
            "        result = event.get_result()",
            "        if result is None or not result.chain or not result.is_llm_result():",
            "            logger.info(",
            "                f\"[SeedAudio] 装饰器跳过（非LLM结果或为空）：result={'None' if result is None else type(result).__name__}, \"",
            "                f\"llm_flag={getattr(result, 'result_content_type', 'N/A')}\"",
            "            )",
            "            return",
        ]),
    ),
    (
        "\n".join([
            "        prov = self._whole_reply_provider()",
            "        if prov is None:",
            "            return",
        ]),
        "\n".join([
            "        prov = self._whole_reply_provider()",
            "        if prov is None:",
            '            logger.info("[SeedAudio] 装饰器跳过：找不到整条语音提供商")',
            "            return",
        ]),
    ),
    (
        "\n".join([
            "        texts = [c.text.strip() for c in result.chain if isinstance(c, Plain) and c.text.strip()]",
            "        if not texts:",
            "            return",
        ]),
        "\n".join([
            "        texts = [c.text.strip() for c in result.chain if isinstance(c, Plain) and c.text.strip()]",
            "        if not texts:",
            '            logger.info("[SeedAudio] 装饰器跳过：结果里没有可合成的文字")',
            "            return",
        ]),
    ),
]
DIAG_MARKERS = ("装饰器跳过（非LLM结果或为空）", "装饰器跳过：找不到整条语音提供商", "结果里没有可合成的文字")

_ANCHORS = (DECORATOR_MARKER, DICE_OLD, CLASS_LINE, INIT_LINE, PROB_LINE, TMPL_LINE, CHAIN_LINE)


def patch_seed_audio_source(text: str) -> str:
    """返回打完全部补丁的 main.py 源码；版本对不上时自动跳过对应补丁。"""
    text = text.replace(TEMP_PATH_OLD, TEMP_PATH_NEW)
    # 各补丁自己判断是否已打过：老版本打过的文件也还能补上新功能。
    if "_voice_blocked_reason" not in text:
        # 任一锚点缺失都说明插件版本不匹配，宁可不打也不留半截补丁。
        if any(anchor not in text for anchor in _ANCHORS):
            return text
        text = text.replace(CLASS_LINE, CLASS_LINE + CLASS_STATE, 1)
        text = text.replace(INIT_LINE, INIT_LINE + INIT_STATE, 1)
        text = text.replace(PROB_LINE, PROB_LINE + PROB_STATE, 1)
        text = text.replace(TMPL_LINE, TMPL_LINE + TMPL_STATE, 1)
        helpers_and_hint = "\n".join(HELPERS) + "\n" + "\n".join(FORCE_VOICE_LINES) + "\n"
        text = text.replace(DECORATOR_MARKER, helpers_and_hint + DECORATOR_MARKER, 1)
        text = text.replace(DICE_OLD, DICE_NEW, 1)
        text = text.replace(CHAIN_LINE, CHAIN_LINE + "        self._note_voice(umo)\n", 1)
    text = _add_speed_and_reference(text)
    text = _add_match_tolerance(text)
    return _add_diagnostics(text)


PROMPT_OLD = """    def _prompt(self, text: str) -> str:
        line = text.replace("“", "「").replace("”", "」").replace('"', "")
        return self.template.format(persona=self.persona, text=line)
"""
PROMPT_NEW = """    def _prompt(self, text: str) -> str:
        line = text.replace("“", "「").replace("”", "」").replace('"', "")
        note = ""
        if str(getattr(self, "reference_path", "") or "").strip():
            note = "用 @Audio1 的音色、语速和说话风格模仿；"
        return note + self.template.format(persona=self.persona, text=line)
"""

HEADERS_OLD = "        headers = {\n"


def _add_speed_and_reference(text: str) -> str:
    """语速参数 + 参考音频（两项都改不动就整体跳过，保持插件可用）。"""
    # 用类属性判断，避免被 default_config_tmpl 里的配置键名误判成「已打过」
    if "self.speech_rate" in text:
        return text
    if AUDIO_CONFIG_OLD not in text:
        return text
    text = text.replace(AUDIO_CONFIG_OLD, AUDIO_CONFIG_NEW, 1)
    # __init__ 里补 speech_rate / reference_path
    text = text.replace(PROB_STATE, PROB_STATE + SPEED_STATE, 1)
    # references 塞在 headers 之前
    if HEADERS_OLD in text:
        text = text.replace(HEADERS_OLD, REFERENCE_BLOCK + HEADERS_OLD, 1)
    # prompt 里加 @Audio1 引用说明
    if PROMPT_OLD in text:
        text = text.replace(PROMPT_OLD, PROMPT_NEW, 1)
    return text


def _add_match_tolerance(text: str) -> str:
    """台词校验放宽到相似度 ≥ 0.9，避免念错一个字就整次重试（重试也计费）。"""
    if "SequenceMatcher" in text or MATCH_OLD not in text:
        return text
    if DIFFLIB_LINE in text and "\nimport difflib\n" not in text:
        text = text.replace(DIFFLIB_LINE, DIFFLIB_NEW, 1)
    return text.replace(MATCH_OLD, MATCH_NEW, 1)


def _add_diagnostics(text: str) -> str:
    """只加日志，改不动也不影响功能。"""
    for (old, new), marker in zip(DIAGNOSTICS, DIAG_MARKERS):
        if old in text and marker not in text:
            text = text.replace(old, new, 1)
    return text
