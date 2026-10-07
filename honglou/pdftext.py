"""PDF 文本抽取与缓存。

《红楼梦脂评汇校本》是文本型 PDF（非扫描件），pypdf 可直接抽字。
批语用私用区（PUA）略字标记版本与批注类型，见 `honglou/annotations.py`。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import paths

PAGE_CACHE = paths.cache("pages.json")

# 页眉/页脚噪声
_HEADER_PATTERNS = (
    re.compile(r"^\s*抚琴居红楼梦脂评汇校本\s*$"),
    re.compile(r"^\s*redactor:\s*k\s*olistan\s*$"),
    re.compile(r"^\s*www\.hlmbbs\.com\s*$"),
)
_PAGE_NUM = re.compile(r"^\s*[IVXLC]{1,7}\s*$")


def extract_pages(pdf_path: Path | str | None = None, force: bool = False) -> list[dict]:
    """抽取全部页面文本，结果缓存为 JSON。"""
    pdf_path = Path(pdf_path or paths.PDF_PATH)
    if PAGE_CACHE.exists() and not force:
        return json.loads(PAGE_CACHE.read_text(encoding="utf-8"))

    import pypdf

    reader = pypdf.PdfReader(str(pdf_path))
    pages = []
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:  # pragma: no cover - 个别页解析失败
            text = ""
        pages.append({"page": i, "text": text})
    PAGE_CACHE.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    return pages


def clean_lines(text: str) -> list[str]:
    """去掉页眉页脚，返回有效行。"""
    out = []
    for ln in text.split("\n"):
        s = ln.strip()
        if not s:
            continue
        if any(p.match(s) for p in _HEADER_PATTERNS):
            continue
        if _PAGE_NUM.match(s):
            continue
        out.append(s)
    return out


if __name__ == "__main__":
    ps = extract_pages()
    print(f"pages={len(ps)} chars={sum(len(p['text']) for p in ps)}")
