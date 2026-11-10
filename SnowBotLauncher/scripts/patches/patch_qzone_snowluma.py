r"""给第三方 qzone 插件打 SnowLuma 兼容补丁（可重复执行）。

问题：qzone 的定时任务在 OneBot WS 重连后可能持有旧 CQHttp 对象，且 get_cookies
没有指定 self_id；SnowLuma 在调度上下文里会报 ApiNotAvailable。

用法：
    python scripts/patches/patch_qzone_snowluma.py "C:\...\data\plugins\astrbot_plugin_qzone"
"""

from __future__ import annotations

import sys
from pathlib import Path


def patch_session(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if "_self_id(self)" in text:
        return False
    old = '''    async def _refresh_ctx_locked(self) -> QzoneContext:
        if not self.cfg.client:
            raise RuntimeError("CQHttp 实例不存在")

        payload = await self.cfg.client.get_cookies(domain=self.DOMAIN)
'''
    new = '''    def _self_id(self) -> int | None:
        """调度任务里没有 event_ws，显式指定 Bot 账号给 SnowLuma/NapCat。"""
        try:
            clients = getattr(self.cfg.client, "_wsr_api_clients", None) or {}
            if isinstance(clients, dict) and clients:
                return int(next(iter(clients)))
        except Exception:
            pass
        return None

    async def _refresh_ctx_locked(self) -> QzoneContext:
        if not self.cfg.client:
            raise RuntimeError("CQHttp 实例不存在")

        payload = await self.cfg.client.get_cookies(
            domain=self.DOMAIN, self_id=self._self_id()
        )
'''
    if old not in text:
        return False
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
    return True


def patch_main(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if "_bot_alive" in text:
        return False
    old = '''    def _capture_page_client(self):
        if self.cfg.client is not None:
            return self.cfg.client
        try:
            platform = self.context.get_platform("aiocqhttp")
        except Exception:
            platform = None
        if platform is None:
            try:
                for candidate in self.context.platform_manager.platform_insts:
                    meta = candidate.meta()
                    if getattr(meta, "name", "") == "aiocqhttp":
                        platform = candidate
                        break
            except Exception:
                platform = None
        bot = getattr(platform, "bot", None) if platform is not None else None
        if bot is not None:
            self.cfg.client = bot
        return self.cfg.client
'''
    new = '''    @staticmethod
    def _bot_alive(bot) -> bool:
        """CQHttp 对象上还挂着 WS 连接才算活着；重连后旧对象会空掉。"""
        clients = getattr(bot, "_wsr_api_clients", None)
        if clients is None:
            return True
        return bool(clients)

    def _capture_page_client(self):
        if self.cfg.client is not None and self._bot_alive(self.cfg.client):
            return self.cfg.client
        self.cfg.client = None
        platforms = []
        try:
            platform = self.context.get_platform("aiocqhttp")
            if platform is not None:
                platforms.append(platform)
        except Exception:
            pass
        try:
            platforms.extend(self.context.platform_manager.platform_insts)
        except Exception:
            pass
        for candidate in platforms:
            try:
                meta = candidate.meta()
            except Exception:
                meta = None
            if meta is not None and getattr(meta, "name", "") not in ("aiocqhttp", "napcat"):
                continue
            bot = getattr(candidate, "bot", None)
            if bot is not None and self._bot_alive(bot):
                self.cfg.client = bot
                logger.info("Qzone 已绑定当前 OneBot 连接")
                return bot
        return self.cfg.client
'''
    if old not in text:
        return False
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
    return True


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: patch_qzone_snowluma.py <qzone 插件目录>")
        return 2
    root = Path(sys.argv[1])
    session = root / "core" / "qzone" / "session.py"
    main_py = root / "main.py"
    if not session.is_file() or not main_py.is_file():
        print(f"找不到 qzone 插件文件：{root}")
        return 1
    print("session.py:", "patched" if patch_session(session) else "already/未匹配")
    print("main.py:", "patched" if patch_main(main_py) else "already/未匹配")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
