"""银钱账簿：把正文里出现的每一笔银钱抽出来，换成人能感知的尺度。

抽取
----
数目所指若是银两，则用中文数字解出两/钱/分；若所指为制钱，则另列吊/文。
「三两日」之类不是钱，剔除：只看后面不接日、月、年、天、夜者，
且前后十二字内须有银、赏、封、称、兑、欠、赎、价、买、卖、典、当、
月钱、月例、分例、利、租、赙、聘、工价等字样。

换算
----
全书唯一的内生购买力基准是刘姥姥那句「这一顿的钱够我们庄家人过一年了」，
其时螃蟹一宴共二十余两——遂以 <b>二十两 = 庄家人一岁之用</b> 为锚。
另一锚在第七十二回：琏二爷一房连四个丫头的月钱「通共一二十两，
还不够三五天的使用」——遂有大观园内的另一种时间感。

产物：docs/data/money.json
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import db, paths

# ---------- 数字 ----------
DIG = {'零': 0, '〇': 0, '一': 1, '壹': 1, '二': 2, '两': 2, '三': 3, '四': 4,
       '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}


UNIT = {'十': 10.0, '百': 100.0, '千': 1000.0}


def cn2num(s: str) -> float:
    """中文数字 → 数。支持 十 / 二十 / 十二 / 一百二十 / 二三十（取其中）。"""
    s = (s or '').strip()
    if not s:
        return 0.0
    if s.isdigit():
        return float(s)
    if len(s) == 3 and s[0] in DIG and s[1] in DIG and s[2] in UNIT:
        return (DIG[s[0]] + DIG[s[1]]) / 2 * UNIT[s[2]]     # 二三十两 ≈ 二十五两
    section, number = 0.0, 0.0
    for c in s:
        if c in DIG:
            number = float(DIG[c])
        elif c in UNIT:
            section += (number or 1.0) * UNIT[c]
            number = 0.0
        else:
            return 0.0
    return section + number


NUMTOK = '零〇一二两三四五六七八九十百千\\d'
RE_TAEL = re.compile(f'([{NUMTOK}]{{1,6}})两(?:银子|银)?(?:([{NUMTOK}]{{1,2}})钱'
                     f'(?:([{NUMTOK}]{{1,2}})分)?)?')
RE_CASH = re.compile(f'([{NUMTOK}]{{1,4}})(?:吊|贯)(?:钱|银)?')
RE_QIAN = re.compile(f'([{NUMTOK}]{{1,3}})钱(?:银子|银)?')     # 五钱 / 二钱
RE_WEN = re.compile(f'([{NUMTOK}]{{1,4}})百(?:文|钱)')
# 衰迹：后期日见其窘的关键词
DECAY_KEYS = ('当铺', '当了', '去当', '典当', '变卖', '赎', '利钱', '亏空',
              '接不上', '艰难', '偷当', '挪借', '放帐', '借当')

# 后面不能出现的字—— 「三两日」「二两年」不是钱
BAD_AFTER = ('日', '月', '年', '天', '夜', '载', '旬', '个',
             '口', '人', '只', '件', '地', '面', '间', '遭')
CTX_STRONG = ('银', '月钱', '月例', '分例', '工价', '盘缠', '使费', '贽', '赙',
              '赎', '当', '典', '兑', '租', '账', '帐', '锞', '价')
CTX_WEAK = ('赏', '封', '称', '买', '卖', '欠', '利', '礼', '还', '锦', '缎',
            '绸', '衣裳', '棺', '丧', '药', '杂项')

TAG_KEYS = [
    ('丧葬赙赠', ('殡', '丧', '赙', '祭', '吊问', '赠银', '棺', '香烛', '坟')),
    ('赏赐人情', ('赏', '封', '贽见', '贺', '礼', '打赏', '给', '送')),
    ('月例薪酬', ('月钱', '月例', '分例', '工价', '使用', '食用', '月银')),
    ('买办物价', ('价', '买', '卖', '货', '值', '兑', '称', '使费', '盘缠', '房租')),
    ('欠借典当', ('欠', '借', '当', '典', '赎', '利', '合同', '挪', '放款')),
    ('官司打点', ('状', '衙门', '打点', '告', '有司', '臬司', '顶', '缺')),
    ('佛道布施', ('醮', '布施', '斋僧', '诵经', '香火', '道场', '庙', '观',
                 '施舍', '打斋')),
    ('医药养生', ('药', '参', '医', '病', '燕窝', '调养', '诊视', '脉案')),
]

# ---------- 锚 ----------
ANCHORS = [
    dict(ch=39, taels=20.0, per='庄家人一岁之用',
         quote='这一顿的钱够我们庄家人过一年了',
         from_='第三十九回　螃蟹一宴，连酒菜共二十余两'),
    dict(ch=72, taels=15.0, per='琏二爷一房三五日之用',
         quote='这屋里有的没的，我和你姑爷一月的月钱，再连上四个丫头的月钱，'
               '通共一二十两银子，还不够三五天的使用呢',
         from_='第七十二回　琏二奶奶房中'),
]


def _sentence(text: str, i: int, j: int, pad: int = 46) -> str:
    return text[max(0, i - pad):j + pad].replace('\n', '')


def _ctx_ok(text: str, i: int, j: int) -> bool:
    after = text[j:j + 2]
    if after and after[0] in BAD_AFTER:      # 「三两日」「二两年」非钱
        return False
    win = text[max(0, i - 14):j + 14]
    if any(k in win for k in CTX_STRONG):
        return True
    return sum(1 for k in CTX_WEAK if k in win) >= 2


def _tags(text: str, i: int, j: int) -> list[str]:
    win = text[max(0, i - 26):j + 26]
    return [name for name, keys in TAG_KEYS if any(k in win for k in keys)] or ['其他']


def _who(text: str, i: int, j: int, names: list[str]) -> str:
    win = text[max(0, i - 40):j + 24]
    best = ''
    for nm in names:
        if nm in win and len(nm) > len(best):
            best = nm
    return best


def _persons() -> list[str]:
    out = []
    for p in db.q('SELECT name, aliases FROM persons'):
        out.append(p['name'])
        if len(p['name']) == 3:
            out.append(p['name'][1:])
        try:
            for a in json.loads(p['aliases'] or '[]'):
                if len(a) >= 2:
                    out.append(a)
        except Exception:
            pass
    return sorted(out, key=lambda s: (-len(s), s))


def decay_rows(rows) -> list[dict]:
    """逐回点算典当借贷之辞：愈到后来愈密者，即「外面的架子虽没很倒」之反面。"""
    out = []
    for row in rows:
        ch, text = row['chapter'], row['text'] or ''
        hits = sum(text.count(k) for k in DECAY_KEYS)
        if not hits:
            continue
        idx = -1
        for k in DECAY_KEYS:
            idx = text.find(k)
            if idx >= 0:
                break
        out.append(dict(ch=ch, n=hits,
                        ctx=text[max(0, idx - 34):idx + 56].replace('\n', '')))
    return sorted(out, key=lambda r: (-r['n'], r['ch']))


def collect():
    rows = db.q('SELECT chapter, text FROM v_main ORDER BY chapter, id')
    names = _persons()
    entries, wages, wage_ctx = [], [], set()
    for row in rows:
        ch, text = row['chapter'], row['text'] or ''
        for m in RE_TAEL.finditer(text):
            i, j = m.start(), m.end()
            if not _ctx_ok(text, i, j):
                continue
            taels = cn2num(m.group(1))
            if m.group(2):
                taels += cn2num(m.group(2)) / 10
            if m.group(3):
                taels += cn2num(m.group(3)) / 100
            if not 0 < taels < 100000:
                continue
            entries.append(dict(ch=ch, taels=round(taels, 3), unit='两',
                                raw=m.group(0), ctx=_sentence(text, i, j),
                                tags=_tags(text, i, j),
                                who=_who(text, i, j, names)))
        for m in RE_QIAN.finditer(text):          # 五钱 / 二钱：小数目
            i, j = m.start(), m.end()
            v = cn2num(m.group(1)) / 10
            if not 0 < v < 10:
                continue
            win_ok = any(k in text[max(0, i - 12):j + 12]
                         for k in ('银', '赏', '称', '兑', '月例', '分例',
                                   '月钱', '价', '买', '还', '称'))
            if not win_ok:
                continue
            entries.append(dict(ch=ch, taels=round(v, 3), unit='两',
                                raw=m.group(0), ctx=_sentence(text, i, j),
                                tags=_tags(text, i, j),
                                who=_who(text, i, j, names)))
        for m in RE_CASH.finditer(text):          # 吊 / 贯：制钱
            i, j = m.start(), m.end()
            if not _ctx_ok(text, i, j):
                continue
            v = cn2num(m.group(1))
            if not 0 < v < 10000:
                continue
            entries.append(dict(ch=ch, taels=round(v, 3), unit='吊',
                                raw=m.group(0), ctx=_sentence(text, i, j),
                                tags=_tags(text, i, j),
                                who=_who(text, i, j, names)))
        # 月钱 / 月例 / 分例 —— 荣府的工资表
        for m in re.finditer(r'月钱|月例|分例|月银', text):
            i, j = m.start(), m.end()
            win = text[max(0, i - 60):j + 60]
            got = []
            for mm in RE_TAEL.finditer(win):
                if mm.end() < 1:
                    continue
                v = cn2num(mm.group(1))
                if mm.group(2):
                    v += cn2num(mm.group(2)) / 10
                if 0 < v <= 200:
                    got.append((f'{mm.group(0)}', v, '两'))
            for mm in re.finditer(f'([{NUMTOK}]{{1,3}})吊', win):
                got.append((mm.group(0), cn2num(mm.group(1)), '吊'))
            for mm in re.finditer(f'([{NUMTOK}]{{1,3}})百(?:文|钱)', win):
                got.append((mm.group(0), cn2num(mm.group(1)) * 0.1, '两'))
            key = (ch, i // 40)
            if key in wage_ctx:
                continue
            for raw, v, unit in got[:3]:
                wage_ctx.add(key)
                wages.append(dict(ch=ch, amount=v, unit=unit, raw=raw,
                                  who=_who(text, i, j, names),
                                  ctx=_sentence(text, i, j, 60)))
    seen: set[tuple] = set()
    dedup = []
    for w in wages:                                # 同一句话里的多个数目只留其一
        key = (w['ch'], w['raw'], w['ctx'][:34])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(w)
    entries.sort(key=lambda e: (e['ch'], -e['taels']))
    return entries, sorted(dedup, key=lambda w: (w['ch'], -w['amount'])), \
        decay_rows(rows)


SCALES = [('< 一钱', lambda v, u: u == '两' and v < 0.1),
          ('一钱—一两', lambda v, u: u == '两' and 0.1 <= v < 1),
          ('一两—十两', lambda v, u: u == '两' and 1 <= v < 10),
          ('十两—百两', lambda v, u: u == '两' and 10 <= v < 100),
          ('百两—千两', lambda v, u: u == '两' and 100 <= v < 1000),
          ('千两以上', lambda v, u: u == '两' and v >= 1000),
          ('制钱（吊）', lambda v, u: u == '吊')]


def build(dst: Path | None = None) -> Path:
    out = dst or (paths.SITE_DIR / 'data')
    out.mkdir(parents=True, exist_ok=True)
    entries, wages, decay = collect()

    by_ch = defaultdict(lambda: dict(n=0, taels=0.0, cash=0))
    for e in entries:
        d = by_ch[e['ch']]
        d['n'] += 1
        if e['unit'] == '两':
            d['taels'] += e['taels']
        else:
            d['cash'] += e['taels']
    chs = sorted(by_ch)
    series = [dict(ch=c, n=by_ch[c]['n'], taels=round(by_ch[c]['taels'], 2),
                   cash=round(by_ch[c]['cash'], 2)) for c in chs if c]

    tiers = []
    for name, test in SCALES:
        sel = [e for e in entries if test(e['taels'], e['unit'])]
        if sel:
            tiers.append(dict(name=name, n=len(sel),
                              sum=round(sum(e['taels'] for e in sel
                                            if e['unit'] == '两'), 2),
                              top=max(sel, key=lambda e: e['taels'])['raw'],
                              sample=sel[0]['ctx'][:70]))
    # 极大 arg下的例子（金银比值）
    notable = sorted([e for e in entries if e['unit'] == '两' and e['taels'] >= 20],
                     key=lambda e: -e['taels'])[:26]

    tag_count = Counter(t for e in entries for t in e['tags'])
    anchor = ANCHORS[0]
    for e in entries:
        if e['unit'] == '两':
            e['years'] = round(e['taels'] / anchor['taels'], 3)
        else:
            e['years'] = round(e['taels'] / anchor['taels'], 3)

    doc = dict(entries=entries, wages=wages, series=series, tiers=tiers,
               notable=notable, anchors=ANCHORS, decay=decay,
               tags=tag_count.most_common(),
               stats=dict(n=len(entries), chaps=len([c for c in chs if c]),
                          taels=round(sum(e['taels'] for e in entries
                                          if e['unit'] == '两'), 2),
                          cash=round(sum(e['taels'] for e in entries
                                         if e['unit'] != '两'), 2),
                          max=round(max((e['taels'] for e in entries
                                         if e['unit'] == '两'), default=0), 2),
                          wages=len(wages)))
    fp = out / 'money.json'
    fp.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    return fp


BODY = """
<h2>银钱账簿 · 二十两是庄家人的一年</h2>
<div class="card small">
把正文里每一处写到数目的钱捋出来：先看后接之字（「三两日」不是钱），
再看前后有无银、赏、封、称、兑、欠、赎、价、月钱、分例等字样，两道闸门过尽者录入。
<b>换算的锚</b>是书中唯一的内生基准——第三十九回刘姥姥说螃蟹那一宴
「一共倒有二十多两银子……这一顿的钱够我们庄家人过一年了」，
故<b>二十两＝庄家人一岁之用</b>；另据第七十二回，琏二爷一房连四个丫头的月钱
「通共一二十两，还不够三五天的使用」，同一种银子在府里只是三五天。
抽取的条目、数目阶梯与逐回流向皆在下方，点<code>账簿</code>里的标签可分类翻检。
</div>
<div class="grid" id="ledger-cards"></div>
<h2>现金流 · 逐回计入</h2>
<div class="card gcanvas">
  <div class="gtools">
    <button id="mAmount" class="on">金额（对数）</button>
    <button id="mCount">提及次数</button>
    <span class="gstat" id="mstat"></span>
  </div>
  <svg id="cash" viewBox="0 0 1080 300" preserveAspectRatio="xMidYMid meet"></svg>
