"""AstrBot 4.x WebUI API 客户端。

按 AstrBot 4.3.x 的实际路由实现：
- 登录：POST /api/auth/login（密码为 MD5）
- 配置：GET /api/config/get，POST /api/config/astrbot/update
- 人格：/api/persona/list|detail|create|update|delete
- 插件：/api/plugin/get|install|install-upload|on|off|reload
- 插件配置：/api/config/get?plugin_name=，/api/config/plugin/update?plugin_name=
- 提供商：/api/config/provider/new|update|delete|check_one
"""

from __future__ import annotations

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
        # AstrBot 的 unzip_file 假定第一个条目是插件目录
        zf.writestr(f"{top}/", b"")
        for path in folder.rglob("*"):
            if path.is_dir():
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            zf.write(path, str(Path(top) / path.relative_to(folder)))
    return buf.getvalue()


class AstrBotClient:
    def __init__(self, base_url: str, timeout: int = 30, api_prefix: str = "/api"):
        self.root = base_url.rstrip("/")
        self.api_prefix = api_prefix
        self.token: str | None = None
        self.timeout = timeout

    # ---------- 基础请求 ----------
    def _request(
        self,
        method: str,
        path: str,
        body=None,
        raw_body: bytes | None = None,
        content_type: str = "application/json",
        timeout: int | None = None,
        absolute: bool = False,
    ) -> dict:
        url = self.root + path if absolute else self.root + self.api_prefix + path
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

    def call(
        self,
        method: str,
        path: str,
        body=None,
        raw_body: bytes | None = None,
        content_type: str = "application/json",
        timeout: int | None = None,
    ) -> dict:
        return self._request(
            method, path, body, raw_body, content_type, timeout, absolute=False
        )

    @staticmethod
    def ok(result: dict) -> bool:
        status = result.get("status")
        return result.get("_http", 200) < 400 and status in ("ok", "success", None)

    @staticmethod
    def message(result: dict) -> str:
        return str(
            result.get("message") or result.get("detail") or result.get("status") or result
        )[:500]

    def require(self, result: dict) -> dict:
        if not self.ok(result):
            raise ApiError(self.message(result))
        return result

    # ---------- 认证 ----------
    def login(self, username: str, password: str) -> bool:
        md5 = hashlib.md5(password.encode("utf-8")).hexdigest()
        # AstrBot 4.29 使用明文密码；4.3.x 使用密码 MD5。优先当前新版的明文，
        # 失败后再兼容旧版，避免每次连接都先产生一次无谓的失败登录。
        candidates = [
            ("/api/auth/login", password),
            ("/api/auth/login", md5),
            ("/api/v1/auth/login", password),
            ("/api/v1/auth/login", md5),
        ]
        for path, candidate in candidates:
            result = self._request(
                "POST",
                path,
                {"username": username, "password": candidate},
                absolute=True,
            )
            data = result.get("data")
            if isinstance(data, dict) and data.get("token"):
                self.token = str(data["token"])
                return True
        return False

    # ---------- 全局配置 ----------
    def get_profile(self, name: str = "default") -> dict:
        if name in ("", None, "default"):
            result = self.require(self.call("GET", "/config/get"))
        else:
            result = self.require(
                self.call("GET", f"/config/abconf?id={urllib.parse.quote(name)}")
            )
        data = result.get("data") or {}
        config = data.get("config") if isinstance(data, dict) else None
        if not isinstance(config, dict):
            raise ApiError("AstrBot 返回的配置为空")
        return config

    def put_profile(self, config: dict, name: str = "default") -> None:
        self.require(
            self.call(
                "POST",
                "/config/astrbot/update",
                {"config": config, "conf_id": name or "default"},
            )
        )

    # ---------- 人格 ----------
    def list_personas(self) -> list:
        result = self.call("GET", "/persona/list")
        data = result.get("data")
        return data if isinstance(data, list) else []

    def get_persona(self, persona_id: str) -> dict | None:
        result = self.call("POST", "/persona/detail", {"persona_id": persona_id})
        data = result.get("data")
        if self.ok(result) and isinstance(data, dict) and data.get("persona_id") == persona_id:
            return data
        return None

    def upsert_persona(self, persona_id: str, system_prompt: str, extra: dict | None = None) -> None:
        current = self.get_persona(persona_id)
        body = {"persona_id": persona_id, "system_prompt": system_prompt}
        if extra:
            for key in ("begin_dialogs", "tools"):
                if key in extra:
                    body[key] = extra[key]
        if current:
            self.require(self.call("POST", "/persona/update", body))
        else:
            body.setdefault("begin_dialogs", [])
            body.setdefault("tools", None)
            self.require(self.call("POST", "/persona/create", body))

    def delete_persona(self, persona_id: str) -> bool:
        return self.ok(self.call("POST", "/persona/delete", {"persona_id": persona_id}))

    # ---------- 插件 ----------
    def list_plugins(self) -> list:
        data = self.call("GET", "/plugin/get").get("data")
        return data if isinstance(data, list) else []

    def plugin_installed(self, name: str) -> bool:
        return any(
            isinstance(plugin, dict) and plugin.get("name") == name
            for plugin in self.list_plugins()
        )

    @staticmethod
    def _repo_url(market_id: str) -> str:
        value = str(market_id or "").strip()
        if not value:
            return value
        if value.startswith(("http://", "https://")):
            return value
        if "github.com/" in value:
            return "https://" + value.lstrip("/")
        return "https://github.com/" + value.strip("/")

    def install_market_plugin(self, market_id: str, timeout: int = 600) -> None:
        self.require(
            self.call(
                "POST", "/plugin/install", {"url": self._repo_url(market_id)}, timeout=timeout
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
                "/plugin/install-upload",
                raw_body=head + payload + tail,
                content_type=f"multipart/form-data; boundary={boundary}",
                timeout=timeout,
            )
        )

    def get_plugin_config(self, name: str) -> dict:
        result = self.require(
            self.call("GET", f"/config/get?plugin_name={urllib.parse.quote(name)}")
        )
        data = result.get("data") or {}
        config = data.get("config") if isinstance(data, dict) else None
        if not isinstance(config, dict):
            raise ApiError(f"读不到插件 {name} 的配置")
        return config

    def put_plugin_config(self, name: str, config: dict) -> None:
        self.require(
            self.call(
                "POST",
                f"/config/plugin/update?plugin_name={urllib.parse.quote(name)}",
                config,
            )
        )

    def set_plugin_enabled(self, name: str, enabled: bool) -> None:
        self.require(
            self.call("POST", "/plugin/on" if enabled else "/plugin/off", {"name": name})
        )

    def reload_plugin(self, name: str, timeout: int = 180) -> None:
        self.require(self.call("POST", "/plugin/reload", {"name": name}, timeout=timeout))

    # ---------- 模型提供商 ----------
    def get_provider(self, provider_id: str) -> dict | None:
        for provider in self.get_profile().get("provider", []):
            if isinstance(provider, dict) and provider.get("id") == provider_id:
                return provider
        return None

    def upsert_provider(self, provider: dict) -> None:
        provider_id = str(provider.get("id") or "")
        if not provider_id:
            raise ApiError("provider 缺少 id")
        current = self.get_provider(provider_id)
        if current:
            merged = {**current, **provider}
            # AstrBot 4.3.x 的 provider 更新接口会先加载新实例，再用旧列表同步，
            # 把刚加载的实例误终止。改为删除后新增，确保实例真正进入 inst_map。
            if not self.delete_provider(provider_id):
                raise ApiError("更新提供商失败：无法移除旧配置")
            self.require(self.call("POST", "/config/provider/new", merged))
        else:
            self.require(self.call("POST", "/config/provider/new", provider))

    def delete_provider(self, provider_id: str) -> bool:
        return self.ok(self.call("POST", "/config/provider/delete", {"id": provider_id}))

    def test_provider(self, provider_id: str, timeout: int = 90) -> tuple[bool, str]:
        result = self.call(
            "GET",
            f"/config/provider/check_one?id={urllib.parse.quote(provider_id)}",
            timeout=timeout,
        )
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        status = str(data.get("status") or "")
        if self.ok(result) and status in ("available", "ok", "success"):
            return True, ""
        return False, str(data.get("error") or self.message(result))[:300]

    # ---------- 其他 ----------
    def install_pip(self, package: str, timeout: int = 600) -> None:
        self.require(
            self.call("POST", "/update/pip-install", {"package": package}, timeout=timeout)
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
