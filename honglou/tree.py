"""家族谱系：把 relations 的一百二十九条边铺成四卷世系树。

relations 的写法是「甲 · 关系 · 乙」，有两类读法须甄别：
  一、甲 是 乙的 XX      —— 母、父、祖母、继母女、主仆、携、司
  二、甲 乙 为 XX        —— 母子、母女、父子、兄弟、夫妇、妯娌

本模块先判为五类：
  直系（铺树的骨）   —— 母、父、母子、母女、父女、继母女
  配偶（合成一房）   —— 夫、夫妇、娶、婚约
  房内（挂于名下）   —— 妾（依性别定主妾）
  侍婢（挂于名下）   —— 主仆，以微字列于牌位之下
  旁系（虚线牵连）   —— 祖母、祖孙、外祖孙、兄妹、表姐妹、姑侄、叔侄、
                        侄孙女、妯娌、兄弟、友、知己、情、情缘、害、恩、师友…

一房之内，主位取有血统者（父母俱录者）或其夫/妻；配偶附第二行，妾与侍附微字行。
同一人若父母俱在，依「父系优先」只挂一位名下，另一位改作虚线，免枝干交错。
凡由他处补入者（早夭的贾珠、巧姐之父母），作虚框「推得」，并写明凭据。

产物：docs/data/tree.json
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from . import db, paths

# ---------- 语义表 ----------
DIRECT = {'母', '父'}                       # 甲为乙之父母
DIRECT_PAIR = {'母子', '母女', '父女', '父子'}   # 须据性别或长幼字号定尊卑
STEP = {'继母女'}
ANCESTOR = {'祖母', '祖孙', '外祖孙'}         # 隔代：只作虚线，不入骨
SPOUSE = {'夫', '夫妇', '娶', '婚约'}
HOME = {'妾'}
MAID = {'主仆'}
ELDER_MARK = ('姨妈', '姨娘', '夫人', '姥姥', '嬷嬷', '婆', '太君')

MYTH_ROOTS = ('神瑛侍者', '茫茫大士', '渺渺真人', '警幻仙姑')
MYTH_NAMES = {'神瑛侍者', '绛珠仙草', '茫茫大士', '渺渺真人', '通灵宝玉',
              '警幻仙姑', '警幻之妹兼美', '金陵十二钗册', '情榜'}
MYTH_PARENT = {'携', '司', '灌溉', '还泪'}     # 神话界内的施受，亦按父子之序铺树
# 足以表明「同出一族」的旁系；仅友朋、主仆、情缘者不足以独立成脉
KIN_AUX = {'侄孙女', '兄妹', '兄弟', '表姐妹', '姨表兄妹', '姑侄', '叔侄',
           '妯娌', '叔嫂', '继母女', '母子', '母女', '父子', '父女', '夫妇',
           '夫', '妾', '娶', '婚约'}

# ---------- 版式 ----------
PAD_X, PAD_Y = 12, 8
ROW_GAP, COL_GAP, MIN_GAP = 58, 26, 15
MAID_MAXW = 178
REG_DOT = {'正册': '#9e2b25', '副册': '#c2504a',
           '又副册': '#cf8b86', '情榜之首': '#b08d57'}
MARGIN = 26


# ============================================================ 取数
def _alias_map() -> dict[str, str]:
    """别号 → 正名。relations 里的称呼未必等于 persons.name。"""
    m: dict[str, str] = {}
    for p in db.q('SELECT name, aliases FROM persons'):
        name = p['name']
        m[name] = name
        if len(name) == 3:
            m.setdefault(name[1:], name)     # 贾宝玉 → 宝玉
        try:
            for a in json.loads(p['aliases'] or '[]'):
                m.setdefault(a, name)
        except Exception:
            pass
    return m


def _people(alias: dict[str, str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in db.q('SELECT name, gender, role, residence, qingbang, fate, '
                  'traits, aliases, registry FROM persons'):
        out[p['name']] = dict(name=p['name'], gender=p['gender'] or '',
                              role=p['role'] or '', res=p['residence'] or '',
                              bang=p['qingbang'] or '', fate=p['fate'] or '',
                              traits=p['traits'] or '', reg=p['registry'] or '',
                              derived=False, note='')
    try:                                      # 出场：首次 / 末次 / 回数 / 次数
        for r in db.q('SELECT person, MIN(chapter) a, MAX(chapter) b, '
                      'COUNT(DISTINCT chapter) c, SUM(n) s '
                      'FROM mentions GROUP BY 1'):
            nm = alias.get(r['person'], r['person'])
            if nm in out:
                out[nm].update(first=r['a'], last=r['b'],
                               chaps=r['c'], hits=r['s'])
    except Exception:
        pass
    return out


def _derived(people: dict[str, dict]) -> list[tuple[str, str, str, str]]:
    """relations 未录而书中确有依据的父母线，补入并注明凭据。"""
    out: list[tuple[str, str, str, str]] = []
    people.setdefault('贾珠', dict(
        name='贾珠', gender='男', role='贾政与王夫人长子，李纨之夫，贾兰之父',
        res='', bang='', fate='不到二十岁一病死了', traits='', reg='',
        derived=True,
        note='推得：李纨身份作「贾珠遗孀」，贾兰以「母子」系于李纨；'
             '第二回冷子兴演说荣国府已言其亡'))
    for a, b, rel in (('贾政', '贾珠', '父'), ('王夫人', '贾珠', '母'),
                      ('贾珠', '李纨', '夫妇'), ('贾珠', '贾兰', '父')):
        out.append((a, b, rel, '推得：见节点注'))
    qj = next((n for n in people if '巧姐' in n), '贾巧姐')
    if qj not in people:
        people[qj] = dict(name=qj, gender='女', role='凤姐与贾琏之女', res='',
                          bang='', fate='家亡后赖刘姥姥搭救，纺绩为生',
                          traits='', reg='', derived=True, note='推得')
    for a, rel in (('贾琏', '父'), ('王熙凤', '母')):
        out.append((a, qj, rel, '推得：人物表作「凤姐与贾琏之女」，'
                                '刘姥姥以「恩」系于贾巧姐'))
    return out


def classify(edges: list[dict], people: dict[str, dict]):
    """拆出直系 / 配偶 / 房内 / 侍婢 / 旁系五类。"""
    gender = lambda n: people.get(n, {}).get('gender', '')      # noqa: E731
    parents, spouses, home, maids, aux = [], [], [], [], []
    for e in edges:
        s, rel, t = e['source'], e['rel'], e['target']
        gs, gt = gender(s), gender(t)
        if rel in DIRECT:
            parents.append((s, t, rel, ''))
        elif rel in DIRECT_PAIR:
            if rel in ('母子', '父子'):
                head_first = (gs == '女') if rel == '母子' else (gs == '男')
            else:                              # 母女：以长辈字号辨其尊卑
                mark = ELDER_MARK if rel == '母女' else ('爹', '爷', '公')
                head_first = not any(k in t for k in mark)
            head, child = (s, t) if head_first else (t, s)
            parents.append((head, child, rel[0], ''))
        elif rel in STEP:
            parents.append((s, t, '继母', ''))
        elif rel in ANCESTOR:
            aux.append((s, t, rel))
        elif rel in MYTH_PARENT and s in MYTH_NAMES and t in MYTH_NAMES:
            parents.append((s, t, rel, ''))   # 灌溉 stars、携玉、司册：施者在前
        elif rel in SPOUSE:
            spouses.append((s, t, rel))
        elif rel in HOME:
            home.append((s, t, '妾') if gt != '男' else (t, s, '妾'))
        elif rel in MAID:
            maids.append((s, t))
        else:
            aux.append((s, t, rel))
    return parents, spouses, home, maids, aux


class _UF:
    """配偶合并为「一房」。"""

    def __init__(self) -> None:
        self.p: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def _subtree(units: dict, root: str) -> set[str]:
    seen, stack = set(), [root]
    while stack:
        k = stack.pop()
        if k in seen or k not in units:
            continue
        seen.add(k)
        stack += [c[0] for c in units[k]['kids']]
    return seen


# ============================================================ 版式
def _wrap(tokens: list[str], size: int, maxw: int) -> list[str]:
    lines, cur = [], ''
    for tk in tokens:
        if cur and (len(cur) + 1 + len(tk)) * size > maxw:
            lines.append(cur)
            cur = tk
        else:
            cur = f'{cur}·{tk}' if cur else tk
    if cur:
        lines.append(cur)
    return lines


def _box(u: dict, people: dict[str, dict]) -> dict:
    """一房一个牌位：主位、配偶、妾、侍。"""
    pinfo = people.get(u['primary'], {})
    raw: list[tuple[str, str]] = [(u['primary'], 'nm')]
    if u['consort']:
        raw.append(('＝' + '　'.join(u['consort']), 'sp'))
    if u['home']:
        raw.append(('妾 ' + '·'.join(u['home']), 'hm'))
    if u['maids']:
        raw.append(('侍 ' + '·'.join(u['maids']), 'hm'))
    lines, w = [], 0
    for text, cls in raw:
        size = 15 if cls == 'nm' else (13 if cls == 'sp' else 11)
        if cls == 'hm' and len(text) * 11 > MAID_MAXW:
            for seg in _wrap(text[2:].split('·'), 11, MAID_MAXW):
                lines.append({'t': '　' + seg, 's': 11, 'c': cls})
                w = max(w, (len(seg) + 2) * 11)
        else:
            lines.append({'t': text, 's': size, 'c': cls})
            w = max(w, len(text) * (size + 1))
    h = PAD_Y * 2 + 21 + 18 * max(0, sum(1 for l in lines if l['c'] == 'sp')) \
        + 15 * sum(1 for l in lines if l['c'] == 'hm')
    return dict(lines=lines, w=int(max(66, w + PAD_X * 2)), h=h,
                gender=pinfo.get('gender', ''), reg=pinfo.get('reg', ''),
                derived=bool(pinfo.get('derived')))


def _layout_tree(root: str, units: dict, people: dict) -> dict:
    """上下分层铺一棵树：同层左右排布，父母尽量居中于诸子之上。"""
    order, stack, seen = [], [root], set()
    while stack:                                   # 前序：子树节点相连
        k = stack.pop(0)
        if k in seen or k not in units:
            continue
        seen.add(k)
        order.append(k)
        stack = [c[0] for c in units[k]['kids']] + stack

    rows: dict[int, list[str]] = defaultdict(list)
    depth: dict[str, int] = {}

    def assign(k: str, d: int) -> None:
        depth[k] = d
        rows[d].append(k)
        for c, *_ in units[k]['kids']:
            if c in units:
                assign(c, d + 1)
    assign(root, 0)

    boxes = {k: _box(units[k], people) for k in order}
    row_h = {d: max(boxes[k]['h'] for k in rows[d]) for d in rows}
    row_y, y = {}, 0
    for d in sorted(rows):
        row_y[d] = y
        y += row_h[d] + ROW_GAP

    for d in sorted(rows):                         # 先顺序排布
        cur = 0.0
        for k in rows[d]:
            boxes[k]['x'] = cur
            cur += boxes[k]['w'] + COL_GAP
    for d in sorted(rows)[:-1]:                    # 再令父母居中于诸子
        want = {}
        for k in rows[d]:
            ks = [c[0] for c in units[k]['kids'] if c[0] in boxes]
            want[k] = ((min(boxes[c]['x'] for c in ks)
                        + max(boxes[c]['x'] + boxes[c]['w'] for c in ks)) / 2
                       - boxes[k]['w'] / 2) if ks else boxes[k]['x']
        prev = None
        for k in rows[d]:                          # 自左向右消重叠
            boxes[k]['x'] = max(want[k], prev + MIN_GAP if prev is not None else 0)
            prev = boxes[k]['x'] + boxes[k]['w']

    nodes = []
    for k in order:
        b = boxes[k]
        nodes.append(dict(id=k, name=units[k]['primary'], x=round(b['x'], 1),
                          y=row_y[depth[k]], w=b['w'], h=b['h'], lines=b['lines'],
                          gender=b['gender'], reg=b['reg'], derived=b['derived'],
                          members=units[k]['members'], home=units[k]['home'],
                          maids=units[k]['maids']))
    links = [dict(a=k, b=c[0], kind='kin', label=c[1],
                  detail=f'{c[3]} · {c[1]} · {c[4]}', why=c[2])
             for k in order for c in units[k]['kids'] if c[0] in boxes]
    return dict(root=root, nodes=nodes, links=links,
                w=int(max(b['x'] + b['w'] for b in boxes.values())),
                h=int(row_y[max(row_y)] + row_h[max(row_y)]))


# ============================================================ 造册
TAB_NOTES = {
    'rong': '贾母之下赦、政、敏三房：赦房出琏、迎春，政房出珠、元春、宝玉、'
            '探春、环，敏房适林如海而生黛玉。虚线是隔代提携、手足与姻娅之牵连。',
    'ning': '贾敬一味好道，宁府实务尽在贾珍；珍生蓉，蓉娶秦可卿。'
            '尤氏姊妹以「继母女」系于尤氏名下，一线牵出二姐、三姐两桩公案。',
    'kin': '薛、史、王与甄、秦、刘、贾代儒诸门，各有其脉，而以婚姻虚线与两府相连。'
           '内中薛家——姨妈、蟠、宝钗、蝌、宝琴——最是紧要。',
    'myth': '神瑛灌溉、绛珠还泪，是一部书的因缘；一僧一道携石入世，'
            '警幻司十二钗册与情榜。此非家谱，乃缘起：'
            '实线为施受之次第，虚线为往复之还报。',
}


def build(dst: Path | None = None) -> Path:
    out = dst or (paths.SITE_DIR / 'data')
    out.mkdir(parents=True, exist_ok=True)

    alias = _alias_map()
    people = _people(alias)
    edges = [{'source': alias.get(r['source'], r['source']), 'rel': r['rel'],
              'target': alias.get(r['target'], r['target'])}
             for r in db.q('SELECT source, rel, target FROM relations')]
    parents, spouses, home, maids, aux = classify(edges, people)
    parents += _derived(people)
    alias.setdefault('贾珠', '贾珠')

    names = {e['source'] for e in edges} | {e['target'] for e in edges} | \
            {a for a, b, _, _ in parents} | {b for a, b, _, _ in parents}
    uf = _UF()
    for a, b, _ in spouses:
        uf.union(a, b)
    for a, b, rel, _ in parents:                   # 补入的婚配（贾珠—李纨）同归一房
        if rel in ('夫妇', '夫', '娶', '婚约'):
            uf.union(a, b)
    groups: dict[str, list[str]] = defaultdict(list)
    for n in sorted(names):
        groups[uf.find(n)].append(n)
    unit_of = {n: k for k, ms in groups.items() for n in ms}
    units = {k: dict(id=k, members=ms, kids=[], parent=None, home=[], maids=[])
             for k, ms in groups.items()}

    # 直系：一房只挂一处名下。候选按「尊长自身有父母者（即血胤）—男—神话序」排定，
    # 先到先得，被排挤者改作虚线。如此就不会出现一房两处、或外祖夺了本宗之位。
    claim: dict[str, list] = defaultdict(list)
    for head, child, rel, why in parents:
        hk, ck = unit_of.get(head), unit_of.get(child)
        if hk and ck and hk != ck:
            claim[child].append((head, hk, rel, why))
    has_parent = set(claim)

    def hkey(c: tuple):
        ck, child, head, hk, rel, why = c
        g = people.get(head, {}).get('gender', '')
        pref = MYTH_ROOTS.index(head) if head in MYTH_ROOTS else 9
        return (0 if head in has_parent else 1, 0 if g == '男' else 1, pref, head)

    cands_all = [(unit_of[child], child) + c
                 for child, cs in claim.items() for c in cs]
    for c in sorted(cands_all, key=hkey):
        ck, child, head, hk, rel, why = c
        if units[ck]['parent'] or hk in _subtree(units, ck):
            aux.append((head, child, rel))      # 已有所归，或会首尾相衔成回环
            continue
        units[hk]['kids'].append((ck, rel, why, head, child))
        units[ck]['parent'] = hk

    # 隔代补线：无直系父母可依者，由祖孙 / 外祖孙承重（板儿之于刘姥姥）
    anc = [a for a in aux if a[2] in ANCESTOR]
    aux = [a for a in aux if a[2] not in ANCESTOR]
    for s, t, rel in anc:
        hk, ck = unit_of.get(s), unit_of.get(t)
        if not hk or not ck or hk == ck or units[ck]['parent'] \
                or hk in _subtree(units, ck):
            aux.append((s, t, rel))
            continue
        units[hk]['kids'].append((ck, rel, '', s, t))
        units[ck]['parent'] = hk

    for master, conc, _ in home:                   # 妾挂于所事之房
        k = unit_of.get(master)
        if k:
            units[k]['home'].append(conc)
    for master, sv in maids:
        k = unit_of.get(master)
        if k:
            units[k]['maids'].append(sv)
    for u in units.values():
        u['home'] = list(dict.fromkeys(u['home']))
        u['maids'] = list(dict.fromkeys(u['maids']))
        head_of = {c[3] for c in u['kids']}

        def pkey(n: str):
            g = people.get(n, {}).get('gender', '')
            return (0 if n in has_parent else 1, 0 if n in head_of else 1,
                    0 if g == '男' else 1, len(n))
        u['primary'] = min(u['members'], key=pkey)
        u['consort'] = [n for n in u['members'] if n != u['primary']]

    # 分卷：孤立但有族属牵连者可独立成脉，仅友朋主仆者不立
    kinish: set[str] = set()
    for s, t, rel in aux + anc:
        if rel in KIN_AUX or rel in ANCESTOR:
            for n in (s, t):
                if unit_of.get(n):
                    kinish.add(unit_of[n])
    roots = [k for k, u in units.items()
             if not u['parent'] and (u['kids'] or k in kinish
                                     or set(u['members']) & MYTH_NAMES)]
    rong_root, ning_root = unit_of.get('贾母'), unit_of.get('贾敬')
    rong = _subtree(units, rong_root) if rong_root else set()
    ning = _subtree(units, ning_root) if ning_root else set()
    myth_roots, kin_roots = [], []
    for r in roots:
        if r in rong or r in ning:
            continue
        mem = set()
        for k in _subtree(units, r):
            mem |= set(units[k]['members'])
        if units[r]['primary'] in MYTH_ROOTS or mem & MYTH_NAMES:
            myth_roots.append(r)
        else:
            kin_roots.append(r)
    myth_roots.sort(key=lambda k: MYTH_ROOTS.index(units[k]['primary'])
                    if units[k]['primary'] in MYTH_ROOTS else 9)
    kin_roots.sort(key=lambda k: units[k]['primary'])

    unit_tab: dict[str, str] = {}
    tabs = []
    for key, title, roots_ in (
            ('rong', '贾府·荣房', [rong_root] if rong_root else []),
            ('ning', '贾府·宁房', [ning_root] if ning_root else []),
            ('kin', '亲族·外戚', kin_roots),
            ('myth', '太虚·神话', myth_roots)):
        trees, nodes, links = [], [], []
        oy = 0
        for r in roots_:
            if r not in units:
                continue
            tr = _layout_tree(r, units, people)
            shift = oy + (26 if oy else 0)
            for n in tr['nodes']:
                n['y'] += shift
            tr['oy'] = shift
            tr['caption'] = units[r]['primary']
            for n in tr['nodes']:
                unit_tab[n['id']] = key
                nodes.append(n)
            links += tr['links']
            trees.append(tr)
            oy = tr['oy'] + tr['h'] + 40
        seen_links = set()
        for s, t, rel in aux:                      # 卷内虚线
            ka, kb = unit_of.get(s), unit_of.get(t)
            if not ka or not kb or ka == kb:
                continue
            if unit_tab.get(ka) != key or unit_tab.get(kb) != key:
                continue
            sig = (min(ka, kb), max(ka, kb), rel)
            if sig in seen_links:
                continue
            seen_links.add(sig)
            links.append(dict(a=ka, b=kb, kind='aux', label=rel,
                              detail=f'{s} · {rel} · {t}', why=''))
        tabs.append(dict(key=key, title=title, note=TAB_NOTES[key],
                         trees=trees, nodes=nodes, links=links,
                         w=int(max([tr['w'] for tr in trees] or [0]) + MARGIN),
                         h=int(max([(tr['oy'] + tr['h']) for tr in trees] or [0])
                               + MARGIN)))

    # 人物档案（含关系表，供右侧栏查阅）
    rel_of = defaultdict(list)
    for e in edges:
        rel_of[e['source']].append((e['rel'], e['target']))
        rel_of[e['target']].append((e['rel'], e['source']))
    for a, b, rel, _ in parents:
        if _:
            rel_of[a].append((rel, b))
            rel_of[b].append((rel, a))
    for n, p in people.items():
        k = unit_of.get(n)
        people[n]['tab'] = unit_tab.get(k, '') if k else ''
        people[n]['unit'] = k or ''
        rl = rel_of.get(n, [])
        seen2 = set()
        p['rels'] = [r for r in rl if not (r in seen2 or seen2.add(r))][:28]

    doc = dict(tabs=tabs, people=people,
               stats=dict(rooms=sum(len(t['trees']) for t in tabs),
                          units=len(units),
                          nodes=sum(len(t['nodes']) for t in tabs),
                          kin=sum(1 for t in tabs for l in t['links']
                                  if l['kind'] == 'kin'),
                          aux=sum(1 for t in tabs for l in t['links']
                                  if l['kind'] != 'kin')))
    fp = out / 'tree.json'
    fp.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    return fp


# ============================================================ 页面
BODY = """
<h2>家族谱系 · 宁荣两府与诸姻娅</h2>
<div class="card small">
relations 一百二十九条，先按语义拆作直系、配偶、房内、侍婢、旁系五类，再铺为树：
<b>实线</b>为父之血胤，<b>虚线</b>为祖孙、手足、姻娅、友朋之情牵；
牌位上第一行是主位（有血统者或其夫/妻），第二行＝配偶，微字行＝妾与侍婢。
同一人若父母俱录，依父系只挂一处，另一处改虚线，以免一子两父、枝干交错。
<b>虚框</b>为「推得」——贾珠早夭、巧姐父母之类，点开节点可见凭据。
点牌位看档案，点档案里的人名可跳到他名下。
</div>
<div class="tabs" id="tabs"></div>
<div class="card gcanvas">
  <div class="gtools">
    <label><input type="checkbox" id="auxOn" checked> 显示旁系虚线</label>
    <span class="gstat" id="stat"></span>
  </div>
  <svg id="tree" preserveAspectRatio="xMidYMin meet"></svg>
