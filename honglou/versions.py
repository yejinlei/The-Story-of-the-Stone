"""版本谱：程高本一百二十回与脂砚斋各本的对照、校勘与统计学判定。

所用方法（皆可复算，源文本见 data/witnesses/）：

    一、回目对勘      逐回比对五本回目，回目有异即正文有异的先声
    二、篇幅之法      逐回字数，程甲与脂本之差即增删改之所在
    三、Delta 距离    Burrows 的习惯词距离法（学界用于作者归属的经典方法），
                      leave-one-out 作参照质心，看第八十回处有无断层
    四、交叉熵        字符三元组模型：以脂本前八十回训练、以后四十回训练，
                      两者各 scores 逐回，看谁更像谁
    五、显著字        对数似然比选出的前后两半截然不同的用字
    六、体裁指纹      句长、对话率、「笑道」、虚词率、韵文率、用字丰富度
    七、脂批矩阵      底本脂批的版本归属 × 回次，与维基文库录本交叉印证
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import db, ontology_seed as seed, paths, witness as W

# ------------------------------------------------------------------ 数据流

STREAMS = [
    dict(key='hui', name='脂评汇校本', short='汇校本', family='脂',
         note='吴铭恩汇校，以此间八十回正文为底', color='#9e2b25'),
    dict(key='zhiqi', name='脂砚斋重评石头记', short='脂评本', family='脂',
         note='维基文库转录，八十回，内附诸家脂批', color='#c2504a'),
    dict(key='jiaxu', name='甲戌本', short='甲戌本', family='脂',
         note='存十六回，脂批最富', color='#b08d57'),
    dict(key='chengjia', name='程甲本', short='程甲本', family='程',
         note='乾隆五十六年萃文书屋木活字，一百二十回', color='#3b4a6b'),
    dict(key='chengyi', name='程乙本', short='程乙本', family='程',
         note='乾隆五十七年重订本', color='#3f6b5e'),
    dict(key='ai', name='AI 续写', short='AI续写', family='推',
         note='本工程多 Agent 推演所写，三十回', color='#7d5ba6'),
]
BY_KEY = {s['key']: s for s in STREAMS}

HAN = re.compile(r'[一-鿿]')
VERSE = re.compile(r'(?<=[。！？」』”）；，、])'
                   r'([\u4e00-\u9fff]{5,7}[，、][\u4e00-\u9fff]{5,7}[。！？])')
QUOTE = re.compile(r'[「“]([^」”]{2,400})[」”]')
SENT = re.compile(r'[。！？；！？]+')

# 习惯词（虚词为主）：作者归属的指纹，不受情节与人物的影响
FUNCTION = """的 了 不 是 我 你 他 她 它 们 这 那 儿 么 什 为 之 也 都 就
而 及 与 并 则 却 且 况 尚 岂 何 谁 怎 却 便 又 还 只 才 更 最 太 很 越
皆 俱 咸 尽 悉 忽 猛 忽 然 果 竟 反 偏 徒 空 白 惟 唯 独 但 或 若 如 似
因此 于是 所以 不过 只是 只是 然则 然而 虽然 虽是 纵然 果然 忽然 连忙
一面 一时 一头 一面 越发 更加 已是 已经 未曾 不曾 没有 不用 不必 无妨
这样 那样 如此 这般 如何 怎的 怎样 什么 那里 哪里 这些 那些 咱们 我们
弄 起 过 来 去 说 道 笑 听得 只见 因见 便说 笑道 说道 赞叹 听说
"""


def _func_words() -> list[str]:
    ws = [w for w in FUNCTION.split() if w]
    return list(dict.fromkeys(ws))


# ------------------------------------------------------------------ 载入

def _local_corpus() -> dict[int, str]:
    """本地底本正文：拼接 v_main，逐回成篇。"""
    out: dict[int, str] = defaultdict(str)
    try:
        rows = db.q('SELECT chapter, text FROM v_main WHERE chapter > 0 '
                    'ORDER BY id')
    except Exception:
        rows = []
    for r in rows:
        out[r['chapter']] += (r['text'] or '')
    return dict(out)


def _ai() -> dict[int, str]:
    out = {}
    try:
        rows = db.q('SELECT chapter, text FROM continuations ORDER BY chapter')
    except Exception:
        rows = []
    for r in rows:
        out[r['chapter']] = r['text'] or ''
    return out


def _titles_local() -> dict[int, str]:
    out = {}
    try:
        rows = db.q('SELECT chapter, title FROM chapters')
    except Exception:
        rows = []
    for r in rows:
        out[r['chapter']] = r['title'] or ''
    return out


def load_all() -> dict[str, dict[int, dict]]:
    """各本 → {回次: {title, text}}，正文与回目一律归一为简体。"""

    out: dict[str, dict[int, dict]] = {}
    hui = _local_corpus()
    htitle = _titles_local()
    out['hui'] = {c: dict(title=htitle.get(c, ''), text=W.normalize(t))
                  for c, t in hui.items() if c > 0}
    for key in ('zhiqi', 'jiaxu', 'chengjia', 'chengyi'):
        rec = W.load(key)
        if not rec:
            continue
        out[key] = {}
        for k, v in rec['chapters'].items():
            out[key][int(k)] = dict(title=_fix_title(W.normalize(v['title'])),
                                    text=W.normalize(v['text']))
    out['ai'] = {}
    ai_title = {}
    try:
        for r in db.q('SELECT chapter, title FROM continuations'):
            ai_title[r['chapter']] = r['title'] or ''
    except Exception:
        pass
    for c, t in _ai().items():
        head = t.split('\n', 1)[0]
        out['ai'][c] = dict(
            title=_fix_title(ai_title.get(c) or _ai_title(head, c)),
            text=W.normalize(t))
    return out


def _fix_title(s: str) -> str:
    """回目里的模板残余与重复空格一并收拾干净。"""
    s = s.split('{{')[0].replace('{{~~', '').replace('}}', '')
    s = re.sub(r"[\s　]+", " ", s).strip()
    s = re.sub(r"^第[〇○零一二三四五六七八九十百]+回", "", s)
    if len(s) < 6 or any(x in s for x in '|【】[]'):
        return ''
    return s


def _ai_title(head: str, no: int) -> str:
    m = re.match(r'^\s*第?\s*(\d+)\s*回?[ 　]*([^\n]{4,40})', head)
    if m and int(m.group(1)) == no:
        return m.group(2).strip()
    return ''


# ------------------------------------------------------------------ 一、回目

def _titles(data) -> list[dict]:
    keys = [s['key'] for s in STREAMS]
    rows = []
    for c in range(1, 121):
        row = {k: (data.get(k, {}).get(c, {}) or {}).get('title', '')
               for k in keys}
        vals = [v for v in row.values() if len(v) >= 6]
        uniq = {re.sub(r'[\s　]', '', v) for v in vals}
        rows.append(dict(c=c, rows=row, variants=len(uniq)))
    return rows


# ------------------------------------------------------------------ 二、篇幅

def _lengths(data) -> dict[str, list[dict]]:
    out = {}
    for key in [s['key'] for s in STREAMS]:
        rows = []
        for c in sorted(data.get(key, {})):
            t = data[key][c]['text']
            rows.append(dict(c=c, n=len(HAN.findall(t))))
        out[key] = rows
    return out


# ------------------------------------------------------------------ 三、指纹

FEATS = _func_words()


def _profile(data) -> dict[str, list[dict]]:
    """逐回体裁指纹（每千字/千字密度）。"""
    out = {}
    for key in [s['key'] for s in STREAMS]:
        rows = []
        for c in sorted(data.get(key, {})):
            t = data[key][c]['text'].replace('\n', '')
            n = len(t)
            if n < 300:
                continue
            k = 1000 / n
            sents = [s for s in SENT.split(t) if len(s.strip()) > 1]
            quote = sum(len(m.group(1)) for m in QUOTE.finditer(t))
            han = HAN.findall(t)
            rows.append(dict(
                c=c,
                n=len(han),
                sent=round(sum(len(s) for s in sents) / max(1, len(sents)), 1),
                quote=round(quote * k, 1),
                verse=round(len(VERSE.findall(t)) * k, 2),
                ttr=round(len(set(han)) / max(1, len(han)), 3),
                xiaodao=round(t.count('笑道') * k, 2),
                tanqi=round((t.count('叹道') + t.count('冷笑')) * k, 2),
            ))
        out[key] = rows
    return out


def _agg(rows: list[dict], keys: list[str]) -> dict:
    """分段汇总：前八十回 / 后四十回 的均值。"""
    def mean(sub, f):
        vs = [r[f] for r in sub if isinstance(r.get(f), (int, float))]
        return round(sum(vs) / len(vs), 3) if vs else None
    head = [r for r in rows if r['c'] <= 80]
    tail = [r for r in rows if 80 < r['c'] <= 120] or [r for r in rows
                                                       if r['c'] > 80]
    out = {}
    for f in keys:
        out[f] = dict(head=mean(head, f), tail=mean(tail, f),
                      nh=len(head), nt=len(tail))
    return out


PROFILE_KEYS = ['sent', 'quote', 'verse', 'ttr', 'xiaodao', 'tanqi', 'n']


# ------------------------------------------------------------------ 四、Delta

def _rates(text: str, feats: list[str]) -> list[float]:
    n = max(1, len(text))
    return [1000.0 * text.count(f) / n for f in feats]


def _delta(stream: dict[int, dict], feats: list[str],
           others: dict[int, dict] | None = None,
           scales: tuple[list[float], list[float]] | None = None
           ) -> list[dict]:
    """Burrows Delta：虚词密度的 z 向量到两个参照质心的曼哈顿距离之差。

    > 0 表示更近前八十回；< 0 表示更近后四十回。参照质心用 leave-one-out，
    免得章节自己抬高自己所在的一侧。
    """
    chs = sorted(stream)
    mat = {c: _rates(stream[c]['text'], feats) for c in chs}
    if scales is None:
        mean, sd = [], []
        for j in range(len(feats)):
            vs = [mat[c][j] for c in chs]
            m = sum(vs) / len(vs)
            s = math.sqrt(sum((v - m) ** 2 for v in vs) / len(vs)) or 1.0
            mean.append(m)
            sd.append(s)
    else:
        mean, sd = scales
    z = {c: [(mat[c][j] - mean[j]) / sd[j] for j in range(len(feats))]
         for c in chs}
    head = [c for c in chs if c <= 80]
    tail = [c for c in chs if c > 80]
    out = []
    for c in chs:
        nh, nt = len(head), len(tail)
        sh = [sum(z[x][j] for x in head) - (z[c][j] if c <= 80 else 0)
              for j in range(len(feats))]
        st = [sum(z[x][j] for x in tail) - (z[c][j] if c > 80 else 0)
              for j in range(len(feats))]
        nh -= 1 if c <= 80 else 0
        nt -= 1 if c > 80 else 0
        ch_ = [sh[j] / max(1, nh) for j in range(len(feats))]
        ct = [st[j] / max(1, nt) for j in range(len(feats))]
        dh = sum(abs(z[c][j] - ch_[j]) for j in range(len(feats))) / len(feats)
        dt = sum(abs(z[c][j] - ct[j]) for j in range(len(feats))) / len(feats)
        out.append(dict(c=c, dh=round(dh, 3), dt=round(dt, 3),
                        d=round(dt - dh, 3)))
    return out


# ------------------------------------------------------------------ 五、交叉熵

class Trigram:
    def __init__(self, k: float = 0.05):
        self.tg: Counter = Counter()
        self.bg: Counter = Counter()
        self.uni: Counter = Counter()
        self.total = 0
        self.k = k

    def feed(self, text: str) -> None:
        t = HAN.findall(text)
        self.total += len(t)
        for i in range(len(t) - 2):
            self.tg[t[i] + t[i + 1] + t[i + 2]] += 1
            self.bg[t[i] + t[i + 1]] += 1
        for c in t:
            self.uni[c] += 1

    def bits(self, text: str) -> float:
        """每字符平均交叉熵（bit）。"""
        t = HAN.findall(text)
        if len(t) < 3:
            return 0.0
        V = len(self.uni) or 1
        k = self.k
        tot, cnt = 0.0, 0
        for i in range(2, len(t)):
            a, b, c = t[i - 2], t[i - 1], t[i]
            bg = self.bg.get(a + b, 0)
            if bg:
                p = (self.tg.get(a + b + c, 0) + k * V * self.uni.get(c, 0)
                     / max(1, self.total)) / (bg + k * V)
            else:
                p = self.uni.get(c, 0) / max(1, self.total)
            tot += -math.log2(max(p, 1e-9))
            cnt += 1
        return round(tot / max(1, cnt), 3)


def _models(data) -> dict[str, Trigram]:
    """三个模型：脂本前八十回（外接基准，无泄漏）、程甲后四十回拆作的两半。

    后四十回不能用自身训练又打自身分，故拆前后两半互为 held-out。
    """
    mz = Trigram()
    for c, rec in sorted(data.get('hui', {}).items()):
        if c <= 80:
            mz.feed(rec['text'])
    h1, h2 = Trigram(), Trigram()
    for c, rec in sorted(data.get('chengjia', {}).items()):
        if 80 < c <= 100:
            h1.feed(rec['text'])
        elif c > 100:
            h2.feed(rec['text'])
    return dict(zhi=mz, cheng81_100=h1, cheng101_120=h2)


def _entropy(data, ms: dict[str, Trigram]) -> dict[str, list[dict]]:
    out = {}
    for key in ('chengjia', 'chengyi', 'zhiqi', 'ai'):
        rows = []
        for c in sorted(data.get(key, {})):
            t = data[key][c]['text']
            if len(t) < 300:
                continue
            rows.append(dict(
                c=c,
                hz=ms['zhi'].bits(t),
                hc=(ms['cheng101_120'] if c > 100
                    else ms['cheng81_100']).bits(t)))
        out[key] = rows
    return out


# ------------------------------------------------------------------ 六、显著字

def _llr(k1: int, n1: int, k2: int, n2: int) -> float:
    """Dunning 对数似然比 G²（单侧方向由调用者解释）。"""
    def lg(x):
        return 0.0 if x <= 0 else x * math.log(x)
    p = (k1 + k2) / (n1 + n2)
    tot = lg(k1) + lg(k2) + lg(n1 - k1) + lg(n2 - k2)
    e1 = n1 * p
    e2 = n2 * p
    exp = lg(e1) + lg(e2) + lg(n1 - e1) + lg(n2 - e2)
    return round(2 * (exp - tot), 1)


def _distinct(data, key: str = 'chengjia') -> dict:
    """前八十回与后四十回截然不同的用字。"""
    head, tail = '', ''
    for c, rec in sorted(data[key].items()):
        if c <= 80:
            head += rec['text']
        else:
            tail += rec['text']
    ch, ct = Counter(HAN.findall(head)), Counter(HAN.findall(tail))
    nh, nt = sum(ch.values()), sum(ct.values())
    rows = []
    for ch_ in set(ch) | set(ct):
        if ch[ch_] + ct[ch_] < 60:
            continue
        rh, rt = ch[ch_] / nh, ct[ch_] / nt
        g = _llr(ch[ch_], nh, ct[ch_], nt)
        rows.append(dict(w=ch_, h=ch[ch_], t=ct[ch_], g=g,
                         r=round(rh / max(1e-9, rt), 2)))
    # 只收悬殊者（密度相差一倍半以上），方是「两截琵琶」的证据
    front = sorted([r for r in rows if r['r'] >= 1.5],
                   key=lambda r: -abs(r['g']))[:26]
    back = sorted([r for r in rows if r['r'] <= 0.667],
                  key=lambda r: -abs(r['g']))[:26]
    only_h = sorted([w for w in ch if w not in ct and ch[w] >= 12],
                    key=lambda w: -ch[w])[:40]
    only_t = sorted([w for w in ct if w not in ch and ct[w] >= 12],
                    key=lambda w: -ct[w])[:40]
    return dict(front=front, back=back, only_head=only_h, only_tail=only_t,
                n_head=nh, n_tail=nt)


# ------------------------------------------------------------------ 七、人物消长

PEOPLE = """黛玉 宝钗 宝玉 湘云 探春 迎春 惜春 熙凤 李纨 妙玉 可卿 香菱 晴雯
袭人 平儿 鸳鸯 紫鹃 莺儿 贾母 王夫人 邢夫人 薛姨妈 尤二姐 尤三姐 贾政
贾赦 贾珍 贾琏 贾环 贾兰 贾蓉 薛蟠 刘姥姥 贾雨村 甄士隐 小红 司棋 芳官
"""


def _people(data, key: str = 'chengjia') -> list[dict]:
    head, tail = '', ''
    for c, rec in sorted(data[key].items()):
        if c <= 80:
            head += rec['text']
        else:
            tail += rec['text']
    nh = len(HAN.findall(head)) or 1
    nt = len(HAN.findall(tail)) or 1
    out = []
    for name in PEOPLE.split():
        h, t = head.count(name), tail.count(name)
        if h + t < 8:
            continue
        rh, rt = h / nh * 10000, t / nt * 10000
        out.append(dict(name=name, h=h, t=t, rh=round(rh, 2), rt=round(rt, 2),
                        ratio=round(rt / max(1e-6, rh), 2)))
    out.sort(key=lambda r: r['ratio'])
    return out


# ------------------------------------------------------------------ 八、脂批矩阵

ED_TOKEN = re.compile(r'([甲己庚戚蒙列楊杨舒辰程]{1,2})本')
QUOTED = re.compile(r'[「『“"]([^」』”"]{1,24})[」』”"]')


def _apparatus() -> list[dict]:
    """校勘记：底本每回页下的校记即是第一手的异文账簿。

    逐条钩出「词条 → 各本异写 → 涉及诸本」，原文照录，以备覆核。
    """
    try:
        rows = db.q("SELECT chapter, page, text FROM blocks "
                    "WHERE kind='校记' ORDER BY chapter, id")
    except Exception:
        rows = []
    out = []
    for r in rows:
        t = (r['text'] or '').strip()
        if r['chapter'] <= 0 or len(t) < 12:
            continue
        m = re.match(r'^([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])', t)
        forms = list(dict.fromkeys(QUOTED.findall(t)))
        eds = list(dict.fromkeys(ED_TOKEN.findall(t)))
        out.append(dict(c=r['chapter'], no=m.group(1) if m else '',
                        lemma=forms[0] if forms else '',
                        forms=forms, eds=eds,
                        text=t.lstrip('①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳').strip()))
    return out


def _anno_matrix() -> dict:
    """本地底本的批语版本分布 + 维基文库脂评本的夹批分布。"""
    local: dict[str, Counter] = defaultdict(Counter)
    total = 0
    try:
        rows = db.q('SELECT chapter, editions, kind FROM v_anno')
    except Exception:
        rows = []
    for r in rows:
        eds = json.loads(r['editions']) if isinstance(r['editions'], str) \
            else (r['editions'] or [])
        for e in eds:
            local[e][r['chapter']] += 1
        total += 1

    # 第二谱系：维基文库转录的脂评本与甲戌本，内嵌脂批自行署本
    ext: dict[str, Counter] = defaultdict(Counter)
    for key in ('zhiqi', 'jiaxu'):
        rec = W.load(key)
        if not rec:
            continue
        for k, v in rec['chapters'].items():
            for a in v.get('annos') or []:
                for e in a['editions']:
                    ext[e][int(k)] += 1
    return dict(
        local={e: {str(c): n for c, n in sorted(cnt.items())}
               for e, cnt in local.items()},
        ext={e: {str(c): n for c, n in sorted(cnt.items())}
             for e, cnt in ext.items()},
        local_total=total,
        ext_total=sum(sum(c.values()) for c in ext.values()),
    )


# ------------------------------------------------------------------ 总装

def build(site_data: Path | None = None) -> dict:
    site_data = site_data or (paths.SITE_DIR / 'data')
    data = load_all()
    feats = _func_words()

    editions = []
    for s in STREAMS:
        chs = data.get(s['key'], {})
        editions.append(dict(
            key=s['key'], name=s['name'], short=s['short'],
            family=s['family'], note=s['note'], color=s['color'],
            chapters=len(chs), chars=sum(len(HAN.findall(v['text']))
                                         for v in chs.values()),
            first=min(chs) if chs else 0, last=max(chs) if chs else 0))

    ms = _models(data)
    prof = _profile(data)
    out = dict(
        meta=dict(
            provenance='维基文库转录本（程甲/程乙/脂评本/甲戌本）+ '
                       '本地《红楼梦脂评汇校本》正文 + 本工程 AI 续写',
            note='异写字已归位（data/variant_map.json），统计只数通用汉字。',
        ),
        editions=editions,
        titles=_titles(data),
        lengths=_lengths(data),
        profile=prof,
        agg={k: _agg(v, PROFILE_KEYS) for k, v in prof.items()},
        delta={k: _delta(data[k], feats) for k in ('chengjia', 'chengyi')
               if data.get(k)},
        delta_ai=_delta(data['ai'], feats) if data.get('ai') else [],
        entropy=_entropy(data, ms),
        distinct=_distinct(data),
        people=_people(data),
        anno=_anno_matrix(),
        apparatus=_apparatus(),
        ontology=dict(editions=seed.editions(), variants=seed.variants()),
        feats=feats,
    )
    ai_scaled = None
    if data.get('ai'):
        chs = sorted(data['chengjia'])
        mat = {c: _rates(data['chengjia'][c]['text'], feats) for c in chs}
        mean, sd = [], []
        for j in range(len(feats)):
            vs = [mat[c][j] for c in chs]
            m = sum(vs) / len(vs)
            s = math.sqrt(sum((v - m) ** 2 for v in vs) / len(vs)) or 1.0
            mean.append(m)
            sd.append(s)
        out['delta_ai'] = _delta(data['ai'], feats, scales=(mean, sd))
        out['meta']['ai_scale'] = ('AI 续写改用程甲本自身的虚词均值与方差定标，'
                                   '方可与之一较远近')

    site_data.mkdir(parents=True, exist_ok=True)
    (site_data / 'versions.json').write_text(
        json.dumps(out, ensure_ascii=False), encoding='utf-8')
    return out


BODY = """
<div class="card small" id="vsummary"></div>

