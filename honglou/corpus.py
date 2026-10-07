"""把《红楼梦脂评汇校本》PDF 切成「回 → 块」结构，并分离正文与各版本脂批。

分块依据不是标点，而是**字体**：
    宋体（12pt 黑字）        → 正文
    宋体（18pt）             → 回目
    楷体（10/12pt，带颜色）  → 脂批（红=朱批，墨绿/深蓝=墨批）
    楷体（9pt 黑字）         → 校记（页下注）
    楷体（12pt 黑字）        → 回前批 / 回后批 / 总评
    EUDC                     → 批语略字标记
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict

from . import paths
from .annotations import INK_BY_COLOR, decode_marker, is_mark
from .bootstrap import ensure_pymupdf

ensure_pymupdf()
import pymupdf  # noqa: E402

CN_NUM = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
CHAP_RE = re.compile(r'^第\s*([一二三四五六七八九十]{1,3})\s*回\s*(.+)$')
# 回前常单独成一行作「第 四 回」样式的回次标记（字间带空格）
HEAD_NUM_RE = re.compile(r'^第([一二三四五六七八九十]{1,3})回$')
NOTE_MARK = re.compile(r'^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]')
# 页眉页脚噪声
NOISE_RE = re.compile(
    r'^(?:redactor.*|www\.hlmbbs\.com.*|抚琴居.*|\d{1,4}|[IVXLC]{1,7})$')


def is_noise(s: str) -> bool:
    return bool(NOISE_RE.match(s.strip()))

BODY_LAST_PAGE = 989          # 附录一「各抄本收藏者序跋」起始页之前
FRONT_LAST_PAGE = 6           # 目录之前的说明页


def _fixname(s: str) -> str:
    """PDF 中的中文字体名常被按 latin-1 解码成乱码，还原为 GBK。"""
    try:
        return s.encode('latin-1').decode('gbk')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def cn2int(s: str) -> int | None:
    s = s.replace(' ', '')
    if s in CN_NUM:
        return CN_NUM[s]
    if s.startswith('十'):
        return 10 + CN_NUM.get(s[1:], 0)
    if '十' in s:
        a, b = s.split('十', 1)
        return CN_NUM[a] * 10 + CN_NUM.get(b, 0)
    return None


def classify(font: str, size: float, color: int) -> str:
    f = _fixname(font)
    if 'EUDC' in font.upper():
        return 'mark'
    if '宋' in f or 'Song' in font or 'SimSun' in font:
        if size >= 14:
            return 'head'      # 回目
        if size <= 11:
            return 'note'      # 校记（页下 / 回末注）
        return 'main'          # 正文
    if '楷' in f or 'Kai' in font:
        if color == 0 and size <= 10.5:
            return 'note'
        return 'anno' if color else 'anno0'
    if '黑' in f or 'Hei' in font:
        return 'head'
    if 'Times' in font:
        return 'note'
    return 'other'


@dataclass
class Block:
    id: int
    kind: str            # 正文 / 批语 / 校记 / 回目 / 回前批 / 回后批
    text: str
    page: int
    editions: list[str] = field(default_factory=list)
    atype: str = ''      # 眉批 / 侧批 / 夹批
    ink: str = ''        # 朱批 / 墨批
    note_no: str = ''


def _page_chapter(page_text: str) -> tuple[int | None, str]:
    for ln in page_text.split('\n'):
        s = ln.strip()
        if '…' in s or '…' in s:
            continue
        m = CHAP_RE.match(s)
        if m and 4 <= len(m.group(2).strip()) <= 32:
            return cn2int(m.group(1)), m.group(2).strip()
    return None, ''


def _head_marks(blocks: list['Block']) -> list[tuple[int, int]]:
    """按阅读顺序找每一回的起点：形如「第 X 回」的回次行。

    PDF 排版里「第 X 回」多以回前批字体单独成行（且字间带空格，如「第 四 回」），
    紧随其后才是回目标题块。此二者是唯一可靠的分回依据。
    """
    out: list[tuple[int, int]] = []
    for i, b in enumerate(blocks):
        t = (b.text or '').replace(' ', '').strip()
        m = HEAD_NUM_RE.match(t)
        if not m:
            continue
        n = cn2int(m.group(1))
        if not n:
            continue
        if out and (i - out[-1][0] <= 2 or out[-1][1] >= n):
            continue                      # 同一回的重复标注
        out.append((i, n))
    return out


def _heading_title(blocks: list['Block'], start: int) -> str:
    """回次行之后的首个（可能被拆行的）回目名称。"""
    title = ''
    for j in range(start, min(start + 5, len(blocks))):
        b = blocks[j]
        if b.kind == '回目':
            title += b.text.strip()
        elif title:
            break
    return title


ANNO_KINDS = ('批语', '回前批', '回后批', '校记')
_TAIL_PUNCT = '。！？；：”」』）…'


def _merge_strays(blocks: list[Block]) -> list[Block]:
    """把夹在批语中间、因罕用字改用宋体而被误判为「正文」的碎片并回批语。

    例如第四十四回回首诗「莺莺燕燕闘芳菲」中的「闘」、第七十八回「《姽婳词》」
    中的「姽婳」，在 PDF 里换了字体字号，被 classify() 认成正文。
    """
    out: list[Block] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        prev = out[-1] if out else None
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        if (prev is not None and b.kind == '正文' and 0 < len(b.text or '') <= 4
                and not any(c in (b.text or '') for c in '。！？')
                and prev.kind in ANNO_KINDS
                and prev.page in (b.page, b.page - 1)
                and (not prev.text or prev.text[-1] not in _TAIL_PUNCT)):
            prev.text += b.text
            i += 1
            # 碎片原是「批语—碎片—批语」被腰斩的，把后半截也接回来
            while (nxt is not None and nxt.kind == prev.kind and nxt.ink == prev.ink
                   and nxt.page == prev.page
                   and (prev.text or '')[-1:] not in _TAIL_PUNCT
                   and not (nxt.text or '')[:1] in '“《（'):
                prev.text += nxt.text
                i += 1
                nxt = blocks[i + 1] if i + 1 < len(blocks) else None
            continue
        out.append(b)
        i += 1
    return out


def _assign_blocks(blocks: list['Block'], chapters: dict) -> None:
    """以回次标记把全局有序的块回填到各回。

    旧实现是「块 → 所在页 → 页所属回」：一页常同时含上回之末与下回之首，
    页级检测（要求「第X回+回目」同处一行）又常认不出回首，
    于是回首被并入上一回，结果是每回首页缺开头、末尾多带下一回开头。
    此处改以回次标记为唯一权威，页归属只作为页码统计的副产品。
    """
    for c in chapters.values():
        c['blocks'] = []
        c['pages'] = []
    bounds: list[tuple[int, int, int]] = []
    marks = _head_marks(blocks)
    for k, (idx, no) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(blocks)
        bounds.append((no, idx, end))
    if blocks and (not bounds or bounds[0][1] > 0):
        bounds.insert(0, (0, 0, bounds[0][1] if bounds else len(blocks)))
    for no, a, b in bounds:
        title = ''
        got = chapters.get(no)
        if got is not None:
            title = got['title']
        if not title and no > 0:
            title = _heading_title(blocks, a)
        ch = chapters.setdefault(
            no, dict(no=no, title=title, pages=[], blocks=[]))
        for blk in blocks[a:b]:
            ch['blocks'].append(blk)
            if blk.page not in ch['pages']:
                ch['pages'].append(blk.page)


def extract(save: bool = True) -> dict:
    doc = pymupdf.open(str(paths.PDF_PATH))
    chapters: dict[int, dict] = {}
    cur_chap = 0
    cur_title = '凡例'
    blocks: list[Block] = []
    bid = 0
    pending_marks: list[str] = []      # 最近一次标记串
    pending_ink = ''
    last_main = ''                     # 批语所锚定的正文片段

    for pno in range(1, BODY_LAST_PAGE + 1):
        page = doc[pno]
        raw = page.get_text()
        chap_no, chap_title = _page_chapter(raw)
        if chap_no:
            cur_chap, cur_title = chap_no, chap_title
        ch = chapters.setdefault(cur_chap, dict(no=cur_chap, title=cur_title, pages=[], blocks=[]))
        ch['pages'].append(pno)

        # 收集字符（按阅读顺序）
        chars = []
        for b in page.get_text('rawdict')['blocks']:
            if b['type'] != 0:
                continue
            for ln in b['lines']:
                for sp in ln['spans']:
                    k = classify(sp['font'], sp['size'], sp['color'])
                    for c in sp['chars']:
                        chars.append((c['c'], k, sp['color'], ln['bbox'][1], c['bbox'][0]))

        # 合并同类相邻字符
        runs: list[dict] = []
        for ch_, k, color, y, x in chars:
            if is_mark(ch_):
                k = 'mark'
            if runs and runs[-1]['k'] == k and abs(runs[-1]['y'] - y) < 3:
                runs[-1]['s'] += ch_
                runs[-1]['x1'] = x
            else:
                runs.append(dict(k=k, s=ch_, color=color, y=y, x0=x, x1=x, page=pno))

        left = min((r['x0'] for r in runs if r['k'] == 'main'), default=60.0)
        prev_main_run = False
        for r in runs:
            s = r['s'].strip()
            if not s or NOISE_RE.search(s):
                continue
            if r['k'] == 'mark':
                pending_marks = [c for c in s if is_mark(c)]
                continue
            if r['k'] == 'main':
                indent = r['x0'] > left + 8
                if blocks and blocks[-1].kind == '正文' and not indent and prev_main_run:
                    blocks[-1].text += s
                else:
                    bid += 1
                    blocks.append(Block(bid, '正文', s, pno))
                last_main = blocks[-1].text[-40:]
                prev_main_run = True
                continue
            prev_main_run = False
            if r['k'] == 'head':
                bid += 1
                blocks.append(Block(bid, '回目', s, pno))
                continue
            if r['k'] == 'note':
                if 'www.hlmbbs.com' in s or '抚琴居' in s or CHAP_RE.match(s):
                    continue
                parts = re.split(r'(?=[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])', s)
                for p in parts:
                    p = p.strip()
                    if not p:
                        continue
                    no = NOTE_MARK.match(p)
                    if no and len(p) <= 2:
                        continue          # 正文中的校记序号，不单独立块
                    prev = blocks[-1] if blocks else None
                    if (no is None and prev is not None and prev.kind == '校记'
                            and prev.page in (pno, pno - 1)):
                        prev.text += p
                        continue
                    bid += 1
                    blocks.append(Block(bid, '校记', p, pno, note_no=no.group(0) if no else ''))
                continue
            if r['k'].startswith('anno'):
                editions, atype = decode_marker(''.join(pending_marks)) if pending_marks else ([], '')
                ink = INK_BY_COLOR.get(r['color'], '墨批')
                if r['k'] == 'anno0':
                    kind = '回后批' if s.startswith('总评') else '回前批'
                    ink = '墨批'
                else:
                    kind = '批语'
                # 无标记且紧接上一条同墨色批语 → 跨行续接
                prev = blocks[-1] if blocks else None
                if (not pending_marks and prev is not None and prev.page == pno
                        and prev.kind in ('批语', '回前批', '回后批') and prev.ink == ink):
                    prev.text += s
                    pending_marks = []
                    continue
                bid += 1
                blocks.append(Block(bid, kind, s, pno, editions, atype, ink))
                pending_marks = []
                continue
            # other：忽略
        ch['blocks'] = []  # 稍后统一回填

    # 罕用字造成的伪正文碎片先归并，再按回次标记回填到各回
    blocks = _merge_strays(blocks)
    _assign_blocks(blocks, chapters)

    chs = []
    for k in sorted(chapters):
        c = dict(chapters[k])
        bl = [asdict(b) for b in c['blocks']]
        # 回前批 / 回后批：按相对正文的位置再判一次
        idx = [i for i, b in enumerate(bl) if b['kind'] == '正文']
        if idx:
            for i, b in enumerate(bl):
                if b['kind'] == '回前批' and i > idx[0] and not b['text'].startswith('总评'):
                    b['kind'] = '回后批' if i > idx[-1] else '回前批'
        c['blocks'] = bl
        chs.append(c)
    out = dict(
        meta=dict(
            source=paths.PDF_PATH.name,
            edition='《红楼梦脂评汇校本》Kolistan 汇校（版本 3.13，2009.7.20）',
            pages=BODY_LAST_PAGE + 1,
            chapters=len([c for c in chapters if c > 0]),
            blocks=len(blocks),
        ),
        chapters=chs,
    )
    if save:
        paths.data('corpus.json').write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    return out


def stats(corpus: dict) -> dict:
    from collections import Counter
    kinds = Counter()
    ed = Counter()
    at = Counter()
    for ch in corpus['chapters']:
        for b in ch['blocks']:
            kinds[b['kind']] += 1
            for e in b.get('editions', []):
                ed[e] += 1
            if b.get('atype'):
                at[b['atype']] += 1
    return dict(kinds=dict(kinds), editions=dict(ed), atypes=dict(at))


if __name__ == '__main__':
    c = extract()
    print(json.dumps(c['meta'], ensure_ascii=False))
    print(json.dumps(stats(c), ensure_ascii=False, indent=1))
