"""时序同轴 · 谁在第几回做什么（泳道时间轴与事件本体）。

书里的「同一时间」并无日历可据：作者从不写干支，只写「次日」「这日」「一时」。
故本模块的取法是这样：

一・**以场景为单位**。把每回正文按书场标记（且说、次日、这日、话说……）切成若干
   场景——一个场景就是「同一时地、同一组人」的最小单位，比回更细，比句更粗。
二・**以行事定取舍**。    被提到不等于当场：须在该场景里有言语或动作（名字近处有
   「道」「笑」「哭」一类动词，或紧接引语），才记为一条「故事实」。
    无可措手处即不入场，所以「有人提了一句」与「本人亲到」是两回事。
三・**以类目定性质**。就这人所在的句子统计 ontology_seed.EVENT_TYPES 各类的标志词，
   取最重者为类；类目凡十六，是此间自定的判断规则，规则公开，可复算。
四・**以原句备验**。每条故事实都带一句原文，点开即可对着字面看，不许空口说话。
五・**以回次为横轴**。x 用回次加场内次第；季节由文字推得（先剔去人名，
   否则「迎春」「探春」会被算作春），叙事分段由元宵除夕一类词聚簇而来，
   两者都标「推算」，不作历元之断言。

产物：docs/data/timeline.json，并回写 DuckDB 的 events 表以便用 SQL 复核。
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import db, ontology_seed as seed, paths

# ---------------------------------------------------------------- 场景切分
# 书场标记：场景由此另起
SCENE_MARKS = ('却说', '且说', '话说', '再说', '单说', '如今且说', '不说',
               '至次日', '到了次日', '次日', '这日', '那日', '一日', '忽一日',
               '看看', '正说着', '且听下回')
SOFT_MAX = 1000          # 场景最长字数，超过则强分时新的一幕

# 行事：名字近处出现这些字，才算「亲到」
ACT_PAT = (r'{a}[^。！？；\n]{{0,9}}?(?:道|笑|哭|泣|叹|骂|啐|瞅|瞧|听|应|'
           r'问|答|答应|念|吟|唱|写|看|吃|喝|饮|斟|摔|打|掷|拉|扶|抱|接|送|劝|'
           r'叫|让|请|跪|拜|站|坐|来|去|过来|出来|进去|起身|坐下|接过|拉了)')

# 引语标记（底本用弯引号）
QUOTE_OPEN = '“'

# 年关词（据以推算故事分段，非历元）
NEW_YEAR_WORDS = ('元宵', '除夕', '新春', '过年', '腊月', '年近岁逼')
# 四季助詞（正文四季字先剔人名再数）
SEASON_TERMS = {
    '春': ('春', '清明', '踏青', '花朝', '上巳'),
    '夏': ('夏', '端午', '伏天', '暑热', '蒲扇'),
    '秋': ('秋', '中秋', '重阳', '七夕', '桂花'),
    '冬': ('冬', '冬至', '雪', '严寒', '红梅', '梅花'),
}
TYPE_COLORS = ['#9e2b25', '#3b4a6b', '#b08d57', '#3f6b5e', '#7d5ba6', '#8a6d3b',
               '#c2504a', '#4a7d6b', '#6b5a8a', '#a1743c', '#2f6d8a', '#8a5a6b',
               '#5a6b3f', '#6b3f5a', '#3f5a6b', '#8a6d3b']


# ---------------------------------------------------------------- 语料与辞様
def _alias_by_person() -> dict[str, list[str]]:
    """人物 -> 其名与别名（长者优先），供正文比对。"""
    out: dict[str, list[str]] = {}
    for p in seed.persons():
        names = {p['name']} | {a for a in p['aliases'] if len(a) >= 2}
        out[p['name']] = sorted(names, key=len, reverse=True)
    return out


def _places() -> list[str]:
    return sorted((p['name'] for p in seed.places()), key=len, reverse=True)


def _types() -> list[dict]:
    ts = seed.event_types()
    for i, t in enumerate(ts):
        t['color'] = TYPE_COLORS[i % len(TYPE_COLORS)]
    return ts


def _sents(text: str) -> list[str]:
    out, start = [], 0
    for m in re.finditer(r'[。！？…；!?;]+[」』”"）]*', text):
        out.append(text[start:m.end()])
        start = m.end()
    if start < len(text):
        out.append(text[start:])
    return [s for s in out if s.strip()]


def _strip_names(text: str, alias_by_person: dict[str, list[str]]) -> str:
    """剔去人名再数四季字，否则「迎春」「探春」皆成春。"""
    s = text
    for names in alias_by_person.values():
        for n in names:
            s = s.replace(n, '〇')
    return s


# ---------------------------------------------------------------- 场景
def _split_scenes(blocks: list[str]) -> list[list[str]]:
    """把一回正文切成若干场景。"""
    scenes: list[list[str]] = []
    cur: list[str] = []
    size = 0
    for b in blocks:
        head = b[:6]
        mark = any(m in head for m in SCENE_MARKS)
        if (mark or size >= SOFT_MAX) and cur:
            scenes.append(cur)
            cur, size = [], 0
        cur.append(b)
        size += len(b)
    if cur:
        scenes.append(cur)
    return scenes or [[b] for b in blocks]


def _chapter_blocks() -> dict[int, list[str]]:
    """前八十回正文，按回聚合。"""
    out: dict[int, list[str]] = {}
    for r in db.q("SELECT chapter, text FROM blocks WHERE kind = '正文' "
                  "AND chapter > 0 AND chapter <= 80 ORDER BY chapter, id"):
        out.setdefault(int(r['chapter']), []).append(r['text'] or '')
    return out


def _continuation_blocks() -> dict[int, list[str]]:
    """推演所得后三十回正文，按回分段。"""
    out: dict[int, list[str]] = {}
    for r in db.q('SELECT chapter, text FROM continuations ORDER BY chapter'):
        lines = [x.strip() for x in (r['text'] or '').split('\n') if x.strip()]
        if lines and re.match(r'^第\s*[一二三四五六七八九十百零〇\d]+\s*回', lines[0]):
            lines = lines[1:]
        if lines:
            out[int(r['chapter'])] = lines
    return out


# ---------------------------------------------------------------- 时间推定
def _seasons(chapters: dict[int, list[str]],
             alias_by_person: dict[str, list[str]]) -> dict[int, str]:
    """逐回推季节：剔人名后数四季字，取最多者；无则从上一回继承。"""
    out: dict[int, str] = {}
    last = ''
    for ch in sorted(chapters):
        raw = ''.join(chapters[ch])
        s = _strip_names(raw, alias_by_person)
        acc = {k: sum(s.count(w) for w in ws) for k, ws in SEASON_TERMS.items()}
        best = max(acc, key=lambda k: acc[k])
        last = best if acc[best] else last
        out[ch] = last
    return out


def _epochs(chapters: dict[int, list[str]]) -> tuple[dict[int, int], list[dict]]:
    """年关分段：元宵、除夕、腊月一类词聚成簇，每簇之后算进入新的一段。

    这只是「叙事节奏的分段」，不是历元，页面上必标明为推算。
    """
    marks = []
    for ch in sorted(chapters):
        raw = ''.join(chapters[ch])
        hit = [w for w in NEW_YEAR_WORDS if raw.count(w)]
        if hit:
            marks.append((ch, hit))
    clusters: list[list[tuple[int, list[str]]]] = []
    for m in marks:
        if clusters and m[0] - clusters[-1][-1][0] <= 2:
            clusters[-1].append(m)
        else:
            clusters.append([m])
    epoch_of: dict[int, int] = {}
    bands: list[dict] = []
    for ch in sorted(chapters):
        epoch_of[ch] = 1
    cur = 1
    for cl in clusters:
        words: list[str] = []
        for _, ws in cl:
            words += [w for w in ws if w not in words]
        bands.append(dict(epoch=cur, lo=cl[0][0], hi=cl[-1][0],
                          words=words, lo2=cl[-1][0] + 1))
        cur += 1
        for ch in sorted(chapters):
            if ch > cl[-1][0]:
                epoch_of[ch] = cur
    return epoch_of, bands


def _festival_terms() -> dict[int, str]:
    """据本体所录节令，给出每回的节候（以 seeds 为准）。"""
    out: dict[int, str] = {}
    for f in seed.festivals():
        ns = [int(x) for x in re.findall(r'\d+', f['chapter'] or '')]
        if not ns:
            continue
        term = (f['solar_term'] or '').strip()
        if not term or term == '—':
            continue
        lo, hi = min(ns), max(ns) if len(ns) > 1 else min(ns)
        for ch in range(lo, hi + 1):
            out.setdefault(ch, term)
    return out


# ---------------------------------------------------------------- 故事实
def _acting(text: str, alias: str) -> bool:
    """这人在此场景是否真有言语动作（而非只被旁人提起）。"""
    pat = ACT_PAT.format(a=re.escape(alias))
    if re.search(pat, text):
        return True
    for m in re.finditer(re.escape(alias), text):
        tail = text[m.end():m.end() + 8]
        if QUOTE_OPEN in tail:
            return True
    return False


def _quote(sent: str, alias: str, limit: int = 30) -> str:
    """取一句原文，并以名字为中心裁窗，便于覆核。"""
    s = sent.strip()
    if len(s) <= limit:
        return s
    i = s.find(alias)
    if i < 0:
        i = 0
    half = limit // 2
    a = max(0, i - 6)
    return ('…' if a else '') + s[a:a + limit] + '…'


def _scene_person_event(name: str, aliases: list[str], text: str,
                        sents: list[str], types: list[dict]) -> dict | None:
    """就某场景判某人：类目、动作、原句。无所事事者不录（无从定类）。"""
    hits = [a for a in aliases if a in text]
    if not hits:
        return None
    if not any(_acting(text, a) for a in hits):
        return None
    mine = [s for s in sents if any(a in s for a in hits)]
    ctx = ''.join(mine) or text
    scored = []
    for ti, t in enumerate(types):
        score = 0
        terms: list[tuple[str, int]] = []
        # 标志词以字数平方计权：二字、三字之词组重于单字，
        # 免得书中满坑满谷的「道」把众人之行事都压成「言谈」
        for v in t['verbs']:
            c = ctx.count(v)
            if c:
                w = c * len(v) ** 2
                score += w
                terms.append((v, w))
        scored.append((score, ti, terms))
    best = max(scored, key=lambda x: (x[0], -x[1]))
    if best[0] == 0:
        return None                  # 这一幕查不出他在做什么，宁缺毋滥
    ti = best[1]
    terms = sorted(best[2], key=lambda x: -x[1])
    acts = '、'.join(v for v, _ in terms[:2]) or '在场'
    lead = terms[0][0] if terms else ''
    qs = [s for s in (mine or sents) if (lead and lead in s) or any(a in s for a in hits)]
    quote = _quote(qs[0] if qs else (mine[0] if mine else text), hits[0])
    return dict(typ=ti, acts=acts, quote=quote,
                speech=1 if re.search(
                    r'(?:道|笑道|说道|笑|哭|问|叹|啐)', ctx) else 0,
                n=sum(text.count(a) for a in hits))


# ---------------------------------------------------------------- 主构图
def build(dst: Path | None = None, with_llm: bool = False) -> Path:
    out = dst or (paths.SITE_DIR / 'data')
    out.mkdir(parents=True, exist_ok=True)

    types = _types()
    alias_by_person = _alias_by_person()
    places = _places()
    persons_meta = {p['name']: p for p in seed.persons()}
    seasons = _seasons(_chapter_blocks(), alias_by_person)
    base = _chapter_blocks()
    cont = _continuation_blocks()
    all_blocks = dict(base)
    all_blocks.update(cont)
    epoch_of, bands = _epochs(all_blocks)
    terms = _festival_terms()
    titles = {int(r['chapter']): r['title'] or ''
              for r in db.q('SELECT chapter, title FROM chapters WHERE chapter > 0')}

    events: list[dict] = []
    times: list[dict] = []
    scene_n = 0
    for ch in sorted(all_blocks):
        src = '推演' if ch > 80 else '本'
        scenes = _split_scenes(all_blocks[ch])
        for idx, blocks in enumerate(scenes):
            scene_n += 1
            text = ''.join(blocks)
            sents = _sents(text)
            place = next((p for p in places if p in text), '')
            sid = ch * 1000 + idx
            t_pos = ch + (idx + 0.5) / max(1, len(scenes))
            for name, aliases in alias_by_person.items():
                e = _scene_person_event(name, aliases, text, sents, types)
                if not e:
                    continue
                events.append(dict(id=len(events), sid=sid, ch=ch, t=t_pos,
                                   person=name, etype=types[e['typ']]['name'],
                                   place=place, acts=e['acts'], quote=e['quote'],
                                   speech=e['speech'], n=e['n'],
                                   season=seasons.get(ch, ''),
                                   epoch=epoch_of.get(ch, 1), src=src))
        times.append(dict(ch=ch, title=titles.get(ch, ''),
                          term=terms.get(ch, ''), season=seasons.get(ch, ''),
                          epoch=epoch_of.get(ch, 1), scenes=len(scenes),
                          src='推演' if ch > 80 else '本'))

    # --- 人物泳道
    lane_stats: dict[str, dict] = {}
    for e in events:
        s = lane_stats.setdefault(e['person'], dict(n=0, types=Counter(),
                                                    lo=99, hi=0, seasons=Counter()))
        s['n'] += 1
        s['types'][e['etype']] += 1
        s['lo'] = min(s['lo'], e['ch'])
        s['hi'] = max(s['hi'], e['ch'])
        s['seasons'][e['season']] += 1
    lanes = []
    for name, s in sorted(lane_stats.items(), key=lambda kv: -kv[1]['n']):
        meta = persons_meta.get(name, {})
        lanes.append(dict(name=name, role=meta.get('role', ''),
                          residence=meta.get('residence', ''), n=s['n'],
                          lo=s['lo'], hi=s['hi'],
                          types=[k for k, _ in s['types'].most_common(3)]))

    # --- 锚点事件以正文或回目核验
    anchors = []
    for k in seed.key_events():
        body = ''.join(all_blocks.get(k['chapter'], []))
        row_title = titles.get(k['chapter'], '')
        hit = next((w for w in k['terms'] if w in body or w in row_title), '')
        if not hit:
            continue
        anchors.append(dict(ch=k['chapter'], name=k['name'], actors=k['actors'],
                            term=hit, scene='', title=row_title))

    tnames = [t['name'] for t in types]
    tcount = Counter(e['etype'] for e in events)
    name_idx = {l['name']: i for i, l in enumerate(lanes)}

    # --- 可选：请大模型给每幕起一个小标题（无 LLM 则跳过，页面照常）
    scene_titles: dict[str, str] = {}
    if with_llm:
        scene_titles = _scene_titles(all_blocks, scenes_of=_scene_index(events))
    for e in events:
        key = f"{e['ch']}-{e['sid'] % 1000}"
        if scene_titles.get(key):
            e['title'] = scene_titles[key]

    rows = [(e['id'], e['sid'], e['ch'], 0, e['person'], e['etype'], e['place'],
             e['acts'], e['quote'], e['speech'], e['n'], round(e['t'], 4),
             e['season'], e['epoch'], e['src']) for e in events]
    con = db.conn()
    con.execute('DELETE FROM events')
    if rows:
        con.executemany('INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
    con.close()

    doc = dict(
        meta=dict(created_at=datetime.now().isoformat(timespec='seconds'),
                  base=max(base) if base else 0, cont=(max(cont) if cont else 80),
                  scenes=scene_n, events=len(events), lanes=len(lanes),
                  anchors=len(anchors), llm=bool(scene_titles),
                  types=len(types)),
        types=[dict(name=t['name'], gloss=t['gloss'], verbs=t['verbs'],
                    color=t['color'], n=tcount.get(t['name'], 0)) for t in types],
        lanes=lanes,
        times=times,
        epochs=bands,
        anchors=anchors,
        events=[dict(i=e['id'], p=name_idx[e['person']],
                     y=tnames.index(e['etype']), ch=e['ch'],
                     t=round(e['t'], 3), sid=e['sid'],
                     a=e['acts'], q=e['quote'], n=e['n'], s=e['speech'],
                     pl=e['place'], ep=e['epoch'], se=e['season'],
                     **({'c': 1} if e['src'] == '推演' else {}),
                     **({'ti': e['title']} if e.get('title') else {}))
                for e in events],
        stats=dict(base_events=sum(1 for e in events if e['src'] == '本'),
                   cont_events=sum(1 for e in events if e['src'] == '推演'),
                   speech=sum(1 for e in events if e['speech']),
                   placed=sum(1 for e in events if e['place']),
                   per_chapter=round(len(events) / max(1, len(all_blocks)), 1)))
    fp = out / 'timeline.json'
    fp.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    print(f'时序同轴：{len(events)} 条故事实 / {scene_n} 幕 / {len(lanes)} 条泳道 / '
          f'锚点验得 {len(anchors)} 条 → {fp.name} '
          f'({fp.stat().st_size / 1024:.0f} KB)')
    return fp


def _scene_index(events: list[dict]) -> dict[int, list[int]]:
    """回 -> 该回的场景序号（供 LLM 起幕 TITLE）。"""
    idx: dict[int, list[int]] = {}
    for e in events:
        idx.setdefault(e['ch'], [])
    for e in events:
        s = e['sid'] % 1000
        if s not in idx[e['ch']]:
            idx[e['ch']].append(s)
    return {ch: sorted(v) for ch, v in idx.items()}


SCENE_TITLE_PROMPT = """你是《红楼梦》的细读者。下面列出第{ch}回的若干「幕」，
每幕给出回目、在场者与一句原文。请为每一幕起一个**不超过十个字**的中文小标题，
概括这一幕在做什么（如「黛玉葬花」「宝钗扑蝶」）。