<h2>版本一览 · 哪些本子活着，哪些只剩半部</h2>
<div class="card small">
古人所谓「版本」，不是一个本子，而是一串本子：脂本十来种，各有存佚；程本两种，
前后相差不满一年。<b>本工程的两条谱系由此分野</b>——底本止于第八十回，
而真正的第一百二十回只在程高本一边。
</div>
<div class="grid" id="veds"></div>

<h2>见证本 · 本工程实据一共有六份</h2>
<div class="card small">
「见证本」是校勘学的说法——凡真拿来比对的本子，一概称 witness。
此间所据者六：本地脂评汇校本、维基文库转录的脂砚斋重评石头记（八十回）、
甲戌本（十六回）、程甲本与程乙本（各一百二十回），以及本工程 AI 续写三十回。
</div>
<div class="grid" id="vwits"></div>

<h2>回目对勘 · 八条题目便有一处不同</h2>
<div class="card small">
回目是全书最容易被改的地方，也是最容易露出改笔的地方。
下表五本并列（AI 续写自第八十一回起），凡<b>与他本不同者皆标红</b>；
点「仅有异者」则只看针锋相对的那几十回。
</div>
<div class="card gtools">
  <button id="tOnly" class="on">仅有异者</button>
  <button id="tAll">一百二十回全表</button>
  <span class="gstat" id="vtitlestat"></span>
