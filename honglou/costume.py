"""衣冠谱：人人身上都有文章。

本体论的衣冠一门（成衣 / 首服 / 足衣 / 佩饰 / 雨具，见 ontology_seed.OBJECTS）
既立，乃逐回钩出每一处落笔，并作四项考究：

一・只一斗篷：第四十九回雪地群像，一人一件衣裳，脂批一句
    「只一斗篷，写得前后照耀生色」便是这一门最好的注脚。本页把这一回里
    「谁穿着什么」逐条排出来，与脂批的九句断语对读。
二・服色即性情：以「穿/披/罩/戴……」截出一处处「衣事」，色字（大红/水红/玫瑰紫/
    月白/石青/葱绿……）只在衣事之内、或贴着衣裳本体字十字以内才算数；色各有主——
    名物之主取本体论所写者，其余取动词之前最近的主人（跳过「贾母与他的」这类领格）。
三・逐回疏密：以「衣事」计办事之疏密，千字密度一眼可见这门笔墨自第几回淡下去，
    并与本次续写（八十一回以下）比较——续写接住了多少件，丢了多少件。
四・待接之衣：凡脂本里给了托意而续写（八十一回以下）不曾复现者，列作一张「衣单」，
    供续写诸 Agent 依单接衣。

产物：docs/data/costume.json
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from . import db, paths
from .relics import ALIAS, CAT_COLOR

CATS = ['成衣', '首服', '足衣', '佩饰', '雨具']

CAT_NOTE = {'成衣': '外罩、中衣、下裳', '首服': '冠、帽、抹额、勒子、笠',
            '足衣': '靴、屐', '佩饰': '锁、符等悬佩之物',
            '雨具': '蓑、笠'}

# 穿衣动词：一句中有此，便算一处「衣事」（一次穿戴就是一处落笔）
WEAR_VERBS = ['穿着', '穿上', '披着', '披了', '披上', '罩着', '罩了', '罩上',
              '换上', '换衣', '更衣', '脱了', '戴着', '戴上', '登着', '系着',
              '束着', '围着', '挽着']

# 衣裳本体字：一句里须有其一，才算真在写衣裳（不取窗纱帘幕、花色鸟名）
GARMENT = ['衣裳', '衣服', '衣', '袄', '褂', '裙', '靴', '帽', '氅', '裘', '袍',
           '衫', '绦', '笠', '蓑', '屐', '披风', '斗篷', '斗蓬', '抹额', '勒子',
           '朝靴', '汗巾', '兜肚', '抹胸', '孝服', '素服', '巾']

SCENE_RE = re.compile('[^。；！？\n]{0,30}(?:' + '|'.join(WEAR_VERBS)
                      + ')[^。；！？\n]{0,46}')

FAMILIES = [
    dict(key='red', name='红', color='#9e2b25',
         terms=['大红', '银红', '水红', '桃红', '粉红', '猩红', '石榴红', '血红',
                '朱红', '绛红', '茜红', '朱', '绛', '茜', '绯', '赤', '丹', '红']),
    dict(key='plain', name='素白', color='#3b4a6b',
         terms=['雪白', '月白', '素白', '洁白', '缟素', '素服', '素', '缟', '白']),
    dict(key='cyan', name='青绿', color='#3f6b5e',
         terms=['石青', '莲青', '鸭蛋青', '葱绿', '松绿', '柳绿', '石绿', '翡翠',
                '青', '绿']),
    dict(key='gold', name='金黄', color='#b08d57',
         terms=['鹅黄', '葱黄', '秋香色', '蜜合色', '杏黄', '金黄', '片金', '黄']),
    dict(key='purple', name='紫', color='#6b5b95',
         terms=['玫瑰紫', '茄色', '茄紫', '酱色', '紫']),
    dict(key='dark', name='皂黑', color='#5d5449',
         terms=['鸦青', '玄', '皂', '黑']),
]

SEGS = [(1, 20, '一至二十'), (21, 40, '二十一至四十'),
        (41, 60, '四十一至六十'), (61, 80, '六十一至八十'),
        (81, 110, '续写三十回')]

# 第四十九回群像：脂批九句断语（第四十九回回末总评，见 corpus 批语）
VERDICT = {'薛宝琴': '贾母所赐，言其亲也', '贾宝玉': '为后雪披一衬也',
           '林黛玉': '白狐皮斗篷，明其弱也', '李纨': '哆啰呢，昭其质也',
           '薛宝钗': '莲青斗纹锦，致其文也', '贾母': '大斗篷，尊之词也',
           '王熙凤': '披着斗篷，恰似掌家人也', '史湘云': '有斗篷不穿，着其异样行动也',
           '邢岫烟': '无斗篷，叙其穷也'}


def _alts(name: str) -> list[str]:
    return ALIAS.get(name) or [name]


def _all_terms() -> tuple[re.Pattern, dict[str, str]]:
    """色字正则（长者先，免「大红」被「红」吃掉）与 词→色系 映射。"""
    pairs = sorted(((t, f['key']) for f in FAMILIES for t in f['terms']),
                   key=lambda kv: (-len(kv[0]), kv[0]))
    return re.compile('(?:' + '|'.join(t for t, _ in pairs) + ')'), dict(pairs)


_RE, _TERM2FAM = _all_terms()


@lru_cache(maxsize=1)
def _person_index() -> tuple[tuple[str, ...], dict[str, str]]:
    """人名索引：一切称呼（宝钗、凤姐、颦儿……）皆可查，并归到本名。"""
    forms: set[str] = set()
    canon: dict[str, str] = {}
    for p in db.q('SELECT name, aliases FROM persons'):
        nm = (p['name'] or '').strip()
        if not nm:
            continue
        extras = [nm[1:]] if len(nm) == 3 else []      # 薛宝钗 → 宝钗
        try:
            extras += [a for a in json.loads(p['aliases'] or '[]') if len(a) >= 2]
        except Exception:
            pass
        for f in [nm, *extras]:
            forms.add(f)
            canon.setdefault(f, nm)
    junk = {'妹妹', '姑娘', '丫头', '奶奶', '老太太', '老爷', '姐儿'}
    names = tuple(sorted(forms - junk, key=lambda s: (-len(s), s)))
    return names, canon


def _subject_before(text: str, pos: int, span: int = 30) -> str:
    """动词之前最近的主人——跳过领格用法。

    「穿着贾母与他的一件大褂子」里，贾母是领格而非主语；凡人名紧接
    「与 / 的 / 之」者，皆跳过，取其次近者（于是仍归史湘云）。
    """
    win = text[max(0, pos - span):pos]
    cands = []
    for nm in _person_index()[0]:
        start = 0
        while True:
            k = win.find(nm, start)
            if k < 0:
                break
            cands.append((k + len(nm), len(nm), nm, win[k + len(nm):k + len(nm) + 1]))
            start = k + 1
    cands.sort(key=lambda t: (-t[0], -t[1]))
    for _, _, nm, tail in cands:
        if tail in ('与', '的', '之'):
            continue
        return _canon(nm)
    return ''


def _canon(nm: str) -> str:
    return _person_index()[1].get(nm, nm) if nm else ''


_SENT_START = re.compile(r'[。；！？\n]')


def _alias2owner(items: list[dict]) -> dict[str, list[str]]:
    """衣裳名（含别名）→ 传承之链；便于「这一处色落在谁身上」的判定。"""
    out: dict[str, list[str]] = {}
    for it in items:
        owners = _owners(it['owner'])
        for alt in _alts(it['name']):
            out[alt] = owners
    return out


def _owner_nearby(window: str, a2o: dict[str, list[str]]) -> str:
    """若句中出现了某件录入的名物，则此色当归该物的最后一位主人。"""
    best = ('', [])
    for alt, owners in a2o.items():
        if alt in window and len(alt) > len(best[0]):
            best = (alt, owners)
    return best[1][-1] if best[1] else ''


def _owners(owner: str) -> list[str]:
    """「贾母→湘云／宝玉／众姊妹」解开为 [贾母, 湘云, 宝玉, 众姊妹]。"""
    if not owner or owner in ('—', '-', '－'):
        return []
    out: list[str] = []
    for seg in re.split(r'→|->', owner):
        for nm in re.split(r'／|/|、', seg):
            nm = re.sub(r'（.*?）|\(.*?\)|拾|借', '', nm).strip()
            if nm and nm not in out:
                out.append(nm)
    return out


def _who(text: str, i: int, j: int) -> str:
    """衣裳归谁穿着（层层退守，务求其勿夺他人之衣）。

    一，落笔前十字内有「穿/披/罩/戴……」者，取动词之前最近的人名——
       「独李纨穿一件青哆啰呢褂子，薛宝钗穿一件莲青鹤氅」，于是各归其主；
    二，否则取本句最靠前的人名（「史湘云来了，穿着贾母与他的…」，
       句首主语言不为句内领格所占）；三，再取之前最近者，先近后远
       （跨句回指，如「只见他里头穿着…」上承湘云）；四，乃取之后。
    """
    for v in WEAR_VERBS:
        k = text.rfind(v, max(0, i - 18), i)
        if k >= 0:
            nm = _subject_before(text, k)
            if nm:
                return nm
    return ''


def _ctx(text: str, i: int, j: int) -> str:
    return text[max(0, i - 44):j + 44].replace('\n', '')


def _books() -> tuple[dict[int, str], dict[int, str]]:
    main: dict[int, str] = {}
    for r in db.q('SELECT chapter, text FROM v_main WHERE chapter > 0 ORDER BY id'):
        main.setdefault(r['chapter'], '')
        main[r['chapter']] += r['text'] or ''
    cont: dict[int, str] = {}
    try:
        rows = db.q('SELECT chapter, text FROM continuations ORDER BY chapter')
    except Exception:
        rows = []
    for r in rows:
        cont.setdefault(r['chapter'], '')
        cont[r['chapter']] += r['text'] or ''
    return main, cont


def build(dst: Path | None = None) -> Path:
    out = dst or (paths.SITE_DIR / 'data')
    out.mkdir(parents=True, exist_ok=True)

    qs = ','.join('?' * len(CATS))
    garments = db.q('SELECT name, owner, category, symbol FROM objects '
                    'WHERE category IN (%s)' % qs, CATS)
    main, cont = _books()
    books = [('书', main), ('续', cont)]

    # ---- 一・衣冠名物的每一次现身
    items = []
    for g in garments:
        hits = []
        for src, book in books:
            for ch, text in book.items():
                # 一条名物的别写逐个试，先见到谁便用谁（雀金裘/雀金呢、
                # 斗篷/斗蓬），免失落一条线
                for alt in _alts(g['name']):
                    ms = list(re.finditer(re.escape(alt), text))
                    if not ms:
                        continue
                    for m in ms:
                        i, j = m.start(), m.end()
                        hits.append(dict(ch=ch, src=src, alias=alt,
                                         who=_who(text, i, j),
                                         ctx=_ctx(text, i, j)))
                    break
        if not hits:
            continue
        hits.sort(key=lambda h: (h['ch'], h['src'] != '书'))
        chapters = sorted({h['ch'] for h in hits})
        items.append(dict(name=g['name'], owner=g['owner'] or '',
                          cat=g['category'], symbol=g['symbol'] or '',
                          hits=hits, chapters=chapters, n=len(hits),
                          first=chapters[0], last_=chapters[-1],
                          n_xu=sum(1 for h in hits if h['src'] == '续')))
    items.sort(key=lambda it: (-it['n'], it['first'], it['name']))
    a2o = _alias2owner(items)          # 衣裳名 → 传承之链，供服色归属之用

    # ---- 二・衣事：一句一次穿戴
    scenes, colors, spans = [], [], defaultdict(list)
    for src, book in books:
        for ch, text in book.items():
            for m in SCENE_RE.finditer(text):
                clause = m.group()
                if not any(g in clause for g in GARMENT):
                    continue
                i, j = m.start(), m.end()
                spans[(src, ch)].append((i, j))
                who = _who(text, i, j)
                owner = _owner_nearby(clause, a2o)
                for cm in _RE.finditer(clause):
                    colors.append(dict(ch=ch, src=src,
                                       fam=_TERM2FAM[cm.group()],
                                       term=cm.group(),
                                       who=owner or who, ctx=clause))
                scenes.append(dict(ch=ch, src=src, who=owner or who, text=clause))
    # 漏网之色：不在任何衣事之内、却贴着衣裳本体字十字以内者
    for src, book in books:
        for ch, text in book.items():
            sp = spans.get((src, ch), ())
            for m in _RE.finditer(text):
                i, j = m.start(), m.end()
                if any(a <= i and j <= b for a, b in sp):
                    continue
                near = text[max(0, i - 10):j + 10]
                if not any(g in near for g in GARMENT):
                    continue
                colors.append(dict(ch=ch, src=src, fam=_TERM2FAM[m.group()],
                                   term=m.group(),
                                   who=_owner_nearby(near, a2o) or _who(text, i, j),
                                   ctx=_ctx(text, i, j)))

    # ---- 三・逐回疏密
    wear, lens = Counter(), Counter()
    for src, book in books:
        for ch, text in book.items():
            lens[(src, ch)] = len(text)
    for s_ in scenes:
        wear[(s_['src'], s_['ch'])] += 1
    goods_by_ch = Counter()
    for it in items:
        for h in it['hits']:
            goods_by_ch[(h['src'], h['ch'])] += 1
    series = []
    for src, book in books:
        for ch in sorted(book):
            ln = max(1, lens[(src, ch)])
            series.append(dict(ch=ch, src=src, wear=wear[(src, ch)], len=ln,
                               dens=round(wear[(src, ch)] / ln * 1000, 3),
                               goods=goods_by_ch.get((src, ch), 0)))

    def _dens(src: str) -> float:
        w = sum(wear[(s, c)] for (s, c) in lens if s == src)
        l = max(1, sum(lens[(s, c)] for (s, c) in lens if s == src))
        return round(w / l * 1000, 3)

    # ---- 四・人物 × 衣裳 / 服色
    known = set(_person_index()[1].values())       # 本体论里的人名
    raw_wear: dict[str, Counter] = defaultdict(Counter)
    raw_fam: dict[str, Counter] = defaultdict(Counter)
    raw_act: Counter = Counter()
    for it in items:                       # 衣裳之主，由本体论写定，非出算法之猜度
        for h in it['hits']:
            owners = _owners(it['owner'])
            for nm in (owners or ([h['who']] if h['who'] else [])):
                raw_wear[nm][it['name']] += 1
    for c in colors:
        if c['who']:
            raw_fam[c['who']][c['fam']] += 1
    for s_ in scenes:
        if s_['who']:
            raw_act[s_['who']] += 1

    def _merge(raw) -> dict[str, Counter]:
        """归本名（宝玉→贾宝玉），并剔除「众姊妹」等非人名。"""
        out: dict[str, Counter] = defaultdict(Counter)
        for nm, c in raw.items():
            cn = _canon(nm)
            if cn in known:
                out[cn].update(c)
        return out

    p_wear = _merge(raw_wear)
    p_fam = _merge(raw_fam)
    p_act = Counter({_canon(k): v for k, v in raw_act.items()
                     if _canon(k) in known})
    persons = []
    for nm in sorted({*p_wear, *p_fam}):
        w, f = p_wear.get(nm, Counter()), p_fam.get(nm, Counter())
        acts = p_act.get(nm, 0)
        if not sum(w.values()) and not sum(f.values()) and not acts:
            continue
        top_fam = f.most_common(1)[0][0] if f else ''
        persons.append(dict(name=nm, goods=sum(w.values()), colors=sum(f.values()),
                            acts=acts, top=top_fam,
                            fams=[[k, f[k]] for k, _ in f.most_common()],
                            items=[[k, w[k]] for k, _ in w.most_common(6)]))
    persons.sort(key=lambda p: (-(p['acts'] + p['colors']), p['name']))
    persons = persons[:18]

    # ---- 五・第四十九回雪地群像
    #      这一回各人分什么衣裳，本体论里已按原文写定 owner（非由算法猜测）；
    #      排序依脂批断语的先后：宝琴→宝玉→黛玉→李纨→宝钗→贾母→凤姐→湘云→岫烟。
    order = {nm: i for i, nm in enumerate(VERDICT)}
    ch49 = []
    for it in items:
        keys = [k for k in _owners(it['owner']) if k in VERDICT]
        verdict = VERDICT.get(min(keys, key=lambda k: order[k]), '') if keys else ''
        for h in it['hits']:
            if h['ch'] == 49 and h['src'] == '书':
                ch49.append(dict(name=it['name'], cat=it['cat'],
                                 owner=it['owner'], symbol=it['symbol'],
                                 verdict=verdict, ctx=h['ctx']))
    ch49.sort(key=lambda r: (min([order.get(k, 99) for k in _owners(r['owner'])]
                                 or [99]), r['name']))

    # ---- 六・段落构成
    def _in_seg(ch: int, src: str, lo: int, hi: int) -> bool:
        return lo <= ch <= hi and (src == '书' if hi <= 80 else src == '续')

    segs = []
    for lo, hi, label in SEGS:
        cs = Counter(c['fam'] for c in colors
                     if _in_seg(c['ch'], c['src'], lo, hi))
        gs = Counter(it['name'] for it in items for h in it['hits']
                     if _in_seg(h['ch'], h['src'], lo, hi))
        w = sum(wear[(s, c)] for (s, c) in lens if _in_seg(c, s, lo, hi))
        ln = max(1, sum(lens[(s, c)] for (s, c) in lens if _in_seg(c, s, lo, hi)))
        tot = sum(cs.values())
        segs.append(dict(name=label, lo=lo, hi=hi, n=tot, kinds=len(gs),
                         dens=round(w / ln * 1000, 3),
                         fams=[[f['key'], cs.get(f['key'], 0)] for f in FAMILIES],
                         share=[[f['key'], round(cs.get(f['key'], 0) / tot, 3)]
                                for f in FAMILIES] if tot else [],
                         top=gs.most_common(5)))

    # ---- 七・续写的服色（脂本之红，与续写之青）
    fam_main = Counter(c['fam'] for c in colors if c['src'] == '书')
    fam_xu = Counter(c['fam'] for c in colors if c['src'] == '续')
    xu_red = [dict(ch=c['ch'], term=c['term'], ctx=c['ctx'])
              for c in colors if c['src'] == '续' and c['fam'] == 'red']

    # ---- 八・续写接住了几件（未接者即「待接之衣」）
    picked = [it['name'] for it in items if it['n_xu']]
    owed = [dict(name=it['name'], owner=it['owner'], symbol=it['symbol'],
                 cat=it['cat'], ch=it['first'])
            for it in items if not it['n_xu']]

    stats = dict(items=len(items), hits=sum(it['n'] for it in items),
                 chaps=len({h['ch'] for it in items for h in it['hits']}),
                 colors=len(colors),
                 scenes=len(scenes),
                 scenes_main=sum(1 for s_ in scenes if s_['src'] == '书'),
                 scenes_xu=sum(1 for s_ in scenes if s_['src'] == '续'),
                 wear=sum(wear.values()),
                 dens_main=_dens('书'), dens_xu=_dens('续'),
                 top_ch=max((s for s in series if s['src'] == '书'),
                            key=lambda s: s['dens'], default={'ch': 0})['ch'],
                 picked=picked, owed=len(owed),
                 fam_main=[[f['key'], fam_main.get(f['key'], 0)] for f in FAMILIES],
                 fam_xu=[[f['key'], fam_xu.get(f['key'], 0)] for f in FAMILIES],
                 n_main=sum(fam_main.values()), n_xu=sum(fam_xu.values()),
                 xu_red=xu_red,
                 cats=[[c, sum(1 for it in items if it['cat'] == c)] for c in CATS])

    doc = dict(items=items, colors=colors, series=series, segs=segs, scenes=scenes,
               persons=persons, ch49=ch49, owed=owed, stats=stats,
               fams=[[f['key'], f['name'], f['color']] for f in FAMILIES],
               cats=CATS,
               colors_cat=CAT_COLOR)
    fp = out / 'costume.json'
    fp.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    return fp


BODY = """
<h2>衣冠谱 · 人人身上都有文章</h2>
<div class="card small">
衣裳在《红楼》里从来不是衬<em>着</em>人，而是<em>写</em>人。本体论先立衣冠一门——
<b>成衣 / 首服 / 足衣 / 佩饰 / 雨具</b>——把雀金裘、凫靥裘、猩猩毡斗篷、
白狐里鹤氅、紫金冠、抹额、掐金挖云小靴、玉针蓑……逐件录入，注明所主与托意；
再回正文把这批名物的每一次现身，连前后原文与在场之人一并钩出。
<b>不为修辞上的好看夸张半分</b>：色字只有在衣裳、缎绫等字的一十四字之内才算「服色」，
人名只取离它最近的那一个——换言之，此页所呈现的一切冷暖浓淡，都是可用原句复核的。
</div>
<div class="grid" id="cos-cards"></div>

