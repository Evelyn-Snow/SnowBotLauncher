"""程序与用户数据目录。"""
import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent

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
APP_VERSION = "1.3.2"
AUTOSTART_TASK = "SnowBotLauncher"

PRESETS_DIR = DATA_DIR / "presets"
TEMP_DIR = DATA_DIR / "temp"
for _d in (DATA_DIR, LOG_DIR, PACKS_DIR, BACKUPS_DIR, PRESETS_DIR, TEMP_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