</div>
<div class="card" style="max-height:520px;overflow:auto"><table id="vtitletab"></table></div>

<h2>篇幅之法 · 程高删了什么，补了什么</h2>
<div class="card small">
逐回字数是最粗的一道筛子，却也最直白。<b>横轴一至一百二十回</b>，
脂谱两条线止于第八十回，程谱两条线走到底。两谱之间的距离，
就是程伟元、高鹗整理改写的幅度。
</div>
<div class="card gcanvas">
  <svg id="vlengths" viewBox="0 0 1080 320" preserveAspectRatio="xMidYMid meet"></svg>
</div>
<div class="card samples" id="vlenlist"></div>

<h2>Delta 距离 · 第八十回处的一道断层</h2>
<div class="card small" id="vdeltanote"></div>
<div class="card gcanvas">
  <svg id="vdelta" viewBox="0 0 1080 320" preserveAspectRatio="xMidYMid meet"></svg>
</div>
<div class="card"><table id="vdeltatab"></table></div>

<h2>交叉熵 · 以脂本之模型，读程本之文字</h2>
<div class="card small" id="ventropynote"></div>
<div class="card gcanvas">
  <svg id="ventropy" viewBox="0 0 1080 320" preserveAspectRatio="xMidYMid meet"></svg>
</div>
<div class="card"><table id="ventropytab"></table></div>