<h2>只一斗篷 · 第四十九回的雪地群像</h2>
<div class="card">
<p class="small">
第四十九回是全书唯一一回「人人一身行头」的群戏：一夜大雪，众姊妹披着各自的衣裳聚到稻香村。
第四十九回回末总评撮一篇短文字说得极刻薄，也极公允：
</p>
<div class="poem">此文线索在斗篷。宝琴翠羽斗篷，贾母所赐，言其亲也；宝玉红猩猩毡斗篷，为后雪披一衬也；黛玉白狐皮斗篷，明其弱也；李宫裁斗篷是哆啰呢，昭其质也；宝钗斗篷是莲青斗纹锦，致其文也；贾母是大斗篷，尊之词也；凤姐是披着斗篷，恰似掌家人也；湘云有斗篷不穿，着其异样行动也；岫烟无斗篷，叙其穷也。只一斗篷，写得前后照耀生色。</div>
<p class="small">
下表把这一回里<b>谁穿着什么</b>逐条排出，一列是原文，一列是脂批的断语（有则有，无则留白）。
<b>一人配一件衣裳</b>，其人的亲疏、穷通、性情便都写在里面了。
<b>贾母赐衣即是赐分数</b>：赐予琴儿一件凫靥裘，众人便知老太太疼谁；岫烟一人无氅，不必再说一句穷字。
</p>
</div>
<div class="gwrap">
  <div class="card samples" id="cos49"></div>
  <aside class="card gside" id="cos49side"><p class="small">点一行看原文与托意。</p></aside>
