"""AstrBot WebUI API 客户端。

封装配置包需要用到的后台接口：登录、全局配置、人格、插件、模型提供商、
PIP 安装、工具权限，以及通用的 /api/v1 请求（供扩展步骤使用）。
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Any


class ApiError(Exception):
    """API 调用失败。"""


def get_path(data: dict, dotted: str):
    cur: Any = data
    for key in dotted.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def set_path(data: dict, dotted: str, value) -> None:
    keys = dotted.split(".")
    cur = data
    for key in keys[:-1]:
        if not isinstance(cur.get(key), dict):
            cur[key] = {}
        cur = cur[key]
    cur[keys[-1]] = value


def zip_folder(folder: Path) -> bytes:
    buf = io.BytesIO()
    top = folder.name
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in folder.rglob("*"):
            if path.is_dir():
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            zf.write(path, str(Path(top) / path.relative_to(folder)))
    return buf.getvalue()


class AstrBotClient:
    def __init__(self, base_url: str, timeout: int = 30):
        self.root = base_url.rstrip("/")
        self.token: str | None = None
        self.timeout = timeout

    # ---------- 基础请求 ----------
    def call(
        self,
        method: str,
        path: str,
        body=None,
        raw_body: bytes | None = None,
        content_type: str = "application/json",
        timeout: int | None = None,
    ) -> dict:
        url = self.root + "/api/v1" + path
        data = raw_body
        if data is None and body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", content_type)
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                text = resp.read().decode("utf-8", "replace")
                code = resp.status
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")
            code = exc.code
        except Exception as exc:
            raise ApiError(f"连接 AstrBot 失败：{exc}") from exc
        try:
            payload = json.loads(text) if text else {}
        except ValueError:
            payload = {"status": "error", "message": text[:500]}
        if not isinstance(payload, dict):
            payload = {"status": "ok", "data": payload}
        payload["_http"] = code
        return payload

    @staticmethod
    def ok(result: dict) -> bool:
        return result.get("_http", 200) < 400 and result.get("status", "ok") != "error"

    @staticmethod
    def message(result: dict) -> str:
        return str(
            result.get("message") or result.get("detail") or result.get("data") or result
        )[:400]

    def require(self, result: dict) -> dict:
        if not self.ok(result):
            raise ApiError(self.message(result))
        return result

    # ---------- 认证 ----------
    def login(self, username: str, password: str) -> bool:
        for candidate in (password, hashlib.md5(password.encode("utf-8")).hexdigest()):
            result = self.call("POST", "/auth/login", {"username": username, "password": candidate})
            data = result.get("data")
            if isinstance(data, dict) and data.get("token"):
                self.token = str(data["token"])
                return True
        return False

    # ---------- 全局配置 ----------
    def get_profile(self, name: str = "default") -> dict:
        result = self.require(self.call("GET", f"/config-profiles/{urllib.parse.quote(name)}"))
        data = result.get("data") or {}
        config = data.get("config") if isinstance(data, dict) else None
        if not isinstance(config, dict):
            raise ApiError("AstrBot 返回的配置为空")
        return config

    def put_profile(self, config: dict, name: str = "default") -> None:
        self.require(self.call("PUT", f"/config-profiles/{urllib.parse.quote(name)}", config))

    # ---------- 人格 ----------
    def list_personas(self) -> list:
        result = self.call("GET", "/personas")
        data = result.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("personas", "items", "list"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []

    def get_persona(self, persona_id: str) -> dict | None:
        result = self.call(
            "GET", f"/personas/{urllib.parse.quote(persona_id, safe='')}"
        )
        data = result.get("data")
        if self.ok(result) and isinstance(data, dict) and data.get("persona_id") == persona_id:
            return data
        return None

    def upsert_persona(self, persona_id: str, system_prompt: str, extra: dict | None = None) -> None:
        current = self.get_persona(persona_id)
        qid = urllib.parse.quote(persona_id, safe="")
        if current:
            body = {
                k: v
                for k, v in current.items()
                if k in ("begin_dialogs", "skills", "folder_id", "sort_order", "custom_error_message")
            }
            body.update({"system_prompt": system_prompt, "tools": None})
            if extra:
                body.update(extra)
            self.require(self.call("PUT", f"/personas/{qid}", body))
        else:
            body = {
                "persona_id": persona_id,
                "system_prompt": system_prompt,
                "begin_dialogs": [],
                "tools": None,
            }
            if extra:
                body.update(extra)
            self.require(self.call("POST", "/personas", body))

    def delete_persona(self, persona_id: str) -> bool:
        result = self.call(
            "DELETE", f"/personas/{urllib.parse.quote(persona_id, safe='')}"
        )
        return self.ok(result)

    # ---------- 插件 ----------
    def list_plugins(self) -> list:
        result = self.call("GET", "/plugins")
        data = result.get("data")
        return data if isinstance(data, list) else []

    def plugin_installed(self, name: str) -> bool:
        for plugin in self.list_plugins():
            if isinstance(plugin, dict) and plugin.get("name") == name:
                return True
        return False

    def install_market_plugin(self, market_id: str, timeout: int = 600) -> None:
        self.require(
            self.call(
                "POST",
                "/plugins/install/github",
                {"install_method": "market", "market_plugin_id": market_id},
                timeout=timeout,
            )
        )

    def upload_plugin(self, payload: bytes, filename: str, timeout: int = 600) -> None:
        boundary = uuid.uuid4().hex
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode("utf-8")
        tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
        self.require(
            self.call(
                "POST",
                "/plugins/install/upload",
                raw_body=head + payload + tail,
                content_type=f"multipart/form-data; boundary={boundary}",
                timeout=timeout,
            )
        )

    def get_plugin_config(self, name: str) -> dict:
        result = self.call(
            "GET", f"/plugins/config?plugin_id={urllib.parse.quote(name)}"
        )
        data = result.get("data")
        config = data.get("config") if isinstance(data, dict) else None
        if not isinstance(config, dict):
            raise ApiError(f"读不到插件 {name} 的配置")
        return config

    def put_plugin_config(self, name: str, config: dict) -> None:
        self.require(
            self.call("PUT", "/plugins/config", {"plugin_id": name, "config": config})
        )

    def set_plugin_enabled(self, name: str, enabled: bool) -> None:
        self.require(
            self.call("PATCH", "/plugins/enabled", {"plugin_id": name, "enabled": bool(enabled)})
        )

    def reload_plugin(self, name: str, timeout: int = 180) -> None:
        self.require(
            self.call("POST", "/plugins/reload", {"plugin_id": name}, timeout=timeout)
        )

    # ---------- 模型提供商 ----------
    def get_provider(self, provider_id: str) -> dict | None:
        result = self.call(
            "GET", f"/providers/{urllib.parse.quote(provider_id, safe='')}"
        )
        data = result.get("data")
        if isinstance(data, dict):
            data = data.get("provider", data)
        if isinstance(data, dict) and data.get("id") == provider_id:
            return data
        return None

    def upsert_provider(self, provider: dict) -> None:
        provider_id = str(provider.get("id") or "")
        if not provider_id:
            raise ApiError("provider 缺少 id")
        current = self.get_provider(provider_id)
        if current:
            merged = {**current, **provider}
            self.require(
                self.call(
                    "PUT",
                    f"/providers/{urllib.parse.quote(provider_id, safe='')}",
                    {"config": merged},
                )
            )
        else:
            self.require(self.call("POST", "/providers", {"config": provider}))

    def delete_provider(self, provider_id: str) -> bool:
        result = self.call(
            "DELETE", f"/providers/{urllib.parse.quote(provider_id, safe='')}"
        )
        return self.ok(result)

    def test_provider(self, provider_id: str, timeout: int = 90) -> tuple[bool, str]:
        result = self.call(
            "POST", "/providers/test", {"provider_id": provider_id}, timeout=timeout
        )
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        status = str(data.get("status") or result.get("status") or "")
        if self.ok(result) and status not in ("error", "unavailable", "failed"):
            return True, ""
        return False, str(
            data.get("error") or data.get("message") or self.message(result)
        )[:300]

    # ---------- 其他 ----------
    def install_pip(self, package: str, timeout: int = 600) -> None:
        self.require(self.call("POST", "/pip/install", {"package": package}, timeout=timeout))

    def set_tool_permission(self, tool: str, permission: str) -> None:
        self.require(
            self.call(
                "PATCH",
                f"/tools/{urllib.parse.quote(tool, safe='')}/permission",
                {"permission": permission},
            )
        )

    def request(
        self,
        method: str,
        path: str,
        body=None,
        timeout: int = 120,
        raw_body: bytes | None = None,
        content_type: str = "application/json",
    ) -> dict:
        return self.call(
            method,
            path,
            body=body,
            raw_body=raw_body,
            content_type=content_type,
            timeout=timeout,
        )