</div>
<div class="gwrap">
  <aside class="card gside" id="side"><p class="small">点一枚牌位。</p></aside>
  <div class="card small">图例：<span class="tag">实线 父·母</span>
  <span class="tag">虚线 祖孙·手足·姻娅</span>
  <span class="tag red">红点 正册</span><span class="tag">赭点 副册</span>
  <span class="tag">淡赭点 又副册</span><span class="tag">金点 情榜之首</span>
  <span class="tag">虚框 推得</span></div>
</div>
"""

JS = r"""
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
let D=null,T=null,SEL=null,HOV=null,IX=new Map();

function tabOf(name){
  for(const t of D.tabs){for(const n of t.nodes){
    if(n.name===name||(n.members||[]).includes(name)||(n.home||[]).includes(name)
       ||(n.maids||[]).includes(name)) return [t.key,n.id];}}
  return null;
}
function nodes(){return (D.tabs.find(t=>t.key===T)||{nodes:[]}).nodes;}
function byId(id){return nodes().find(n=>n.id===id);}

function draw(){
  const tab=D.tabs.find(t=>t.key===T)||{nodes:[],links:[]};
  const svg=$('tree');
  svg.setAttribute('viewBox',`0 0 ${tab.w+26} ${tab.h}`);
  let s='';
  for(const tr of (tab.trees||[])){
    if(tab.trees.length>1)
      s+=`<text x=6 y=${tr.oy-14} font-size=13 fill="#8a7f6d" font-family="serif">${esc(tr.caption)}一脉</text>`;
  }
  const rel=(a,b)=>tab.links.filter(l=>(l.a===a&&l.b===b)||(l.a===b&&l.b===a));
  // 旁系虚线
  if($('auxOn').checked){
    for(const l of tab.links.filter(l=>l.kind!=='kin')){
      const A=byId(l.a),B=byId(l.b); if(!A||!B)continue;
      const on=SEL&&(SEL===l.a||SEL===l.b), dim=SEL&&!on;
      const x1=(A.x+A.w/2)<(B.x+B.w/2)?A.x+A.w:A.x, y1=A.y+A.h/2;
      const x2=(A.x+A.w/2)<(B.x+B.w/2)?B.x:B.x+B.w, y2=B.y+B.h/2;
      const dx=Math.max(36,Math.abs(x2-x1)*0.42)*((x2>=x1)?1:-1);
      s+=`<path d="M${x1} ${y1} C${x1+dx} ${y1},${x2-dx} ${y2},${x2} ${y2}" `
        +`fill="none" stroke="${on?'#9e2b25':'#c2b498'}" stroke-width="${on?1.5:.9}" `
        +`stroke-opacity="${dim?.10:on?.85:.5}"><title>${esc(l.detail)}</title></path>`;
    }
  }
  // 直系
  for(const l of tab.links.filter(l=>l.kind==='kin')){
    const A=byId(l.a),B=byId(l.b); if(!A||!B)continue;
    const on=SEL&&(SEL===l.a||SEL===l.b), dim=SEL&&!on;
    const x1=A.x+A.w/2,y1=A.y+A.h,x2=B.x+B.w/2,y2=B.y,my=(y1+y2)/2;
    s+=`<path d="M${x1} ${y1} L${x1} ${my} L${x2} ${my} L${x2} ${y2}" fill="none" `
      +`stroke="${on?'#9e2b25':'#8f8368'}" stroke-width="${on?1.6:1}" `
      +`stroke-opacity="${dim?.18:.72}"><title>${esc(l.detail)}</title></path>`;
    s+=`<text x=${(x1+x2)/2} y=${my-4} text-anchor="middle" font-size="9.5" `
      +`fill="#8a7f6d" opacity="${dim?.2:.62}" font-family="serif">${esc(l.label)}</text>`;
  }
  // 牌位
  for(const n of nodes()){
    const sel=SEL===n.id;
    const bg=n.gender==='女'?'#fdf7f4':'#fffdf8';
    const dot=(n.reg&&({'正册':'#9e2b25','副册':'#c2504a','又副册':'#cf8b86',
      '情榜之首':'#b08d57'})[n.reg])||'';
    s+=`<g data-id="${n.id}" style="cursor:pointer">`;
    s+=`<rect x=${n.x} y=${n.y} width=${n.w} height=${n.h} rx=3 fill="${bg}" `
      +`stroke="${sel?'#9e2b25':(n.derived?'#b7a98d':'#ddd2b8')}" `
      +`stroke-width="${sel?1.9:1}"`
      +(n.derived?' stroke-dasharray="5,3"':'')
      +(sel?' filter="drop-shadow(0 2px 5px rgba(120,90,50,.18))"':'')+'/>';
    if(dot) s+=`<circle cx=${n.x+n.w-7} cy=${n.y+7.5} r=3 fill="${dot}"/>`;
    let y=n.y+8+15;
    n.lines.forEach((l,i)=>{
      if(i) y += n.lines[i-1].c==='nm'?21:(n.lines[i-1].c==='sp'?18:15);
      const col=l.c==='nm'?'#2f2a25':(l.c==='sp'?'#6b5f52':'#9a8d78');
      s+=`<text x=${n.x+12} y=${y} font-size=${l.s} fill="${col}" font-family="serif"`
        +(l.c==='nm'?' font-weight="600"':'')+`>${esc(l.t)}</text>`;
    });
    s+=`<rect x=${n.x} y=${n.y} width=${n.w} height=${n.h} fill="transparent"/></g>`;
  }
  svg.innerHTML=s;
  svg.querySelectorAll('[data-id]').forEach(g=>{
    const id=g.dataset.id;
    g.onclick=()=>{SEL=id;draw();panel(id);};
    g.onmouseenter=()=>{HOV=id;};g.onmouseleave=()=>{HOV=null;};
  });
  const st=D.stats;
  $('stat').textContent=`本卷 ${tab.nodes.length} 房 · 直系 ${tab.links.filter(l=>l.kind==='kin').length} 线 · 虚线 ${tab.links.filter(l=>l.kind!=='kin').length} 条 · 全书共 ${st.nodes} 房`;
}

