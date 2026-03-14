"""后端运行时环境变量加载器。"""

from __future__ import annotations

import os
import threading
from pathlib import Path


_LOCK = threading.Lock()
_LOADED = False


def _should_skip_autoload() -> bool:
    # 测试场景保持可控，避免读取开发机真实 .env 污染测试结果。
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    if str(os.getenv("CCAD_DISABLE_LOCAL_ENV_AUTOLOAD") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True
    return False


def ensure_local_env_loaded() -> bool:
    """按需加载后端根目录 .env，仅补齐进程内缺失变量。"""
    global _LOADED
    if _LOADED or _should_skip_autoload():
        return False

    with _LOCK:
        if _LOADED or _should_skip_autoload():
            return False

        env_path = Path(__file__).resolve().parents[1] / ".env"
        if not env_path.exists():
            _LOADED = True
            return False

        loaded = False
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
                loaded = True

        _LOADED = True
        return loaded


__all__ = ["ensure_local_env_loaded"]