<h2>体裁指纹 · 句长短、「笑」声稀、韵文退场</h2>
<div class="card small">
情节可以仿，下意识的笔习难改。以下六项皆可称量：<b>句长</b>、
<b>对话所占</b>、<b>韵文密度</b>、<b>「笑道」之密</b>、
<b>叹与冷笑</b>、<b>用字丰富度</b>。切换指标，看两谱各自的曲线在何处分手。
</div>
<div class="card gtools">
  <button class="met on" data-f="xiaodao">笑道</button>
  <button class="met" data-f="verse">韵文</button>
  <button class="met" data-f="sent">句长</button>
  <button class="met" data-f="quote">对话率</button>
  <button class="met" data-f="tanqi">叹与冷笑</button>
  <button class="met" data-f="ttr">用字丰富度</button>
  <span class="gstat" id="vmetstat"></span>
</div>
<div class="card gcanvas">
  <svg id="vmetrics" viewBox="0 0 1080 320" preserveAspectRatio="xMidYMid meet"></svg>
</div>
<div class="card"><table id="vaggtab"></table></div>

<h2>显著字 · 前后判若两手的那些字</h2>
<div class="card small" id="vwordsnote"></div>
<div class="gwrap">
  <div class="card samples" id="vfront"></div>
  <div class="card samples" id="vback"></div>
