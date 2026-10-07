"""本体图谱：把知识库各表织成多重视图，供学习与研究。

视图
----
relations   人物关系网（113 人物 / 129 条关系，分血缘·婚姻·主仆·情缘·社会·神话）
abode       家族·府邸·园林·院落（families × places × 居者）
imagery     意象谱（49 类意象 × 诗人 × 诗词共现）
symbols     器物·典故·概念（24 物件 · 27 典故 · 概念）
fate        册籍·判词·探佚（太虚幻境册籍 → 判词/曲 → 探佚结局 → 脂批线索落地）
timeline    时序长卷（前八十回节令 + 后三十回骨架 110 回）
debate      推演脉络（主题 × Agent × 立论，含置信度）

产物：docs/data/graph.json（全部视图一次导出，浏览器端只做布局与交互）。
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import db, paths

# ---------------- 配色（与 theme.py 宣纸·朱印同一套）
CINNABAR = '#9e2b25'
CINNABAR_L = '#c2504a'
JADE = '#3f6b5e'
INDIGO = '#3b4a6b'
GOLD = '#b08d57'
MUTED = '#8a7f6d'
PLUM = '#7a5c8a'
CLAY = '#b0703c'
MOSS = '#5c8a6a'
BRONZE = '#8a6a3b'
ROSE = '#a8626a'
ASH = '#6f6a63'

SERV_KW = ('丫鬟', '小厮', '丫头', '管家', '总管', '婆子', '媳妇', '家人',
           '乳母', '陪房', '太监', '买办', '庄头', '仆', '侍', '戏子',
           '门客', '管事', '稳婆', '园中', '奶娘', '官媒')
FANGWAI_KW = ('和尚', '道人', '尼', '僧', '仙', '警幻', '空空', '渺渺',
              '道士', '癞头', '跛足', '姑子', '道婆', '修行', '出家')
FANGWAI_PLACE = ('庵', '寺', '观', '庙')
SURNAME_G = [('贾', '贾府'), ('史', '史家'), ('王', '王家'), ('薛', '薛家'),
             ('甄', '甄家'), ('林', '林家'), ('秦', '秦家'), ('尤', '尤家')]
GROUP_COLOR = {
    '贾府': CINNABAR, '史家': JADE, '王家': INDIGO, '薛家': GOLD,
    '甄家': PLUM, '林家': MOSS, '秦家': CLAY, '尤家': ROSE,
    '仆役': BRONZE, '方外': ASH, '他姓·外戚': MUTED,
}
KIN = {'父', '母', '父子', '母子', '父女', '母女', '兄妹', '兄弟', '姐妹',
       '祖母', '祖孙', '外祖孙', '姑侄', '叔侄', '叔嫂', '姨表兄妹',
       '表姐妹', '侄孙女', '妯娌', '夫妻', '继母女'}
MARR = {'夫', '妇', '夫妇', '娶', '妾', '婚约'}
SERV = {'主仆', '司', '携'}
LOVE = {'情', '情缘', '知己', '还泪', '灌溉'}
MYTH = {'灌溉', '还泪', '携'}
KIND_COLOR = {
    '血缘': CINNABAR, '婚姻': GOLD, '主仆': BRONZE,
    '情缘': CINNABAR_L, '社会': INDIGO, '神话': PLUM, '其他': MUTED,
}
IMG_COLOR = {'植物': MOSS, '天象': INDIGO, '器物': GOLD, '禽鸟': CLAY,
             '地理': JADE, '时间': PLUM, '心理': ROSE}
PLACE_COLOR = {'园林': MOSS, '院落': JADE, '建筑': BRONZE, '府邸': CINNABAR,
               '厅堂': CLAY, '寺庙': PLUM, '庙宇': PLUM, '道观': PLUM,
               '仙境': INDIGO, '山': ASH, '城邑': MUTED, '地点': MUTED,
               '学堂': GOLD, '街巷': MUTED, '城门': MUTED}


# ---------------- 基础取材

def _persons() -> dict[str, dict]:
    out = {}
    for r in db.q('SELECT * FROM persons'):
        try:
            r['alias_list'] = json.loads(r['aliases'] or '[]')
        except Exception:
            r['alias_list'] = []
        out[r['name']] = r
    return out


def _person_group(r: dict) -> str:
    blob = f"{r.get('role') or ''}{r.get('residence') or ''}{r.get('traits') or ''}"
    if any(k in blob for k in FANGWAI_KW) or any(
            k in (r.get('residence') or '') for k in FANGWAI_PLACE):
        return '方外'
    if any(k in blob for k in SERV_KW):
        return '仆役'
    for pre, g in SURNAME_G:
        if r['name'].startswith(pre) and len(r['name']) <= 4:
            return g
    return '他姓·外戚'


def _mentions() -> tuple[dict[str, list[int]], dict[str, int]]:
    """人物 → 逐回提及数（1..80 的 80 元数组）与总数。"""
    per = defaultdict(lambda: [0] * 80)
    for r in db.q('SELECT person, chapter, SUM(n) n FROM mentions GROUP BY 1, 2'):
        c = int(r['chapter'] or 0)
        if 1 <= c <= 80:
            per[r['person']][c - 1] += int(r['n'] or 0)
    tot = {k: sum(v) for k, v in per.items()}
    return per, tot


def _main_text() -> dict[int, str]:
    d: dict[int, str] = {}
    for r in db.q("SELECT chapter, text FROM blocks WHERE kind='正文'"):
        d[r['chapter']] = d.get(r['chapter'], '') + (r['text'] or '')
    return d


def _occur(terms, texts: dict[int, str], cap: int = 40) -> dict[str, list[list[int]]]:
    """词 → [[回, 次数], ...]（只留前八十回正文实见处）。"""
    out = {}
    for t in terms:
        if not t or len(t) < 1:
            continue
        hit = []
        for c in sorted(texts):
            if c > 80:
                continue
            n = texts[c].count(t)
            if n:
                hit.append([c, n])
        if hit:
            out[t] = hit[:cap]
    return out


def _spark(hit: list[list[int]], upto: int = 110) -> dict:
    """逐回计数只存非零处（p=[[回, 次数], ...]），前端再铺成条形。"""
    agg: dict[int, int] = {}
    for c, n in hit or []:
        if 1 <= c <= upto:
            agg[c] = agg.get(c, 0) + n
    pairs = [[c, agg[c]] for c in sorted(agg)]
    return dict(p=pairs, m=max(agg.values()) if agg else 1, n=upto)


def _poems() -> list[dict]:
    return db.q('SELECT * FROM poems')


def _poem_lines() -> dict[str, list[str]]:
    d = defaultdict(list)
    for r in db.q('SELECT poem_id, seq, line FROM poem_lines ORDER BY poem_id, seq'):
        d[r['poem_id']].append(r['line'])
    return d


def _outline() -> dict:
    f = paths.data('outline.json')
    if not f.exists():
        return {}
    return json.loads(f.read_text(encoding='utf-8'))


def _timeline_events() -> list[str]:
    """从骨架硬约束里取【时序】一行（为免拉起 LLM 依赖，直接从产物读）。"""
    doc = _outline()
    for c in doc.get('constraints', []):
        if c.startswith('【时序】'):
            return [x.strip() for x in c[len('【时序】'):].split('→') if x.strip()]
    return []


def _bigrams(s: str) -> set[str]:
    s = re.sub(r'[（）()【】\s]', '', s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


# ---------------- 视图一：人物关系网

def view_relations() -> dict:
    persons = _persons()
    per, tot = _mentions()
    rels = db.q('SELECT source, rel, target FROM relations')
    deg = Counter()
    for r in rels:
        deg[r['source']] += 1
        deg[r['target']] += 1
    keep = {p for p in persons
            if deg[p] or (persons[p]['registry'] or '') not in ('', '—')
            or (persons[p]['fate'] or '') not in ('', '—')}
    poems = _poems()
    n_poem = Counter(p['author'] for p in poems if p['author'])
    objs = db.q('SELECT name, owner FROM objects')
    allu = db.q('SELECT name, person FROM allusions')
    nodes = []
    for name in sorted(keep):
        p = persons[name]
        g = _person_group(p)
        owns = [o['name'] for o in objs if name in (o['owner'] or '')]
        als = [a['name'] for a in allu if name in (a['person'] or '')]
        seen_ch = sum(1 for x in per[name] if x)
        info = [['身份', p['role']], ['性别', p['gender']],
                ['居所', p['residence']], ['册籍', p['registry']],
                ['情榜', p['qingbang']], ['探佚结局', p['fate']],
                ['别名', '、'.join(p['alias_list'])],
                ['提及', f"{tot[name]} 处 · 见 {seen_ch} 回" if tot.get(name) else ''],
                ['诗作', f"{n_poem[name]} 首" if n_poem.get(name) else ''],
                ['所持器物', '、'.join(owns)], ['相关典故', '、'.join(als)],
                ['关系', f"{deg[name]} 条"]]
        nodes.append(dict(id=f'P:{name}', name=name, group=g,
                          color=GROUP_COLOR.get(g, MUTED),
                          w=tot.get(name, 0) or deg[name] * 3,
                          label=deg[name] >= 4 or tot.get(name, 0) >= 200,
                          info=[x for x in info if x[1]],
                          spark=_spark([[c + 1, v] for c, v in enumerate(per[name]) if v]),
                          nb=[f'P:{r["target"] if r["source"] == name else r["source"]}'
                              for r in rels if name in (r['source'], r['target'])]))
    links = []
    for r in rels:
        if r['source'] not in keep or r['target'] not in keep:
            continue
        rel = r['rel']
        kind = ('血缘' if rel in KIN else '婚姻' if rel in MARR
                else '主仆' if rel in SERV else '情缘' if rel in LOVE
                else '神话' if rel in MYTH else '社会')
        links.append(dict(source=f'P:{r["source"]}', target=f'P:{r["target"]}',
                          rel=rel, kind=kind))
    legend = [dict(c=GROUP_COLOR[g], t=g) for g in
              ['贾府', '史家', '王家', '薛家', '甄家', '林家', '秦家', '尤家',
               '仆役', '方外', '他姓·外戚']]
    return dict(id='relations', name='人物关系网',
                hint='节点大小＝提及热度，颜色＝家族/身份；'


                     '边色：朱＝血缘、金＝婚姻、褐＝主仆、绯＝情缘、蓝＝社会、紫＝神话；箭头自施者指受者。',
                nodes=nodes, links=links, legend=legend, directed=True,
                layout='force')


# ---------------- 视图二：家族·府邸·院落

def view_abode() -> dict:
    persons = _persons()
    texts = _main_text()
    places = db.q('SELECT * FROM places')
    occ = _occur([p['name'] for p in places], texts)
    res = Counter(q['residence'] for q in persons.values()
                  if q['residence'] and q['residence'] not in ('—', '（无固定居所）'))
    nodes = [dict(id=f'F:{f["name"]}', name=f'{f["name"]}家', group='family',
                  color=CINNABAR, w=8, label=True,
                  info=[['源流', f['origin']], ['府邸', f['seat']], ['说明', f['note']]])
             for f in db.q('SELECT * FROM families')]
    pnames = {p['name'] for p in places}
    for pl in places:
        cat = pl['category'] or '地点'
        col = PLACE_COLOR.get(cat, MUTED)
        owners = [n for n, p in persons.items() if p['residence'] == pl['name']]
        nodes.append(dict(id=f'L:{pl["name"]}', name=pl['name'], group=cat, color=col,
                          w=4 + 3 * len(owners), label=bool(owners) or cat in ('园林', '府邸'),
                          info=[['类别', cat], ['所属', pl['belongs']], ['说明', pl['note']],
                                ['居者', '、'.join(owners)]],
                          spark=_spark(occ.get(pl['name'], []), 80),
                          spark_label='正文现身（回）'))
    for name, p in persons.items():
        r = p['residence']
        if not r or r in ('—', '（无固定居所）'):
            continue
        if r not in pnames:
            nodes.append(dict(id=f'L:{r}', name=r, group='地点', color=MUTED, w=3,
                              label=False, info=[['类别', '（本体未单列）'],
                                                 ['居者', '、'.join(
                                                     [n for n, q in persons.items()
                                                      if q['residence'] == r])]],
                              spark=_spark(occ.get(r, []), 80)))
        nodes.append(dict(id=f'P:{name}', name=name, group='居者', color=BRONZE,
                          w=2, label=False,
                          info=[['居所', r], ['身份', p['role']],
                                ['家族', _person_group(p)]],
                          nb=[f'L:{r}']))
    links = []
    for pl in places:
        if pl['belongs']:
            b = pl['belongs'].split('/')[0].strip()
            if b in pnames or b in {f['name'] for f in db.q('SELECT name FROM families')}:
                tgt = f'L:{b}' if b in pnames else f'F:{b}'
                links.append(dict(source=f'L:{pl["name"]}', target=tgt, rel='属',
                                  kind='从属'))
    for f in db.q('SELECT * FROM families'):
        for s in re.split(r'[,，、]', f['seat'] or ''):
            s = s.strip().strip('（）()')
            if s and s in pnames:
                links.append(dict(source=f'F:{f["name"]}', target=f'L:{s}',
                                  rel='府邸', kind='府邸'))
    fams = {f['name'] for f in db.q('SELECT name FROM families')}
    for name, p in persons.items():
        r = p['residence']
        if not r or r in ('—', '（无固定居所）'):
            continue
        links.append(dict(source=f'P:{name}', target=f'L:{r}', rel='居', kind='居所'))
        g = _person_group(p)
        if g in fams:
            links.append(dict(source=f'P:{name}', target=f'F:{g}', rel='族', kind='族属'))
    legend = [dict(c=CINNABAR, t='家族')] + \
             [dict(c=PLACE_COLOR.get(c, MUTED), t=c) for c in
              ['园林', '院落', '建筑', '府邸', '寺庙', '仙境', '山', '城邑']] + \
             [dict(c=BRONZE, t='居者')]
    return dict(id='abode', name='家族·府邸·院落',
                hint='家族（朱）→ 府邸/园林（绿）→ 院落（青）→ 居者（褐）；'
                     '点地点看居者与正文现身回次。',
                nodes=nodes, links=links, legend=legend, layout='force')


# ---------------- 视图三：意象谱

def view_imagery() -> dict:
    texts = _main_text()
    lines = _poem_lines()
    poems = _poems()
    ptitle = {p['id']: (p['title'] or '(无题)') for p in poems}
    pchap = {p['id']: p['chapter'] for p in poems}
    imgs = db.q('SELECT image, category, emotion, context FROM imagery')
    names = [i['image'] for i in imgs]
    occ = _occur(names, texts)
    pi = db.q('SELECT poem_id, image, n FROM poem_images')
    use = Counter()
    by_poet = Counter()
    pair = Counter()
    poet_imgs: dict[str, Counter] = defaultdict(Counter)
    per_poem = defaultdict(set)
    for r in pi:
        if r['image'] in names:
            use[r['image']] += 1
            per_poem[r['poem_id']].add(r['image'])
    author = {p['id']: (p['author'] or '') for p in poems}
    for pid, ims in per_poem.items():
        a = author.get(pid, '')
        if a and not a.startswith('（'):
            for im in ims:
                by_poet[im] += 1
                poet_imgs[a][im] += 1
        for x in sorted(ims):
            for y in sorted(ims):
                if x < y:
                    pair[(x, y)] += 1
    nodes = []
    for i in imgs:
        im = i['image']
        hit = occ.get(im, [])
        samples = []
        for pid, ls in lines.items():
            for ln in ls:
                if im in ln and len(ln) < 40:
                    samples.append(f"{ptitle.get(pid, '')}（第{pchap.get(pid, 0)}回）：{ln}")
                    break
            if len(samples) >= 3:
                break
        nodes.append(dict(id=f'I:{im}', name=im, group=i['category'],
                          color=IMG_COLOR.get(i['category'], MUTED),
                          w=2 + use[im] + min(12, len(hit)),
                          label=use[im] >= 5 or len(hit) >= 8,
                          info=[['类别', i['category']], ['情感指向', i['emotion']],
                                ['语境', i['context']],
                                ['入诗', f'{use[im]} 处'], ['正文现身', f'{len(hit)} 回']],
                          lines=samples,
                          spark=_spark(hit, 80), spark_label='正文现身（回）'))
    poet_rank = sorted(poet_imgs.items(), key=lambda kv: -sum(kv[1].values()))[:16]
    for a, c in poet_rank:
        nodes.append(dict(id=f'A:{a}', name=a, group='诗人', color=INDIGO,
                          w=2 + sum(c.values()) // 2, label=True,
                          info=[['诗人', a], ['入诗意象', '、'.join(k for k, _ in c.most_common(10))],
                                ['诗作', f"{sum(1 for p in poems if p['author'] == a)} 首"]],
                          nb=[f'I:{k}' for k in c]))
    links = []
    for pid, ims in per_poem.items():
        a = author.get(pid, '')
        if a and not a.startswith('（'):
            for im in ims:
                if im in names:
                    links.append(dict(source=f'A:{a}', target=f'I:{im}', rel='入诗',
                                      kind='用'))
    for (x, y), n in pair.most_common(90):
        if n >= 2:
            links.append(dict(source=f'I:{x}', target=f'I:{y}', rel=f'共现×{n}',
                              kind='共现'))
    legend = [dict(c=INDIGO, t='诗人')] + \
             [dict(c=IMG_COLOR[c], t=c) for c in
              ['植物', '天象', '器物', '禽鸟', '地理', '时间', '心理']]
    return dict(id='imagery', name='意象谱',
                hint='意象（按类别上色，大小＝入诗与正文现身之数）—诗人（蓝）二分图；'
                     '绯色细边＝同一首诗词中并见（共现），可看意象组合。',
                nodes=nodes, links=links, legend=legend, layout='force')


# ---------------- 视图四：器物·典故·概念

def view_symbols() -> dict:
    persons = _persons()
    texts = _main_text()
    objs = db.q('SELECT * FROM objects')
    allu = db.q('SELECT * FROM allusions')
    cons = db.q('SELECT * FROM concepts')
    terms = [o['name'] for o in objs] + [c['name'] for c in cons]
    occ = _occur(terms, texts)
    nodes, links = [], []

    def owner_nodes(raw: str, src: str, rel: str):
        for o in re.split(r'[、/，,]|→', raw or ''):
            o = o.strip()
            if not o or o.startswith('（'):
                continue
            tid = f'P:{o}'
            if o in persons:
                p = persons[o]
                if not any(n['id'] == tid for n in nodes):
                    nodes.append(dict(id=tid, name=o, group='人物', color=CINNABAR,
                                      w=4, label=True,
                                      info=[['身份', p['role']], ['居所', p['residence']],
                                            ['探佚结局', p['fate']]]))
            elif not any(n['id'] == tid for n in nodes):
                nodes.append(dict(id=tid, name=o, group='他者', color=MUTED, w=3,
                                  label=True, info=[['说明', '本体未单列，见器物/典故所系']]))
            links.append(dict(source=f'X:{src}', target=tid, rel=rel, kind=rel))

    for o in objs:
        nodes.append(dict(id=f'X:{o["name"]}', name=o['name'], group='器物',
                          color=GOLD, w=4,
                          label=True,
                          info=[['类别', o['category']], ['持有者', o['owner']],
                                ['象征/谶应', o['symbol']],
                                ['正文现身', f"{len(occ.get(o['name'], []))} 回"]],
                          spark=_spark(occ.get(o['name'], []), 80),
                          spark_label='正文现身（回）'))
        owner_nodes(o['owner'], o['name'], '持有')
    for a in allu:
        nodes.append(dict(id=f'D:{a["name"]}', name=a['name'], group='典故',
                          color=PLUM, w=3, label=True,
                          info=[['出处', a['source']], ['红楼用例', a['usage']],
                                ['所涉', a['person']], ['寓意', a['gloss']]]))
        owner_nodes(a['person'], a['name'], '所涉')
    for c in cons:
        hit = occ.get(c['name'], [])
        related = [n for n, p in persons.items()
                   if c['name'] and c['name'] in (p.get('fate', '') + p.get('qingbang', '')
                                                  + p.get('role', ''))]
        nodes.append(dict(id=f'C:{c["name"]}', name=c['name'], group='概念',
                          color=JADE, w=4, label=True,
                          info=[['类别', c['category']], ['释义', c['gloss']],
                                ['系于人', '、'.join(related)],
                                ['正文现身', f'{len(hit)} 回']],
                          spark=_spark(hit, 80), spark_label='正文现身（回）'))
        for n in related:
            links.append(dict(source=f'C:{c["name"]}', target=f'P:{n}', rel='系于',
                              kind='系于'))
    legend = [dict(c=CINNABAR, t='人物'), dict(c=GOLD, t='器物'),
              dict(c=PLUM, t='典故'), dict(c=JADE, t='概念')]
    return dict(id='symbols', name='器物·典故·概念',
                hint='物件（金）→ 持有者，典故（紫）→ 所涉人物，'
                     '概念（青）→ 所系人物；点节点看象征、出处与正文现身回次。',
                nodes=nodes, links=links, legend=legend, layout='force')


# ---------------- 视图五：册籍·判词·探佚

CLUE_KEYS = {
    '狱神庙': ['狱神庙', '慰宝玉', '茜雪'],
    '花袭人有始有终': ['有始有终', '袭人'],
    '卫若兰射圃': ['射圃', '若兰', '麒麟'],
    '悬崖撒手': ['悬崖', '撒手', '出家'],
    '情榜': ['情榜'],
    '甄宝玉送玉': ['送玉', '甄宝玉'],
    '讽谏': ['讽谏', '借词'],
    '知命强英雄': ['知命', '强英雄', '被休'],
    '对景悼颦儿': ['悼颦', '对景'],
    '薛宝钗借词含讽谏': ['讽谏', '借词'],
    '金玉良缘': ['金玉', '良缘'],
    '黛玉之死': ['泪尽', '夭亡'],
}


def _keys_of(clue: str) -> list[str]:
    ks = [k for k, vs in CLUE_KEYS.items() if k in clue]
    out = []
    for k in ks:
        out += CLUE_KEYS[k]
    out += [t for t in re.split(r'[\s、，,（）()]', clue) if len(t) >= 2]
    seen, res = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            res.append(t)
    return res


def view_fate() -> dict:
    persons = _persons()
    per, tot = _mentions()
    poems = _poems()
    clues = db.q('SELECT * FROM lost_clues')
    doc = _outline()
    rows = doc.get('chapters', [])
    conts = db.q('SELECT chapter, text, title FROM continuations')
    nodes, links = [], []
    reg_color = {'正册': CINNABAR, '副册': GOLD, '又副册': BRONZE,
                 '情榜之首': PLUM, '—': MUTED, '': MUTED}
    regd = [p for p in persons.values()
            if (p['registry'] or '') not in ('', '—') or (p['fate'] or '') not in ('', '—')]
    for p in regd:
        reg = p['registry'] or '—'
        nodes.append(dict(id=f'P:{p["name"]}', name=p['name'], group=reg or '未入册',
                          color=reg_color.get(reg, MUTED),
                          w=4 + tot.get(p['name'], 0) // 60,
                          label=True,
                          info=[['册籍', reg], ['情榜', p['qingbang']],
                                ['身份', p['role']], ['探佚结局', p['fate']],
                                ['别名', '、'.join(p['alias_list'])],
                                ['提及', f"{tot.get(p['name'], 0)} 处"]],
                          spark=_spark([[c + 1, v] for c, v in enumerate(per[p['name']]) if v])))
    # 判词 / 曲 / 花签
    for pm in poems:
        if pm['genre'] not in ('判词', '曲', '花签', '词/曲') or pm['chapter'] > 80:
            continue
        txt = (pm['text'] or '')[:120]
        who = [nm for nm in persons
               if nm in (pm['text'] or '') or nm in (pm['title'] or '')]
        nodes.append(dict(id=f'J:{pm["id"]}', name=(pm['title'] or pm['genre'])[:12],
                          group=pm['genre'], color=INDIGO, w=3, label=False,
                          info=[['体裁', pm['genre']], ['回次', f"第{pm['chapter']}回"],
                                ['正文', txt], ['所咏', '、'.join(who)]],
                          nb=[f'P:{w}' for w in who]))
        for w in who:
            links.append(dict(source=f'J:{pm["id"]}', target=f'P:{w}',
                              rel='判词', kind='判词'))
    # 脂批线索 → 骨架回次 / 续写落地 / 人物
    for cl in clues:
        keys = _keys_of(cl['clue'])
        landed = sorted({c['chapter'] for c in conts
                         if any(k in (c['text'] or '')[:4000] for k in keys)})
        planned = [r for r in rows
                   if any(k in (r['title'] + r['brief']) for k in keys)]
        who = [nm for nm in persons
               if nm in (cl['clue'] or '') + (cl['meaning'] or '')]
        nodes.append(dict(id=f'K:{cl["id"]}', name=cl['clue'][:14], group='脂批线索',
                          color=ROSE, w=5, label=True,
                          info=[['线索', cl['clue']], ['出处', cl['source']],
                                ['含义', cl['meaning']],
                                ['骨架安排', '、'.join(f"第{r['chapter']}回{r['title']}" for r in planned) or '未见于骨架回目'],
                                ['续写落地', '、'.join(f'第{c}回' for c in landed) or '尚未落到正文'],
                                ['关键词', '、'.join(keys[:8])],
                                ['所涉人物', '、'.join(who)]],
                          nb=[f'P:{w}' for w in who] + [f'C{r["chapter"]}' for r in planned]))
        for r in planned:
            links.append(dict(source=f'K:{cl["id"]}', target=f'C{r["chapter"]}',
                              rel='骨架', kind='骨架安排'))
        for w in who:
            links.append(dict(source=f'K:{cl["id"]}', target=f'P:{w}',
                              rel='所涉', kind='所涉'))
        for c in landed:
            links.append(dict(source=f'K:{cl["id"]}', target=f'W{c}',
                              rel='落地', kind='续写落地'))
    for r in rows:
        nodes.append(dict(id=f'C{r["chapter"]}', name=f"第{r['chapter']}回 {r['title'][:10]}",
                          group='骨架回次', color=MUTED, w=3, label=False,
                          info=[['回次', f"第{r['chapter']}回"], ['回目', r['title']],
                                ['要点', r['brief']]]))
    for c in conts:
        nodes.append(dict(id=f'W{c["chapter"]}', name=f"续第{c['chapter']}回",
                          group='续写', color=JADE, w=3, label=False,
                          info=[['回次', f"第{c['chapter']}回"], ['回目', c['title']],
                                ['已成稿', '是']]))
    legend = [dict(c=CINNABAR, t='正册'), dict(c=GOLD, t='副册'),
              dict(c=BRONZE, t='又副册'), dict(c=PLUM, t='情榜之首'),
              dict(c=INDIGO, t='判词/曲/花签'), dict(c=ROSE, t='脂批线索'),
              dict(c=MUTED, t='骨架回次'), dict(c=JADE, t='续写落地')]
    return dict(id='fate', name='册籍·判词·探佚',
                hint='太虚幻境册籍与判词/曲（蓝）连其所咏之人；'
                     '脂批线索（绯）再连骨架回次（灰）与续写落地（青）——'
                     '可见哪一条佚文已落笔、哪一条仍悬。',
                nodes=nodes, links=links, legend=legend, layout='force')


# ---------------- 视图六：时序长卷

def view_timeline() -> dict:
    doc = _outline()
    rows = {r['chapter']: r for r in doc.get('chapters', [])}
    chs = {c['chapter']: c for c in
           db.q('SELECT chapter, title, n_main, n_anno FROM chapters WHERE chapter > 0')}
    conts = {c['chapter']: c for c in db.q('SELECT chapter, title FROM continuations')}
    fests = db.q('SELECT * FROM festivals ORDER BY id')
    events = _timeline_events()
    nodes, links = [], []
    lanes = {}
    for c in range(1, 111):
        if c <= 80 and c not in chs:
            continue
        post = c > 80
        n_anno = chs[c]['n_anno'] if c in chs else 0
        title = chs[c]['title'] if c in chs else rows.get(c, {}).get('title', '')
        info = [['回次', f'第{c}回'], ['回目', title],
                ['正文块', str(chs[c]['n_main']) if c in chs else '（后三十回，未有脂本正文）'],
                ['批语', str(n_anno) if c in chs else '—'],
                ['所属', '脂本前八十回' if not post else '推演后三十回']]
        if c in rows:
            info.append(['骨架要点', rows[c]['brief']])
        if c in conts:
            info.append(['续写', f"已成稿：{conts[c]['title']}（见续写页）"])
        nodes.append(dict(id=f'C{c}', name=f'第{c}回', group='前八十回' if not post else '后三十回',
                          color=MUTED if not post else CINNABAR,
                          w=3 + (n_anno or 0) / 3,
                          label=c in (1, 5, 13, 23, 27, 33, 63, 74, 80, 81, 90, 98, 105, 110),
                          x=c, lane=1, info=info,
                          spark=None))
    for i, f in enumerate(fests):
        nums = [int(x) for x in re.findall(r'\d+', f['chapter'] or '')]
        nid = f'F{i}'
        nodes.append(dict(id=nid, name=f['solar_term'], group='节令', color=MOSS,
                          w=4, label=True, x=(nums[0] if nums else 1 + i * 5),
                          info=[['节令', f['solar_term']], ['回次', f['chapter']],
                                ['事件', f['event']]]))
        for n in nums:
            if 1 <= n <= 110:
                links.append(dict(source=nid, target=f'C{n}', rel=f['solar_term'],
                                  kind='节令'))
    slot: Counter = Counter()
    for i, ev in enumerate(events):
        g = _bigrams(ev)
        hit, score = 0, 0
        for c in range(81, 111):
            if c in rows:
                r = rows[c]
                s = len(g & _bigrams(r['title'] + r['brief']))
                if s > score:
                    hit, score = c, s
        nid = f'E{i}'
        xpos = (hit + (slot[hit] * 1.8) - 1.8) if hit else 82 + i * 2
        if hit:
            slot[hit] += 1
        nodes.append(dict(id=nid, name=ev, group='推演时序', color=PLUM, w=5, label=True,
                          x=round(xpos, 1), dy=(-20 if i % 2 else 16),
                          info=[['推演大事', ev],
                                ['对应回次', f'第{hit}回' if hit else '未定'],
                                ['依据', '脂批（后三十回）+ 判词曲子推得']]))
        if hit:
            links.append(dict(source=nid, target=f'C{hit}', rel='大事', kind='大事'))
    legend = [dict(c=MUTED, t='前八十回'), dict(c=CINNABAR, t='推演后三十回'),
              dict(c=MOSS, t='节令'), dict(c=PLUM, t='推演大事')]
    return dict(id='timeline', name='时序长卷',
                hint='横轴＝回次（1—110）：前八十回（灰）依脂本实有批语多少定大小，'
                     '后三十回（朱）为推演骨架；节令（绿）与推演大事（紫）各系于其回。',
                nodes=nodes, links=links, legend=legend, layout='timeline')


# ---------------- 视图七：推演脉络

AGENT_COLOR = {
    '曹雪芹': CINNABAR, '脂砚斋': CINNABAR_L, '畸笏叟': ROSE,
    '周汝昌': INDIGO, '俞平伯': JADE, '蔡元培': MOSS, '张爱玲': PLUM,
    '数据科学家': CLAY, '文体计量学家': BRONZE, '知识图谱工程师': GOLD,
    '主持人': ASH,
}
AGENT_GROUP = {
    '曹雪芹': '古典组', '脂砚斋': '古典组', '畸笏叟': '古典组',
    '周汝昌': '红学组', '俞平伯': '红学组', '蔡元培': '红学组', '张爱玲': '红学组',
    '数据科学家': '技术组', '文体计量学家': '技术组', '知识图谱工程师': '技术组',
    '主持人': '主持',
}


def view_debate() -> dict:
    claims = db.q('SELECT * FROM claims ORDER BY topic, agent')
    nodes, links = [], []
    topics = sorted({c['topic'] for c in claims})
    for i, t in enumerate(topics):
        stances = [c for c in claims if c['topic'] == t]
        nodes.append(dict(id=f'T{i}', name=t, group='议题', color=INDIGO, w=6, label=True,
                          info=[['议题', t], ['发言', f'{len(stances)} 条'],
                                ['与会', '、'.join(sorted({s["agent"] for s in stances}))]],
                          nb=[f'C{j}' for j, s in enumerate(claims) if s['topic'] == t]))
    for j, c in enumerate(claims):
        g = c['agent'] or ''
        nodes.append(dict(id=f'C{j}', name=g, group=AGENT_GROUP.get(g, '其他'),
                          color=AGENT_COLOR.get(g, MUTED),
                          w=1.5 + float(c['confidence'] or 0) * 4, label=False,
                          info=[['Agent', g], ['立场', c['stance'] or '—'],
                                ['置信度', f"{c['confidence']}"],
                                ['论证', (c['content'] or '')[:900]],
                                ['证据', (c['evidence'] or '')[:600]]]))
        links.append(dict(source=f'T{i}', target=f'C{j}', rel='立论', kind='立论'))
    first: dict[str, str] = {}
    for j, c in enumerate(claims):
        first.setdefault(c['agent'] or '', f'C{j}')
    for g, nid in first.items():
        nodes.append(dict(id=f'G:{g}', name=g, group=AGENT_GROUP.get(g, '其他'),
                          color=AGENT_COLOR.get(g, MUTED), w=6, label=True,
                          info=[['Agent', g], ['组别', AGENT_GROUP.get(g, '其他')],
                                ['发言', f"{sum(1 for c in claims if c['agent'] == g)} 条"],
                                ['立场概要', '；'.join(
                                    (c['stance'] or '')[:24] for c in claims
                                    if c['agent'] == g)[:300]]],
                          nb=[f'C{j}' for j, c in enumerate(claims) if c['agent'] == g]))
    for j, c in enumerate(claims):
        links.append(dict(source=f'G:{c["agent"]}', target=f'C{j}', rel='发言', kind='发言'))
    legend = [dict(c=CINNABAR, t='古典组'), dict(c=INDIGO, t='红学组·议题'),
              dict(c=CLAY, t='技术组'), dict(c=ASH, t='主持')]
    return dict(id='debate', name='推演脉络',
                hint='议题（蓝）—各 Agent（按组别染色）—立论（点大小＝置信度）。'
                     '点立论看其论证、证据与置信度，可复核技术组的统计取证。',
                nodes=nodes, links=links, legend=legend, layout='force')


# ---------------- 图例 / 节点落色

VIEW_ORDER = ['relations', 'abode', 'imagery', 'symbols', 'fate', 'timeline', 'debate']
BUILDERS = {
    'relations': view_relations, 'abode': view_abode, 'imagery': view_imagery,
    'symbols': view_symbols, 'fate': view_fate, 'timeline': view_timeline,
    'debate': view_debate,
}


def build(dst: Path | None = None) -> dict:
    """构建全部视图并写入 docs/data/graph.json。"""
    views = []
    for vid in VIEW_ORDER:
        v = BUILDERS[vid]()
        ids = {n['id'] for n in v['nodes']}
        v['links'] = [l for l in v['links']
                      if l['source'] in ids and l['target'] in ids
                      and l['source'] != l['target']]
        views.append(v)
    doc = dict(views=views)
    out = (dst or (paths.SITE_DIR / 'data'))
    out.mkdir(parents=True, exist_ok=True)
    (out / 'graph.json').write_text(
        json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    return {v['id']: dict(nodes=len(v['nodes']), links=len(v['links'])) for v in views}


BODY = """
<h2>本体图谱</h2>
<div class="card small">
七重视图，皆从本体论各表织出：<b>人物关系网</b>（129 条关系，分血缘·婚姻·主仆·情缘·社会·神话）、
<b>家族·府邸·院落</b>（5 家族 · 46 地点 · 居者）、<b>意象谱</b>（49 类意象 × 诗人 × 同诗共现）、
<b>器物·典故·概念</b>（24 物件 · 27 典故）、<b>册籍·判词·探佚</b>（判词曲子 × 脂批线索 × 骨架回次 × 续写落地）、
<b>时序长卷</b>（1—110 回节令与推演大事）、<b>推演脉络</b>（113 条立论，按置信度大小）。
拖拽节点、滚轮缩放、点选节点即见其本体记录与逐回分布；右栏「关联」可一路点下去。
</div>
<div id="tabs" class="tabs"></div>
<div class="gwrap">
  <div class="card gcanvas">
    <div class="gtools">检索 <input id="q" placeholder="人名 / 意象 / 典故 / 回次…">
      <button id="relayout">重排</button><button id="reset">复位</button>
      <span class="gstat" id="gstat"></span></div>
    <svg id="svg" viewBox="0 0 1040 660" preserveAspectRatio="xMidYMid meet"
         xmlns="http://www.w3.org/2000/svg"></svg>
  </div>
  <aside class="card gside" id="side"></aside>