</div>

<h2>服色即性情</h2>
<div class="card small">
色只许落在衣边：一十四字之内不见衣裳绫缎等字者不计。于是色有主人。
下图每人一条，按色系比例摊开，右侧标出其身上被写到的名物件数与主色。
点一条即见原句——<b>谁偏红，谁偏素，数据自己会说话</b>。
</div>
<div class="card"><div class="legend" id="coslegend"></div>
  <svg id="cosperson" viewBox="0 0 1080 420" preserveAspectRatio="xMidYMin meet"></svg></div>
<div class="gwrap">
  <div class="card small" id="cospeople"><p class="small">点一点看此人的衣裳与服色原句。</p></div>
  <aside class="card gside" id="cospside"></aside>
</div>

<h2>逐回疏密 · 这笔笔墨自第几回淡下去</h2>
<div class="card gcanvas">
  <div class="gtools">
    <button id="cDens" class="on">千字密度</button>
    <button id="cAbs">绝对次数</button>
    <span class="gstat" id="cstat"></span>
  </div>
  <svg id="cosseries" viewBox="0 0 1080 300" preserveAspectRatio="xMidYMid meet"></svg>
</div>
<div class="card"><table id="cossegtab"></table></div>

<h2>四段色调</h2>
<div class="card"><svg id="cossegs" viewBox="0 0 1080 210"
  preserveAspectRatio="xMidYMid meet"></svg></div>

