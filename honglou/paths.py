"""全局路径约定。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PDF_PATH = ROOT / "红楼梦脂评汇校本.pdf"
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
SITE_DIR = ROOT / "docs"          # GitHub Pages 直接托管 docs/
BUILD_DIR = ROOT / "build"        # 中间产物

for _d in (DATA_DIR, CACHE_DIR, SITE_DIR, BUILD_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def data(name: str) -> Path:
    return DATA_DIR / name


def cache(name: str) -> Path:
    return CACHE_DIR / name


def load_env() -> None:
    """加载 .env（仅本地存在，不入库）。"""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