</div>
"""

JS = r"""
const KIND_C={血缘:'#9e2b25',婚姻:'#b08d57',主仆:'#b0703c',情缘:'#c2504a',
社会:'#3b4a6b',神话:'#7a5c8a',从属:'#8a7f6d',府邸:'#9e2b25',居所:'#3f6b5e',
族:'#b08d57',用:'#8a7f6d',共现:'#c2504a',持有:'#b08d57',所涉:'#7a5c8a',
系于:'#3f6b5e',判词:'#3b4a6b',骨架安排:'#9e2b25',续写落地:'#3f6b5e',
节令:'#5c8a6a',大事:'#7a5c8a',立论:'#3b4a6b',发言:'#b0703c'};
const W=1040,H=660;
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const svgEl=$('svg');
let V=[],cur=0,nodes=[],links=[],idx={},pos=[],vel=[],fx={},K={k:1,x:0,y:0},
    sel=null,q='',alpha=1,raf=0,frame=0,dragNode=null,panning=null,regions=[],
    hover=null,qFocus=null;

fetch('data/graph.json').then(r=>r.json()).then(d=>{
  V=d.views;
  const t=$('tabs');
  V.forEach((v,i)=>{const b=document.createElement('button');
    b.textContent=v.name;b.onclick=()=>load(i);t.appendChild(b);});
  load(0);
});

