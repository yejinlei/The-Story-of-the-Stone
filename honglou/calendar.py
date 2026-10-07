"""岁时行事 · 节日复沓：把十六桩节铺成一圈十二月令。

festivals 一表只有日月、回次与本事三项，却藏着红楼梦的结构秘密：
同一个节令会在不同的年份反复出现——元宵三见（失女 / 归省 / 末次之团圆），
中秋两见（起 / 衰音），皆为兴衰之节。故作环形年历：
一扇一月令，同一节令的数次现身沿径向由内而外叠 outwards，
于是「复沓」不用解说，看珠子多寡即明。

产物：docs/data/calendar.json
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from . import db, paths

# 月令十二扇；把书中的时节词语（芒种、暮春、秋雨、除夕……）折到农历月
MONTHS = ['正月', '二月', '三月', '四月', '五月', '六月',
          '七月', '八月', '九月', '十月', '冬月', '腊月']
TERM_MONTH = [
    ('除夕', '腊月'), ('元宵', '正月'), ('上元', '正月'), ('灯节', '正月'),
    ('芒种', '四月'), ('端午', '五月'), ('中秋', '八月'), ('重阳', '九月'),
    ('冬至', '冬月'), ('暮春', '三月'), ('宝玉生日', '四月'),
    ('秋', '七月'), ('冬', '冬月'), ('除夕元宵', '腊月'),
]
# 星点与immung Sequences专用注解：同一节令多次现身的读法
REPEAT_NOTE = {
    '元宵': '元宵三见：第一回英莲被拐（失女）→ 第十七八回元春归省（极盛）'
            '→ 第五十三四回荣府夜宴（末次团圆，席上已是悲音）。'
            '同一个灯节，一家由聚到散，中间不过几年。',
    '中秋': '中秋两见：第一回甄士隐邀贾雨村（起，尚未入场）→ 第七十五六回'
            '凸碧堂品笛、凹晶馆联诗（衰音已透，「寒塘渡鹤」出）。'
            '开局与收局，恰落在同一轮月上。',
    '除夕元宵': '宁府祭宗祠在除夕，荣府夜宴在元宵：这是全书最后一场合族之聚，'
                '第五十四回一过，便再也拢不齐了。',
    '秋': '秋事最密：海棠社、菊花诗、螃蟹咏（三十七八），刘姥姥二进（三十九至四十二），'
          '金兰契与秋窗风雨夕（四十五），至七十七八回已是晴雯之死与芙蓉诔。',
}


def _chapters(s: str) -> list[int]:
    ns = [int(x) for x in re.findall(r'\d+', s or '')]
    if not ns:
        return []
    if len(ns) == 1:
        return [ns[0]]
    a, b = ns[0], ns[1]
    if b < a:                       # 「第75-76」之类
        return list(range(a, a + 1))
    return list(range(a, b + 1))


def _month(term: str) -> str:
    for key, mon in TERM_MONTH:
        if key in (term or ''):
            return mon
    return ''


def build(dst: Path | None = None) -> Path:
    out = dst or (paths.SITE_DIR / 'data')
    out.mkdir(parents=True, exist_ok=True)

    rows = db.q('SELECT id, chapter, solar_term, event FROM festivals ORDER BY id')
    poems = db.q('SELECT id, chapter, title, genre, author FROM poems')

    fests = []
    for r in rows:
        term = (r['solar_term'] or '').strip()
        chs = _chapters(r['chapter'])
        if not chs:
            continue
        mon = _month(term)
        if not mon:
            continue
        rel = [dict(id=p['id'], title=p['title'], genre=p['genre'],
                    author=p['author'], ch=p['chapter'])
               for p in poems if p['chapter'] and p['chapter'] in chs]
        fests.append(dict(fid=int(r['id']), term=term, month=mon,
                          lo=min(chs), hi=max(chs), chapters=chs,
                          event=r['event'] or '', poems=rel[:8]))
    fests.sort(key=lambda f: (MONTHS.index(f['month']), f['lo']))

    # 复沓：同一月令内的同名词
    by_term: dict[str, list[dict]] = {}
    for f in fests:
        key = ('元宵' if '元宵' in f['term'] else
               '中秋' if '中秋' in f['term'] else f['term'])
        by_term.setdefault(key, []).append(f)
    for key, group in by_term.items():
        group.sort(key=lambda f: f['lo'])
        for i, f in enumerate(group):
            f['repeat'] = len(group)
            f['seq'] = i + 1
            f['repeat_key'] = key
    for f in fests:
        f.setdefault('repeat', 1)
        f.setdefault('seq', 1)
        f.setdefault('repeat_key', f['term'])

    # 环形坐标：一扇一月令，同节令的多次现身沿径向由内而外
    CX, CY, R0, R1 = 430, 430, 150, 330
    n = len(MONTHS)
    sectors, marks, labels = [], [], []
    for i, mon in enumerate(MONTHS):
        a0 = 2 * math.pi * i / n - math.pi / 2 - math.pi / n
        a1 = 2 * math.pi * i / n - math.pi / 2 + math.pi / n
        sectors.append(dict(name=mon, a0=a0, a1=a1, idx=i))
        lm = (a0 + a1) / 2
        labels.append(dict(name=mon,
                           x=CX + math.cos(lm) * (R1 + 26),
                           y=CY + math.sin(lm) * (R1 + 26), a=lm))
    for f in fests:
        i = MONTHS.index(f['month'])
        a = 2 * math.pi * i / n - math.pi / 2
        r = R0 + 40 + (f['seq'] - 1) * 46     # 同节数见者，依次外叠
        marks.append(dict(fid=f['fid'], term=f['term'], month=f['month'],
                          seq=f['seq'], repeat=f['repeat'],
                          x=CX + math.cos(a) * r, y=CY + math.sin(a) * r,
                          a=a, r=r, lo=f['lo'], hi=f['hi'], event=f['event']))

    doc = dict(ring=dict(cx=CX, cy=CY, r0=R0, r1=R1, canvas=[860, 860]),
               sectors=sectors, labels=labels, marks=marks, fests=fests,
               notes=REPEAT_NOTE,
               repeats={k: [f['fid'] for f in v] for k, v in by_term.items()
                        if len(v) > 1},
               stats=dict(fests=len(fests), months=len({f['month'] for f in fests}),
                          poems=sum(len(f['poems']) for f in fests),
                          repeat=len([k for k, v in by_term.items() if len(v) > 1])))
    fp = out / 'calendar.json'
    fp.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    return fp


BODY = """
<h2>岁时行事 · 同一个灯节照了三回</h2>
<div class="card small">
十六桩节（本十五桩有节候可考）铺成一圈十二月令：
一扇一月，同一节令若在书中多次现身，就沿半径由内而外叠出去——
元宵占了三颗，中秋占了两颗，珠子的排列本身就是叙事。点一颗珠子看本事与其间的诗词；
点圆环外的月令名可只看该月。
</div>
<div class="card gcanvas">
  <div class="gtools"><span class="gstat" id="gstat"></span></div>
  <svg id="ring" viewBox="0 0 860 860" preserveAspectRatio="xMidYMid meet"></svg>