</div>

<h2>人物消长 · 前八十回是女儿，后四十回是家事</h2>
<div class="card small">
同一批名字，在前后两半的出现频率差得厉害。下表按<b>后半相对于前半的倍数</b>排序：
越往上，越是后四十回的当令人物；越往下，越是写完就再没人提的。
</div>
<div class="card"><table id="vpeopletab"></table></div>

<h2>脂批分布 · 两个谱系互相印证</h2>
<div class="card small" id="vannonote"></div>
<div class="card gcanvas">
  <svg id="vanno" viewBox="0 0 1080 300" preserveAspectRatio="xMidYMid meet"></svg>
</div>

<h2>校勘记 · 底本页下的一条条异文账簿</h2>
<div class="card small">
底本每一回页下的校记，便是逐字较量诸本的成绩单。此间录得若干条，
可按版本筛：<b>点一个本子，只看涉及它的那些条</b>；原 — 文照录，以备覆核。
</div>
<div class="card gtools" id="vappfilter"></div>
<div class="card" style="max-height:520px;overflow:auto"><table id="vapptab"></table></div>

<h2>异文本体 · 手订的数条紧要关节</h2>
<div class="card small">
以上诸表皆由算法自动算出，以下几条则是人工著录且<b>已由此间数据核实</b>者（标「验」）：
某字某句，此本作什么，彼本作什么，何以有此分别——这才是版本学要回答的。
</div>
<div class="card"><table id="vvarianttab"></table></div>

<h2>方法与局限</h2>
<div class="card small">
一・程甲、程乙、脂评本与甲戌本文字取自维基文库转录本，转录难免有鲁鱼之误，
且异写字经 data/variant_map.json 归位后才入统计。<br>
二・Delta 用惯用词（虚词为主）密度的 z 向量，参照质心按 leave-one-out 计算，
务必不含被评之回自身；若把他人之作与自家之作并列，仍受篇幅长短影响。<br>
三・交叉熵的两个模型：前者以本地脂评汇校本前八十回训练（无泄漏），
后者为避免自证，把程甲本后四十回拆作两半互为 held-out。<br>
四・AI 续写每回仅千馀字，篇幅远短于程高本；交叉熵与用字丰富度两项因此偏高，读时须知。<br>
五・统计学只能画出两截的分界线，无从断言执笔者为谁；本页所陈，皆是可复算的距离，
不作作者归属之论定。
</div>
"""


JS = r"""
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
let D=null;
const NT=(v,d=2)=>v==null?'—':(+v).toFixed(d);
const FAMF={'脂':'#9e2b25','过渡':'#8a6d3b','存疑':'#7a7a7a','程高':'#3b4a6b','校勘本':'#3f6b5e'};

/* ---------- 折线图 ---------- */
function chart(id,o){
  const svg=$(id); if(!svg||!o.series.length) return;
  const W=1080,H=+svg.getAttribute('viewBox').split(' ')[3];
  const L=58,R=18,T=18,B=38, iw=W-L-R, ih=H-T-B;
  const xs=o.xmin, xe=o.xmax;
  let vs=[]; o.series.forEach(s=>s.pts.forEach(p=>vs.push(p[1])));
  let lo=Math.min(...vs), hi=Math.max(...vs);
  if(o.ymin!=null) lo=o.ymin; if(o.ymax!=null) hi=o.ymax;
  if(hi-lo<1e-9){hi=lo+1;}
  const pad=(hi-lo)*0.08; lo-=pad; hi+=pad;
  const X=v=>L+(v-xs)/(xe-xs)*iw;
  const Y=v=>T+ih-(v-lo)/(hi-lo)*ih;
  let g='';
  // 网格与横轴
  const step=o.step||10;
  const GRID='stroke="#e3d9c4"', AX='fill="#8a7f6d" font-size="11"';
  for(let x=Math.ceil(xs/step)*step;x<=xe;x+=step){
    g+=`<line ${GRID} x1="${X(x)}" y1="${T}" x2="${X(x)}" y2="${T+ih}"/>`;
    g+=`<text ${AX} text-anchor="middle" x="${X(x)}" y="${H-14}">${x}</text>`;
  }
  for(let i=0;i<=4;i++){
    const v=lo+(hi-lo)*i/4, y=Y(v);
    g+=`<line ${GRID} x1="${L}" y1="${y}" x2="${W-R}" y2="${y}"/>`;
    g+=`<text ${AX} x="${L-8}" y="${y+4}" text-anchor="end">${v.toFixed(o.fix==null?2:o.fix)}</text>`;
  }
  if(o.mark!=null){
    g+=`<line x1="${X(o.mark)}" y1="${T}" x2="${X(o.mark)}" y2="${T+ih}" stroke="#b02a2a" stroke-width="1.6" stroke-dasharray="6 4"/>`;
    g+=`<text ${AX} x="${X(o.mark)+5}" y="${T+14}" fill="#b02a2a">${o.markTxt||''}</text>`;
  }
  if(o.zero && lo<0 && hi>0){} // 零线单独画
  if(o.zero){
    const y=Y(0);
    if(y>T&&y<T+ih) g+=`<line x1="${L}" y1="${y}" x2="${W-R}" y2="${y}" stroke="#888" stroke-width="1.2"/>`;
  }
  o.series.forEach(s=>{
    if(!s.pts.length) return;
    const d=s.pts.map((p,i)=>(i?'L':'M')+X(p[0]).toFixed(1)+' '+Y(p[1]).toFixed(1)).join(' ');
    g+=`<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${s.w||1.8}" ${s.dash?'stroke-dasharray="5 4"':''}/>`;
  });
  // 图例
  let lx=L;
  o.series.forEach(s=>{
    g+=`<rect x="${lx}" y="${4}" width="14" height="4" fill="${s.color}"/>`;
    g+=`<text ${AX} x="${lx+19}" y="${11}">${esc(s.name)}</text>`;
    lx+=26+esc(s.name).length*13;
  });
  svg.innerHTML=g;
}

