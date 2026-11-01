"""Windows 单实例锁；提权重启时可以先释放，避免新旧进程互相挡住。"""

from __future__ import annotations

from .paths import LOCK_PATH

_lock_file = None


def acquire_single_instance() -> bool:
    """尝试获取锁；已有实例时返回 False。"""
    global _lock_file
    if _lock_file is not None:
        return True
    fh = None
    try:
        import msvcrt

        fh = open(LOCK_PATH, "w")
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        _lock_file = fh
        return True
    except OSError:
        if fh is not None:
            try:
                fh.close()
            except Exception:
                pass
        return False
    except Exception:
        # 非 Windows 或锁机制不可用时不影响程序启动。
        return True


def release_single_instance() -> None:
    """释放锁，供热权重启等场景使用。"""
    global _lock_file
    if _lock_file is None:
        return
    try:
        import msvcrt

        try:
            msvcrt.locking(_lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception:
            pass
    finally:
        try:
            _lock_file.close()
        except Exception:
            pass
        _lock_file = None