</div>
<div class="gwrap">
  <div class="card"><h3>数目阶梯</h3><table id="tiers"></table></div>
  <div class="card"><h3>荣府工资表</h3>
  <p class="small">月钱、月例、分例所在句抽出：数额、说话者与原文。</p>
  <div id="wages" class="samples"></div></div>
</div>
<h2>入不敷出 · 典当借贷之辞的逐回疏密</h2>
<div class="card small">若在第九、第十六、第五十三回，当铺与放帐只是当家经理的手法；
到第六十九回「我把两个金项圈当了三百银子」、第七十二回「这会子竟接不上……
至少还得三二千两银子」，便是另一副声口了。以下逐回点算当、典、赎、利钱、
亏空、挪借诸辞的出现数，取最多者十二回。</div>
<div class="card" id="decay"></div>
<h2>账簿</h2>
<div class="card">
  <div class="gtools" id="filters"></div>
  <div class="samples" id="list"></div>
</div>
"""

JS = r"""
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
let D=null,MODE='amount',TAG='全部';

function cards(){
  const a=D.anchors[0];
  const rows=[
    ['录入条目',`${D.stats.n} 笔 / 见 ${D.stats.chaps} 回`],
    ['银两小计',`${D.stats.taels.toLocaleString()} 两`],
    ['制钱小计',`${D.stats.cash} 吊`],
    ['最大一笔',`${D.stats.max} 两`],
    ['簿外之锚','二十两＝庄家人一岁'],
    ['另一本账','一二十两＝琏二爷三五日'],
    ['月例行数',`${D.stats.wages} 行`],
    ['最大者',D.notable[0]?`${D.notable[0].taels} 两　第 ${D.notable[0].ch} 回`:'—'],
  ];
  $('ledger-cards').innerHTML=rows.map(r=>
    `<div class="card"><div class="small">${esc(r[0])}</div><big>${esc(r[1])}</big></div>`).join('');
}

