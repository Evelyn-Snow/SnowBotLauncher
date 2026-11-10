"""程序与用户数据目录。"""
import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    # paths.py 位于 <project>/snowbot/core/paths.py，源码模式要回到项目根目录。
    APP_DIR = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "SnowBotLauncher"
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", str(APP_DIR)))
CONFIG_PATH = DATA_DIR / "config.json"
LOG_DIR = DATA_DIR / "logs"
PACKS_DIR = DATA_DIR / "packs"
BACKUPS_DIR = DATA_DIR / "backups"
LOCK_PATH = DATA_DIR / "launcher.lock"
for _d in (DATA_DIR, LOG_DIR, PACKS_DIR, BACKUPS_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

APP_NAME = "SnowBotLauncher"
APP_VERSION = "1.5.64"
AUTOSTART_TASK = "SnowBotLauncher"
# 语音消息发送需要 ffmpeg（wav 转码）；放在启动器组件目录，随启动器统一管理。
FFMPEG_BIN_DIR = Path.home() / ".astrbot_launcher" / "components" / "ffmpeg" / "bin"

PRESETS_DIR = DATA_DIR / "presets"
PERSONAS_DIR = DATA_DIR / "personas"
TEMP_DIR = DATA_DIR / "temp"
for _d in (DATA_DIR, LOG_DIR, PACKS_DIR, BACKUPS_DIR, PRESETS_DIR, PERSONAS_DIR, TEMP_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