function chip(nm){
  const hit=tabOf(nm);
  return `<span class="nb" data-go="${hit?hit[0]+'|'+hit[1]:''}">${esc(nm)}</span>`;
}

function panel(id){
  const n=byId(id); if(!n)return;
  const P=D.people[n.name]||{name:n.name};
  let h=`<h3>${esc(n.name)}</h3>`;
  h+=`<table class="kv"><tbody>`
    +(P.gender?`<tr><td>性别</td><td>${esc(P.gender)}</td></tr>`:'')
    +(P.role?`<tr><td>身份</td><td>${esc(P.role)}</td></tr>`:'')
    +(P.res?`<tr><td>居所</td><td>${esc(P.res)}</td></tr>`:'')
    +(P.reg?`<tr><td>册籍</td><td>${esc(P.reg)}</td></tr>`:'')
    +(P.bang&&!P.bang.startsWith('（')?`<tr><td>情榜</td><td>${esc(P.bang)}</td></tr>`:'')
    +(P.fate?`<tr><td>结局</td><td>${esc(P.fate)}</td></tr>`:'')
    +(P.first!=null?`<tr><td>出场</td><td>第 ${P.first} 回起，至第 ${P.last} 回止；`
      +`见 ${P.chaps} 回，提到 ${P.hits} 次</td></tr>`:'')
    +`</tbody></table>`;
  if(P.note) h+=`<p class="small">谱据：${esc(P.note)}</p>`;
  const peers=(n.members||[]).filter(x=>x!==n.name);
  if(peers.length) h+=`<p class="small">同房：${peers.map(chip).join('')}</p>`;
  if((n.home||[]).length) h+=`<p class="small">妾：${n.home.map(chip).join('')}</p>`;
  if((n.maids||[]).length) h+=`<p class="small">侍：${n.maids.map(chip).join('')}</p>`;
  if((P.rels||[]).length)
    h+=`<div class="small" style="margin-top:8px">关系：`
      +P.rels.map(r=>`<span class="nb" data-go="${(tabOf(r[1])||['','']).join('|')}">`
        +`${esc(r[0])} ${esc(r[1])}</span>`).join('')+`</div>`;
  const side=$('side'); side.innerHTML=h;
  side.querySelectorAll('[data-go]').forEach(el=>{
    el.onclick=()=>{const [tk,nid]=el.dataset.go.split('|');
      if(!nid)return; T=tk; SEL=nid; drawTabs(); draw(); panel(nid);};
  });
}

function drawTabs(){
  $('tabs').innerHTML=D.tabs.map(t=>
    `<button class="${t.key===T?'on':''}" data-k="${t.key}">${esc(t.title)}</button>`).join('')
    +D.tabs.filter(t=>t.key===T).map(t=>`<span class="tag">${esc(t.note)}</span>`).join('');
  $('tabs').querySelectorAll('button').forEach(b=>{
    b.onclick=()=>{T=b.dataset.k;SEL=null;drawTabs();draw();$('side').innerHTML='<p class="small">点一枚牌位。</p>';};
  });
}

fetch('data/tree.json').then(r=>r.json()).then(d=>{
  D=d;T=D.tabs[0].key;drawTabs();draw();
});
"""