function chart(){
  const S=D.series,W=1080,H=300,PL=44,PB=34;
  const vals=S.map(s=>MODE==='amount'?Math.log10(s.taels+1):s.n);
  const mx=Math.max(...vals,0.6), n=S.length;
  const x=i=>PL+i*(W-PL-14)/(Math.max(1,n-1));
  const y=v=>H-PB-(v/mx)*(H-PB-16);
  let s='';
  [0,.5,1].forEach(f=>{const yy=PB+(H-PB-16)*f;
    s+=`<line x1=${PL} y1=${H-yy} x2=${W-14} y2=${H-yy} stroke="#e3d9c4"/>`;});
  const bars=MODE==='amount';
  S.forEach((d,i)=>{
    const v=bars?Math.log10(d.taels+1):d.n, yy=y(v);
    if(bars) s+=`<rect x=${x(i)-3} y=${yy} width=6 height=${H-PB-yy} fill="#9e2b25" opacity=".62"><title>第${d.ch}回：${d.taels} 两 / ${d.cash} 吊 / ${d.n} 处</title></rect>`;
    else s+=`<path d="M${x(i)-3} ${yy} L${x(i)+3} ${yy}" stroke="#9e2b25" stroke-width="2"/>`;
  });
  if(!bars){let p='';S.forEach((d,i)=>{p+=(p?'L':'M')+x(i)+' '+y(Math.log10(d.taels+1));});
    s+=`<path d="${p}" fill="none" stroke="#b08d57" stroke-width="1.2" opacity=".7"/>`;}
  D.anchors.forEach(a=>{
    const i=S.findIndex(d=>d.ch===a.ch); if(i<0)return;
    s+=`<line x1=${x(i)} y1=8 x2=${x(i)} y2=${H-PB} stroke="#3b4a6b" stroke-dasharray="3,4"/>`;
    s+=`<text x=${x(i)+4} y=20 font-size=10.5 fill="#3b4a6b" font-family="serif">${esc(a.ch)}回锚</text>`;});
  [1,20,40,60,80].forEach(c=>{const i=S.findIndex(d=>d.ch===c); if(i<0)return;
    s+=`<text x=${x(i)} y=${H-14} text-anchor="middle" font-size=10.5 fill="#8a7f6d" font-family="serif">${c}</text>`;});
  s+=`<text x=${PL} y=14 font-size=11 fill="#8a7f6d" font-family="serif">${MODE==='amount'?'金额 log10(两)':'每回提及次数'}</text>`;
  $('cash').innerHTML=s;
  $('mstat').textContent=`${MODE==='amount'?'柱＝该回金额对数，金线＝对数曲线':'点＝该回提及次数'}　虚线为两处锚所在回`;
}