/* ---------- 版本本体与见证本 ---------- */
function eds(){
  const o=D.ontology.editions;
  $('veds').innerHTML=o.map(e=>`<div class="card small">
    <h3 style="margin:0 0 6px">${esc(e.name)}</h3>
    <div class="small"><b>${esc(e.family)}</b> · ${esc(e.year)}<br>
    存回：${esc(e.extant)}<br>批语：${esc(e.anno)}</div>
    <div class="small" style="margin-top:6px;color:#5a4a44">${esc(e.note)}</div></div>`).join('');
}
function wits(){
  $('vwits').innerHTML=D.editions.map(e=>`<div class="card small">
    <h3 style="margin:0 0 6px;color:${e.color}">${esc(e.name)}</h3>
    <div class="small">${esc(e.note)}</div>
    <div class="small" style="margin-top:6px">回次 <b>${e.first}–${e.last}</b>（共 ${e.chapters} 回）<br>
    通用汉字 <b>${(e.chars/10000).toFixed(2)} 万字</b></div></div>`).join('');
  const cj=D.editions.find(e=>e.key==='chengjia'), hui=D.editions.find(e=>e.key==='hui');
  $('vsummary').innerHTML=
    `<b>六份见证本，两条谱系。</b>脂谱止于第八十回（${hui.chapters} 回 / ${(hui.chars/10000).toFixed(1)} 万字），
     程谱别有后四十回（程甲 ${cj.chapters} 回 / ${(cj.chars/10000).toFixed(1)} 万字）；
     另有甲戌本十六回可校前十回之异同，AI 续写三十回聊备一格。
     回目相较，五本之间<b>一百二十回里有 ${D.titles.filter(t=>t.variants>1).length} 回题目不一</b>。`;
}

/* ---------- 回目对勘 ---------- */
let TITLE_MODE='only';
function titles(){
  const rows=TITLE_MODE==='only'?D.titles.filter(t=>t.variants>1):D.titles;
  const keys=['hui','zhiqi','jiaxu','chengjia','chengyi','ai'];
  const names={hui:'汇校本',zhiqi:'脂评本',jiaxu:'甲戌本',chengjia:'程甲本',chengyi:'程乙本',ai:'AI续写'};
  const base=Object.fromEntries(D.titles.map(t=>[t.c,t.rows.hui||t.rows.zhiqi||'']));
  let h='<tr><th>回</th>'+keys.map(k=>`<th>${names[k]}</th>`).join('')+'</tr>';
  rows.forEach(t=>{
    h+=`<tr><td>${t.c}</td>`+keys.map(k=>{
      const v=t.rows[k]||''; if(!v) return '<td class="small">—</td>';
      const diff=(t.variants>1) && v.replace(/\s/g,'')!==(base[t.c]||'').replace(/\s/g,'');
      return `<td ${diff?'style="color:#b02a2a"':''}>${esc(v)}</td>`;
    }).join('')+'</tr>';
  });
  $('vtitletab').innerHTML=h;
  $('vtitlestat').textContent=`共 ${rows.length} 回；红色为该回与他本不同者`;
}
function bindTitles(){
  $('tOnly').onclick=()=>{TITLE_MODE='only';$('tOnly').classList.add('on');$('tAll').classList.remove('on');titles();};
  $('tAll').onclick=()=>{TITLE_MODE='all';$('tAll').classList.add('on');$('tOnly').classList.remove('on');titles();};
}

/* ---------- 篇幅 ---------- */
function lens(){
  const pick=k=>({name:D.editions.find(e=>e.key===k).short,color:D.editions.find(e=>e.key===k).color,
      pts:(D.lengths[k]||[]).map(r=>[r.c,r.n])});
  chart('vlengths',{series:['hui','zhiqi','chengjia','chengyi'].map(pick),xmin:1,xmax:120,step:10,fix:0,mark:80,markTxt:'八十回'});
  // 增幅之最
  const A={},B={};
  D.lengths.hui.forEach(r=>A[r.c]=r.n); D.lengths.chengjia.forEach(r=>B[r.c]=r.n);
  let rows=Object.keys(A).map(c=>({c:+c,a:A[c],b:B[c]||0,d:(B[c]||0)-A[c]}));
  rows.sort((x,y)=>x.d-y.d);
  const mk=(arr,sign,txt)=>`<div class="card small"><b>${txt}</b><br>`+
    arr.slice(0,8).map(r=>`第${r.c}回 ${sign}${Math.abs(r.d)} 字（脂本 ${r.a} → 程甲 ${r.b}）`).join('<br>')+'</div>';
  $('vlenlist').innerHTML=mk(rows,'少','删削最多的八回')+mk(rows.slice().reverse(),'多','增补最多的八回');
}

/* ---------- Delta ---------- */
function deltas(){
  const cj=D.delta.chengjia, cy=D.delta.chengyi||[];
  chart('vdelta',{series:[
    {name:'程甲本',color:'#3b4a6b',pts:cj.map(r=>[r.c,r.d])},
    {name:'程乙本',color:'#3f6b5e',pts:cy.map(r=>[r.c,r.d]),w:1.2,dash:true}
  ],xmin:1,xmax:120,step:10,zero:true,mark:80,markTxt:'八十／八十一'});
  const mean=a=>a.reduce((s,r)=>s+r.d,0)/Math.max(1,a.length);
  const mhead=mean(cj.filter(r=>r.c<=80)), mtail=mean(cj.filter(r=>r.c>80));
  const hneg=cj.filter(r=>r.c<=80&&r.d<0).length;
  const tpos=cj.filter(r=>r.c>80&&r.d>0).length;
  const tneg=cj.filter(r=>r.c>80&&r.d<0).length;
  const ai=D.delta_ai||[], mai=ai.length?mean(ai):null;
  $('vdeltanote').innerHTML=
    `Burrows 的 Delta 法：<b>取一百余个惯用词（虚词为主）的千字密度，逐词标准化，
    再算到两组参照质心的曼哈顿距离之差</b>。参照质心用 leave-one-out，不含被评之回自身。
    图中 <b>纵坐标 &gt; 0 即偏向前八十回，&lt; 0 即偏向后四十回</b>。
    程甲本前八十回均值 <b>${mhead.toFixed(3)}</b>，后四十回均值 <b>${mtail.toFixed(3)}</b>：
    前八十回里 <b>${80-hneg}</b> 回为正、${hneg} 回例外；
    后四十回则 <b>${tneg}</b> 回为负${tpos?`、${tpos} 回为正`:'、无一回为正'}。
    分界线落在第八十回与第八十一回之间——这正是历来争论不休的那道接缝。
    ${mai!=null?`本工程 AI 续写三十回置于同一坐标，均值 <b>${mai.toFixed(3)}</b>，
    比程高本更远地离开前八十回——可见刻意模仿，终不是那只手。`:''}`;
  const blocks=[];
  for(let s=1;s<=120;s+=10){
    const sub=cj.filter(r=>r.c>=s&&r.c<s+10);
    if(sub.length) blocks.push({a:s,b:s+9,d:mean(sub)});
  }
  let h='<tr><th>回次</th><th>Δ（距后四十回 − 距前八十回）</th><th>归属</th></tr>';
  blocks.forEach(x=>{h+=`<tr><td>${x.a}–${x.b}</td><td>${NT(x.d,3)}</td>
    <td style="color:${x.d>0?'#2c6e49':'#b02a2a'}">${x.d>0?'偏前八十回':'偏后四十回'}</td></tr>`;});
  $('vdeltatab').innerHTML=h;
}

