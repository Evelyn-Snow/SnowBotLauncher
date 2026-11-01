"""端口探测、进程控制与 AstrBot/NapCat 服务管理。"""
import json
import os
import socket
import subprocess
import time
from pathlib import Path

import psutil
import re

from .config import now_str
from .paths import FFMPEG_BIN_DIR, LOG_DIR

def list_tcp_connections():
    try:
        return psutil.net_connections(kind="tcp")
    except Exception:
        return []


def port_listening(port: int, conns=None) -> bool:
    conns = conns if conns is not None else list_tcp_connections()
    for c in conns:
        try:
            if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port:
                return True
        except Exception:
            continue
    if conns:
        return False
    # 后备方案：psutil 不可用时直接尝试连接
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def listening_pid(port: int, conns=None):
    conns = conns if conns is not None else list_tcp_connections()
    for c in conns:
        try:
            if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port:
                return c.pid
        except Exception:
            continue
    return None


def onebot_connected(port: int, conns=None) -> bool:
    conns = conns if conns is not None else list_tcp_connections()
    for c in conns:
        try:
            if c.status != psutil.CONN_ESTABLISHED:
                continue
            if (c.laddr and c.laddr.port == port) or (c.raddr and c.raddr.port == port):
                return True
        except Exception:
            continue
    return False


def qq_processes():
    result = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if (p.info["name"] or "").lower() == "qq.exe":
                result.append(p)
        except Exception:
            continue
    return result


def kill_tree(pid: int, timeout: float = 6.0) -> None:
    if not pid:
        return
    try:
        proc = psutil.Process(pid)
        procs = proc.children(recursive=True)
        procs.append(proc)
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        _, alive = psutil.wait_procs(procs, timeout=timeout)
        for p in alive:
            try:
                p.kill()
            except Exception:
                pass
    except psutil.NoSuchProcess:
        pass
    except Exception:
        pass


ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def tail_text(path: Path, max_bytes: int = 80000, max_lines: int = 700) -> str:
    try:
        if not path or not path.exists():
            return ""
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read()
        text = data.decode("utf-8", "replace")
        # AstrBot 日志带 ANSI 颜色转义码，直接显示会出现 [0m[33m 之类乱码。
        text = ANSI_RE.sub("", text)
        return "\n".join(text.splitlines()[-max_lines:])
    except Exception:
        return ""


