"""大观园图：把空间本体铺成一张可游的园图。

`places` 四十六处按「大观园 / 荣宁二府 / 城外寺观 / 江南城邑 / 神话仙境」分区落点，
院落大小＝该处在正文中现身的回次与次数，点一处即见：谁住在这里、它现身于哪些回、
以及写到它的诗句。园中一水为沁芳溪，自沁芳亭贯潇湘馆、蘅芜苑而入藕香榭。

空间即性格：潇湘馆的竹与泪、蘅芜苑的藤与雪洞、稻香村的假田园、栊翠庵的槛外人，
皆可从「居者—院落—诗句」三者的对应中读出。

产物：docs/data/garden.json。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from . import db, graph, paths

CANVAS = (1120, 720)

# 分区框（x, y, w, h）
ZONES = [
    dict(id='rong', name='荣国府', x=48, y=140, w=184, h=470, color='#9e2b25'),
    dict(id='ning', name='宁国府', x=60, y=48, w=125, h=72, color='#9e2b25'),
    dict(id='yuan', name='大观园', x=255, y=72, w=625, h=528, color='#3f6b5e'),
    dict(id='out', name='城外寺观 · 街巷', x=40, y=612, w=340, h=110, color='#8a7f6d'),
    dict(id='myth', name='大荒山 · 青埂峰', x=440, y=640, w=250, h=90, color='#5d5449'),
    dict(id='imm', name='太虚幻境', x=880, y=52, w=230, h=120, color='#6b5b95'),
    dict(id='jiang', name='江南 · 城邑', x=900, y=210, w=210, h=390, color='#3b4a6b'),
]

# 手订坐标（园之方位大略依第十七回「大观园试才题对额」的行游次第）
COORD = {
    '宁国府': (120, 84),
    '荣国府': (140, 168), '荣禧堂': (95, 238), '贾母院': (176, 288),
    '王夫人房': (95, 344), '凤姐院': (176, 398), '绛芸轩': (95, 452),
    '梨香院': (180, 508), '家塾': (120, 566),
    '紫菱洲': (330, 168), '蘅芜苑': (520, 168), '栊翠庵': (720, 168),
    '凸碧山庄': (830, 238), '芦雪庵': (320, 278), '蜂腰桥': (450, 302),
    '怡红院': (615, 300), '秋爽斋': (800, 358), '潇湘馆': (330, 402),
    '沁芳亭': (505, 418), '花冢': (385, 482), '暖香坞': (690, 472),
    '稻香村': (350, 552), '藕香榭': (540, 558), '凹晶溪馆': (795, 562),
    '花枝巷': (185, 644), '清虚观': (62, 630), '铁槛寺': (52, 674),
    '水月庵': (126, 700), '馒头庵': (206, 700), '狱神庙': (292, 692),
    '天齐庙': (366, 698),
    '大荒山': (560, 664), '无稽崖': (480, 700), '青埂峰': (642, 700),
    '太虚幻境': (945, 96), '警幻宫': (1045, 142), '赤瑕宫': (1080, 72),
    '灵河岸': (902, 162),
    '阊门': (925, 252), '姑苏': (1000, 312), '扬州': (1075, 388),
    '金陵': (1000, 462), '京城': (1080, 532), '紫檀堡': (930, 572),
    '葫芦庙': (1082, 244),
}

# 沁芳溪：自园西北来，贯芦雪庵、蜂腰桥、沁芳亭、藕香榭而出
WATER = [(268, 120), (300, 210), (322, 276), (452, 300), (505, 418),
         (540, 558), (660, 590), (795, 570)]

CAT_COLOR = {
    '院落': '#3f6b5e', '建筑': '#b08d57', '园林': '#3f6b5e', '府邸': '#9e2b25',
    '厅堂': '#7d1f1b', '寺庙': '#8a7f6d', '庙宇': '#8a7f6d', '道观': '#8a7f6d',
    '仙境': '#6b5b95', '城邑': '#3b4a6b', '城门': '#5d5449', '学堂': '#5d5449',
    '街巷': '#8a7f6d', '山': '#5d5449', '地点': '#5d5449',
}

# 落点 → 分区（用于筛选）
def _zone_of(name: str, cat: str, belongs: str) -> str:
    if name == '宁国府':
        return 'ning'
    if name in ('荣国府', '荣禧堂', '贾母院', '王夫人房', '凤姐院', '绛芸轩',
                '梨香院', '家塾'):
        return 'rong'
    if (belongs or '').startswith('大观园') or name in (
            '紫菱洲', '蘅芜苑', '栊翠庵', '凸碧山庄', '凹晶溪馆', '沁芳亭',
            '芦雪庵', '藕香榭', '蜂腰桥', '怡红院', '秋爽斋', '潇湘馆',
            '暖香坞', '稻香村', '花冢'):
        return 'yuan'
    if name in ('太虚幻境', '警幻宫', '赤瑕宫', '灵河岸'):
        return 'imm'
    if name in ('大荒山', '无稽崖', '青埂峰'):
        return 'myth'
    if cat in ('城邑', '城门') or name in ('姑苏', '扬州', '金陵', '京城',
                                          '阊门', '葫芦庙', '紫檀堡'):
        return 'jiang'
    return 'out'


def build(dst: Path | None = None) -> Path:
    out = dst or (paths.SITE_DIR / 'data')
    out.mkdir(parents=True, exist_ok=True)

    places = db.q('SELECT * FROM places')
    texts = graph._main_text()
    occ = graph._occur([p['name'] for p in places], texts, cap=60)

    persons = db.q('SELECT name, role, residence FROM persons')
    res: dict[str, list[dict]] = {}
    for p in persons:
        r = (p['residence'] or '').strip()
        if r and r not in ('—', '（无固定居所）'):
            res.setdefault(r, []).append(dict(name=p['name'], role=p['role'] or ''))

    # 写到该处的诗句
    plines = db.q('SELECT poem_id, seq, line FROM poem_lines ORDER BY poem_id, seq')
    pmeta = {p['id']: p for p in db.q('SELECT id, title, chapter, author FROM poems')}
    hits: dict[str, list[dict]] = {}
    for r in plines:
        ln = r['line'] or ''
        for p in places:
            nm = p['name']
            if nm in ln and len(hits.get(nm, [])) < 4:
                m = pmeta.get(r['poem_id'], {})
                hits.setdefault(nm, []).append(dict(
                    t=m.get('title') or '', c=m.get('chapter') or 0,
                    a=(m.get('author') or '').strip(), line=ln.strip()))

    nodes = []
    for p in places:
        nm = p['name']
        hit = occ.get(nm, [])
        total = sum(n for _, n in hit)
        xy = COORD.get(nm)
        if not xy:                       # 未手订者，依类别散落园外
            xy = (960 + (len(nm) % 3) * 40, 640 + (len(nodes) % 4) * 22)
        nodes.append(dict(
            id=nm, name=nm, cat=p['category'] or '地点',
            color=CAT_COLOR.get(p['category'], '#5d5449'),
            x=xy[0], y=xy[1],
            r=round(4.5 + 2.0 * math.sqrt(total), 1),
            total=total, chapters=len(hit),
            ev=[[c, n] for c, n in hit[:40]],
            zone=_zone_of(nm, p['category'] or '', p['belongs'] or ''),
            belongs=p['belongs'] or '', note=p['note'] or '',
            residents=res.get(nm, []),
            poems=hits.get(nm, []),
        ))

    legend = [dict(c='#3f6b5e', t='院落'), dict(c='#b08d57', t='建筑'),
              dict(c='#9e2b25', t='府邸厅堂'), dict(c='#8a7f6d', t='寺观街巷'),
              dict(c='#6b5b95', t='仙境'), dict(c='#3b4a6b', t='城邑')]
    doc = dict(canvas=list(CANVAS), zones=ZONES, water=WATER,
               nodes=nodes, legend=legend)
    (out / 'garden.json').write_text(
        json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    return out / 'garden.json'


BODY = """
<h2>大观园图 · 空间即性格</h2>
<div class="card small">
四十六处地点按「大观园／荣宁二府／城外寺观／江南城邑／神话仙境」分区落点，
院落大小＝它在前八十回正文中现身的次数（对数），色随类别。
<b>点一处</b>即见：谁住在这里、现身于哪些回、写到它的诗句。
一水为沁芳溪，自园西北贯芦雪庵、蜂腰桥、沁芳亭而入藕香榭——葬花、联句、烤鹿肉，皆在水边。
</div>
<div class="card gcanvas"><svg id="gd" viewBox="0 0 1120 720"
  preserveAspectRatio="xMidYMid meet"></svg></div>