function load(i){
  cur=i;sel=null;hover=null;qFocus=null;q='';$('q').value='';
  document.querySelectorAll('#tabs button').forEach((b,j)=>b.className=(j===i?'on':''));
  const v=V[i];
  nodes=v.nodes.map(n=>Object.assign({},n));
  const ids=new Set(nodes.map(n=>n.id));
  links=v.links.filter(l=>ids.has(l.source)&&ids.has(l.target));
  idx={};nodes.forEach((n,j)=>idx[n.id]=j);
  const wmax=Math.max(1,...nodes.map(n=>n.w||1));
  nodes.forEach(n=>{n.r=3.4+7.4*Math.sqrt((n.w||1)/wmax);});
  K={k:1,x:0,y:0};
  layout(v);
  $('gstat').textContent=nodes.length+' 节点 · '+links.length+' 边';
  intro();
  simulate(v.layout!=='timeline');
}

function layout(v){
  fx={};regions=[];
  if(v.layout==='timeline'){
    const lanes=[['推演时序',H*0.10],['节令',H*0.30],['后三十回',H*0.60],
                 ['前八十回',H*0.78]];
    pos=nodes.map(n=>{
      const x=36+((n.x||1)-1)/109*(W-72);
      let y=H*0.78;
      for(const g of lanes){if(n.group===g[0])y=g[1];}
      y+=(n.dy||0);
      fx[n.id]=true;n.ax=x;n.ay=y;
      return {x:x,y:y+(Math.random()-.5)*8};
    });
    const half={'推演时序':46,'节令':32};
    regions=lanes.map(g=>({name:g[0],x0:14,y0:g[1]-(half[g[0]]||26),
      x1:W-14,y1:g[1]+(half[g[0]]||26),
      color:(nodes.find(n=>n.group===g[0])||{}).color||'#8a7f6d'}));
    vel=nodes.map(()=>({x:0,y:0}));
    return;
  }
  // 分区：按族群做「平方根马赛克」分块（行高列宽皆取 √size，形状匀称），区内再作力导向
  const groups={};
  nodes.forEach(n=>{(groups[n.group]=groups[n.group]||[]).push(n);});
  const list=Object.entries(groups).sort((a,b)=>b[1].length-a[1].length);
  mosaic(list,16,16,W-16,H-16);
  pos=nodes.map(n=>{
    const b=n.bx;
    return {x:b.x0+18+Math.random()*Math.max(8,b.x1-b.x0-36),
            y:b.y0+24+Math.random()*Math.max(8,b.y1-b.y0-40)};
  });
  vel=nodes.map(()=>({x:0,y:0}));
}