</div>
<div class="gwrap">
  <div class="card small" id="notes"></div>
  <aside class="card gside" id="cside"><p class="small">点一颗珠子。</p></aside>
</div>
<h2>行事一览</h2>
<div class="card"><table id="ftab"></table></div>
"""

JS = r"""
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
let D=null,SEL=null;

function pol(cx,cy,r,a){return [cx+r*Math.cos(a), cy+r*Math.sin(a)];}

function draw(){
  const R=D.ring,[W,H]=R.canvas;
  let s='';
  [R.r0,R.r0+46,R.r1].forEach((r,i)=>{
    s+=`<circle cx=${R.cx} cy=${R.cy} r=${r} fill="none" stroke="#e3d9c4" `
      +(i===1?'stroke-dasharray="3,6"':'')+'/>';});
  D.sectors.forEach((c,i)=>{
    const [x0,y0]=pol(R.cx,R.cy,R.r0,c.a0),[x1,y1]=pol(R.cx,R.cy,R.r1,c.a0);
    s+=`<line x1=${x0.toFixed(1)} y1=${y0.toFixed(1)} x2=${x1.toFixed(1)} y2=${y1.toFixed(1)} stroke="#efe6d3"/>`;
    const [mx,my]=pol(R.cx,R.cy,(R.r0+R.r1)/2,c.a0);
    s+=`<text x=${mx.toFixed(1)} y=${my.toFixed(1)} font-size=11 fill="#c9bda2" font-family="serif">${esc(c.name.slice(0,1))}</text>`;
  });
  D.labels.forEach(l=>{
    s+=`<text x=${l.x.toFixed(1)} y=${l.y.toFixed(1)} text-anchor="middle" font-size=13 `
      +`fill="#5d5449" font-family="serif">${esc(l.name)}</text>`;});
  D.marks.forEach(m=>{
    const on=SEL===m.fid;
    const col=m.repeat>1?'#9e2b25':'#b08d57';
    s+=`<circle cx=${m.x.toFixed(1)} cy=${m.y.toFixed(1)} r=${on?13:8+m.repeat} `
      +`fill="${col}" fill-opacity="${on?.95:.72}" stroke=${on?'#9e2b25':'#fdf8ee'} `
      +`stroke-width=${on?2:1} data-f="${m.fid}" style="cursor:pointer">`
      +`<title>${esc(m.event)}</title></circle>`;
    s+=`<text x=${m.x.toFixed(1)} y=${m.y.toFixed(1)+4} text-anchor="middle" font-size=10 `
      +`fill="#fdf6ec" font-family="serif" pointer-events="none">${m.seq}</text>`;
  });
  $('ring').innerHTML=s;
  $('ring').querySelectorAll('[data-f]').forEach(el=>{
    el.onclick=()=>{SEL=+el.dataset.f;draw();panel(SEL);};});
  $('gstat').textContent=`${D.stats.fests} 桩行事 · ${D.stats.months} 个月令 · 复沓 ${D.stats.repeat} 组 · 相关诗词 ${D.stats.poems} 首`;
}

