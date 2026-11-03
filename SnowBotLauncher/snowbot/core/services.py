"""端口探测、进程控制与 AstrBot/NapCat 服务管理。"""
import json
import os
import shutil
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
    # Windows 的 TCP 表偶尔会把监听态报成 NONE/CLOSED（进程仍在正常服务），
    # 不管有没有拿到连接列表，都用实际 TCP 连接兜底，避免状态误判成“已停止”。
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False


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


class QqHealthMonitor:
    """QQ/NapCat 掉线监控：区分「WS 抖动」与「QQ 真掉线」。

    - 主动停止 NapCat 不算掉线；
    - NapCat 日志里出现 `KickedOffLine` / `账号状态变更为离线` 是确凿的登录失效（需重新扫码）；
    - 仅 6199 连接断开多半是反向 WS 抖动，NapCat 会 30 秒自动重连，不算掉线；
    - 掉线/恢复/QQ 版本变化都写进 qq_health.json，便于统计频率。
    """

    CONFIRM_TICKS = 2
    OFFLINE_MARK_RE = re.compile(r"KickedOffLine|账号状态变更为离线")
    LOG_TIME_RE = re.compile(r"(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})")

    def __init__(self, data_dir: Path, napcat_log_dir: Path | None = None):
        self.data_dir = Path(data_dir)
        self.napcat_log_dir = Path(napcat_log_dir) if napcat_log_dir else None
        self.events_path = self.data_dir / "qq_health.json"
        self._online: bool | None = None
        self._down_ticks = 0
        self._offline_since: float | None = None
        self._last_version = ""
        self._last_marker_ts = 0.0
        self._events: list[dict] = []
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.events_path.read_text(encoding="utf-8"))
            self._events = data.get("events", [])[-200:]
            self._last_version = str(data.get("qq_version") or "")
        except Exception:
            self._events = []

    def _save(self) -> None:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.events_path.write_text(
                json.dumps(
                    {"qq_version": self._last_version, "events": self._events[-200:]},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    def napcat_offline_marker(self) -> float:
        """读最新 NapCat 日志尾部，返回最后一次「登录失效」的时间戳（0 表示没有）。

        只读文件尾部 64KB，开销很小；`反向WebSocket 连接意外关闭` 不算（那是抖动，会自动重连）。
        """
        if self.napcat_log_dir is None or not self.napcat_log_dir.is_dir():
            return 0.0
        try:
            logs = sorted(
                self.napcat_log_dir.glob("*.log"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not logs:
                return 0.0
            newest = logs[0]
            size = newest.stat().st_size
            with open(newest, "rb") as f:
                f.seek(max(0, size - 65536))
                tail = f.read().decode("utf-8", "ignore")
        except Exception:
            return 0.0
        year = time.localtime().tm_year
        for line in reversed(tail.splitlines()):
            if not self.OFFLINE_MARK_RE.search(line):
                continue
            match = self.LOG_TIME_RE.search(line)
            if not match:
                continue
            month, day, hour, minute, sec = (int(g) for g in match.groups())
            try:
                return time.mktime((year, month, day, hour, minute, sec, 0, 0, -1))
            except Exception:
                return 0.0
        return 0.0

    def qrcode_waiting(self, within_minutes: int = 30) -> bool:
        """NapCat 正在等扫码：cache/qrcode.png 在最近 N 分钟内被刷新过。

        未登录时 NapCat 会周期性重写这个二维码文件；登录后就不再更新。
        """
        if self.napcat_log_dir is None:
            return False
        try:
            qr = self.napcat_log_dir.parent / "cache" / "qrcode.png"
            if not qr.exists():
                return False
            age = time.time() - qr.stat().st_mtime
            return 0 <= age <= max(1, int(within_minutes)) * 60
        except Exception:
            return False

    def update(
        self,
        *,
        connected: bool,
        napcat_running: bool,
        qq_version: str = "",
        offline_marker: float = 0.0,
        now: float | None = None,
    ) -> list[dict]:
        """喂入一次状态采样，返回本次需要通知的事件（可能为空）。"""
        now = time.time() if now is None else now
        events: list[dict] = []

        # QQ 版本变化（多半是自动更新，会引发设备指纹变化）
        if qq_version and self._last_version and qq_version != self._last_version:
            rec = {
                "type": "version_change",
                "time": now,
                "detail": f"QQ 版本由 {self._last_version} 变为 {qq_version}",
            }
            events.append(rec)
            self._events.append(rec)
        if qq_version:
            self._last_version = qq_version

        if not napcat_running:
            # 进程没了（用户主动停止或崩溃）：清状态，不告警
            self._online = None
            self._down_ticks = 0
            self._offline_since = None
            self._last_marker_ts = 0.0
            self._save()
            return events

        # 日志里有新的「登录失效」标记 → 确凿掉线（不用防抖）
        new_marker = offline_marker and offline_marker > self._last_marker_ts
        if new_marker:
            self._last_marker_ts = offline_marker

        self._down_ticks = 0 if (connected and not new_marker) else self._down_ticks + 1
        confirmed_offline = new_marker or (
            self._down_ticks >= self.CONFIRM_TICKS and not connected
        )

        if confirmed_offline:
            if self._online is not False:
                rec = {
                    "type": "offline",
                    "time": now,
                    "detail": (
                        "QQ 登录失效，需要重新扫码"
                        if new_marker
                        else "QQ 掉线：NapCat 在运行但连接中断"
                    ),
                }
                events.append(rec)
                self._events.append(rec)
                self._online = False
                self._offline_since = now
        elif connected:
            if self._online is False and self._offline_since is not None:
                minutes = max(0, int((now - self._offline_since) / 60))
                rec = {
                    "type": "online",
                    "time": now,
                    "detail": f"QQ 恢复在线（掉线约 {minutes} 分钟）",
                    "offline_minutes": minutes,
                }
                events.append(rec)
                self._events.append(rec)
            self._online = True
            self._offline_since = None
        self._save()
        return events

    @property
    def last_offline(self) -> dict | None:
        for rec in reversed(self._events):
            if rec.get("type") == "offline":
                return rec
        return None

    def offline_count_today(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        return sum(
            1
            for r in self._events
            if r.get("type") == "offline"
            and time.strftime("%Y-%m-%d", time.localtime(float(r.get("time", 0)))) == day
        )


class ServiceManager:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.procs = {"astrbot": None, "napcat": None, "snowluma": None}
        self.started_at = {"astrbot": None, "napcat": None, "snowluma": None}
        self.log_files = {}
        LOG_DIR.mkdir(exist_ok=True)

    # ---------- QQ 协议端 ----------
    def qq_backend(self) -> str:
        return "snowluma" if str(self.cfg.get("qq_backend") or "").lower() == "snowluma" else "napcat"

    def qq_backend_label(self) -> str:
        return "SnowLuma" if self.qq_backend() == "snowluma" else "NapCat"

    def snowluma_dir(self) -> Path:
        return Path(str(self.cfg.get("snowluma_dir") or r"C:\SnowLuma"))

    def snowluma_webui_port(self) -> int:
        try:
            return int(self.cfg.get("snowluma_webui_port") or 5099)
        except Exception:
            return 5099

    def snowluma_account(self) -> str:
        cfgdir = self.snowluma_dir() / "config"
        try:
            for f in sorted(cfgdir.glob("onebot_*.json")):
                num = f.stem.replace("onebot_", "")
                if num.isdigit() and 5 <= len(num) <= 12:
                    return num
        except Exception:
            pass
        return ""

    def snowluma_log_file(self):
        p = LOG_DIR / "snowluma_console.log"
        return p if p.exists() else None

    def _ensure_snowluma_runtime(self) -> None:
        """确保 SnowLuma 自动注入 QQ，并使用启动器配置的 WebUI 端口。"""
        cfgdir = self.snowluma_dir() / "config"
        cfgdir.mkdir(parents=True, exist_ok=True)
        path = cfgdir / "runtime.json"
        data = {}
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        data["webuiPort"] = self.snowluma_webui_port()
        data["webuiHost"] = "127.0.0.1"
        data["hookAutoLoad"] = True
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- 状态 ----------
    def status(self) -> dict:
        conns = list_tcp_connections()
        dash = int(self.cfg["dashboard_port"])
        ob = int(self.cfg["onebot_port"])
        nc = int(self.cfg["napcat_port"])
        backend = self.qq_backend()
        webui_port = self.snowluma_webui_port() if backend == "snowluma" else nc

        astrbot_up = port_listening(dash, conns)
        qq_up = port_listening(webui_port, conns)
        qqs = qq_processes()

        return {
            "astrbot_up": astrbot_up,
            "astrbot_pid": listening_pid(dash, conns),
            "qq_backend": backend,
            "qq_label": "SnowLuma" if backend == "snowluma" else "NapCat",
            "qq_up": qq_up,
            "qq_pid": listening_pid(webui_port, conns),
            "qq_webui": f"http://127.0.0.1:{webui_port}",
            "qq_webui_port": webui_port,
            # 兼容旧界面字段
            "napcat_up": qq_up,
            "napcat_pid": listening_pid(webui_port, conns),
            "qq_running": bool(qqs),
            "qq_pids": [p.pid for p in qqs],
            "onebot_connected": onebot_connected(ob, conns),
            "token": self.napcat_token() if backend == "napcat" else "",
            "qq": self.snowluma_account() if backend == "snowluma" else self.napcat_account(),
            "astrbot_started_at": self.started_at.get("astrbot"),
            "napcat_started_at": self.started_at.get(backend),
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

    # ---------- SnowLuma（外部安装，启动器只负责启停） ----------
    def start_snowluma(self):
        d = self.snowluma_dir()
        if not (d / "index.mjs").exists():
            return False, f"SnowLuma 目录无效：{d}（需要 index.mjs）"
        if port_listening(self.snowluma_webui_port()):
            return False, "SnowLuma 已在运行"
        node = str(self.cfg.get("node_exe") or "").strip() or shutil.which("node")
        if not node:
            return False, "找不到 Node.js（SnowLuma 需要 24+，可在设置里指定 node.exe）"
        self._ensure_snowluma_runtime()
        # SnowLuma 注入的是已运行的 QQ 进程；没开 QQ 就先拉起来（不带 -q，由用户扫码）。
        if not qq_processes():
            qq_exe = Path(str(self.cfg.get("qq_exe") or r"C:\Program Files\Tencent\QQNT\QQ.exe"))
            if not qq_exe.exists():
                return False, f"QQ 程序不存在：{qq_exe}"
            try:
                subprocess.Popen(
                    [str(qq_exe)],
                    cwd=str(qq_exe.parent),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            except Exception as exc:
                return False, f"启动 QQ 失败：{exc}"
        LOG_DIR.mkdir(exist_ok=True)
        log_path = LOG_DIR / "snowluma_console.log"
        log_f = open(log_path, "ab", buffering=0)
        log_f.write(f"\n===== {now_str()} 启动 SnowLuma =====\n".encode("utf-8"))
        try:
            p = subprocess.Popen(
                [node, "index.mjs"],
                cwd=str(d),
                stdout=log_f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
                | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        except Exception as exc:
            log_f.close()
            return False, f"启动失败：{exc}"
        finally:
            try:
                log_f.close()
            except Exception:
                pass
        self.procs["snowluma"] = p
        self.started_at["snowluma"] = time.time()
        return (
            True,
            f"SnowLuma 启动中，WebUI：http://127.0.0.1:{self.snowluma_webui_port()}",
        )

    def stop_snowluma(self):
        stopped = False
        p = self.procs.get("snowluma")
        if p and p.poll() is None:
            kill_tree(p.pid)
            stopped = True
        d = str(self.snowluma_dir()).lower()
        for proc in psutil.process_iter(["pid", "name", "cmdline", "cwd"]):
            try:
                name = (proc.info["name"] or "").lower()
                cmd = " ".join(proc.info.get("cmdline") or [])
                cwd = (proc.info.get("cwd") or "").lower()
                if name.startswith("node") and "index.mjs" in cmd and d in cwd:
                    kill_tree(proc.pid)
                    stopped = True
            except Exception:
                continue
        for proc in qq_processes():
            try:
                proc.kill()
                stopped = True
            except Exception:
                pass
        self.started_at["snowluma"] = None
        return (
            (True, "SnowLuma / QQ 已停止")
            if stopped
            else (False, "SnowLuma / QQ 未在运行")
        )

    # 统一入口：界面只关心“QQ 协议端”，具体后端由配置决定。
    def start_qq(self):
        return self.start_snowluma() if self.qq_backend() == "snowluma" else self.start_napcat()

    def stop_qq(self):
        return self.stop_snowluma() if self.qq_backend() == "snowluma" else self.stop_napcat()

    def start_all(self):
        msgs = []
        ok1, m1 = self.start_astrbot()
        msgs.append(m1)
        ok2, m2 = self.start_qq()
        msgs.append(m2)
        # “已经在运行”对一键启动来说属于成功，不应弹黄色警告。
        ok1 = ok1 or "已在运行" in m1
        ok2 = ok2 or "已在运行" in m2
        return bool(ok1 and ok2), "；".join(msgs)

    def stop_all(self):
        msgs = []
        ok1, m1 = self.stop_astrbot()
        msgs.append(m1)
        ok2, m2 = self.stop_qq()
        msgs.append(m2)
        return ok1 or ok2, "；".join(msgs)