function mosaic(list,x0,y0,x1,y1){
  if(!list.length)return;
  if(list.length===1){assignBox(list[0][1],list[0][0],{x0:x0,y0:y0,x1:x1,y1:y1});return;}
  const wt=g=>Math.sqrt(g[1].length);
  const rows=Math.max(1,Math.round(Math.sqrt(list.length)));
  const buckets=Array.from({length:rows},()=>[]);
  const sums=new Array(rows).fill(0);
  list.forEach(g=>{let k=0;for(let i=1;i<rows;i++)if(sums[i]<sums[k]-1e-9)k=i;
    buckets[k].push(g);sums[k]+=wt(g);});
  const tsum=sums.reduce((a,b)=>a+b,0)||1;
  let y=y0;
  buckets.forEach((row,ri)=>{
    if(!row.length)return;
    const h=(y1-y0)*sums[ri]/tsum;
    let x=x0;
    const rsum=row.reduce((a,g)=>a+wt(g),0)||1;
    row.forEach(g=>{
      const w=(x1-x0)*wt(g)/rsum;
      assignBox(g[1],g[0],{x0:x,y0:y,x1:x+w,y1:y+h});
      x+=w;});
    y+=h;});
}

function assignBox(g,name,R){
  const col=(g[0]||{}).color||'#8a7f6d';
  const w=Math.max(30,R.x1-R.x0),h=Math.max(30,R.y1-R.y0);
  const reg={name:name,x0:R.x0,y0:R.y0,x1:R.x1,y1:R.y1,color:col,n:g.length,
    cap:Math.max(3,Math.round(w*h/(h<70?11000:6200)))};
  regions.push(reg);
  g.forEach(n=>{n.bx=R;n.reg=reg;n.ax=(R.x0+R.x1)/2;n.ay=(R.y0+R.y1)/2;
    n.rest=Math.max(24,Math.min(78,Math.sqrt(w*h)/7));});
}