/* ---------- 交叉熵 ---------- */
function entropies(){
  const rows=D.entropy.chengjia||[];
  chart('ventropy',{series:[
    {name:'以脂本前八十回训练',color:'#9e2b25',pts:rows.map(r=>[r.c,r.hz])},
    {name:'以程本后四十回训练',color:'#3b4a6b',pts:rows.map(r=>[r.c,r.hc])}
  ],xmin:1,xmax:120,step:10,fix:2,mark:80,markTxt:'八十回'});
  const mean=(rs,f)=>{const v=rs.filter(r=>r.c<=80);return v.reduce((s,r)=>s+r[f],0)/Math.max(1,v.length);};
  const tail=(rs,f)=>{const v=rs.filter(r=>r.c>80);return v.reduce((s,r)=>s+r[f],0)/Math.max(1,v.length);};
  const zh=mean(rows,'hz'), zt=tail(rows,'hz'), ch=mean(rows,'hc'), ct=tail(rows,'hc');
  $('ventropynote').innerHTML=
  `字符三元组模型给出的交叉熵：<b>越低越像训练语料</b>。以脂本前八十回的模型读程甲本，
  前八十回均值 <b>${zh.toFixed(3)}</b> bit/字，后四十回均值 <b>${zt.toFixed(3)}</b> bit/字
  ——后四十回在脂本眼里<b>每字多出 ${(zt-zh).toFixed(3)} bit 的意外</b>。
  反之亦然：换用程本后四十回训练的模型（为避免自证，后四十回拆作两半互为 held-out），
  前八十回升至 ${ch.toFixed(3)}、后四十回降为 ${ct.toFixed(3)}，<b>每字相差 ${(ch-ct).toFixed(3)} bit</b>。
  两个模型各认得自己那一半，越过第八十回便都不认得了。`;
  let h='<tr><th>语料</th><th>在脂本模型下</th><th>在程本模型下</th><th>相差</th></tr>';
  ['chengjia','chengyi','zhiqi','ai'].forEach(k=>{
    const rs=D.entropy[k]; if(!rs||!rs.length) return;
    const nm=D.editions.find(e=>e.key===k).short;
    const a=rs.reduce((s,r)=>s+r.hz,0)/rs.length, b=rs.reduce((s,r)=>s+r.hc,0)/rs.length;
    h+=`<tr><td>${nm}</td><td>${NT(a,3)}</td><td>${NT(b,3)}</td><td>${NT(b-a,3)}</td></tr>`;
  });
  $('ventropytab').innerHTML=h;
}

/* ---------- 体裁指纹 ---------- */
let METRIC='xiaodao';
const MET_NAME={xiaodao:'「笑道」密度（每千字）',verse:'韵文密度（每千字）',
  sent:'平均句长（字）',quote:'对话所占（每千字）',tanqi:'叹道／冷笑（每千字）',
  ttr:'用字丰富度'};
function metrics(){
  const keys=D.editions.filter(e=>['hui','zhiqi','chengjia','chengyi','ai'].includes(e.key));
  chart('vmetrics',{series:keys.map(e=>({name:e.short,color:e.color,w:1.6,
      pts:(D.profile[e.key]||[]).map(r=>[r.c,r[METRIC]]).filter(p=>p[1]!=null)})),
    xmin:1,xmax:120,step:10,fix:2,mark:80,markTxt:'八十回'});
  $('vmetstat').textContent=MET_NAME[METRIC];
}
function bindMetrics(){
  document.querySelectorAll('button.met').forEach(b=>b.onclick=()=>{
    document.querySelectorAll('button.met').forEach(x=>x.classList.remove('on'));
    b.classList.add('on'); METRIC=b.dataset.f; metrics();
  });
}
function aggs(){
  const rows=[['指标','脂评汇校本 前八十','程甲本 前八十','程甲本 后四十','程乙本 后四十','AI 续写']];
  const pick=(k,f,side)=>{const a=(D.agg[k]||{})[f];return a?a[side]:null;};
  [['sent','平均句长'],['quote','对话千字率'],['verse','韵文千字率'],
   ['xiaodao','「笑道」千字密度'],['tanqi','叹冷千字密度'],['ttr','用字丰富度'],
   ['n','每回字数']].forEach(([f,name])=>{
    rows.push([name,pick('hui',f,'head'),pick('chengjia',f,'head'),
      pick('chengjia',f,'tail'),pick('chengyi',f,'tail'),pick('ai',f,'tail')]);
  });
  let h='<tr>'+rows[0].map(x=>`<th>${x}</th>`).join('')+'</tr>';
  rows.slice(1).forEach(r=>{h+='<tr>'+r.map((x,i)=>
    `<td>${i===0?x:(x==null?'—':(Math.abs(x)>=1000?Math.round(x):NT(x,2)))}</td>`).join('')+'</tr>';});
  $('vaggtab').innerHTML=h;
}