<h2>名物</h2>
<div class="card">
  <div class="gtools" id="coscats"></div>
</div>
<div class="gwrap">
  <div class="card samples" id="coslist"></div>
  <aside class="card gside" id="cosside"><p class="small">点一件看它的每一次现身。</p></aside>
</div>

<h2>续写的服色 · 三十回里再没有一笔新的红</h2>
<div class="card small">
续写三十回里，明写「穿／披／换／脱」的只有三处：第八十一回「换衣整洁」、
第八十五回若兰「换上了射衣」、第一百五回湘莲「脱了绫罗，换了布衣」——
<b>而且都不是为着好看</b>，是为了告别。
更要紧的是颜色：<b>脂本的红，到续写里几乎不见了</b>。下表两相对照，
并把续写里仅存的几处「红」逐条列出：<b>其中真正属于贾家的，一笔也没有</b>。
</div>
<div class="card"><table id="cosxutab"></table></div>
<div class="card samples" id="cosxured"></div>

<h2>待接之衣 · 续写诸君的账单</h2>
<div class="card small">
凡脂本里给了托意、而本次续写（八十一回以下）不曾复现者，尽在此单。
衣裳多是细小之物，丢下一两件原不必大惊；这张单子真正的用场在另一处——
<b>续写者若要接住脂本的草蛇灰线，照单拿去看，一件都不会漏</b>。
</div>
<div class="card small" id="cosowedsum"></div>
<div class="card samples" id="cosowed"></div>
"""


JS = r"""
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
let D=null,CAT='全部',MODE='dens';
const FAM=D0=>Object.fromEntries(D0.fams.map(f=>[f[0],{name:f[1],color:f[2]}]));
let FM=null;