function simulate(on){
  cancelAnimationFrame(raf);alpha=1;frame=0;
  if(!on){draw();return;}
  const lim=nodes.length>150?260:420;
  const tick=()=>{
    frame++;
    const k=Math.max(0.04,alpha);
    for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){
      let dx=pos[j].x-pos[i].x,dy=pos[j].y-pos[i].y;
      let d2=dx*dx+dy*dy;if(d2<1)d2=1;
      const d=Math.sqrt(d2);
      const rep=(320+80*(nodes[i].r+nodes[j].r))/d2*3.2*k;
      const ux=dx/d*rep,uy=dy/d*rep;
      vel[i].x-=ux;vel[i].y-=uy;vel[j].x+=ux;vel[j].y+=uy;
    }
    links.forEach(l=>{
      const a=idx[l.source],b=idx[l.target];if(a==null||b==null)return;
      const share=(l.kind==='共现'?0.45:1);
      const same=nodes[a].bx&&nodes[b].bx&&nodes[a].bx===nodes[b].bx;
      const base=same?Math.min(nodes[a].rest||70,nodes[b].rest||70)
                     :Math.min(150,Math.max(nodes[a].rest||70,nodes[b].rest||70)+50);
      const w=(l.kind==='共现'?base*1.25:base)+(nodes[a].r+nodes[b].r)*1.6;
      const dx=pos[b].x-pos[a].x,dy=pos[b].y-pos[a].y;
      const d=Math.sqrt(dx*dx+dy*dy)||1;
      const f=(d-w)*(same?0.05:0.005)*share*k;
      vel[a].x+=f*dx/d;vel[a].y+=f*dy/d;vel[b].x-=f*dx/d;vel[b].y-=f*dy/d;
    });
    nodes.forEach((n,i)=>{
      if(fx[n.id])return;
      const p=pos[i],u=vel[i];
      u.x+=(n.ax-p.x)*0.014*k;u.y+=(n.ay-p.y)*0.016*k;
      u.x*=0.72;u.y*=0.72;
      p.x+=Math.max(-9,Math.min(9,u.x));
      p.y+=Math.max(-9,Math.min(9,u.y));
      if(n.bx){
        p.x=Math.max(n.bx.x0+n.r+3,Math.min(n.bx.x1-n.r-3,p.x));
        p.y=Math.max(n.bx.y0+16+n.r,Math.min(n.bx.y1-n.r-3,p.y));
      }else{
        p.x=Math.max(14,Math.min(W-14,p.x));p.y=Math.max(14,Math.min(H-14,p.y));
      }
    });
    draw();alpha*=0.985;
    if(frame<lim)raf=requestAnimationFrame(tick);else raf=0;
  };
  raf=requestAnimationFrame(tick);
}

