"""刷手机事件的纯逻辑：B站热门 / 小黑盒信息流解析、去重与提示词。

不依赖 AstrBot，可单独测试。B站热门和小黑盒 feeds 都能在未登录状态读取；
小红书首页需要登录 Cookie，暂不纳入自动刷。
"""

from __future__ import annotations

import hashlib
import random
import time
import re

HKEY_CHARSET = "AB45STUVWZEFGJ6CH01D237IXYPQRKLMN89"


# ---------------- 小黑盒 hkey（公开逆向实现） ----------------
def _vm(e: int) -> int:
    return (255 & ((e << 1) ^ 27)) if e & 128 else e << 1


def _qm(e: int) -> int:
    return _vm(e) ^ e


def _dm(e: int) -> int:
    return _qm(_vm(e))


def _ym(e: int) -> int:
    return _dm(_qm(_vm(e)))


def _gm(e: int) -> int:
    return _ym(e) ^ _dm(e) ^ _qm(e)


def _km(e: list[int]) -> list[int]:
    e = list(e)
    e[:4] = [
        _gm(e[0]) ^ _ym(e[1]) ^ _dm(e[2]) ^ _qm(e[3]),
        _qm(e[0]) ^ _gm(e[1]) ^ _ym(e[2]) ^ _dm(e[3]),
        _dm(e[0]) ^ _qm(e[1]) ^ _gm(e[2]) ^ _ym(e[3]),
        _ym(e[0]) ^ _dm(e[1]) ^ _qm(e[2]) ^ _gm(e[3]),
    ]
    return e


def _map_chars(text: str, charset: str, length: int) -> str:
    part = charset[:length] if length < 0 else charset[:length]
    return "".join(part[ord(ch) % len(part)] for ch in text)


def _map_full(text: str, charset: str) -> str:
    return "".join(charset[ord(ch) % len(charset)] for ch in text)


def generate_hkey(path: str, timestamp: int, nonce: str) -> str:
    parts = [part for part in str(path).split("/") if part]
    normalized = "/" + "/".join(parts) + "/"
    comps = [
        _map_chars(str(timestamp), HKEY_CHARSET, -2),
        _map_full(normalized, HKEY_CHARSET),
        _map_full(nonce, HKEY_CHARSET),
    ]
    interleaved = "".join(
        comps[index][pos]
        for pos in range(max(len(comp) for comp in comps))
        for index in range(len(comps))
        if pos < len(comps[index])
    )
    md5 = hashlib.md5(interleaved[:20].encode()).hexdigest()
    prefix = _map_chars(md5[:5], HKEY_CHARSET, -4)
    return prefix + f"{sum(_km([ord(ch) for ch in md5[-6:]])) % 100:02d}"


def heybox_feed_params() -> dict:
    timestamp = int(time.time())
    nonce = hashlib.md5(
        (str(timestamp) + str(random.random())).encode()
    ).hexdigest().upper()
    return {
        "pull": "0",
        "offset": "0",
        "dw": "844",
        "os_type": "web",
        "app": "heybox",
        "client_type": "web",
        "version": "999.0.4",
        "web_version": "2.5",
        "x_client_type": "web",
        "x_app": "heybox_website",
        "heybox_id": "",
        "x_os_type": "Windows",
        "device_info": "Chrome",
        "device_id": "2c2fef8385ccef915e3b3caf94e3aa06",
        "hkey": generate_hkey("/bbs/app/feeds", timestamp, nonce),
        "_time": timestamp,
        "nonce": nonce,
    }


# ---------------- 信息流解析 ----------------
def parse_bili_popular(payload: dict) -> list[dict]:
    data = (payload or {}).get("data") or {}
    rows = []
    for item in data.get("list") or []:
        if not isinstance(item, dict):
            continue
        bvid = str(item.get("bvid") or "").strip()
        title = str(item.get("title") or "").strip()
        if not bvid or not title:
            continue
        rows.append(
            {
                "id": bvid,
                "platform": "B站",
                "title": title,
                "desc": str(item.get("desc") or "").strip()[:300],
                "author": str((item.get("owner") or {}).get("name") or "").strip(),
                "url": f"https://www.bilibili.com/video/{bvid}",
                "duration": int(item.get("duration") or 0),
                "image": str(item.get("pic") or "").strip(),
            }
        )
    return rows


def parse_heybox_feeds(payload: dict) -> list[dict]:
    result = (payload or {}).get("result") or {}
    rows = []
    for item in result.get("links") or []:
        if not isinstance(item, dict):
            continue
        link_id = str(item.get("link_id") or item.get("linkid") or "").strip()
        title = str(item.get("title") or "").strip()
        if not link_id or not title:
            continue
        rows.append(
            {
                "id": link_id,
                "platform": "小黑盒",
                "title": title,
                "desc": str(item.get("description") or "").strip()[:300],
                "author": str((item.get("user") or {}).get("username") or "").strip(),
                "url": f"https://www.xiaoheihe.cn/app/bbs/link/{link_id}",
                "duration": 0,
                "image": str(item.get("image") or item.get("thumb") or "").strip(),
                "has_video": bool(item.get("has_video")),
            }
        )
    return rows


def pick_fresh(items: list[dict], seen: set[str], limit: int) -> list[dict]:
    """挑没见过的条目；优先非视频，避免刷手机事件太重。"""
    fresh = [item for item in items if str(item.get("id")) not in seen]
    fresh.sort(key=lambda item: (bool(item.get("has_video")), item.get("platform") != "B站"))
    return fresh[: max(1, int(limit))]


def trim_seen(seen: list[str], cap: int = 300) -> list[str]:
    return list(dict.fromkeys(str(item) for item in seen))[-cap:]


def build_browsing_prompt(items: list[dict], minutes: int = 15) -> str:
    lines = []
    for index, item in enumerate(items, 1):
        lines.append(
            f"{index}. [{item.get('platform')}]《{item.get('title')}》"
            f"（{item.get('author') or '未知作者'}）"
            + (f"\n   简介：{item['desc']}" if item.get("desc") else "")
        )
    return (
        f"你刚刷了 {minutes} 分钟手机，刷到这些内容：\n"
        + "\n".join(lines)
        + "\n\n用第一人称写一段刷手机记录：挑 1-2 条你最有感的，说说看到什么、你怎么想、"
        "有没有想吐槽或分享的；不要逐条罗列，不要伪造没看到的情节，200 字以内。"
        "语气自然，像自己随手记的。"
    )


def browsing_filename(day: str) -> str:
    return f"{str(day or '')[:10]} 刷手机.md"


def sanitize_title(text: str, limit: int = 80) -> str:
    value = re.sub(r"[\r\n\t]+", " ", str(text or "")).strip()
    return value[:limit]