function cards(){
  const s=D.stats;
  const rows=[['录入衣冠',`${s.items} 件`],['名物现身',`${s.hits} 处 / 涉 ${s.chaps} 回`],
    ['服色落笔',`${s.colors} 处`],['衣着字总计',`${s.wear} 处`],
    ['密度之最',`第 ${s.top_ch} 回`],
    ['脂本 / 续写 千字密度',`${s.dens_main} / ${s.dens_xu}`],
    ['续写接住',`${s.picked.length} 件`],['待接之衣',`${s.owed} 件`]];
  $('cos-cards').innerHTML=rows.map(r=>
    `<div class="card"><div class="small">${esc(r[0])}</div><big>${esc(r[1])}</big></div>`).join('');
}

function ch49(){
  const rows=D.ch49;
  $('cos49').innerHTML=rows.map((r,i)=>
    `<div><b>${esc(r.who||'—')}</b>`
    +`<span class="tag">${esc(r.name)}</span>`
    +`<span class="tag">${esc(r.cat)}</span>`
    +(r.verdict?`<span class="tag red">脂批：${esc(r.verdict)}</span>`:'')
    +`<br><span class="small">…${esc(r.ctx)}…</span></div>`).join('');
  $('cos49').querySelectorAll('div').forEach((el,i)=>{el.style.cursor='pointer';
    el.onclick=()=>{
      const r=rows[i];
      $('cos49side').innerHTML=`<h3>${esc(r.name)}</h3>`
        +`<p class="small">${esc(r.cat)} · 所主 ${esc(r.owner||'—')}</p>`
        +(r.symbol&&r.symbol!=='—'?`<p>${esc(r.symbol)}</p>`:'')
        +(r.verdict?`<p class="small">脂批：${esc(r.verdict)}</p>`:'')
        +`<p class="small">…${esc(r.ctx)}…</p>`;};});
}