class ServiceManager:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.procs = {"astrbot": None, "napcat": None}
        self.started_at = {"astrbot": None, "napcat": None}
        self.log_files = {}
        LOG_DIR.mkdir(exist_ok=True)

    # ---------- 状态 ----------
    def status(self) -> dict:
        conns = list_tcp_connections()
        dash = int(self.cfg["dashboard_port"])
        ob = int(self.cfg["onebot_port"])
        nc = int(self.cfg["napcat_port"])

        astrbot_up = port_listening(dash, conns)
        napcat_up = port_listening(nc, conns)
        qqs = qq_processes()

        return {
            "astrbot_up": astrbot_up,
            "astrbot_pid": listening_pid(dash, conns),
            "napcat_up": napcat_up,
            "napcat_pid": listening_pid(nc, conns),
            "qq_running": bool(qqs),
            "qq_pids": [p.pid for p in qqs],
            "onebot_connected": onebot_connected(ob, conns),
            "token": self.napcat_token(),
            "qq": self.napcat_account(),
            "astrbot_started_at": self.started_at.get("astrbot"),
            "napcat_started_at": self.started_at.get("napcat"),
        }

    # ---------- 信息读取 ----------
    def napcat_token(self) -> str:
        p = Path(self.cfg["napcat_dir"]) / "config" / "webui.json"
        try:
            return str(json.loads(p.read_text(encoding="utf-8-sig")).get("token", ""))
        except Exception:
            return ""

    def napcat_account(self) -> str:
        cfgdir = Path(self.cfg["napcat_dir"]) / "config"
        try:
            for f in cfgdir.glob("onebot11_*.json"):
                num = f.stem.replace("onebot11_", "")
                if num.isdigit():
                    return num
        except Exception:
            pass
        return ""

    def napcat_log_file(self):
        logs = list((Path(self.cfg["napcat_dir"]) / "logs").glob("*.log"))
        if not logs:
            return None
        return max(logs, key=lambda p: p.stat().st_mtime)

    # ---------- 启动 ----------
    def start_astrbot(self):
        cfg = self.cfg
        if port_listening(int(cfg["dashboard_port"])):
            return False, "AstrBot 已在运行"
        py = Path(cfg["python_exe"])
        d = Path(cfg["astrbot_dir"])
        if not py.exists():
            return False, f"Python 解释器不存在：{py}"
        if not (d / "main.py").exists():
            return False, f"AstrBot 目录无效：{d}"

        LOG_DIR.mkdir(exist_ok=True)
        log_path = LOG_DIR / "astrbot.log"
        log_f = open(log_path, "ab", buffering=0)
        log_f.write(
            f"\n===== {now_str()} 启动 AstrBot =====\n".encode("utf-8")
        )
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        # 语音发送需要 ffmpeg/ffprobe（Record 组件转 wav），优先用启动器自带的组件目录。
        if FFMPEG_BIN_DIR.is_dir():
            env["PATH"] = f"{FFMPEG_BIN_DIR}{os.pathsep}{env.get('PATH', '')}"
        # 官方启动器也是通过环境变量覆盖面板监听地址/端口，这里保持一致，
        # 否则设置页修改端口后 AstrBot 仍会绑定 cmd_config.json 里的旧端口。
        env["DASHBOARD_HOST"] = "127.0.0.1"
        env["DASHBOARD_PORT"] = str(int(cfg["dashboard_port"]))
        try:
            p = subprocess.Popen(
                [str(py), "main.py"],
                cwd=str(d),
                stdout=log_f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW
                | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        except Exception as e:
            log_f.close()
            return False, f"启动失败：{e}"
        finally:
            try:
                log_f.close()
            except Exception:
                pass

        self.procs["astrbot"] = p
        self.started_at["astrbot"] = time.time()
        self.log_files["astrbot"] = log_path
        return True, "AstrBot 启动中…"

    def _prepare_napcat_file_log(self):
        cfgdir = Path(self.cfg["napcat_dir"]) / "config"
        for name in ["napcat.json", *[f"napcat_{n}.json" for n in self._napcat_uins()]]:
            p = cfgdir / name
            if not p.exists():
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8-sig"))
                data["fileLog"] = True
                data["consoleLog"] = True
                p.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception:
                pass

    def _napcat_uins(self):
        cfgdir = Path(self.cfg["napcat_dir"]) / "config"
        uins = []
        try:
            for f in cfgdir.glob("napcat_*.json"):
                num = f.stem.replace("napcat_", "")
                if num.isdigit() and not f.stem.startswith("napcat_protocol"):
                    uins.append(num)
        except Exception:
            pass
        return uins

    def start_napcat(self):
        cfg = self.cfg
        if port_listening(int(cfg["napcat_port"])) or qq_processes():
            return False, "NapCat / QQ 已在运行"
        d = Path(cfg["napcat_dir"])
        if not (d / "launcher.bat").exists():
            return False, f"NapCat 目录无效：{d}"

        self._prepare_napcat_file_log()
        LOG_DIR.mkdir(exist_ok=True)
        log_path = LOG_DIR / "napcat_console.log"
        log_f = open(log_path, "ab", buffering=0)
        log_f.write(f"\n===== {now_str()} 启动 NapCat =====\n".encode("utf-8"))
        command = ["cmd", "/c", "launcher.bat"]
        quick_account = self.napcat_account()
        quick_login = bool(self.cfg.get("napcat_quick_login", True) and quick_account)
        if quick_login:
            # NapCat 不带 -q 时会强制走二维码登录；已保存的账号应直接快速登录。
            command.extend(["-q", quick_account])
        try:
            p = subprocess.Popen(
                command,
                cwd=str(d),
                stdout=log_f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as e:
            log_f.close()
            return False, f"启动失败：{e}"
        finally:
            try:
                log_f.close()
            except Exception:
                pass

        self.procs["napcat"] = p
        self.started_at["napcat"] = time.time()
        return (
            True,
            f"NapCat 启动中，正在快速登录 {quick_account}…"
            if quick_login
            else "NapCat 启动中，QQ 登录窗口即将出现…",
        )

    # ---------- 停止 ----------
    def stop_astrbot(self):
        pid = listening_pid(int(self.cfg["dashboard_port"]))
        p = self.procs.get("astrbot")
        if not pid and p and p.poll() is None:
            pid = p.pid
        if not pid:
            return False, "AstrBot 未在运行"
        kill_tree(int(pid))
        self.started_at["astrbot"] = None
        return True, "AstrBot 已停止"

    def stop_napcat(self):
        stopped = False
        for p in qq_processes():
            try:
                p.kill()
                stopped = True
            except Exception:
                pass
        # 关闭可能残留的引导进程
        for p in psutil.process_iter(["pid", "name"]):
            try:
                if (p.info["name"] or "").lower() == "napcatwinbootmain.exe":
                    p.kill()
                    stopped = True
            except Exception:
                continue
        pid = listening_pid(int(self.cfg["napcat_port"]))
        if pid:
            kill_tree(int(pid))
            stopped = True
        p = self.procs.get("napcat")
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
            stopped = True
        self.started_at["napcat"] = None
        return (True, "NapCat / QQ 已停止") if stopped else (False, "NapCat / QQ 未在运行")

    def start_all(self):
        msgs = []
        ok1, m1 = self.start_astrbot()
        msgs.append(m1)
        ok2, m2 = self.start_napcat()
        msgs.append(m2)
        # “已经在运行”对一键启动来说属于成功，不应弹黄色警告。
        ok1 = ok1 or "已在运行" in m1
        ok2 = ok2 or "已在运行" in m2
        return bool(ok1 and ok2), "；".join(msgs)

    def stop_all(self):
        msgs = []
        ok1, m1 = self.stop_astrbot()
        msgs.append(m1)
        ok2, m2 = self.stop_napcat()
        msgs.append(m2)
        return ok1 or ok2, "；".join(msgs)
