"""配置读写与 AstrBot 信息读取。"""
import ctypes
from datetime import datetime
import json
import os
import sys
from pathlib import Path

from .paths import APP_DIR, CONFIG_PATH, DATA_DIR

def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def discover_napcat_dir() -> Path:
    """定位常见的 NapCat Shell 目录。"""
    candidates = [
        Path(r"C:\NapCat\NapCat.Shell"),
        Path.home() / "NapCat" / "NapCat.Shell",
        Path(r"C:\NapCat"),
    ]
    for path in candidates:
        if (path / "launcher.bat").is_file():
            return path
    return candidates[0]


def _astrbot_candidates() -> list[tuple[float, Path, Path, int]]:
    """返回 (修改时间, core, python, dashboard_port) 候选。"""
    result: list[tuple[float, Path, Path, int]] = []
    instances = Path.home() / ".astrbot_launcher" / "instances"
    if instances.is_dir():
        for inst in instances.iterdir():
            try:
                core = inst / "core"
                py = inst / "venv" / "Scripts" / "python.exe"
                main_py = core / "main.py"
                if not (main_py.is_file() and py.is_file()):
                    continue
                cmd_cfg = core / "data" / "cmd_config.json"
                dashboard = _read_json(cmd_cfg).get("dashboard") or {}
                port = int(dashboard.get("port") or 0)
                mtime = max(
                    main_py.stat().st_mtime,
                    cmd_cfg.stat().st_mtime if cmd_cfg.exists() else 0,
                )
                result.append((mtime, core, py, port))
            except Exception:
                continue

    legacy = Path(os.environ.get("ASTRBOT_DIR") or r"C:\Users\Administrator\AstrBot")
    legacy_py = Path(
        os.environ.get("ASTRBOT_PYTHON")
        or legacy / ".venv" / "Scripts" / "python.exe"
    )
    try:
        if (legacy / "main.py").is_file() and legacy_py.is_file():
            cmd_cfg = legacy / "data" / "cmd_config.json"
            dashboard = _read_json(cmd_cfg).get("dashboard") or {}
            result.append(
                (
                    (legacy / "main.py").stat().st_mtime,
                    legacy,
                    legacy_py,
                    int(dashboard.get("port") or 0),
                )
            )
    except Exception:
        pass

    result.sort(key=lambda item: item[0], reverse=True)
    return result


def discover_astrbot() -> dict:
    """优先发现官方启动器实例，其次兼容旧版源码目录。"""
    candidates = _astrbot_candidates()
    if not candidates:
        return {}
    _, core, python_exe, port = candidates[0]
    found = {"astrbot_dir": str(core), "python_exe": str(python_exe)}
    if port:
        found["dashboard_port"] = port
    return found


def default_config() -> dict:
    cfg = {
        "astrbot_dir": "",
        "napcat_dir": str(discover_napcat_dir()),
        "python_exe": "",
        "dashboard_port": 6185,
        "onebot_port": 6199,
        "napcat_port": 6099,
        "close_to_tray": True,
        "start_minimized": False,
        "autostart": False,
        "autostart_services": False,
        "napcat_quick_login": True,
        "owner_qq": "",
        "owner_name": "你",
        "bot_name": "助手",
    }
    cfg.update(discover_astrbot())
    return cfg


DEFAULT_CONFIG = default_config()

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
            # 设置页/启动环境变量优先，避免修改端口后增强配置仍连旧端口。
            "port": int(cfg.get("dashboard_port") or dashboard.get("port") or 6185),
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
    return [str(pythonw), str(APP_DIR / "main.py")]