function draw(){
  const v=V[cur],nb=new Set();
  if(sel)links.forEach(l=>{if(l.source===sel)nb.add(l.target);if(l.target===sel)nb.add(l.source);});
  const ql=q.trim(),hit=n=>!ql||n.name.includes(ql);
  let s='<defs><marker id="arw" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6"'
    +' markerHeight="6" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#9e2b25"'
    +' opacity=".5"/></marker></defs><g transform="translate('+K.x.toFixed(1)+','
    +K.y.toFixed(1)+') scale('+K.k.toFixed(3)+')">';
  regions.forEach(r=>{
    s+='<rect x="'+r.x0.toFixed(1)+'" y="'+r.y0.toFixed(1)+'" width="'
      +(r.x1-r.x0).toFixed(1)+'" height="'+(r.y1-r.y0).toFixed(1)
      +'" rx="4" fill="'+r.color+'" fill-opacity="0.05" stroke="'+r.color
      +'" stroke-opacity="0.38" stroke-width="0.9"/>'
      +'<rect x="'+(r.x0+4).toFixed(1)+'" y="'+(r.y0+3).toFixed(1)+'" width="'
      +(r.name.length*11.5+(r.n?30:12)).toFixed(1)+'" height="15" rx="7" fill="'
      +r.color+'" fill-opacity="0.14"/>'
      +'<text x="'+(r.x0+11).toFixed(1)+'" y="'+(r.y0+14).toFixed(1)
      +'" font-size="11" fill="'+r.color+'" fill-opacity="0.95">'
      +esc(r.name)+(r.n?'　'+r.n:'')+'</text>';
  });
  links.forEach(l=>{
    const a=pos[idx[l.source]],b=pos[idx[l.target]];if(!a||!b)return;
    const touch=sel&&(l.source===sel||l.target===sel);
    const op=sel?(touch?0.95:0.09):0.40;
    const c=KIND_C[l.kind]||'#b9ad98';
    s+='<line x1="'+a.x.toFixed(1)+'" y1="'+a.y.toFixed(1)+'" x2="'+b.x.toFixed(1)
      +'" y2="'+b.y.toFixed(1)+'" stroke="'+c+'" stroke-opacity="'+op
      +'" stroke-width="'+(touch?1.4:0.75)+'"'
      +(v.directed?' marker-end="url(#arw)"':'')+'/>';
  });
  const placed=[];
  const hitBox=(x,y,w,h)=>{
    for(const b of placed){if(x<b.x2&&x+w>b.x1&&y<b.y2&&y+h>b.y1)return true;}
    return false;};
  const order=[...nodes.keys()].sort((i,j)=>nodes[j].r-nodes[i].r);
  order.forEach(i=>{
    const n=nodes[i],p=pos[i];
    const dim=(ql&&!hit(n))?0.12:((sel&&n.id!==sel&&!nb.has(n.id))?0.25:1);
    s+='<circle data-id="'+n.id+'" cx="'+p.x.toFixed(1)+'" cy="'+p.y.toFixed(1)
      +'" r="'+n.r.toFixed(1)+'" fill="'+(n.color||'#8a7f6d')+'" fill-opacity="'
      +(0.85*dim).toFixed(2)+'" stroke="#fffdf7" stroke-width="0.9"/>';
    if(n.id===sel)s+='<circle cx="'+p.x.toFixed(1)+'" cy="'+p.y.toFixed(1)+'" r="'
      +(n.r+4.5).toFixed(1)+'" fill="none" stroke="#9e2b25" stroke-width="1.3"/>';
    else if(n.id===hover||(ql&&hit(n)&&ql))s+='<circle cx="'+p.x.toFixed(1)+'" cy="'
      +p.y.toFixed(1)+'" r="'+(n.r+3.5).toFixed(1)
      +'" fill="none" stroke="#b08d57" stroke-width="1"/>';
  });
  const used=new Map();
  order.forEach(i=>{
    const n=nodes[i],p=pos[i];
    if(dimOf(n)<0.5&&n.id!==sel)return;
    const force=n.id===sel||n.id===hover||n.id===qFocus;
    if(!(n.label||force))return;
    if(n.reg){
      const c=used.get(n.reg)||0;
      if(!force&&c>=(n.reg.cap||99))return;
      used.set(n.reg,c+1);
    }
    const w=n.name.length*12+4,h=14;
    const cand=[[p.x-w/2,p.y-n.r-h+2,p.x,p.y-n.r-4,'middle'],
                [p.x-w/2,p.y+n.r+2,p.x,p.y+n.r+11,'middle'],
                [p.x+n.r+3,p.y-h/2,p.x+n.r+3,p.y+4,'start'],
                [p.x-n.r-3-w,p.y-h/2,p.x-n.r-3,p.y+4,'end']];
    let pick=null;
    for(const c of cand){
      if(!hitBox(c[0],c[1],w,h)&&c[0]>2&&c[0]+w<W-2&&c[1]>2&&c[1]<H-2){pick=c;break;}
    }
    if(!pick){if(!force)return;pick=cand[0];}
    placed.push({x1:pick[0],x2:pick[0]+w,y1:pick[1],y2:pick[1]+h});
    s+='<text x="'+pick[2].toFixed(1)+'" y="'+pick[3].toFixed(1)
      +'" font-size="12" text-anchor="'+pick[4]+'" fill="#3f3830" fill-opacity="'
      +Math.max(0.35,dimOf(n))+'" style="paint-order:stroke;stroke:#fffdf7;'
      +'stroke-width:2.6px">'+esc(n.name)+'</text>';
  });
  svgEl.innerHTML=s+'</g>';
}