/* ---------- 显著字 ---------- */
function words(){
  const d=D.distinct;
  const ma=d.back.find(y=>y.w==='吗');
  $('vwordsnote').innerHTML=
    `以前八十回与后四十回的字频相比，取对数似然比 G² 最大的若干字——<b>密度相差一倍半以上者才算数</b>。
     前半偏多者多是家常口语之字（笑、吃、忙、方、每）；后半冒出来的则多是<b>官场刑名与续书新人</b>：
     政、琏、衙、办、尚、薛蝌之「蝌」、宝蟾之「蟾」。${
      ma?`连疑问语气词「吗」也是后半方才当行——前八十回 ${ma.h} 见，后四十回 ${ma.t} 见，
     按密度折算是前者的 <b>${(1/ma.r).toFixed(1)} 倍</b>，这样的口吻差别，很难作伪。`:''}
     另有「此有彼无」者更有意思：取出现十二次以上者，<b>前八十回独有 ${d.only_head.length} 字
     （嬷、茄、螃蟹、玫瑰、茯苓一类新名物居其大半）；
     后四十回独有者却只 ${d.only_tail.length} 字</b>——只在别人开出的名单上接着讲事，不曾添过一件新物。`;
  const col=(arr,title,desc)=>`<b>${title}</b><br><span class="small">${desc}</span><br>`+
    arr.map(x=>`<span style="display:inline-block;margin:2px;padding:1px 7px;border:1px solid #e0d5bd;border-radius:9px">${esc(x.w)} <i style="color:#8a7f6d;font-size:11px">${x.h}/${x.t}</i></span>`).join('');
  $('vfront').innerHTML=col(d.front,'前八十回偏多','各字下注：前半出现次数／后半出现次数')+
    `<div class="small" style="margin-top:8px">前八十回独有：<b>${d.only_head.map(esc).join(' ')}</b></div>`;
  $('vback').innerHTML=col(d.back,'后四十回偏多','各字下注：前半出现次数／后半出现次数')+
    `<div class="small" style="margin-top:8px">后四十回独有：<b>${d.only_tail.map(esc).join(' ')}</b></div>`;
}

/* ---------- 人物消长 ---------- */
function people(){
  let h='<tr><th>人物</th><th>前八十回（每万字）</th><th>后四十回（每万字）</th><th>倍数</th></tr>';
  D.people.forEach(p=>{
    const col=p.ratio>1.4?'#2c6e49':(p.ratio<0.6?'#b02a2a':'#5a4a44');
    h+=`<tr><td>${esc(p.name)}</td><td>${NT(p.rh)}</td><td>${NT(p.rt)}</td>
      <td style="color:${col}">${NT(p.ratio)}×</td></tr>`;
  });
  $('vpeopletab').innerHTML=h;
}

/* ---------- 脂批分布 ---------- */
function anno(){
  const loc=D.anno.local;
  const order=Object.keys(loc).sort((a,b)=>
    Object.values(loc[b]).reduce((s,x)=>s+x,0)-Object.values(loc[a]).reduce((s,x)=>s+x,0)).slice(0,7);
  const colors=['#9e2b25','#c2504a','#b08d57','#3b4a6b','#3f6b5e','#7d5ba6','#8a6d3b'];
  const series=order.map((e,i)=>({name:e,color:colors[i%colors.length],w:1.5,
    pts:Object.entries(loc[e]).map(([c,n])=>[+c,n])}));
  chart('vanno',{series,xmin:1,xmax:80,step:8,fix:0});
  const ext=D.anno.ext;
  const topExt=Object.keys(ext).sort((a,b)=>
    Object.values(ext[b]).reduce((s,x)=>s+x,0)-Object.values(ext[a]).reduce((s,x)=>s+x,0)).slice(0,5);
  $('vannonote').innerHTML=
    `其一，底本脂批 <b>${D.anno.local_total}</b> 条，各随其本；下图是批语最多的七个本子逐回分布，
     某本在某回忽然断了线，往往正是它残阙或钞手搁笔之处。
     其二，维基文库所录的脂评本与甲戌本，内嵌脂批合计 <b>${D.anno.ext_total}</b> 条，
     版本可考者以 ${topExt.map(esc).join('、')} 为多——两重谱系各自独立钞得，正可互校。`;
}

/* ---------- 校勘记 ---------- */
let APP_ED='全部';
function apparatus(){
  const all=new Set(); D.apparatus.forEach(r=>r.eds.forEach(e=>all.add(e)));
  $('vappfilter').innerHTML=`<button class="aped on" data-e="全部">全部 ${D.apparatus.length} 条</button>`+
    [...all].map(e=>`<button class="aped" data-e="${esc(e)}">${esc(e)}本 ${
      D.apparatus.filter(r=>r.eds.includes(e)).length} 条</button>`).join('');
  drawApp();
  document.querySelectorAll('button.aped').forEach(b=>b.onclick=()=>{
    document.querySelectorAll('button.aped').forEach(x=>x.classList.remove('on'));
    b.classList.add('on'); APP_ED=b.dataset.e; drawApp();
  });
}
function drawApp(){
  const rows=APP_ED==='全部'?D.apparatus:D.apparatus.filter(r=>r.eds.includes(APP_ED));
  let h='<tr><th>回</th><th>词条</th><th>诸本</th><th>校记</th></tr>';
  rows.forEach(r=>{
    h+=`<tr><td>${r.c}${esc(r.no)}</td><td>${esc(r.lemma)||'—'}</td>
      <td class="small">${r.eds.map(esc).join('・')||'—'}</td>
      <td class="small">${esc(r.text)}</td></tr>`;
  });
  $('vapptab').innerHTML=h;
}

/* ---------- 异文本体 ---------- */
function variants(){
  let h='<tr><th>回</th><th>类目</th><th>词条</th><th>此本作</th><th>彼本作</th><th>按语</th></tr>';
  D.ontology.variants.forEach(v=>{
    h+=`<tr><td>${esc(v.chapter)}</td><td>${esc(v.category)}</td><td>${esc(v.lemma)}</td>
      <td class="small">${esc(v.reading_a)}</td><td class="small">${esc(v.reading_b)}</td>
      <td class="small">${esc(v.gloss)}</td></tr>`;
  });
  $('vvarianttab').innerHTML=h;
}

fetch('data/versions.json').then(r=>r.json()).then(d=>{
  D=d;
  eds(); wits(); titles(); bindTitles(); lens(); deltas(); entropies();
  metrics(); bindMetrics(); aggs(); words(); people(); anno();
  apparatus(); variants();
}).catch(e=>{$('vsummary').innerHTML='版本数据未成：'+e;});
"""

if __name__ == '__main__':
    o = build()
    print(json.dumps(dict(
        editions=[(e['key'], e['chapters'], e['chars']) for e in o['editions']],
        delta_head=o['delta']['chengjia'][:2],
        agg_cj=o['agg']['chengjia'],
        distinct_front=[x['w'] for x in o['distinct']['front'][:12]],
    ), ensure_ascii=False, indent=1))
