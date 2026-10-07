"""姓氏归一表：Unihan 自动 singers + 人工审定的高频异写字。

扫瞄本转录里混进大量日本印刷体系的略字（𦗟、㸃、𨚫、𬋩 …），Unihan 的
变体字段认不出，须按上下文人工定其本字，再落成 data/variant_map.json。
"""
from __future__ import annotations

import collections
import io
import json
import zipfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".pylibs"))

from honglou import witness as W  # noqa: E402

UNIHAN_URL = "https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip"
FIELDS = ("kTraditionalVariant", "kSimplifiedVariant", "kSemanticVariant",
          "kZVariant", "kSemiSimplifiedVariant", "kSpecializedSemanticVariant")

# 人工审定：皆为频次 ≥30 的印刷略字，逐一按上下文定其本字
CURATED = {
    "𦗟": "听", "㸃": "点", "𨚫": "却", "𬋩": "管", "𮟃": "还",
    "𭺾": "毕", "𪾶": "睡", "𦂳": "紧", "𤨔": "环", "𡚱": "妃",
    "𦘏": "听", "𭣣": "收", "𣲖": "派", "㫁": "断", "𡍼": "涂",
    "㣲": "微", "𭮀": "死", "㫖": "旨", "𧇊": "亏", "㕔": "厅",
    "㨿": "据", "𥦗": "窗", "𥪡": "竖", "𠻳": "嗽", "𤼵": "发",
    "䕶": "护", "𮌖": "脂", "𠋣": "倚", "𡨚": "冤", "𨒖": "迎",
    "㓜": "幼", "𡸁": "垂", "𫎇": "蒙", "𤕤": "爽", "𭭎": "款",
    "㮣": "概", "𭔃": "寄", "𥙊": "祭", "𦂶": "绮", "𮪍": "骑",
    "𮅕": "算", "䌷": "绸", "𦵏": "葬", "𧄇": "蘅", "𣑱": "染",
    "㧓": "抓", "囘": "回", "囬": "回", "聼": "听", "塲": "场",
    "歩": "步", "鳯": "凤", "尙": "尚", "寔": "实", "冺": "泯",
    "䧟": "陷", "鍳": "鉴", "粧": "妆", "様": "样", "偺": "咱",
    "呌": "叫", "徃": "往", "閙": "闹", "著": "着", "么": "么",
    "㩦": "携", "寛": "宽", "腺": "腺", "决": "决", "决": "决",
    "槩": "概", "䖍": "虔", "𡚁": "弊", "𨌩": "荡", "𨻶": "隙",
    "𩔗": "类", "㯽": "槟", "䋲": "绳", "𥂁": "盐", "𫉬": "获",
}


def is_common(c: str) -> bool:
    return "一" <= c <= "鿿"


def load_unihan() -> dict[str, dict[str, list[str]]]:
    p = ROOT / "build" / "Unihan.zip"
    if not p.exists():
        import urllib.request as u
        p.write_bytes(u.urlopen(u.Request(
            UNIHAN_URL, headers={"User-Agent": "Mozilla/5.0"}),
            timeout=60).read())
    out: dict[str, dict[str, list[str]]] = {}
    with zipfile.ZipFile(io.BytesIO(p.read_bytes())) as z:
        for name in z.namelist():
            if "Variants" not in name:
                continue
            for line in z.read(name).decode("utf-8").splitlines():
                if not line or line.startswith("#"):
                    continue
                cp, field, rest = line.split("\t", 2)
                if field not in FIELDS:
                    continue
                grabs = []
                for t in rest.split():
                    t = t.split("<")[0]
                    if t.startswith("U+"):
                        grabs.append(chr(int(t[2:], 16)))
                if grabs:
                    out.setdefault(chr(int(cp[2:], 16)), {})[field] = grabs
    return out


def main():
    unihan = load_unihan()
    from opencc import OpenCC
    cc = OpenCC("t2s")

    rare: collections.Counter = collections.Counter()
    for key in ("chengjia", "chengyi", "zhiqi", "jiaxu"):
        rec = W.load(key)
        for v in rec["chapters"].values():
            for c in v["text"]:
                if is_common(c):
                    continue
                o = ord(c)
                if 0x3400 <= o <= 0x4DBF or o > 0x1FFFF:
                    rare[c] += 1
    total = sum(rare.values())
    print(f"扩展区字数 {len(rare)} 种，出现 {total} 次")

    mapping: dict[str, str] = dict(CURATED)
    for c, n in rare.most_common():
        if n < 2 or c in mapping:
            continue
        cand = []
        for f in FIELDS:
            for t in unihan.get(c, {}).get(f, []):
                if is_common(t):
                    cand.append(cc.convert(t))
                else:
                    for f2 in FIELDS:
                        for t2 in unihan.get(t, {}).get(f2, []):
                            if is_common(t2):
                                cand.append(cc.convert(t2))
        cand = [x for x in cand if x and len(x) == 1]
        if cand:
            mapping[c] = collections.Counter(cand).most_common(1)[0][0]

    # 目标必须是通用字
    bad = [(k, v) for k, v in mapping.items() if not is_common(v)]
    for k, v in bad:
        print(f"  目标非通用字，弃：{k} → {v}")
        mapping.pop(k)
    hit = sum(rare[c] for c in mapping)
    print(f"映射出 {len(mapping)} 种，覆盖 {hit}/{total} "
          f"（{hit / total:.1%}）")
    rest = [(c, n, hex(ord(c))) for c, n in rare.most_common()
            if c not in mapping and n >= 5]
    print(f"未覆盖（≥5 次）{len(rest)} 种：", rest[:40])

    (ROOT / "data" / "variant_map.json").write_text(
        json.dumps(dict(source="Unihan_Variants + 人工审定",
                        built=W.time.strftime("%Y-%m-%d"),
                        map=mapping), ensure_ascii=False, indent=0),
        encoding="utf-8")
    print(f"余下 {len(rest)} 种不入此表；统计时将按扩展区字一并略去。")


if __name__ == "__main__":
    main()