function people(){
  const W=1080,PL=118,PR=150,rowH=Math.min(22,(400)/Math.max(1,D.persons.length));
  let s='';
  D.persons.forEach((p,i)=>{
    const y=10+i*rowH, tot=p.fams.reduce((a,f)=>a+f[1],0)||1;
    s+=`<text x=${PL-8} y=${y+rowH/2+4} text-anchor="end" font-size=12 fill="#3a322a" font-family="serif">${esc(p.name)}</text>`;
    let x=PL;
    p.fams.forEach(f=>{
      const w=(f[1]/tot)*(W-PL-PR);
      s+=`<rect x=${x} y=${y+3} width=${w} height=${rowH-8} fill="${FM[f[0]].color}" opacity=".78" data-p="${i}.${f[0]}">`
        +`<title>${esc(p.name)}　${esc(FM[f[0]].name)} ${f[1]} 处</title></rect>`;
      x+=w;
    });
    s+=`<text x=${W-PR+6} y=${y+rowH/2+4} font-size=11 fill="#8a7f6d" font-family="serif">`
      +`${p.goods} 件 / ${p.colors} 色　主色 ${esc(FM[p.top]?FM[p.top].name:'—')}</text>`;
  });
  $('cosperson').innerHTML=s;
  $('cosperson').querySelectorAll('rect').forEach(el=>el.onclick=()=>{
    const [i,k]=el.dataset.p.split('.'); side(D.persons[+i],k);});
  $('coslegend').innerHTML=D.fams.map(f=>
    `<span><i style="background:${f[2]}"></i>${esc(f[1])}</span>`).join('')
    +'<span class="small">（按色系比例摊开，每人身上的名物件数、服色处数与主色列于右侧）</span>';
}

function chips(){
  $('cospeople').innerHTML='<b>点名字也可见其衣裳：</b>'
    +D.persons.map((p,i)=>`<span class="nb" data-i="${i}">${esc(p.name)}</span>`).join('');
  $('cospeople').querySelectorAll('.nb').forEach(el=>el.onclick=()=>side(D.persons[+el.dataset.i],null));
}

