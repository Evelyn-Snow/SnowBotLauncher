"""配置读写与 AstrBot 信息读取。"""
import ctypes
from datetime import datetime
import json
import os
import sys
from pathlib import Path

from .paths import APP_DIR, CONFIG_PATH, DATA_DIR

DEFAULT_CONFIG = {
    "astrbot_dir": r"C:\Users\Administrator\AstrBot",
    "napcat_dir": r"C:\NapCat\NapCat.Shell",
    "python_exe": r"C:\Users\Administrator\AstrBot\.venv\Scripts\python.exe",
    "dashboard_port": 6185,
    "onebot_port": 6199,
    "napcat_port": 6099,
    "close_to_tray": True,
    "start_minimized": False,
    "autostart": False,
    "autostart_services": False,
}

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def astrbot_dashboard_info(cfg: dict) -> dict:
    """从 AstrBot 的 cmd_config.json 读取后台账号与端口（不读密码）。"""
    try:
        path = Path(cfg.get("astrbot_dir", "")) / "data" / "cmd_config.json"
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        dashboard = data.get("dashboard") or {}
        return {
            "username": str(dashboard.get("username") or ""),
            "port": int(dashboard.get("port") or cfg.get("dashboard_port", 6185)),
        }
    except Exception:
        return {}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    candidates = [CONFIG_PATH, DATA_DIR / "launcher_config.json", APP_DIR / "launcher_config.json"]
    for path in candidates:
        try:
            if path.exists():
                cfg.update(json.loads(path.read_text(encoding="utf-8")))
                break
        except Exception:
            continue
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def launcher_command() -> list:
    """返回启动控制台自身的命令（兼容 PyInstaller 冻结后的 exe）。"""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    return [str(pythonw), str(APP_DIR / "app.py")]