function dimOf(n){
  const ql=q.trim();
  if(ql&&!n.name.includes(ql))return 0.12;
  if(sel&&n.id!==sel&&!nbHas(sel,n.id))return 0.25;
  return 1;
}
function nbHas(id,other){
  for(const l of links){
    if(l.source===id&&l.target===other)return true;
    if(l.target===id&&l.source===other)return true;}
  return false;
}

function nodeName(id){const j=idx[id];return j==null?id:(nodes[j].name||id);}

function intro(){
  const v=V[cur];
  const tops=[...nodes].sort((a,b)=>(b.w||0)-(a.w||0)).slice(0,16);
  $('side').innerHTML='<h3>'+esc(v.name)+'</h3><div class="small">'+v.hint+'</div>'
    +'<div class="legend">'+v.legend.map(l=>'<span><i style="background:'+l.c
      +'"></i>'+esc(l.t)+'</span>').join('')+'</div>'
    +'<div class="small" style="margin-top:8px">要目（按分量）</div><div>'
    +tops.map(n=>'<span class="nb" data-go="'+n.id+'">'+esc(n.name)+'</span>').join('')
    +'</div>';
  bindGo();
}

function sparkSvg(n){
  const s=n.spark,upto=s.n||80,cw=Math.max(0.9,(252/upto)-0.45);
  let bars='';
  s.p.forEach(p=>{const hh=Math.max(1.5,24*Math.sqrt(p[1]/s.m));
    bars+='<rect x="'+((p[0]-1)*252/upto).toFixed(1)+'" y="'+(26-hh).toFixed(1)
      +'" width="'+cw.toFixed(2)+'" height="'+hh.toFixed(1)+'" fill="#9e2b25" opacity=".5"/>';});
  let ticks='';
  const step=upto>80?20:10;
  for(let c=1;c<=upto;c+=step)ticks+='<text x="'+((c-1)*252/upto).toFixed(1)
    +'" y="39" font-size="8.5" fill="#8a7f6d">'+c+'</text>';
  return '<div class="small" style="margin-top:9px">'+esc(n.spark_label||'逐回分布')
    +'</div><svg viewBox="0 0 252 42" style="width:100%;height:54px">'+bars
    +'<line x1="0" y1="26" x2="252" y2="26" stroke="#e3d9c4"/>'+ticks+'</svg>';
}

