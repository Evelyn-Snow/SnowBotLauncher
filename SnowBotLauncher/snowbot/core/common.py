"""启动器通用小工具：JSON 原子读写、URL 归一化、端口/进程快照。"""

from __future__ import annotations

import json
import os
import socket
import tempfile
from pathlib import Path

import psutil


def read_json(path: str | Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return {} if default is None else default


def write_json_atomic(path: str | Path, data) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_name, target)
    finally:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


def normalize_base_url(value: str) -> str:
    url = str(value or "").strip().rstrip("/")
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url


def list_tcp_connections():
    try:
        return psutil.net_connections(kind="tcp")
    except Exception:
        return []


def port_snapshot(port: int, conns=None) -> dict:
    """一次扫描返回端口是否监听 + 监听 pid；Windows 状态异常时用连接兜底。"""
    try:
        port = int(port)
    except (TypeError, ValueError):
        return {"listening": False, "pid": None}
    conns = conns if conns is not None else list_tcp_connections()
    for conn in conns:
        try:
            if (
                conn.status == psutil.CONN_LISTEN
                and conn.laddr
                and conn.laddr.port == port
            ):
                return {"listening": True, "pid": conn.pid}
        except Exception:
            continue
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            listening = sock.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        listening = False
    return {"listening": listening, "pid": None}


def pid_matches(pid: int, names=(), cmd_markers=()) -> bool:
    """确认 pid 是否是我们预期的服务，避免按端口误杀无关进程。"""
    if not pid:
        return False
    names = tuple(str(x).lower() for x in names if x)
    markers = tuple(str(x).lower() for x in cmd_markers if x)
    if not names and not markers:
        return False
    try:
        proc = psutil.Process(int(pid))
        name = (proc.name() or "").lower()
        if names and name in names:
            return True
        if markers:
            try:
                cmdline = " ".join(proc.cmdline()).lower()
            except Exception:
                cmdline = ""
            if any(marker in cmdline for marker in markers):
                return True
    except Exception:
        return False
    return False