要求：只用书内事实，不评论、不考证；标题里尽量带人名。

【输出格式】严格 JSON：{{"{ch}-0":"标题","{ch}-1":"标题"}}，键即幕号，勿增说明。

【回目】{title}
【诸幕】
{body}
"""


def _scene_titles(all_blocks: dict[int, list[str]],
                  scenes_of: dict[int, list[int]]) -> dict[str, str]:
    """请大模型给每幕起标题（可选，落盘 data/timeline_titles.json）。"""
    from . import llm

    cache_f = paths.data('timeline_titles.json')
    cache = {}
    if cache_f.exists():
        try:
            cache = json.loads(cache_f.read_text(encoding='utf-8'))
        except Exception:
            cache = {}
    titles = dict(cache)
    for ch in sorted(all_blocks):
        scenes = _split_scenes(all_blocks[ch])
        nos = scenes_of.get(ch, list(range(len(scenes))))
        body = []
        for i in nos:
            if i >= len(scenes):
                continue
            text = ''.join(scenes[i])
            who = sorted({n for n, als in _alias_by_person().items()
                          if any(a in text for a in als)})
            body.append(f'{ch}-{i}|{text[:220]}|{"、".join(who[:6])}')
        if not body:
            continue
        ask = SCENE_TITLE_PROMPT.format(ch=ch, body='\n'.join(body), title='')
        try:
            got = llm.chat_json([{'role': 'user', 'content': ask}],
                                tag=f'tscene-{ch}', temperature=0.4)
        except Exception as e:
            print(f'第{ch}回 幕标题失败：{str(e)[:80]}', flush=True)
            continue
        for k, v in (got or {}).items():
            if isinstance(v, str) and v.strip():
                titles[str(k)] = v.strip()[:12]
        cache_f.write_text(json.dumps(titles, ensure_ascii=False, indent=1),
                           encoding='utf-8')
        print(f'第{ch}回 幕标题 {len(nos)} 幕', flush=True)
    return titles


BODY = """
<h2>时序同轴 · 谁在这一回做什么</h2>
<div class="card small">
《红楼》从不写干支年月日，只写「次日」「这日」「一时」——所以<b>「同一时间」要靠自己拼</b>。
这里把八十回正文按书场标记（且说、次日、这日、话说……）切成一幕一幕，
判明每幕有谁<b>真的在场有言语动作</b>（不是被旁人提起），就此排成泳道：
<b>横轴是回次与场内次第，纵轴是人物，一个点就是一条故事实</b>，点开即见原文，可当场核对。
点上端回次，可见该回所有人各自的营生；点左边人名，则只看这一人的行迹。
</div>
<div class="card gtools">
  <span class="small">泳道</span>
  <button class="tlbtn on" data-n="10">十人</button>
  <button class="tlbtn" data-n="16">十六人</button>
  <button class="tlbtn" data-n="30">三十人</button>
  <button class="tlbtn" data-n="99">全部</button>
  <span class="small" style="margin-left:10px">类目</span>
  <span id="tlchips"></span>
  <button id="tlcont">含推演三十回</button>
  <span class="gstat" id="tlstat"></span>