function side(p,k){
  const goods=D.items.filter(it=>it.hits.some(h=>h.who===p.name));
  let h=`<h3>${esc(p.name)}</h3><p class="small">身上名物 ${p.goods} 处 · 服色 ${p.colors} 处`;
  if(k) h+=` · 点看 ${esc(FM[k].name)}`;
  h+=`</p>`;
  const cs=D.colors.filter(c=>c.who===p.name&&(!k||c.fam===k)).slice(0,12);
  h+=cs.map(c=>`<div style="border-bottom:1px dotted #e9ddc7;padding:3px 0">`
    +`<span class="tag" style="color:${FM[c.fam].color};border-color:${FM[c.fam].color}">${esc(c.term)}</span>`
    +`<span class="tag">第${c.ch}回</span><br><span class="small">…${esc(c.ctx)}…</span></div>`).join('');
  if(goods.length){
    h+=`<p class="small">所著：${goods.map(g=>esc(g.name)).join('、')}</p>`;
  }
  $('cospside').innerHTML=h;
}

function series(){
  const S=D.series.filter(s=>s.ch>0),W=1080,H=300,PL=46,PB=36;
  const key=MODE==='dens'?'dens':'wear';
  const mx=Math.max(...S.map(s=>s[key]),0.001);
  const x=i=>PL+i*(W-PL-16)/(Math.max(1,S.length-1));
  let s=`<rect x=${x(S.findIndex(d=>d.src==='续'))} y=16 width=${W-16-x(S.findIndex(d=>d.src==='续'))} `
    +`height=${H-PB-16} fill="#3b4a6b" opacity=".05"/>`;
  [0,.5,1].forEach(f=>{const yy=16+(H-PB-16)*f;
    s+=`<line x1=${PL} y1=${yy} x2=${W-16} y2=${yy} stroke="#e3d9c4"/>`;});
  S.forEach((d,i)=>{
    const h=(d[key]/mx)*(H-PB-24);
    if(h<=0)return;
    const col=d.src==='续'?'#3b4a6b':'#9e2b25';
    s+=`<rect x=${x(i)-2.4} y=${H-PB-h} width=4.8 height=${h} fill=${col} opacity="${d.src==='续'?.45:.62}">`
      +`<title>第${d.ch}回（${d.src==='续'?'续写':'脂本'}）：衣事 ${d.wear} 处（${d.dens}/千字）· 录入名物 ${d.goods} 次</title></rect>`;
  });
  [1,20,40,60,80,110].forEach(c=>{const i=S.findIndex(d=>d.ch===c); if(i<0)return;
    s+=`<text x=${x(i)} y=${H-14} text-anchor="middle" font-size=10.5 fill="#8a7f6d" font-family="serif">${c}</text>`;});
  [3,6,8,49,52,63].forEach(c=>{const i=S.findIndex(d=>d.ch===c); if(i<0)return;
    s+=`<circle cx=${x(i)} cy=${(H-PB)-(S[i][key]/mx)*(H-PB-24)} r=3.2 fill="#9e2b25"/>`
      +`<text x=${x(i)} y=${(H-PB)-(S[i][key]/mx)*(H-PB-24)-8} text-anchor="middle" font-size=10 fill="#9e2b25" font-family="serif">${c}</text>`;});
  $('cosseries').innerHTML=s;
  $('cstat').textContent=(MODE==='dens'?'每千字计':'绝对次数')
    +'：一本 ■ 脂本　■ 续写（淡色）　红点＝第三／六／八／四十九／五十二／六十三回';
}

function segs(){
  const W=1080,H=210,PL=118,PB=26,rowH=(H-PB-14)/D.segs.length;
  let s='';
  D.segs.forEach((g,i)=>{
    const tot=g.fams.reduce((a,f)=>a+f[1],0)||1, y=14+i*rowH;
    s+=`<text x=${PL-10} y=${y+rowH/2} text-anchor="end" font-size=12 fill="#5d5449" font-family="serif">${esc(g.name)}</text>`;
    let cx=PL;
    g.fams.forEach(f=>{
      if(!f[1])return;
      const w=(f[1]/tot)*(W-PL-160), col=FM[f[0]].color;
      s+=`<rect x=${cx} y=${y+6} width=${w} height=${rowH-20} fill="${col}" opacity=".75">`
        +`<title>${esc(g.name)}　${esc(FM[f[0]].name)} ${f[1]} 处（${Math.round(f[1]/tot*100)}%）</title></rect>`;
      if(w>36) s+=`<text x=${cx+w/2} y=${y+6+(rowH-20)/2+4} text-anchor="middle" font-size=10.5 fill="#fffdf8" font-family="serif">${Math.round(f[1]/tot*100)}%</text>`;
      cx+=w;
    });
    s+=`<text x=${W-150} y=${y+rowH/2} font-size=11 fill="#8a7f6d" font-family="serif">`
      +`服色 ${g.n} 处 · 名物 ${g.kinds} 种 · ${g.dens}/千字</text>`;
  });
  $('cossegs').innerHTML=s;
  $('cossegtab').innerHTML=`<thead><tr><th>段落</th><th>服色处数</th><th>名物种类</th>`
    +`<th>衣着字密度（/千字）</th><th>最常现身</th></tr></thead><tbody>`
    +D.segs.map(g=>`<tr><td>${esc(g.name)}</td><td>${g.n}</td><td>${g.kinds}</td>`
      +`<td>${g.dens}</td><td>${g.top.map(t=>esc(t[0])+'·'+t[1]).join('　')}</td></tr>`).join('')
    +`</tbody>`;
}