<div class="gwrap">
  <aside class="card gside" id="gside"><p class="small">点园中一处。</p></aside>
</div>
"""

JS = r"""
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
let D=null,SEL=null;

function draw(){
  const [W,H]=D.canvas;
  let s='';
  // 分区框
  D.zones.forEach(z=>{
    s+=`<rect x=${z.x} y=${z.y} width=${z.w} height=${z.h} rx=6 fill="none" stroke="${z.color}" stroke-opacity=".28" stroke-dasharray="6,5"/>`+
       `<text x=${z.x+6} y=${z.y+18} fill="${z.color}" font-size="13" font-family="serif" opacity=".8">${esc(z.name)}</text>`;});
  // 沁芳溪
  const w=D.water.map((p,i)=>(i?'L':'M')+p[0]+' '+p[1]).join(' ');
  s+=`<path d="${w}" fill="none" stroke="#7fa3a8" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" opacity=".38"/>`+
     `<text x=${D.water[2][0]-8} y=${D.water[2][1]-8} fill="#7fa3a8" font-size="11">沁芳溪</text>`;
  // 点
  D.nodes.forEach((n,i)=>{
    const on=SEL&&SEL.name===n.name;
    s+=`<circle cx=${n.x} cy=${n.y} r=${n.r} fill="${n.color}" fill-opacity="${on?.95:.7}" stroke="${on?'#9e2b25':'#fdf8ee'}" stroke-width="${on?2:1}" data-i="${i}" style="cursor:pointer">`+
       `<title>${esc(n.name)}（${esc(n.cat)}）　现身 ${n.chapters} 回 / ${n.total} 次${n.residents.length?'　居者：'+esc(n.residents.map(r=>r.name).join('、')):''}</title></circle>`;
    if(n.chapters>=4||n.residents.length){
      s+=`<text x=${n.x} y=${n.y+n.r+13} text-anchor="middle" font-size="12" fill="${on?'#9e2b25':'#3a322a'}" font-family="serif" data-i="${i}" style="cursor:pointer">${esc(n.name)}</text>`;}
  });
  $('gd').innerHTML=s;
  $('gd').querySelectorAll('[data-i]').forEach(el=>{
    el.onclick=()=>{SEL=D.nodes[+el.dataset.i];draw();panel(SEL);};});
}
function spark(ev){
  const m=Math.max(1,...ev.map(x=>x[1])),W=300,H=26;
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}">`+
    ev.map(([c,n])=>{const x=(c-1)/110*W,h=Math.max(2,n/m*(H-4));
      return `<rect x=${x.toFixed(1)} y=${(H-h).toFixed(1)} width="2.4" height=${h.toFixed(1)} fill="#9e2b25" opacity=".65"><title>第${c}回 ${n} 次</title></rect>`;}).join('')+
    `</svg>`;
}
function panel(n){
  const rs=n.residents.length?n.residents.map(r=>`<span class="tag red">${esc(r.name)}　${esc(r.role)}</span>`).join(''):'<span class="small">—（非常居之所）</span>';
  const ps=n.poems.length?n.poems.map(p=>`<div class="small">「${esc(p.line)}」<br><span class="small">— ${esc(p.t)}　第${p.c}回${p.a?'　'+esc(p.a):''}</span></div>`).join(''):'<span class="small">—</span>';
  const top=n.ev.slice().sort((a,b)=>b[1]-a[1]).slice(0,6).map(([c,k])=>`第${c}回(${k})`).join('、')||'—';
  $('gside').innerHTML=`<h3>${esc(n.name)} <span class="small">${esc(n.cat)}</span></h3>`+
    `<table class="kv"><tr><td>所属</td><td>${esc(n.belongs)}</td></tr>`+
    `<tr><td>现身</td><td>${n.chapters} 回 · ${n.total} 次</td></tr>`+
    `<tr><td>最密</td><td>${top}</td></tr></table>`+
    `<p class="small">${esc(n.note)}</p><div><b>居者</b><br>${rs}</div>`+
    `<div class="small" style="margin-top:8px">正文现身（回次 →）${spark(n.ev)}</div>`+
    `<div style="margin-top:8px"><b>写到它的诗句</b><br>${ps}</div>`;
}
fetch('data/garden.json').then(r=>r.json()).then(d=>{D=d;draw();
  const best=D.nodes.filter(n=>n.zone==='yuan').sort((a,b)=>b.total-a.total)[0];
  if(best){SEL=best;draw();panel(best);}
}).catch(e=>{$('gside').textContent='园图数据加载失败：'+e;});
"""

if __name__ == '__main__':
    print(build())