</div>
<div class="card"><div class="tlbars">
  <div class="tlnames" id="tlnames"></div>
  <div class="tlscroll"><svg id="tl" xmlns="http://www.w3.org/2000/svg"></svg></div>
</div></div>
<div class="gwrap">
  <div class="card small" id="tlnote"></div>
  <aside class="card gside" id="tlside"><p class="small">点一个点，或点上端回次。</p></aside>
</div>

<h2>事件本体 · 十六类目光之下</h2>
<div class="card small">
类目是自制的一把尺：每条故事实据本人所在句子的标志词定类，取最重者，规则可复算。
下表诸类的事件数，即八十回（加推演三十回）里这种事的疏密。
</div>
<div class="card"><table id="tltype"></table></div>

<h2>锚点事件 · 人工著录而以书核之</h2>
<div class="card small">
以下几桩大事由人工著录，构建时拿原书去重查：每条的核验词须在<b>正文或回目里真的出现</b>，
验不中的一律不显示。点一格即跳到该回，看当时谁在做什么。
</div>
<div class="card"><table id="tlanchor"></table></div>

<h2>推算与局限</h2>
<div class="card small">
一・<b>场景</b>由书场标记切分，最粗不过一千字；用底本（脂评汇校本）原文的标点。<br>
二・<b>在场之判</b>用「名字近处有动词或引语」这一条粗法。旁人闲话中提到的名字、以及
叙事者提及的名义人物，仍有混入的可能，不可谓丝毫无误。<br>
三・<b>季节</b>是数出来的：先剔去「迎春」「探春」一类人名，再数春夏秋冬及其助詞。
「算出时节」不等于「作者写明时节」。<br>
四・<b>年关分段</b>只据元宵、除夕、腊月一类词聚簇，簇后进为下一段。
它标记的是叙事节奏的顿挫，不可当历元用。<br>
五・推演三十回（第八十一至一一〇回）是本工程 AI 依脂批线索续写，附录以见後事之走向，
<b>与前十回不同科</b>，不可与八十回原文等量齐观。
</div>
"""

# 本页与「岁时行事」共处一页，两段 JS 会并作一个 <script>，
# 故此处自带闭包，免去顶层 const/let 重名之撞。
JS = r"""
(function(){
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
let D=null, LANES=16, CONT=false, SELTYPE=null, FOCUS=null, EV=[];
const LANEH=32, AXH=56, LEFT=8, STEP=26;

const SEACOL={春:'rgba(120,160,110,.16)',夏:'rgba(190,120,90,.13)',
              秋:'rgba(180,150,70,.15)',冬:'rgba(110,140,180,.14)'};

function tPair(ev){return [D.types[ev.y], D.lanes[ev.p]];}

function visible(){
  const lanes=D.lanes.slice(0,Math.min(LANES,D.lanes.length));
  const ok=new Set(lanes.map(l=>l.name));
  EV=D.events.filter(e=>ok.has(D.lanes[e.p].name))
    .filter(e=>CONT||!e.c)
    .filter(e=>SELTYPE==null||D.types[e.y].name===SELTYPE)
    .filter(e=>!FOCUS||D.lanes[e.p].name===FOCUS);
  return lanes.filter(l=>!FOCUS||l.name===FOCUS);
}

function draw(lanes){
  const maxCh=CONT?(D.meta.cont||80):(D.meta.base||80);
  const minCh=1, W=LEFT*2+(maxCh-minCh+1)*STEP, H=AXH+lanes.length*LANEH;
  const X=t=>LEFT+(t-minCh)*STEP+STEP/2;
  const svg=$('tl');
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
  svg.setAttribute('width',W); svg.setAttribute('height',H);
  const row=i=>AXH+i*LANEH+LANEH/2;
  let g='';
  // 季节带
  (D.times||[]).forEach(tm=>{
    if(tm.ch>maxCh||tm.ch<minCh)return;
    const x0=LEFT+(tm.ch-minCh)*STEP, c=SEACOL[tm.season]||'rgba(0,0,0,0)';
    g+=`<rect x=${x0} y=${AXH} width=${STEP} height=${lanes.length*LANEH} fill="${c}"/>`;
  });
  // 回次栅格与上端
  for(let ch=minCh;ch<=maxCh;ch++){
    const x=LEFT+(ch-minCh)*STEP+STEP/2, ist=ch%5===0||ch===minCh;
    g+=`<line x1=${x} y1=${AXH} x2=${x} y2=${AXH+lanes.length*LANEH} `
      +`stroke="${ist?'#ddd0b4':'#efe6d3'}" stroke-width="1"/>`;
    if(ist) g+=`<text x=${x} y=${AXH-30} text-anchor="middle" font-size=12 `
      +`fill="#5d5449">${ch}</text>`;
    const tm=(D.times||[]).find(t=>t.ch===ch);
    if(tm&&tm.season) g+=`<text x=${x} y=${AXH-14} text-anchor="middle" font-size=11 `
      +`fill="#8a7f6d">${esc(tm.season)}</text>`;
    if(tm&&tm.term) g+=`<text x=${x} y=${AXH-2} text-anchor="middle" font-size=10 `
      +`fill="#9e2b25">${esc(tm.term.slice(0,2))}</text>`;
    g+=`<rect x=${x-STEP/2} y=0 width=${STEP} height=${AXH-34} fill="transparent" `
      +`data-ch="${ch}" style="cursor:pointer"/>`;
  }
  $('tlside').dataset.x=maxCh;
  // 前八十回与推演的分界
  if(CONT&&maxCh>80){
    const x=LEFT+(80-minCh)*STEP+STEP;
    g+=`<line x1=${x} y1=0 x2=${x} y2=${H} stroke="#9e2b25" stroke-width="1.4" stroke-dasharray="5 4"/>`;
    g+=`<text x=${x+5} y=14 font-size=11 fill="#9e2b25">以下推演</text>`;
  }
  // 锚点事件：上端朱笔三角志之
  (D.anchors||[]).forEach(a=>{
    if(a.ch>maxCh)return;
    const x=LEFT+(a.ch-minCh)*STEP+STEP/2;
    g+=`<path d="M${x-4} 1 L${x+4} 1 L${x} 8 Z" fill="#9e2b25" opacity=".8" data-a="${a.ch}"/>`
      +`<text x=${x} y=8 font-size=9 fill="#9e2b25" text-anchor="middle" `
      +`transform="rotate(-90 ${x} 8)" pointer-events="none" style="cursor:pointer">`
      +`</text>`;
  });
  // 泳道横线
  lanes.forEach((l,i)=>{
    g+=`<line x1=${LEFT} y1=${row(i)} x2=${W-LEFT} y2=${row(i)} stroke="#f2e9d6" stroke-width="1"/>`;
  });
  // 故事实
  EV.forEach(e=>{
    const i=lanes.findIndex(l=>l.name===D.lanes[e.p].name); if(i<0)return;
    const t=D.types[e.y], y=row(i), x=X(e.t), r=Math.min(6,3+Math.sqrt(e.n||1));
    g+=`<circle cx=${x.toFixed(1)} cy=${y} r=${r.toFixed(1)} fill="${t.color}" `
      +`fill-opacity="${e.c?.5:.82}" stroke="${e.c?t.color:'#fffdf8'}" stroke-width="1" `
      +`data-e="${e.i}" style="cursor:pointer"><title>${esc(D.lanes[e.p].name)}　`
      +`${esc(e.a)}${e.pl?'　'+esc(e.pl):''}</title></circle>`;
  });
  svg.innerHTML=g;
  svg.querySelectorAll('[data-e]').forEach(el=>el.onclick=()=>{
    const ev=D.events.find(x=>x.i===+el.dataset.e); if(ev)panel(ev);});
  svg.querySelectorAll('[data-ch]').forEach(el=>el.onclick=()=>{
    chapter(+el.dataset.ch);});
}

function names(lanes){
  $('tlnames').innerHTML=`<div style="height:${AXH}px"></div>`
    +lanes.map(l=>`<div style="height:${LANEH}px;line-height:${LANEH}px;text-align:right;`
      +`padding-right:8px;font-size:13px;cursor:pointer;color:`
      +`${FOCUS===l.name?'#9e2b25':'#4a4438'}">${esc(l.name)}</div>`).join('');
  $('tlnames').querySelectorAll('div').forEach((el,i)=>{
    if(i===0)return;
    el.onclick=()=>{const l=lanes[i-1];FOCUS=(FOCUS===l.name?null:l.name);render();};});
}

function chips(){
  const counts={}; D.events.forEach(e=>{counts[D.types[e.y].name]=(counts[D.types[e.y].name]||0)+1;});
  const all=`<span class="nb" id="chipall">全部</span>`;
  const rest=D.types.map(t=>`<span class="nb" data-t="${esc(t.name)}" style="border-color:${
    SELTYPE===t.name?'#9e2b25':'#e0d5bd'};color:${SELTYPE===t.name?'#9e2b25':'#5d5449'}">`
    +`<i style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${
      t.color};margin-right:4px"></i>${esc(t.name)} ${counts[t.name]||0}</span>`).join('');
  const box=$('tlchips'); box.innerHTML=all+rest;
  const ca=$('chipall');
  ca.style.borderColor=SELTYPE?'#e0d5bd':'#9e2b25';
  ca.style.color=SELTYPE?'#5d5449':'#9e2b25';
  ca.onclick=()=>{SELTYPE=null;render();};
  box.querySelectorAll('[data-t]').forEach(el=>el.onclick=()=>{
    SELTYPE=(SELTYPE===el.dataset.t?null:el.dataset.t); render();});
}

function render(){
  const lanes=visible();
  names(lanes); draw(lanes); chips();
  const per=(D.times||[]).slice(0,CONT?undefined:80);
  $('tlstat').textContent=`${EV.length} 条故事实 · ${lanes.length} 条泳道 · `
    +`${per.length} 回 · ${D.meta.scenes} 幕`;
}

function panel(e){
  const t=D.types[e.y], l=D.lanes[e.p];
  const tm=(D.times||[]).find(x=>x.ch===e.ch)||{};
  const same=D.events.filter(x=>x.sid===e.sid&&x.p!==e.p)
    .map(x=>D.lanes[x.p].name).filter((v,i,a)=>a.indexOf(v)===i);
  let h=`<h3>${esc(l.name)} <span class="small">${esc(l.role||'')}</span></h3>`
   +`<table class="kv"><tr><td>回次</td><td>第${e.ch}回 ${esc(tm.title||'')}</td></tr>`
   +`<tr><td>推算之时</td><td>${esc(e.se||'—')}·第 ${e.ep} 段`
   +`${tm.term?'·'+esc(tm.term):''}</td></tr>`
   +`<tr><td>类目</td><td><span style="color:${t.color}">${esc(t.name)}</span>`
   +`　${esc(t.gloss||'')}</td></tr>`
   +`<tr><td>行事</td><td>${esc(e.a)}</td></tr>`
   +`<tr><td>地点</td><td>${esc(e.pl||'—')}</td></tr>`
   +`<tr><td>渊源</td><td>${e.c?'AI 推演':'八十回原文'}　出现 ${e.n} 次</td></tr></table>`
   +`<p class="small" style="margin:8px 0 0">【原文】${esc(e.q)}</p>`;
  if(e.ti) h+=`<p class="small">【本幕】${esc(e.ti)}</p>`;
  if(same.length) h+=`<p class="small">同幕在场：`
    +same.map(n=>`<span class="nb" data-p="${esc(n)}">${esc(n)}</span>`).join('')+`</p>`;
  const side=$('tlside'); side.innerHTML=h;
  side.querySelectorAll('[data-p]').forEach(el=>el.onclick=()=>{
    FOCUS=el.dataset.p; render();});
}

function chapter(ch){
  const list=D.events.filter(e=>e.ch===ch);
  const tm=(D.times||[]).find(x=>x.ch===ch)||{};
  const by={};
  list.forEach(e=>{by[D.lanes[e.p].name]=e;});
  let h=`<h3>第${ch}回</h3><p class="small">${esc(tm.title||'')}`
   +`　${esc(tm.season||'')}${tm.term?'·'+esc(tm.term):''}　共 ${list.length} 条故事实</p>`;
  const rows=Object.keys(by).sort((a,b)=>{
    const ia=D.lanes.findIndex(l=>l.name===a), ib=D.lanes.findIndex(l=>l.name===b);
    return ia-ib;});
  h+=rows.map(n=>{const e=by[n], t=D.types[e.y];
    return `<p class="small" style="border-bottom:1px dotted #e9ddc7;padding:2px 0">`
      +`<b>${esc(n)}</b> <span style="color:${t.color}">${esc(t.name)}</span> `
      +`${esc(e.a)}${e.pl?'（'+esc(e.pl)+'）':''}`
      +` <span data-e="${e.i}" style="color:#9e2b25;cursor:pointer">〔看原文〕</span></p>`;}).join('');
  if(!rows.length) h+=`<p class="small">这一回无人在场。</p>`;
  const side=$('tlside'); side.innerHTML=h;
  side.querySelectorAll('[data-e]').forEach(el=>el.onclick=()=>{
    panel(D.events.find(x=>x.i===+el.dataset.e));});
}

function note(){
  const busiest=(D.times||[]).filter(t=>!t.src||t.src==='本')
    .map(t=>({ch:t.ch,n:D.events.filter(e=>e.ch===t.ch).length}))
    .sort((a,b)=>b.n-a.n)[0];
  const top=D.lanes.slice(0,4).map(l=>`${esc(l.name)} ${l.n}`).join('　');
  $('tlnote').innerHTML=`<b>怎么读</b><br>`
    +`一・一幕之内，众人同在同一时地：看同一竖列上并排的点，即是「同一时间谁在做什么」。<br>`
    +`二・点的颜色是<b>事件类目</b>，大小是此人在该幕出现的多寡。<br>`
    +`三・中间断处即是此人不在场上——<b>缺席也是信息</b>，比如黛玉这条线在後半断得厉害。<br>`
    +`四・最热闹的一回：<b>第${busiest?busiest.ch:'—'}回</b>（${busiest?busiest.n:0} 条故事实）。<br>`
    +`五・故事实最多的人物：${top}。`;
}

function tabs(){
  let h='<tr><th>类目</th><th>释例</th><th>标志词（抽样）</th><th>事件数</th></tr>';
  D.types.forEach(t=>{
    h+=`<tr><td><span style="color:${t.color}">■</span> ${esc(t.name)}</td>`
      +`<td>${esc(t.gloss)}</td>`
      +`<td class="small">${esc((t.verbs||[]).slice(0,8).join('、'))}</td>`
      +`<td>${t.n||0}</td></tr>`;});
  $('tltype').innerHTML=h;
  let a='<tr><th>回</th><th>回目</th><th>锚点事件</th><th>在场者</th><th>核验词</th></tr>';
  (D.anchors||[]).forEach(k=>{
    a+=`<tr style="cursor:pointer" data-ch="${k.ch}"><td>${k.ch}</td>`
      +`<td class="small">${esc(k.title||'')}</td><td>${esc(k.name)}</td>`
      +`<td class="small">${esc((k.actors||[]).join('、'))}</td>`
      +`<td class="small">验：${esc(k.term)}</td></tr>`;});
  $('tlanchor').innerHTML=a;
  $('tlanchor').querySelectorAll('[data-ch]').forEach(tr=>tr.onclick=()=>{
    CONT=+tr.dataset.ch>80||CONT; chapter(+tr.dataset.ch);});
}

fetch('data/timeline.json').then(r=>r.json()).then(d=>{
  D=d; tabs(); note(); render();
  document.querySelectorAll('button.tlbtn').forEach(b=>b.onclick=()=>{
    document.querySelectorAll('button.tlbtn').forEach(x=>x.classList.remove('on'));
    b.classList.add('on'); LANES=+b.dataset.n; render();});
  $('tlcont').onclick=()=>{CONT=!CONT; $('tlcont').classList.toggle('on',CONT); render();};
}).catch(e=>{$('tlnote').innerHTML='时序数据未成：'+e;});
})();
"""

if __name__ == '__main__':
    import sys

    build(with_llm='--llm' in sys.argv)