function tiers(){
  $('tiers').innerHTML=`<thead><tr><th>量级</th><th>笔数</th><th>银两小计</th><th>最大</th></tr></thead><tbody>`
    +D.tiers.map(t=>`<tr><td>${esc(t.name)}</td><td>${t.n}</td><td>${t.sum}</td><td>${esc(t.top)}</td></tr>`).join('')
    +`</tbody>`;
}

function wages(){
  $('wages').innerHTML=D.wages.map(w=>
    `<div><b>${esc(w.who||'—')}</b>　<span class="tag">${esc(w.raw)}</span>`
    +`<span class="tag">第${w.ch}回</span><br>${esc(w.ctx)}</div>`).join('');
}

function decay(){
  const rows=D.decay.slice(0,12), mx=Math.max(...rows.map(r=>r.n),1);
  $('decay').innerHTML=rows.map(r=>`<div style="display:flex;align-items:baseline;gap:8px">`
    +`<span class="tag">第${r.ch}回</span>`
    +`<span style="display:inline-block;height:9px;width:${Math.round(r.n/mx*260)}px;`
    +`background:linear-gradient(90deg,#c2504a,#9e2b25);border-radius:2px"></span>`
    +`<span class="small">${r.n} 处</span></div>`
    +`<div class="small" style="margin:0 0 6px 52px;color:#6b6155">…${esc(r.ctx)}…</div>`).join('');
}

