"""每回白话文串讲：给少年读者的现代汉语改写。

前八十回取脂本正文，后三十回取续写成稿；由 LLM 改写成通顺的白话小故事，
落盘 data/vernacular.json（按回缓存，可断点续跑）。LLM 不可用时自动跳过，
站点照常生成，只是没有白话文。
"""
from __future__ import annotations

import json
import re

from . import db, llm, paths

OUT = paths.data('vernacular.json')

PROMPT = """你是给十岁孩子讲《红楼梦》的老师。请把下面这一回（{title}）
用现代汉语白话讲成一个通顺的小故事。

要求：
1. 400—600 字，分 3—4 段，短句，口语化，孩子一读就懂；
2. 说清「谁、在哪儿、做了什么、结果怎样」；人名第一次出现时点明身份
   （如「贾宝玉，贾府最受宠的公子」）；
3. 保留本回的关键情节与对话要点，不删重要转折，也不添油加醋；
4. 不评论、不考据、不提脂批与程高本，不剧透后面回目的事；
5. 不用「她」「他们」，用「他」「大家」「众人」；不用现代网络语；
6. 回中的诗词只概括其意思，不要整段照抄原文。

直接输出白话文正文，不要小标题、不要任何说明。

【本回原文】
{text}
"""

TITLE_RE = re.compile(r'^第\s*[一二三四五六七八九十百零〇\d]+\s*回\s*')


def load() -> dict[str, dict]:
    if OUT.exists():
        try:
            return json.loads(OUT.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}


def save(doc: dict[str, dict]) -> None:
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding='utf-8')


def chapter_text(ch: int) -> tuple[str, str]:
    """返回 (回目, 正文)。"""
    if ch <= 80:
        rows = db.q('SELECT title FROM chapters WHERE chapter = ?', [ch])
        title = rows[0]['title'] if rows else ''
        blocks = db.q('SELECT kind, text FROM blocks WHERE chapter = ? ORDER BY id',
                      [ch])
        body = ''.join(b['text'] for b in blocks if b['kind'] == '正文')
        if not title:
            for b in blocks:
                if b['kind'] == '回目':
                    title = b['text']
                    break
        return title or '', body
    rows = db.q('SELECT title, text FROM continuations WHERE chapter = ?', [ch])
    if not rows:
        return '', ''
    text = rows[0]['text'] or ''
    lines = [x for x in text.split('\n') if x.strip()]
    if lines and TITLE_RE.match(lines[0].strip()):
        lines = lines[1:]                     # 去掉正文开头的回目行
    return rows[0]['title'] or '', '\n'.join(lines)


MAX_LEN = 1200          # 超过则要求压缩重写一遍


def gen(ch: int, force: bool = False, limit_chars: int = 9000,
        max_len: int = MAX_LEN, max_tokens: int = 1500) -> dict | None:
    """生成一回的白话文；已有则跳过（force 除外）。"""
    doc = load()
    key = str(ch)
    if not force and doc.get(key, {}).get('text'):
        return None
    title, body = chapter_text(ch)
    if not body.strip():
        return None
    text = body[:limit_chars]
    ask = PROMPT.format(title=title or f'第{ch}回', text=text)
    out = llm.chat([{'role': 'user', 'content': ask}],
                   temperature=0.6, max_tokens=max_tokens,
                   tag=f'vern-{ch}').strip()
    out = re.sub(r'^(白话文|译文)[：:]\s*', '', out)
    if len(out) > max_len:          # 稿子太长（或跑飞），压一遍
        short = llm.chat(
            [{'role': 'user', 'content': ask},
             {'role': 'assistant', 'content': out[:2000]},
             {'role': 'user', 'content':
              f'上面这稿 {len(out)} 字，太长了。请压缩到 600 字以内，'
              '只留主干情节与结局，重新输出一遍，不要重复句子。'}],
            temperature=0.5, max_tokens=1200, tag=f'vern2-{ch}').strip()
        short = re.sub(r'^(白话文|译文)[：:]\s*', '', short)
        if 80 < len(short) < len(out):
            out = short
    if len(out) > max_len:          # 仍过长：截至最后一个句号，避免残稿
        cut = out[:max_len]
        k = max(cut.rfind('。'), cut.rfind('！'), cut.rfind('？'))
        out = (cut[:k + 1] if k > max_len * 0.5 else cut) + '…'
    doc[key] = dict(title=title, text=out)
    save(doc)
    return doc[key]


def too_long(doc: dict | None = None, max_len: int = MAX_LEN) -> list[int]:
    """返回白话文超长的回次。"""
    doc = doc if doc is not None else load()
    return sorted(int(k) for k, v in doc.items()
                  if k.isdigit() and len((v or {}).get('text', '')) > max_len)


def build(start: int = 1, end: int = 110, force: bool = False,
          limit: int | None = None, only_long: bool = False) -> list[dict]:
    """逐回生成；单回失败不影响其余。only_long 只重生成超长的回。"""
    done, n = [], 0
    todo = too_long() if only_long else list(range(start, end + 1))
    if only_long:
        force = True
    for ch in (int(x) for x in todo):
        try:
            r = gen(ch, force=force)
        except Exception as e:
            print(f'第{ch}回 白话文失败：{str(e)[:80]}', flush=True)
            continue
        if r:
            n += 1
        done.append(dict(chapter=ch, ok=bool(r), chars=len((r or {}).get('text', ''))))
        print(f'第{ch}回 白话文 {len((r or {}).get("text", ""))} 字', flush=True)
        if limit and n >= limit:
            break
    return done
