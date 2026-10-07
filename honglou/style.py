"""文体一致性：现代词禁例、原文样板取样、风格向量与距离。

续写最大的破绽往往不是情节，而是词汇与句法的「现代腔」。
这里把「禁例」做成可复算的检查项，与统计指标一起构成风格门禁。
"""
from __future__ import annotations

import json
import re
from collections import Counter

from . import db

# 现代书面语 / 翻译腔 / 网络语：出现在续写中即为破绽
MODERN_WORDS = [
    '梦想', '鼓励', '关怀', '希望', '勇敢', '坚强', '坚韧', '未来', '期待',
    '写生', '色彩斑斓', '生机勃勃', '生活', '社会', '家庭', '关系', '压力',
    '情绪', '心理', '意识', '自由', '幸福', '命运多舛', '她', '她们',
    '他俩', '咱们俩', '一些', '一种', '非常', '特别', '真的', '其实',
    '因为', '所以', '但是', '然后', '而且', '如果', '可以', '应该',
    '觉得', '认为', '感到', '显得', '进行', '通过', '关于', '对于',
    '氛围', '环境', '场景', '画面', '瞬间', '时刻', '过程', '状态',
]
# 需用古白话替代的代词/句式
BANNED_PAT = [
    (r'她们?', '他/那人/他姊妹'),
    (r'虽然.*?但是', '虽…然…'),
    (r'如果.*?就', '若…便…'),
    (r'因为.*?所以', '因…故…'),
    (r'觉得', '觉着/自觉'),
    (r'进行|通过|关于|对于', '（改用白话动宾）'),
]

# 曹雪芹常用而与今人不同的词（续写中应当出现，作为正向信号）
PREFERRED = ['笑道', '说道', '因道', '一面', '只见', '忽见', '且说', '话说',
             '当下', '于是', '遂', '只得', '不觉', '越性', '横竖', '仔细',
             '姑娘', '丫头', '婆子', '媳妇', '进来', '出去', '起身', '坐下']


def lint(text: str) -> dict:
    """现代腔检查。"""
    hits = []
    for w in MODERN_WORDS:
        n = text.count(w)
        if n:
            hits.append(dict(word=w, n=n))
    pats = []
    for p, alt in BANNED_PAT:
        m = re.findall(p, text)
        if m:
            pats.append(dict(pattern=p, n=len(m), suggest=alt))
    pref = {w: text.count(w) for w in PREFERRED if text.count(w)}
    return dict(modern=hits, patterns=pats, preferred=pref,
                preferred_n=sum(pref.values()),
                modern_n=sum(h['n'] for h in hits))


def lint_report(text: str) -> str:
    r = lint(text)
    if not r['modern'] and not r['patterns']:
        return '无现代腔违例。'
    s = []
    for h in sorted(r['modern'], key=lambda x: -x['n'])[:12]:
        s.append(f"{h['word']}×{h['n']}")
    for p in r['patterns'][:6]:
        s.append(f"句式「{p['pattern']}」×{p['n']}（宜作{p['suggest']}）")
    return '；'.join(s)


# ---------------------------------------------------------------- 样板

def sample_original(chapters=(78, 79, 80), n: int = 900) -> str:
    """取脂本原笔若干字作为风格样板（few-shot）。"""
    rows = db.q('SELECT text FROM v_main WHERE chapter IN (%s) ORDER BY id'
                % ','.join(str(c) for c in chapters))
    t = ''.join(r['text'] for r in rows)
    return t[-n:] if len(t) > n else t


def style_vector(text: str) -> dict:
    z = re.findall(r'[一-鿿]', text)
    if not z:
        return {}
    sents = [s for s in re.split(r'[。！？；!?;]', text) if s.strip()]
    from .poems import XUCI
    return dict(
        chars=len(z),
        avg_sent_len=round(sum(len(s) for s in sents) / max(1, len(sents)), 2),
        dialog_rate=round(len(re.findall(r'[：「"]', text)) / len(z), 4),
        xuci_rate=round(sum(1 for c in z if c in XUCI) / len(z), 4),
        four_char=len(re.findall(r'[一-鿿]{4}(?=[，。、；])', text)),
        type_token=round(len(set(z)) / len(z), 4),
        top_chars=Counter(z).most_common(20),
    )


def baseline(chapters=(70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80),
             chunk: int = 1500) -> dict:
    """基准风格向量：按等长片段（默认 1500 字）统计后再平均，
    使「型例比」等长度依赖指标可与续写稿（千字量级）比较。"""
    rows = db.q('SELECT text FROM v_main WHERE chapter IN (%s)'
                % ','.join(str(c) for c in chapters))
    t = ''.join(r['text'] for r in rows)
    chunks = [t[i:i + chunk] for i in range(0, len(t), chunk)]
    vs = [style_vector(c) for c in chunks if len(re.findall(r'[一-鿿]', c)) > 800]
    if not vs:
        return style_vector(t)
    out = {k: round(sum(v.get(k, 0) for v in vs) / len(vs), 4)
           for k in ('avg_sent_len', 'dialog_rate', 'xuci_rate', 'type_token')}
    out['chars'] = len(re.findall(r'[一-鿿]', t))
    out['chunks'] = len(vs)
    return out


def distance(a: dict, b: dict) -> float:
    keys = ['avg_sent_len', 'dialog_rate', 'xuci_rate', 'type_token']
    scale = [30.0, 0.03, 0.06, 0.1]
    d = sum(((a.get(k, 0) - b.get(k, 0)) / s) ** 2
            for k, s in zip(keys, scale) if k in a and k in b)
    return round((d / len(keys)) ** 0.5, 4)


def gate(text: str, base: dict | None = None, max_dist: float = 1.0,
         max_modern: int = 6) -> dict:
    """风格门禁：返回是否通过 + 诊断。"""
    base = base or baseline()
    v = style_vector(text)
    d = distance(base, v)
    l = lint(text)
    return dict(pass_=d <= max_dist and l['modern_n'] <= max_modern,
                distance=d, metrics=v, lint=l,
                lint_text=lint_report(text),
                advice=_advice(base, v, l))


def _advice(base: dict, v: dict, l: dict) -> list[str]:
    out = []
    if v.get('avg_sent_len', 0) > base.get('avg_sent_len', 0) * 1.15:
        out.append('句子偏长，宜多作短句、多用「道」字断句。')
    if v.get('dialog_rate', 0) < base.get('dialog_rate', 0) * 0.7:
        out.append('对话偏少，宜增加人物对白（此书以对话见人物）。')
    if v.get('xuci_rate', 0) < base.get('xuci_rate', 0) * 0.9:
        out.append('虚词偏少，文言气韵不足，宜用「之、其、遂、乃、便」。')
    if l['modern_n'] > 6:
        out.append('现代词过多：' + lint_report(''.join(
            [h['word'] * min(h['n'], 2) for h in l['modern']])))
    return out or ['各项均在基准邻域内。']