function list(){
  const items=(CAT==='全部'?D.items:D.items.filter(i=>i.cat===CAT));
  $('coslist').innerHTML=items.map((it,i)=>
    `<div><span class="tag">${esc(it.cat)}</span><b>${esc(it.name)}</b>`
    +`<span class="tag red">${it.n} 处</span>`
    +`<span class="tag">第${it.chapters.slice(0,6).join('、')}回${it.chapters.length>6?'…':''}</span>`
    +(it.n_xu?`<span class="tag">续写 ${it.n_xu}</span>`:'')
    +`<br><span class="small">所主 ${esc(it.owner||'—')}：${esc(it.symbol||'')}</span></div>`).join('');
  $('coslist').querySelectorAll('div').forEach((el,i)=>{el.style.cursor='pointer';
    el.onclick=()=>item(items[i]);});
  $('coscats').innerHTML=['全部'].concat(D.cats).map(c=>
    `<button class="${c===CAT?'on':''}" data-c="${esc(c)}">${esc(c)}</button>`).join('');
  $('coscats').querySelectorAll('button').forEach(b=>b.onclick=()=>{CAT=b.dataset.c;list();
    $('coscats').querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));});
}

function item(it){
  $('cosside').innerHTML=`<h3>${esc(it.name)}</h3>`
    +`<p class="small">${esc(it.cat)} · 所主 ${esc(it.owner||'—')} · 现身 ${it.n} 处`
    +`（脂本 ${it.n-it.n_xu} ／ 续写 ${it.n_xu}）</p><p>${esc(it.symbol||'')}</p>`
    +it.hits.map(h=>`<div style="border-bottom:1px dotted #e9ddc7;padding:3px 0">`
      +`<span class="tag">第${h.ch}回</span>`
      +`<span class="tag${h.src==='续'?' red':''}">${h.src==='续'?'续写':'脂本'}</span>`
      +(h.who?`<b>${esc(h.who)}</b>`:'')
      +`<br><span class="small">…${esc(h.ctx)}…</span></div>`).join('');
}

function xu(){
  const s=D.stats, pc=(n,t)=>t?Math.round(n/t*100):0;
  $('cosxutab').innerHTML=`<thead><tr><th>色系</th>`
    +`<th>脂本前八十回（${s.n_main} 处）</th><th>续写三十回（${s.n_xu} 处）</th></tr></thead><tbody>`
    +D.fams.map(f=>{
      const a=(s.fam_main.find(x=>x[0]===f[0])||[0,0])[1],
            b=(s.fam_xu.find(x=>x[0]===f[0])||[0,0])[1];
      return `<tr><td><i style="display:inline-block;width:9px;height:9px;`
        +`border-radius:50%;margin-right:6px;background:${f[2]}"></i>${esc(f[1])}</td>`
        +`<td>${a}（${pc(a,s.n_main)}%）</td><td>${b}（${pc(b,s.n_xu)}%）</td></tr>`;})
    +`</tbody>`;
  $('cosxured').innerHTML=(s.xu_red.length?
      s.xu_red.map(r=>`<div><span class="tag red">第${r.ch}回 · ${esc(r.term)}</span>`
        +`<br><span class="small">…${esc(r.ctx)}…</span></div>`).join('')
    :'<p class="small">续写三十回里，一处也没有。</p>');
}

function owed(){
  const s=D.stats;
  $('cosowedsum').innerHTML='脂本前八十回记<b>衣事 '+s.scenes_main+' 处</b>'
    +`（每千字 ${s.dens_main} 处），续写三十回只有 <b>${s.scenes_xu} 处</b>`
    +`（每千字 ${s.dens_xu} 处）；录入的 ${s.items} 件名物，续写接住 `
    +`<b>${s.picked.length}</b> 件${s.picked.length?'（'+esc(s.picked.join('、'))+'）':''}，`
    +`尚有 <b>${s.owed}</b> 件待接。`;
  $('cosowed').innerHTML=D.owed.map(o=>
    `<div><span class="tag">${esc(o.cat)}</span><b>${esc(o.name)}</b>`
    +`<span class="tag">首见第${o.ch}回</span>`
    +`<br><span class="small">所主 ${esc(o.owner||'—')}：${esc(o.symbol||'')}</span></div>`).join('')
    || '<p class="small">续写已尽数接住。</p>';
}

fetch('data/costume.json').then(r=>r.json()).then(d=>{
  D=d;FM=FAM(D);
  cards();ch49();people();chips();series();segs();list();xu();owed();
  $('cDens').onclick=()=>{MODE='dens';$('cDens').classList.add('on');$('cAbs').classList.remove('on');series();};
  $('cAbs').onclick=()=>{MODE='abs';$('cAbs').classList.add('on');$('cDens').classList.remove('on');series();};
});
"""
