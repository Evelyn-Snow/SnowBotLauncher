"""增强配置页的共享常量、Qt 导入与后台任务。"""

from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlsplit

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
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
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ....astrbot.client import ApiError, AstrBotClient, get_path, set_path, zip_folder
from ....core.config import save_config
from ....core.paths import APP_DIR, DATA_DIR, PERSONAS_DIR
from ....core.persona_files import (
    import_persona_file,
    list_persona_files,
    read_persona_file,
    render_persona,
    safe_stem,
    write_persona_file,
)
from ....core.services import port_listening
from ....core.vision_config import apply_vision_mode, clear_vision_mode
from ...widgets import scroll_page

__all__ = [
    "ApiError",
    "AstrBotClient",
    "APP_DIR",
    "DATA_DIR",
    "EDGE_VOICES",
    "MEME_EXT",
    "MEMORY_ID",
    "PERSONAS_DIR",
    "Path",
    "QApplication",
    "QCheckBox",
    "QComboBox",
    "QDesktopServices",
    "QDoubleSpinBox",
    "QFileDialog",
    "QFormLayout",
    "QGridLayout",
    "QGroupBox",
    "QHBoxLayout",
    "QLabel",
    "QLineEdit",
    "QListWidget",
    "QListWidgetItem",
    "QMessageBox",
    "QPlainTextEdit",
    "QPushButton",
    "QScrollArea",
    "QSizePolicy",
    "QSpinBox",
    "QStackedWidget",
    "QTabWidget",
    "QThread",
    "QTimer",
    "QUrl",
    "QVBoxLayout",
    "QWidget",
    "Qt",
    "Signal",
    "TTS_IDS",
    "VISION_PRESETS",
    "Worker",
    "_list_from",
    "apply_vision_mode",
    "base64",
    "clear_vision_mode",
    "get_path",
    "import_persona_file",
    "json",
    "list_persona_files",
    "os",
    "port_listening",
    "quote",
    "read_persona_file",
    "render_persona",
    "safe_stem",
    "scroll_page",
    "save_config",
    "set_path",
    "shutil",
    "tempfile",
    "urllib",
    "urlsplit",
    "write_persona_file",
    "zip_folder",
]


MEME_EXT = "/plug/meme_manager"
EDGE_VOICES = [
    "zh-CN-XiaoyiNeural",
    "zh-CN-XiaoxiaoNeural",
    "zh-CN-YunxiNeural",
    "zh-CN-YunjianNeural",
    "zh-CN-YunxiaNeural",
    "zh-CN-YunyangNeural",
    "zh-CN-liaoning-XiaobeiNeural",
    "zh-CN-shaanxi-XiaoniNeural",
]
TTS_IDS = {"edge": "snowbot-tts-edge", "mimo": "snowbot-tts-mimo", "doubao": "snowbot-tts-doubao"}
MEMORY_ID = "snowbot-memory"
VISION_PRESETS = [
    {
        "label": "智谱 GLM-4V-Flash（免费额度）",
        "id": "snowbot-vision-zhipu",
        "base": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4v-flash",
    },
    {
        "label": "阿里云百炼 Qwen-VL（兼容模式）",
        "id": "snowbot-vision-qwen",
        "base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-vl-plus",
    },
    {
        "label": "硅基流动 Qwen2.5-VL",
        "id": "snowbot-vision-siliconflow",
        "base": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen2.5-VL-7B-Instruct",
    },
    {
        "label": "本机 Ollama（需先拉取视觉模型）",
        "id": "snowbot-vision-ollama",
        "base": "http://127.0.0.1:11434/v1",
        "model": "",
    },
]


class Worker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as exc:
            self.failed.emit(str(exc))


def _list_from(result: dict, *keys) -> list:
    data = result.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), list):
                return data[key]
    for key in keys:
        if isinstance(result.get(key), list):
            return result[key]
    return []


