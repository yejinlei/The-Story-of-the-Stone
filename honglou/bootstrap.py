"""依赖引导：优先用已安装的包，找不到时回退到项目内 .pylibs。"""
import sys
from pathlib import Path


def ensure_pylibs() -> None:
    """把 .pylibs（--target 安装的依赖）加入 sys.path。"""
    lib = Path(__file__).resolve().parent.parent / ".pylibs"
    if lib.exists() and str(lib) not in sys.path:
        sys.path.insert(0, str(lib))


def ensure_pymupdf() -> None:
    try:
        import pymupdf  # noqa: F401
        return
    except ImportError:
        pass
    try:
        import fitz  # noqa: F401
        return
    except ImportError:
        pass
    ensure_pylibs()
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        raise SystemExit(
            "缺少 pymupdf，请先执行： pip install -r requirements.txt\n"
            "（PowerShell 若报“不受信任的装入点”，可加 --target <目录> 再把目录加入 PYTHONPATH）"
        )