function show(id){
  const j=idx[id];if(j==null)return;
  sel=id;
  const n=nodes[j],ns=[];
  links.forEach(l=>{if(l.source===id)ns.push(l.target);if(l.target===id)ns.push(l.source);});
  const uniq=[...new Set(ns)];
  let h='<h3>'+esc(n.name)+'</h3><div class="small">'+esc(n.group)
    +' · 直连 '+uniq.length+' 处</div><table class="kv">'
    +(n.info||[]).map(r=>'<tr><td>'+esc(r[0])+'</td><td>'+esc(r[1])+'</td></tr>').join('')
    +'</table>';
  if(n.spark)h+=sparkSvg(n);
  if(n.lines&&n.lines.length)h+='<div class="samples">'
    +n.lines.map(x=>'<div>'+esc(x)+'</div>').join('')+'</div>';
  if(uniq.length)h+='<div class="small" style="margin-top:10px">关联</div><div>'
    +uniq.slice(0,48).map(u=>'<span class="nb" data-go="'+u+'">'+esc(nodeName(u))
      +'</span>').join('')+'</div>';
  $('side').innerHTML=h;
  bindGo();draw();
}

function bindGo(){
  document.querySelectorAll('.nb[data-go]').forEach(e=>{
    e.onclick=()=>{const id=e.getAttribute('data-go');
      if(idx[id]==null)return;show(id);center(id);};});
}

function center(id){
  const p=pos[idx[id]];if(!p)return;
  const k=Math.max(K.k,0.95);
  K.k=k;K.x=W/2-p.x*k;K.y=H/2-p.y*k;draw();
}

function toGraph(e){
  const r=svgEl.getBoundingClientRect();
  const x=(e.clientX-r.left)/r.width*W,y=(e.clientY-r.top)/r.height*H;
  return {x:(x-K.x)/K.k,y:(y-K.y)/K.k};
}

svgEl.addEventListener('mousedown',e=>{
  const id=e.target.getAttribute&&e.target.getAttribute('data-id');
  if(id){dragNode=id;return;}
  panning={x:e.clientX,y:e.clientY,kx:K.x,ky:K.y};
});
window.addEventListener('mousemove',e=>{
  if(dragNode){const j=idx[dragNode];if(j==null)return;
    const g=toGraph(e);pos[j].x=g.x;pos[j].y=g.y;fx[dragNode]=true;draw();return;}
  if(panning){const r=svgEl.getBoundingClientRect();
    K.x=panning.kx+(e.clientX-panning.x)/r.width*W;
    K.y=panning.ky+(e.clientY-panning.y)/r.height*H;draw();return;}
  const id=e.target.getAttribute&&e.target.getAttribute('data-id');
  if(id!==hover){hover=id||null;draw();}
});
window.addEventListener('mouseup',()=>{
  if(dragNode){const j=idx[dragNode];if(j!=null&&pos[j])vel[j]={x:0,y:0};dragNode=null;}
  panning=null;
});
svgEl.addEventListener('click',e=>{
  const id=e.target.getAttribute&&e.target.getAttribute('data-id');
  if(id)show(id);else{sel=null;intro();draw();}
});
svgEl.addEventListener('wheel',e=>{
  e.preventDefault();
  const r=svgEl.getBoundingClientRect();
  const mx=(e.clientX-r.left)/r.width*W,my=(e.clientY-r.top)/r.height*H;
  const k2=Math.max(0.35,Math.min(4,K.k*(e.deltaY<0?1.12:0.9)));
  K.x=mx-(mx-K.x)*k2/K.k;K.y=my-(my-K.y)*k2/K.k;K.k=k2;draw();
},{passive:false});
$('q').addEventListener('input',e=>{
  q=e.target.value.trim();
  const all=q?nodes.filter(n=>n.name.includes(q)):[];
  qFocus=all.length?all[0].id:null;
  draw();
  if(!q)return;
  const hits=all.slice(0,30);
  $('side').innerHTML='<h3>检索「'+esc(q)+'」</h3><div class="small">命中 '
    +hits.length+' 个节点，点选定位</div><div>'
    +hits.map(n=>'<span class="nb" data-go="'+n.id+'">'+esc(n.name)+'</span>').join('')
    +'</div>';
  bindGo();
});
$('relayout').onclick=()=>{const v=V[cur];layout(v);simulate(v.layout!=='timeline');};
$('reset').onclick=()=>{K={k:1,x:0,y:0};draw();};
"""


if __name__ == '__main__':
    import pprint
    pprint.pprint(build())