function panel(fid){
  const f=D.fests.find(x=>x.fid===fid); if(!f)return;
  let h=`<h3>${esc(f.term)}</h3><p class="small">${esc(f.month)} · `
    +`第${f.lo}${f.hi!==f.lo?'—'+f.hi:''}回`
    +`<span class="tag${f.repeat>1?' red':''}">全书第 ${f.seq} 见 / 共 ${f.repeat} 见</span></p>`
    +`<p>${esc(f.event)}</p>`;
  const note=D.notes[f.repeat_key]||'';
  if(f.repeat>1&&note) h+=`<p class="small">${esc(note)}</p>`;
  if(f.poems.length){
    h+=`<div class="small" style="margin-top:6px">此际诗词：`
      +f.poems.map(p=>`<span class="nb">${esc(p.title||'无题')}（${esc(p.genre||'')}`
        +`${p.author?'·'+esc(p.author):''}）</span>`).join('')+`</div>`;}
  else h+=`<p class="small">此际无诗词。</p>`;
  const rs=(D.repeats[f.repeat_key]||[]).filter(i=>i!==fid);
  if(rs.length) h+=`<p class="small">同节另见：`
    +rs.map(i=>`<span class="nb" data-f="${i}">第${D.fests.find(x=>x.fid===i).lo}回</span>`).join('')+`</p>`;
  const side=$('cside');side.innerHTML=h;
  side.querySelectorAll('[data-f]').forEach(el=>el.onclick=()=>{SEL=+el.dataset.f;draw();panel(SEL);});
}

function tab(){
  $('ftab').innerHTML=`<thead><tr><th>月令</th><th>节候</th><th>回次</th><th>本事</th>`
    +`<th>诗词</th><th>复沓</th></tr></thead><tbody>`
    +D.fests.map(f=>`<tr data-f="${f.fid}" style="cursor:pointer"><td>${esc(f.month)}</td>`
      +`<td>${esc(f.term)}</td><td>第${f.lo}${f.hi!==f.lo?'—'+f.hi:''}回</td>`
      +`<td>${esc(f.event)}</td><td>${f.poems.length} 首</td>`
      +`<td>${f.repeat>1?`第${f.seq}/共${f.repeat}`:'—'}</td></tr>`).join('')
    +`</tbody>`;
  $('ftab').querySelectorAll('[data-f]').forEach(tr=>tr.onclick=()=>{
    SEL=+tr.dataset.f;draw();panel(SEL);});
}

fetch('data/calendar.json').then(r=>r.json()).then(d=>{
  D=d;draw();tab();
  $('notes').innerHTML=Object.keys(D.notes).filter(k=>D.repeats[k]).map(k=>
    `<div style="margin-bottom:10px"><h3>${esc(k)}</h3><p>${esc(D.notes[k])}</p></div>`).join('');
});
"""