function filters(){
  const tags=['全部'].concat(D.tags.map(t=>t[0]));
  $('filters').innerHTML=tags.map(t=>
    `<button class="${t===TAG?'on':''}" data-t="${esc(t)}">${esc(t)}</button>`).join('');
  $('filters').querySelectorAll('button').forEach(b=>b.onclick=()=>{TAG=b.dataset.t;filters();list();});
}

function list(){
  const a=D.anchors[0];
  const sel=(TAG==='全部'?D.entries:D.entries.filter(e=>e.tags.includes(TAG)))
    .slice().sort((x,y)=>y.taels-x.taels).slice(0,140);
  $('list').innerHTML=sel.map(e=>{
    const yr=e.years>=1?`约 ${Math.round(e.years*10)/10} 个庄家人年`
      :`约 ${Math.round(e.years*365)} 日嚼用`;
    return `<div><span class="tag">第${e.ch}回</span>`
      +`<span class="tag red">${esc(e.raw)}</span>`
      +`<span class="tag">${esc(e.tags.join('/'))}</span>`
      +(e.who?`<b>${esc(e.who)}</b>`:'')
      +`　<span class="small">${esc(yr)}</span><br>${esc(e.ctx)}</div>`;
  }).join('')||'<p class="small">无。</p>';
}

fetch('data/money.json').then(r=>r.json()).then(d=>{
  D=d;cards();chart();tiers();wages();decay();filters();list();
  $('mAmount').onclick=()=>{MODE='amount';$('mAmount').classList.add('on');$('mCount').classList.remove('on');chart();};
  $('mCount').onclick=()=>{MODE='count';$('mCount').classList.add('on');$('mAmount').classList.remove('on');chart();};
});
"""
