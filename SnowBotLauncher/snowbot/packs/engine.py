"""SnowBot 配置包引擎。

设计借鉴 dafeiyu-config-pack 的「清单驱动 + 后台 API + 可重复执行」思路，并扩展为：
- 通用变量表（文本/密码/下拉/布尔/多行），支持默认值、校验、条件步骤
- 声明式步骤：人格、全局配置、插件安装/配置/启停、模型提供商、PIP、工具权限、HTTP、脚本
- 应用前自动快照备份，支持还原
- 兼容旧版 pack.json 配置包（自动包装为脚本步骤）
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..astrbot.client import ApiError, AstrBotClient, get_path, set_path, zip_folder

SCHEMA = "snowbot-pack/1"
BACKUP_SCHEMA = "snowbot-backup/1"
from ..core.paths import BACKUPS_DIR, DATA_DIR, PACKS_DIR, PRESETS_DIR, TEMP_DIR
STEP_TYPES = {
    "persona",
    "config.set",
    "plugin.install",
    "plugin.config",
    "plugin.enable",
    "plugin.reload",
    "provider.upsert",
    "provider.test",
    "pip.install",
    "tool.permission",
    "http",
    "script",
    "sleep",
}

VAR_TYPES = {"text", "password", "select", "bool", "multiline"}
TOKEN_RE = re.compile(r"\$\{([A-Za-z0-9_]+)\}")


class PackError(Exception):
    """配置包格式或执行错误。"""


@dataclass
class StepResult:
    title: str
    ok: bool
    message: str = ""


@dataclass
class ApplyResult:
    ok: bool
    results: list[StepResult] = field(default_factory=list)
    backup: str = ""
    error: str = ""


@dataclass
class PackContext:
    client: AstrBotClient
    pack: dict
    variables: dict
    config: dict
    platform_id: str
    chat_provider_id: str
    owner_qq: str
    owner_session: str
    pack_dir: Path
    data_dir: Path
    astrbot_python: str
    base_url: str
    log: Callable[[str], None] = lambda _msg: None

    def mapping(self) -> dict:
        data = dict(self.variables)
        data.update(
            {
                "base_url": self.base_url,
                "astrbot_url": self.base_url,
                "platform_id": self.platform_id,
                "chat_provider_id": self.chat_provider_id,
                "owner_qq": self.owner_qq,
                "owner_session": self.owner_session,
                "pack_id": self.pack.get("id", ""),
                "pack_name": self.pack.get("name", ""),
                "pack_version": self.pack.get("version", ""),
                "pack_dir": str(self.pack_dir),
                "data_dir": str(self.data_dir),
                "backups_dir": str(BACKUPS_DIR),
            }
        )
        return data


# ---------------- 通用工具 ----------------
def slugify(text: str, fallback: str = "pack") -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", text.strip()).strip("-").lower()
    return slug[:48] or fallback


def safe_child(root: Path, relative: str) -> Path:
    """把相对路径限制在 pack 目录内。"""
    path = (root / relative).resolve()
    root_resolved = root.resolve()
    if root_resolved != path and root_resolved not in path.parents:
        raise PackError(f"路径越界：{relative}")
    return path


def fill(obj: Any, mapping: dict) -> Any:
    """递归替换 ${var} 占位符。"""
    if isinstance(obj, str):
        return TOKEN_RE.sub(lambda m: str(mapping.get(m.group(1), m.group(0))), obj)
    if isinstance(obj, list):
        return [fill(item, mapping) for item in obj]
    if isinstance(obj, dict):
        return {key: fill(value, mapping) for key, value in obj.items()}
    return obj


def fill_braces(obj: Any, mapping: dict) -> Any:
    """替换 ${var} 以及 {answers_file}/{pack_dir} 这类花括号占位符。"""
    if isinstance(obj, str):
        text = fill(obj, mapping)
        for key, value in mapping.items():
            text = text.replace("{" + key + "}", str(value))
        return text
    if isinstance(obj, list):
        return [fill_braces(item, mapping) for item in obj]
    if isinstance(obj, dict):
        return {key: fill_braces(value, mapping) for key, value in obj.items()}
    return obj


def eval_when(expr: str | None, variables: dict) -> bool:
    """安全求值 when 表达式：变量名、常量、比较、and/or/not/in。"""
    if not expr:
        return True
    expr = TOKEN_RE.sub(lambda m: m.group(1), str(expr))
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise PackError(f"when 表达式无效：{expr}") from exc

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return variables.get(node.id, "")
        if isinstance(node, ast.List):
            return [ev(item) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(ev(item) for item in node.elts)
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(bool(ev(item)) for item in node.values)
            return any(bool(ev(item)) for item in node.values)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not bool(ev(node.operand))
        if isinstance(node, ast.Compare):
            left = ev(node.left)
            for operator, comparator in zip(node.ops, node.comparators):
                right = ev(comparator)
                if isinstance(operator, ast.Eq):
                    ok = left == right
                elif isinstance(operator, ast.NotEq):
                    ok = left != right
                elif isinstance(operator, ast.In):
                    ok = left in right
                elif isinstance(operator, ast.NotIn):
                    ok = left not in right
                elif isinstance(operator, ast.Lt):
                    ok = left < right
                elif isinstance(operator, ast.LtE):
                    ok = left <= right
                elif isinstance(operator, ast.Gt):
                    ok = left > right
                elif isinstance(operator, ast.GtE):
                    ok = left >= right
                else:
                    raise PackError(f"不支持的比较运算：{expr}")
                if not ok:
                    return False
                left = right
            return True
        raise PackError(f"不支持的表达式：{expr}")

    return bool(ev(tree))


# ---------------- 配置包加载 ----------------
def load_pack(path: Path) -> dict:
    meta_path = path / "pack.json"
    if not meta_path.exists():
        raise PackError(f"缺少 pack.json：{path}")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise PackError(f"pack.json 不是合法 JSON：{exc}") from exc
    if meta.get("schema") != SCHEMA:
        raise PackError(f"不支持的配置包格式：{meta.get('schema')!r}，需要 {SCHEMA}")
    for key in ("id", "name", "version", "steps"):
        if key not in meta:
            raise PackError(f"pack.json 缺少字段：{key}")
    if not isinstance(meta["steps"], list) or not meta["steps"]:
        raise PackError("pack.json 的 steps 必须是非空数组")
    variables = meta.get("variables", [])
    if not isinstance(variables, list):
        raise PackError("variables 必须是数组")
    seen = set()
    for var in variables:
        if not isinstance(var, dict) or not var.get("key"):
            raise PackError("variables 中存在缺少 key 的项")
        if var["key"] in seen:
            raise PackError(f"变量重复：{var['key']}")
        seen.add(var["key"])
        var_type = var.get("type", "text")
        if var_type not in VAR_TYPES:
            raise PackError(f"变量 {var['key']} 的类型不支持：{var_type}")
    for index, step in enumerate(meta["steps"], 1):
        if not isinstance(step, dict) or not step.get("type"):
            raise PackError(f"第 {index} 个步骤缺少 type")
        if step["type"] not in STEP_TYPES:
            raise PackError(f"第 {index} 个步骤类型不支持：{step['type']}")
    meta["_path"] = str(path)
    return meta


def list_packs(packs_dir: Path = PACKS_DIR) -> list[dict]:
    packs = []
    if not packs_dir.exists():
        return packs
    for child in sorted(packs_dir.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        try:
            packs.append(load_pack(child))
        except Exception as exc:
            packs.append({"id": child.name, "name": child.name, "version": "?", "_error": str(exc), "_path": str(child)})
    return packs


def variable_defaults(pack: dict) -> dict:
    values = {}
    for var in pack.get("variables", []):
        default = var.get("default", "")
        if var.get("type") == "bool" and not isinstance(default, bool):
            default = str(default).lower() in ("1", "true", "yes", "on")
        values[var["key"]] = default
    return values


def preset_path(pack_id: str) -> Path:
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    return PRESETS_DIR / f"{slugify(pack_id)}.json"


def load_preset(pack: dict) -> dict:
    try:
        return json.loads(preset_path(pack["id"]).read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_preset(pack: dict, values: dict) -> None:
    secret_keys = {
        var["key"]
        for var in pack.get("variables", [])
        if var.get("secret") or var.get("type") == "password"
    }
    data = {key: value for key, value in values.items() if key not in secret_keys}
    try:
        preset_path(pack["id"]).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def resolve_variables(pack: dict, provided: dict | None = None) -> dict:
    values = variable_defaults(pack)
    values.update(load_preset(pack))
    if provided:
        values.update(provided)
    for var in pack.get("variables", []):
        key = var["key"]
        value = values.get(key, "")
        label = var.get("label", key)
        if var.get("required") and (value is None or str(value).strip() == ""):
            raise PackError(f"请填写「{label}」")
        if var.get("type") == "select":
            allowed = [str(opt.get("value") if isinstance(opt, dict) else opt) for opt in var.get("options", [])]
            if allowed and str(value) not in allowed:
                raise PackError(f"「{label}」只能是：{' / '.join(allowed)}")
        pattern = var.get("pattern")
        if pattern and value not in (None, "") and not re.fullmatch(pattern, str(value)):
            raise PackError(f"「{label}」格式不正确")
        if var.get("type") == "bool":
            values[key] = bool(value)
    return values


# ---------------- 运行上下文 ----------------
def build_context(pack: dict, variables: dict, cfg: dict, log: Callable[[str], None] | None = None) -> PackContext:
    log = log or (lambda _m: None)
    base_url = str(variables.get("base_url") or f"http://127.0.0.1:{cfg.get('dashboard_port', 6185)}").rstrip("/")
    username = str(variables.get("astrbot_username") or "astrbot")
    password = str(variables.get("astrbot_password") or "")
    if not password:
        raise PackError("请填写 AstrBot 后台密码")
    client = AstrBotClient(base_url)
    if not client.login(username, password):
        raise PackError("登录 AstrBot 失败：请检查后台地址、账号和密码")
    log("已登录 AstrBot 后台")
    config = client.get_profile()

    platforms = [p for p in config.get("platform", []) if isinstance(p, dict) and p.get("type") == "aiocqhttp"]
    platforms.sort(key=lambda p: (p.get("id") != "napcat", not p.get("enable", True)))
    platform_id = platforms[0].get("id", "") if platforms else ""

    provider_id = get_path(config, "agent_runner.config.model.provider_id") or ""
    if not provider_id:
        providers = [
            p for p in config.get("provider", [])
            if isinstance(p, dict)
            and p.get("provider_type", "chat_completion") == "chat_completion"
            and p.get("enable", True)
        ]
        provider_id = providers[0].get("id", "") if providers else ""

    owner_qq = str(variables.get("owner_qq") or "")
    owner_session = f"{platform_id}:FriendMessage:{owner_qq}" if platform_id and owner_qq else ""
    if not platform_id:
        log("警告：没有找到 OneBot v11 平台，模板中的会话占位符将为空")

    ctx = PackContext(
        client=client,
        pack=pack,
        variables=variables,
        config=config,
        platform_id=platform_id,
        chat_provider_id=provider_id,
        owner_qq=owner_qq,
        owner_session=owner_session,
        pack_dir=Path(pack["_path"]),
        data_dir=DATA_DIR,
        astrbot_python=str(cfg.get("python_exe") or ""),
        base_url=base_url,
        log=log,
    )
    log(f"平台：{platform_id or '未找到'}　对话模型：{provider_id or '未配置'}")
    return ctx


# ---------------- 计划 ----------------
def step_title(step: dict, ctx: PackContext) -> str:
    mapping = ctx.mapping()
    kind = step["type"]
    if kind == "persona":
        return f"写入人格「{fill(step.get('id', ''), mapping)}」"
    if kind == "config.set":
        return f"修改全局配置（{len(step.get('values', {}))} 项）"
    if kind == "plugin.install":
        return f"安装插件「{fill(step.get('name') or step.get('market_id') or step.get('path', ''), mapping)}」"
    if kind == "plugin.config":
        return f"配置插件「{fill(step.get('plugin', ''), mapping)}」"
    if kind == "plugin.enable":
        state = "启用" if step.get("enabled", True) else "停用"
        return f"{state}插件「{fill(step.get('plugin', ''), mapping)}」"
    if kind == "plugin.reload":
        return f"重载插件「{fill(step.get('plugin', ''), mapping)}」"
    if kind == "provider.upsert":
        provider = step.get("provider", {})
        return f"写入模型提供商「{fill(provider.get('id', ''), mapping)}」"
    if kind == "provider.test":
        return f"测试模型提供商「{fill(step.get('id', ''), mapping)}」"
    if kind == "pip.install":
        return f"安装 Python 依赖（{len(step.get('packages', []))} 个）"
    if kind == "tool.permission":
        return f"设置工具权限「{fill(step.get('tool', ''), mapping)}」"
    if kind == "http":
        return f"调用接口 {step.get('method', 'POST')} {fill(step.get('path', ''), mapping)}"
    if kind == "script":
        return f"运行脚本「{fill(step.get('name') or step.get('file', ''), mapping)}」"
    if kind == "sleep":
        return f"等待 {step.get('seconds', 1)} 秒"
    return kind


@dataclass
class PlanItem:
    index: int
    step: dict
    title: str
    is_script: bool


def build_plan(pack: dict, ctx: PackContext) -> list[PlanItem]:
    items = []
    for step in pack["steps"]:
        if not eval_when(step.get("when"), ctx.variables):
            continue
        items.append(
            PlanItem(
                index=len(items) + 1,
                step=step,
                title=step_title(step, ctx),
                is_script=step["type"] == "script",
            )
        )
    return items


# ---------------- 快照 ----------------
def _backup_snapshot(pack: dict, ctx: PackContext, items: list[PlanItem]) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = BACKUPS_DIR / f"{slugify(pack.get('id', 'pack'))}-{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "schema": BACKUP_SCHEMA,
        "created": datetime.now().isoformat(timespec="seconds"),
        "pack": {"id": pack.get("id"), "name": pack.get("name"), "version": pack.get("version")},
        "config": ctx.config,
        "personas": {},
        "plugin_configs": {},
        "providers": {},
    }
    for item in items:
        step = item.step
        kind = step["type"]
        if kind == "persona":
            pid = str(fill(step.get("id", ""), ctx.mapping()))
            snapshot["personas"][pid] = ctx.client.get_persona(pid)
        elif kind == "plugin.config":
            name = str(fill(step.get("plugin", ""), ctx.mapping()))
            try:
                snapshot["plugin_configs"][name] = ctx.client.get_plugin_config(name)
            except Exception:
                snapshot["plugin_configs"][name] = None
        elif kind == "provider.upsert":
            pid = str(fill(step.get("provider", {}).get("id", ""), ctx.mapping()))
            snapshot["providers"][pid] = ctx.client.get_provider(pid)
    path = folder / "snapshot.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    _prune_backups()
    return path


def _prune_backups(keep: int = 10) -> None:
    try:
        folders = sorted(
            [p for p in BACKUPS_DIR.iterdir() if p.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in folders[keep:]:
            shutil.rmtree(old, ignore_errors=True)
    except Exception:
        pass


def list_backups() -> list[dict]:
    result = []
    try:
        for folder in sorted(BACKUPS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            snapshot = folder / "snapshot.json"
            if not folder.is_dir() or not snapshot.exists():
                continue
            try:
                data = json.loads(snapshot.read_text(encoding="utf-8"))
                result.append(
                    {
                        "path": str(snapshot),
                        "name": folder.name,
                        "created": data.get("created", ""),
                        "pack": data.get("pack", {}),
                    }
                )
            except Exception:
                continue
    except Exception:
        pass
    return result


def restore_backup(snapshot_path: str, cfg: dict, base_url: str, username: str, password: str,
                   log: Callable[[str], None] | None = None) -> ApplyResult:
    log = log or (lambda _m: None)
    data = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    if data.get("schema") != BACKUP_SCHEMA:
        return ApplyResult(False, error="不是有效的 SnowBot 备份文件")
    client = AstrBotClient(base_url)
    if not client.login(username, password):
        return ApplyResult(False, error="登录 AstrBot 失败")
    results = []
    try:
        if data.get("config"):
            client.put_profile(data["config"])
            results.append(StepResult("还原全局配置", True))
        for pid, persona in (data.get("personas") or {}).items():
            if persona:
                client.upsert_persona(pid, persona.get("system_prompt", ""), persona)
                results.append(StepResult(f"还原人格「{pid}」", True))
            else:
                ok = client.delete_persona(pid)
                results.append(StepResult(f"删除新增人格「{pid}」", ok, "" if ok else "删除失败，可手动处理"))
        for name, conf in (data.get("plugin_configs") or {}).items():
            if conf is not None:
                client.put_plugin_config(name, conf)
                results.append(StepResult(f"还原插件配置「{name}」", True))
        for pid, provider in (data.get("providers") or {}).items():
            if provider:
                client.upsert_provider(provider)
                results.append(StepResult(f"还原提供商「{pid}」", True))
            else:
                ok = client.delete_provider(pid)
                results.append(StepResult(f"删除新增提供商「{pid}」", ok, "" if ok else "删除失败，可手动处理"))
        log("备份还原完成")
        return ApplyResult(True, results=results)
    except Exception as exc:
        return ApplyResult(False, results=results, error=str(exc))


# ---------------- 步骤执行 ----------------
def _run_step(step: dict, ctx: PackContext) -> StepResult:
    kind = step["type"]
    mapping = ctx.mapping()
    client = ctx.client

    if kind == "persona":
        pid = str(fill(step.get("id", ""), mapping))
        if not pid:
            raise PackError("persona 步骤缺少 id")
        if step.get("file"):
            path = safe_child(ctx.pack_dir, str(fill(step["file"], mapping)))
            prompt = path.read_text(encoding="utf-8-sig")
        else:
            prompt = str(step.get("prompt", ""))
        prompt = fill(prompt, mapping)
        for old, new in (step.get("replace") or {}).items():
            prompt = prompt.replace(old, str(fill(new, mapping)))
        client.upsert_persona(pid, prompt, fill(step.get("extra") or {}, mapping))
        return StepResult(f"写入人格「{pid}」", True)

    if kind == "config.set":
        values = fill(step.get("values", {}), mapping)
        for dotted, value in values.items():
            set_path(ctx.config, dotted, value)
        client.put_profile(ctx.config)
        return StepResult(f"修改全局配置（{len(values)} 项）", True)

    if kind == "plugin.install":
        name = str(fill(step.get("name") or "", mapping))
        if name and client.plugin_installed(name) and not step.get("force"):
            return StepResult(f"插件「{name}」已安装，跳过", True)
        if step.get("market_id"):
            client.install_market_plugin(str(fill(step["market_id"], mapping)))
        elif step.get("path"):
            path = safe_child(ctx.pack_dir, str(fill(step["path"], mapping)))
            if path.is_dir():
                payload = zip_folder(path)
                filename = path.name + ".zip"
            else:
                payload = path.read_bytes()
                filename = path.name
            client.upload_plugin(payload, filename)
        else:
            raise PackError("plugin.install 需要 market_id 或 path")
        if name and not client.plugin_installed(name):
            return StepResult(f"插件「{name}」安装后未出现在列表", False, "可能需要重启 AstrBot 或插件名称不一致")
        return StepResult(f"安装插件「{name or step.get('market_id') or step.get('path')}」", True)

    if kind == "plugin.config":
        name = str(fill(step.get("plugin", ""), mapping))
        if not name:
            raise PackError("plugin.config 缺少 plugin")
        if not client.plugin_installed(name):
            if step.get("required", False):
                raise PackError(f"插件「{name}」未安装")
            return StepResult(f"插件「{name}」未安装，跳过", True, "跳过")
        conf = client.get_plugin_config(name)
        values = fill(step.get("values", {}), mapping)
        for dotted, value in values.items():
            set_path(conf, dotted, value)
        client.put_plugin_config(name, conf)
        return StepResult(f"配置插件「{name}」（{len(values)} 项）", True)

    if kind == "plugin.enable":
        name = str(fill(step.get("plugin", ""), mapping))
        client.set_plugin_enabled(name, bool(step.get("enabled", True)))
        return StepResult(f"插件「{name}」{'启用' if step.get('enabled', True) else '停用'}", True)

    if kind == "plugin.reload":
        name = str(fill(step.get("plugin", ""), mapping))
        client.reload_plugin(name, timeout=int(step.get("timeout", 180)))
        return StepResult(f"重载插件「{name}」", True)

    if kind == "provider.upsert":
        provider = fill(step.get("provider", {}), mapping)
        client.upsert_provider(provider)
        pid = str(provider.get("id", ""))
        if step.get("test"):
            ok, why = client.test_provider(pid)
            if not ok:
                if step.get("disable_on_fail", True):
                    provider = {**provider, "enable": False}
                    client.upsert_provider(provider)
                    return StepResult(f"提供商「{pid}」写入但测试失败，已停用", False, why)
                return StepResult(f"提供商「{pid}」写入但测试失败", False, why)
        return StepResult(f"写入模型提供商「{pid}」", True)

    if kind == "provider.test":
        pid = str(fill(step.get("id", ""), mapping))
        ok, why = client.test_provider(pid)
        return StepResult(f"测试提供商「{pid}」", ok, why)

    if kind == "pip.install":
        packages = [str(fill(p, mapping)) for p in step.get("packages", [])]
        for package in packages:
            ctx.log(f"安装 Python 包：{package}")
            client.install_pip(package, timeout=int(step.get("timeout", 600)))
        return StepResult(f"安装 Python 依赖（{len(packages)} 个）", True)

    if kind == "tool.permission":
        tool = str(fill(step.get("tool", ""), mapping))
        permission = str(fill(step.get("permission", "admin"), mapping))
        client.set_tool_permission(tool, permission)
        return StepResult(f"设置工具权限「{tool}」→ {permission}", True)

    if kind == "http":
        method = str(step.get("method", "POST")).upper()
        path = str(fill(step.get("path", ""), mapping))
        body = fill(step.get("body"), mapping)
        result = client.request(
            method,
            path,
            body=body,
            timeout=int(step.get("timeout", 120)),
        )
        if step.get("require_ok", True) and not client.ok(result):
            raise PackError(f"接口调用失败：{client.message(result)}")
        return StepResult(f"调用接口 {method} {path}", True)

    if kind == "sleep":
        seconds = float(step.get("seconds", 1))
        time.sleep(min(seconds, 60))
        return StepResult(f"等待 {seconds:g} 秒", True)

    if kind == "script":
        return _run_script(step, ctx)

    raise PackError(f"不支持的步骤类型：{kind}")


def _run_script(step: dict, ctx: PackContext) -> StepResult:
    script_path = safe_child(ctx.pack_dir, str(fill(step["file"], ctx.mapping())))
    if not script_path.exists():
        raise PackError(f"脚本不存在：{script_path}")
    interpreter = step.get("python", "astrbot")
    if interpreter == "astrbot":
        python_exe = ctx.astrbot_python
        if not python_exe or not Path(python_exe).exists():
            raise PackError("找不到 AstrBot 的 Python 解释器，无法运行配置包脚本")
    else:
        if getattr(sys, "frozen", False):
            raise PackError("打包版控制台不能直接运行脚本，请使用 astrbot 解释器")
        python_exe = sys.executable

    answers = step.get("answers")
    answers_path = None
    if isinstance(answers, str):
        rendered = fill(answers, ctx.mapping())
        answers = json.loads(rendered)
    elif isinstance(answers, dict):
        answers = fill(answers, ctx.mapping())
    else:
        answers = None

    extra_mapping = dict(ctx.mapping())
    if answers is not None:
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="answers-", suffix=".json", dir=str(TEMP_DIR))
        os.close(fd)
        answers_path = Path(temp_name)
        answers_path.write_text(json.dumps(answers, ensure_ascii=False, indent=2), encoding="utf-8")
        extra_mapping["answers_file"] = str(answers_path)

    args = [str(fill_braces(a, extra_mapping)) for a in step.get("args", [])]
    env = os.environ.copy()
    env.update(
        {
            "SNOWBOT_PACK_DIR": str(ctx.pack_dir),
            "SNOWBOT_DATA_DIR": str(ctx.data_dir),
            "SNOWBOT_ASTRBOT_URL": ctx.base_url,
            "SNOWBOT_PLATFORM_ID": ctx.platform_id,
            "PYTHONUTF8": "1",
        }
    )
    for key, value in (step.get("env") or {}).items():
        env[str(key)] = str(fill(value, ctx.mapping()))

    ctx.log(f"运行脚本：{script_path.name} {' '.join(args)}")
    try:
        proc = subprocess.run(
            [str(python_exe), str(script_path), *args],
            cwd=str(ctx.pack_dir),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(step.get("timeout", 3600)),
        )
    finally:
        if answers_path:
            try:
                answers_path.unlink()
            except Exception:
                pass
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    for line in output.splitlines()[-80:]:
        if line.strip():
            ctx.log("  " + line.rstrip())
    if proc.returncode != 0:
        tail = "\n".join(output.strip().splitlines()[-8:])
        raise PackError(f"脚本退出码 {proc.returncode}：{tail}")
    return StepResult(f"运行脚本「{script_path.name}」", True)


# ---------------- 应用 ----------------
def apply_pack(
    pack: dict,
    ctx: PackContext,
    run_scripts: bool = False,
    progress: Callable[[int, int, str, bool, str], None] | None = None,
    backup: bool = True,
) -> ApplyResult:
    progress = progress or (lambda *_args: None)
    try:
        items = build_plan(pack, ctx)
    except Exception as exc:
        return ApplyResult(False, error=str(exc))
    if not items:
        return ApplyResult(False, error="没有可执行的步骤（可能全部被 when 条件跳过）")
    if any(item.is_script for item in items) and not run_scripts:
        return ApplyResult(False, error="此配置包包含脚本步骤，需要勾选「允许运行包内脚本」后重试")

    backup_path = ""
    if backup:
        try:
            backup_path = str(_backup_snapshot(pack, ctx, items))
            ctx.log(f"已备份当前配置：{backup_path}")
        except Exception as exc:
            return ApplyResult(False, error=f"备份失败，已中止：{exc}")

    results: list[StepResult] = []
    total = len(items)
    for item in items:
        progress(item.index, total, item.title, False, "running")
        ctx.log(f"[{item.index}/{total}] {item.title}")
        try:
            result = _run_step(item.step, ctx)
        except Exception as exc:
            result = StepResult(item.title, False, str(exc))
            ctx.log(f"  ✘ {exc}")
        results.append(result)
        progress(item.index, total, item.title, result.ok, result.message)
        if result.ok:
            ctx.log("  ✔ " + (result.message or "完成"))

    ok = all(result.ok for result in results)
    return ApplyResult(ok, results=results, backup=backup_path)


# ---------------- 导入 / 旧版转换 ----------------
def _copy_tree(src: Path, dst: Path) -> None:
    ignore = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.pyo")
    shutil.copytree(src, dst, ignore=ignore)


def _is_snowbot_root(path: Path) -> bool:
    meta_path = path / "pack.json"
    if not meta_path.exists():
        return False
    try:
        return json.loads(meta_path.read_text(encoding="utf-8-sig")).get("schema") == SCHEMA
    except Exception:
        return False


def _find_pack_root(base: Path) -> Path | None:
    if _is_snowbot_root(base):
        return base
    for child in base.iterdir():
        if child.is_dir() and _is_snowbot_root(child):
            return child
    return None


def _locate_pack(base: Path) -> tuple[str, Path] | None:
    if _detect_legacy(base):
        return "legacy", base
    root = _find_pack_root(base)
    if root:
        return "snowbot", root
    for child in base.iterdir():
        if child.is_dir() and _detect_legacy(child):
            return "legacy", child
    return None


def _detect_legacy(base: Path) -> tuple[Path, Path] | None:
    if not (base / "settings" / "pack.json").exists():
        return None
    scripts = sorted((base / "tools").glob("import_*.py")) if (base / "tools").is_dir() else []
    if not scripts:
        return None
    return base / "settings" / "pack.json", scripts[0]


def _legacy_name(base: Path, settings: dict) -> str:
    readme = base / "README.md"
    if readme.exists():
        for line in readme.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("# "):
                title = line[2:].strip()
                if title:
                    return title
    return settings.get("name") or base.name


def _legacy_wrapper(base: Path, settings: dict, script: Path) -> dict:
    name = _legacy_name(base, settings)
    pack_id = "legacy-" + slugify(base.name)
    persona = settings.get("persona") if isinstance(settings.get("persona"), dict) else {}
    voice = settings.get("voice") if isinstance(settings.get("voice"), dict) else {}
    memory = settings.get("memory") if isinstance(settings.get("memory"), dict) else {}
    is_dafeiyu = bool(persona.get("id")) and bool(voice) and bool(memory)

    if is_dafeiyu:
        variables = [
            {"key": "base_url", "label": "AstrBot 后台地址", "type": "text", "default": "http://127.0.0.1:6185", "required": True},
            {"key": "astrbot_username", "label": "后台账号", "type": "text", "default": "astrbot", "required": True},
            {"key": "astrbot_password", "label": "后台密码", "type": "password", "secret": True, "required": True},
            {"key": "owner_qq", "label": "主人 QQ（大号）", "type": "text", "required": True, "pattern": r"\d+", "placeholder": "123456789"},
            {
                "key": "memory", "label": "记忆方式", "type": "select", "default": "0",
                "options": [
                    {"value": "0", "label": "先不启用"},
                    {"value": "1", "label": "本机 Ollama（免费）"},
                    {"value": "2", "label": "硅基流动（需要 Key）"},
                ],
                "description": "选 1 需先安装并运行 Ollama；选 2 需填写硅基流动 Key",
            },
            {"key": "siliconflow_key", "label": "硅基流动 Key", "type": "password", "secret": True, "description": "记忆方式选 2 时填写"},
            {
                "key": "voice", "label": "语音方案", "type": "select", "default": "0",
                "options": [
                    {"value": "0", "label": "先不启用"},
                    {"value": "1", "label": "微软 Edge（免费）"},
                    {"value": "2", "label": "小米 MiMo 克隆音（需要 Key）"},
                    {"value": "3", "label": "豆包 Seed Audio（需要 APP ID / Token）"},
                ],
            },
            {"key": "mimo_key", "label": "MiMo Key", "type": "password", "secret": True, "description": "语音方案选 2 时填写"},
            {"key": "volc_app_id", "label": "豆包语音 APP ID", "type": "text", "description": "语音方案选 3 时填写"},
            {"key": "volc_access_token", "label": "豆包语音 Access Token", "type": "password", "secret": True, "description": "语音方案选 3 时填写"},
        ]
        answers = {
            "base_url": "${base_url}",
            "username": "${astrbot_username}",
            "password": "${astrbot_password}",
            "owner_qq": "${owner_qq}",
            "memory": "${memory}",
            "voice": "${voice}",
            "siliconflow_key": "${siliconflow_key}",
            "mimo_key": "${mimo_key}",
            "volc_app_id": "${volc_app_id}",
            "volc_access_token": "${volc_access_token}",
        }
        description = "旧版配置包（自动转换）。原包：%s。通过运行其导入器应用；支持重复执行。" % name
    else:
        variables = [
            {"key": "base_url", "label": "AstrBot 后台地址", "type": "text", "default": "http://127.0.0.1:6185", "required": True},
            {"key": "astrbot_username", "label": "后台账号", "type": "text", "default": "astrbot", "required": True},
            {"key": "astrbot_password", "label": "后台密码", "type": "password", "secret": True, "required": True},
            {"key": "answers_json", "label": "额外回答（JSON）", "type": "multiline", "default": "{}",
             "description": "传给旧版导入器 --answers 文件的额外字段，留空为 {}"},
        ]
        answers = "${answers_json}"
        description = "旧版配置包（自动转换）。原包：%s。通过运行其导入器应用。" % name

    return {
        "schema": SCHEMA,
        "id": pack_id,
        "name": name,
        "version": "legacy",
        "author": "legacy-import",
        "description": description,
        "tags": ["legacy"],
        "variables": variables,
        "steps": [
            {
                "type": "script",
                "name": "运行旧版导入器",
                "file": str(script.relative_to(base)).replace("\\", "/"),
                "args": ["--answers", "{answers_file}"],
                "answers": answers,
                "python": "astrbot",
                "timeout": 7200,
            }
        ],
    }


def import_pack(source: Path, packs_dir: Path = PACKS_DIR) -> dict:
    if not source.exists():
        raise PackError(f"路径不存在：{source}")
    packs_dir.mkdir(parents=True, exist_ok=True)

    extracted = None
    base = source
    if source.is_file():
        if source.suffix.lower() != ".zip":
            raise PackError("请选择配置包文件夹或 .zip 文件")
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        extracted = Path(tempfile.mkdtemp(prefix="snowbot-pack-", dir=str(TEMP_DIR)))
        with zipfile.ZipFile(source) as zf:
            zf.extractall(extracted)
        base = extracted

    try:
        located = _locate_pack(base)
        if not located:
            raise PackError(
                "没有找到 pack.json，也不是可识别的旧版配置包"
                "（settings/pack.json + tools/import_*.py）"
            )
        kind, base = located
        if kind == "legacy":
            legacy = _detect_legacy(base)
            if not legacy:
                raise PackError("旧版配置包缺少 settings/pack.json 或 tools/import_*.py")
            settings_path, script = legacy
            settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
            wrapper = _legacy_wrapper(base, settings, script)
            pack_id = wrapper["id"]
            target = packs_dir / pack_id
            if target.exists():
                raise PackError(f"配置包已存在：{target.name}")
            _copy_tree(base, target)
            (target / "pack.json").write_text(
                json.dumps(wrapper, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return load_pack(target)

        meta = load_pack(base)
        target = packs_dir / str(meta["id"])
        if target.exists():
            raise PackError(f"配置包已存在：{target.name}")
        _copy_tree(base, target)
        return load_pack(target)
    finally:
        if extracted:
            shutil.rmtree(extracted, ignore_errors=True)


def export_pack(pack: dict, target_zip: Path) -> None:
    source = Path(pack["_path"])
    with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in source.rglob("*"):
            if path.is_dir():
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            zf.write(path, str(Path(source.name) / path.relative_to(source)))


def duplicate_pack(pack: dict, packs_dir: Path = PACKS_DIR) -> dict:
    source = Path(pack["_path"])
    new_id = f"{pack['id']}-copy-{int(time.time())}"
    target = packs_dir / new_id
    _copy_tree(source, target)
    meta = json.loads((target / "pack.json").read_text(encoding="utf-8-sig"))
    meta["id"] = new_id
    meta["name"] = f"{pack.get('name', new_id)}（副本）"
    (target / "pack.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return load_pack(target)
