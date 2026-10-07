"""物色流转图：二十四件器物各有其主，转手即是命运。

objects 表的 owner 字段本是传承之链（蒋玉菡→宝玉→袭人、北静王→宝玉→黛玉掷还、
柳湘莲→尤三姐……），把它解开为节点，再把每件在正文与续写里的每一次现身标出来，
于是可作两条对照：一，物的失得与人的存没是否同点；二，续写三十回里，
哪些器物被接住应验了，哪些就此再不提起。

产物：docs/data/relics.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import db, paths

ALIAS = {
    '通灵宝玉': ['通灵宝玉', '通灵玉', '衔玉'],
    '金麒麟': ['金麒麟', '麒麟'],
    '金锁': ['金锁', '金项圈', '项圈'],
    '茜香罗': ['茜香罗', '汗巾'],
    '大红汗巾': ['大红汗巾', '汗巾'],
    '扇坠': ['扇坠'],
    '风月宝鉴': ['风月宝鉴', '宝鉴'],
    '绣春囊': ['绣春囊', '春囊'],
    '鹡鸰香念珠': ['鹡鸰香念珠', '念珠'],
    '芙蓉诔': ['芙蓉诔'],
    '黛玉诗稿': ['诗稿'],
    '宝玉旧手帕': ['旧手帕'],
    '玻璃炕屏': ['炕屏'],
    '虾须镯': ['虾须镯'],
    '冷香丸': ['冷香丸'],
    '鸳鸯剑': ['鸳鸯剑'],

    # --- 衣冠一门（详见 honglou/costume.py）：别写（雀金呢／斗蓬）与省称在此备查
    '雀金裘': ['雀金裘', '雀金呢', '孔雀金线'],
    '猩猩毡斗篷': ['猩猩毡斗篷', '大红猩猩毡斗篷', '猩猩毡斗蓬', '大红猩猩毡斗蓬'],
    '白狐狸里鹤氅': ['大红羽纱面白狐狸里的鹤氅', '白狐狸里的鹤氅'],
    '莲青鹤氅': ['莲青斗纹锦上添花洋线番羓丝的鹤氅', '莲青', '番羓丝'],
    '青哆啰呢对襟褂': ['青哆啰呢对襟褂子'],
    '家常旧衣': ['家常旧衣'],
    '茄色哆啰呢狐皮袄': ['茄色哆啰呢狐皮袄子'],
    '海龙皮鹰膀褂': ['海龙皮小小鹰膀褂'],
    '石青起花八团倭缎排穗褂': ['石青起花八团倭缎排穗褂'],
    '束发嵌宝紫金冠': ['束发嵌宝紫金冠', '紫金冠'],
    '猩猩毡昭君套': ['挖云鹅黄片金里大红猩猩毡昭君套', '大红猩猩毡昭君套'],
    '掐金挖云红香羊皮小靴': ['掐金挖云红香羊皮小靴'],
    '青缎粉底小朝靴': ['青缎粉底小朝靴'],
}

CAT_COLOR = {'玉石': '#3b4a6b', '念珠': '#8a7f6d', '织物': '#c2504a',
             '金器': '#b08d57', '首饰': '#cf8b86', '镜子': '#6b8a3f',
             '兵器': '#5d5449', '药': '#3f6b5e',
             '器物': '#9e2b25', '玉饰': '#3b4a6b', '文': '#7d1f1b',
             '文稿': '#7d1f1b', '诗': '#9e2b25', '词': '#c2504a',
             # 衣冠
             '成衣': '#9c4a3c', '首服': '#b08d57', '足衣': '#6b6155',
             '佩饰': '#cf8b86', '雨具': '#4a6b5e'}


def _alts(name: str) -> list[str]:
    return ALIAS.get(name) or [name]


def _chain(owner: str) -> list[str]:
    if not owner or owner in ('—', '-', '－'):
        return []
    parts = re.split(r'→|->|→', owner)
    out = []
    for p in parts:
        p = p.strip()
        for sub in re.split(r'/', p):
            sub = re.sub(r'（.*?）|\(.*?\)|借|拾', '', sub).strip()
            if sub and sub not in out:
                out.append(sub)
    return out


def build(dst: Path | None = None) -> Path:
    out = dst or (paths.SITE_DIR / 'data')
    out.mkdir(parents=True, exist_ok=True)

    objs = db.q('SELECT name, owner, category, symbol FROM objects')
    people = {p['name']: p for p in db.q(
        'SELECT name, gender, role, fate, residence FROM persons')}
    try:
        last = {r['person']: r['b'] for r in db.q(
            'SELECT person, MAX(chapter) b FROM mentions GROUP BY 1')}
    except Exception:
        last = {}

    main = db.q('SELECT chapter, text FROM v_main ORDER BY chapter, id')
    try:
        cont = db.q('SELECT chapter, text FROM continuations ORDER BY chapter')
    except Exception:
        cont = []

    lanes = []
    for o in objs:
        name = o['name']
        hits = []
        for row in main:                       # 脂本正文（第 0 回为目录，不计）
            if not row['chapter']:
                continue
            text = row['text'] or ''
            for alt in _alts(name):
                i = text.find(alt)
                if i < 0:
                    continue
                hits.append(dict(ch=row['chapter'], src='书', alias=alt,
                                 ctx=text[max(0, i - 34):i + 46].replace('\n', '')))
                break
        for row in cont:                                    # 续写三十回
            text = row['text'] or ''
            for alt in _alts(name):
                i = text.find(alt)
                if i < 0:
                    continue
                hits.append(dict(ch=row['chapter'], src='续', alias=alt,
                                 ctx=text[max(0, i - 34):i + 46].replace('\n', '')))
                break
        hits.sort(key=lambda h: (h['ch'], h['src'] != '书'))
        if not hits:
            continue
        chain_names = _chain(o['owner'])
        ps = []
        for nm in chain_names:
            info = people.get(nm)
            ps.append(dict(name=nm, fate=(info or {}).get('fate', ''),
                           role=(info or {}).get('role', ''),
                           last=last.get(nm)))
        lanes.append(dict(name=name, cat=o['category'] or '器物',
                          owner=o['owner'] or '', symbol=o['symbol'] or '',
                          chain=chain_names, persons=ps, hits=hits,
                          first=hits[0]['ch'], last_=hits[-1]['ch'],
                          n=len(hits),
                          n_main=sum(1 for h in hits if h['src'] == '书'),
                          n_xu=sum(1 for h in hits if h['src'] == '续')))
    lanes.sort(key=lambda l: (-l['n'], l['first'], l['name']))

    cats = sorted({l['cat'] for l in lanes})
    doc = dict(lanes=lanes, cats=cats, colors=CAT_COLOR,
               stats=dict(objects=len(lanes), hits=sum(l['n'] for l in lanes),
                          xu=[l['name'] for l in lanes if l['n_xu']],
                          lost=[l['name'] for l in lanes if not l['n_xu']]))
    fp = out / 'relics.json'
    fp.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    return fp


BODY = """
<h2>物色流转 · 一物之失得，一人之生死</h2>
<div class="card small">
二十四件器物各有其主：一根汗巾自蒋玉菡到宝玉再到袭人，一串念珠由北静王赐下、
转赠黛玉而被掷还，一把鸳鸯剑先属湘莲终随三姐自刎。<b>横轴是回次</b>（一至八十为脂本，
八十一至一百一十为本工程续写，以淡色标出），每一点是该物的一次现身：
实心为脂本正文，空心为续写。点一点看原文与它的传承之链；
点物名看它历任主人各自的下场。
</div>
<div class="card gcanvas">
  <div class="gtools">
    <span class="gstat" id="rstat"></span>
  </div>
  <svg id="rel" preserveAspectRatio="xMidYMin meet"></svg>
</div>
<div class="gwrap">
  <div class="card small" id="rlegend"></div>
  <aside class="card gside" id="rside"><p class="small">点一点看原文。</p></aside>
</div>
"""

JS = r"""
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
let D=null,SEL=null;

function draw(){
  const LS=D.lanes, LH=26, X0=150, X1=1044, TOP=34;
  const W=1080, H=TOP+LS.length*LH+18;
  $('rel').setAttribute('viewBox',`0 0 ${W} ${H}`);
  const x=c=>X0+(Math.min(c,110)-1)*(X1-X0)/109;
  let s=`<rect x=${X0} y=${TOP-16} width=${1044-X0} height=${LS.length*LH+8} fill="#fdf6ec" opacity=".5"/>`;
  s+=`<rect x=${x(81)} y=${TOP-16} width=${1044-x(81)} height=${LS.length*LH+8} fill="#3b4a6b" opacity=".05"/>`;
  s+=`<text x=${x(81)+6} y=${TOP-4} font-size=10.5 fill="#3b4a6b" font-family="serif">← 脂本前八十回 ｜ 续写三十回 →</text>`;
  [1,10,20,30,40,50,60,70,80,90,100,110].forEach(c=>{
    s+=`<line x1=${x(c)} y1=${TOP-12} x2=${x(c)} y2=${TOP+LS.length*LH} stroke="#e3d9c4"/>`;
    s+=`<text x=${x(c)} y=${TOP-16} text-anchor="middle" font-size=10 fill="#8a7f6d" font-family="serif">${c}</text>`;});
  LS.forEach((l,i)=>{
    const y=TOP+i*LH+LH/2, col=D.colors[l.cat]||'#8a7f6d', on=SEL===l.name;
    s+=`<text x=${X0-10} y=${y+4} text-anchor="end" font-size=${on?13:12.5} `
      +`fill="${on?'#9e2b25':'#3a322a'}" font-family="serif" data-l="${esc(l.name)}" style="cursor:pointer">${esc(l.name)}</text>`;
    s+=`<line x1=${X0} y1=${y} x2=${X1} y2=${y} stroke="#e9ddc7" stroke-opacity="${on?.9:.5}"/>`;
    l.hits.forEach((h,j)=>{
      const hx=x(h.ch), xu=h.src==='续';
      s+=`<circle cx=${hx} cy=${y} r=${on?6:4.6} fill=${xu?'#fffdf8':col} `
        +`stroke="${col}" stroke-width=${on?1.8:1.1} data-i="${i}.${j}" style="cursor:pointer">`
        +`<title>${esc(l.name)}　第${h.ch}回（${xu?'续写':'脂本'}）</title></circle>`;
    });
    l.persons.forEach(p=>{
      if(!p.last)return;
      const px=x(Math.min(p.last,110));
      s+=`<path d="M${px} ${y-9} L${px+4} ${y-14} L${px-4} ${y-14} Z" fill="#9e2b25" opacity=".5">`
        +`<title>${esc(p.name)}：末见于第${p.last}回</title></path>`;
    });
    if(l.n_xu) s+=`<text x=${X1+4} y=${y+4} font-size=10.5 fill="#3b4a6b" font-family="serif">续 ${l.n_xu}</text>`;
  });
  $('rel').innerHTML=s;
  $('rel').querySelectorAll('[data-i]').forEach(el=>el.onclick=()=>{
    const [i,j]=el.dataset.i.split('.');SEL=D.lanes[+i].name;hit(D.lanes[+i],D.lanes[+i].hits[+j]);draw();});
  $('rel').querySelectorAll('[data-l]').forEach(el=>el.onclick=()=>{
    const l=D.lanes.find(x=>x.name===el.dataset.l);SEL=l.name;obj(l);draw();});
  $('rstat').textContent=`${D.stats.objects} 件器物 / ${D.stats.hits} 处现身 · `
    +`续写中被接住 ${D.stats.xu.length} 件：${D.stats.xu.slice(0,6).join('、')}${D.stats.xu.length>6?'…':''}`;
  $('rlegend').innerHTML='<div class="legend">'
    +D.cats.map(c=>`<span><i style="background:${D.colors[c]||'#8a7f6d'}"></i>${esc(c)}</span>`).join('')
    +'<span><i style="background:#9e2b25;border-radius:0"></i>▲ 主人末见于第几回</span></div>';
}

function hit(l,h){
  let t=`<h3>${esc(l.name)}</h3><p class="small">第${h.ch}回<span class="tag${h.src==='续'?' red':''}">${h.src==='续'?'续写':'脂本'}</span>`
    +`<span class="tag">${esc(l.cat)}</span></p><p>…${esc(h.ctx)}…</p>`;
  t+=`<p class="small">转是这样转的：${esc(l.owner||'—')}</p>`;
  if(l.symbol&&l.symbol!=='—') t+=`<p class="small">托意：${esc(l.symbol)}</p>`;
  t+=l.persons.map(p=>`<div class="small">${esc(p.name)}：${esc(p.fate||p.role||'—')}`
    +(p.last?`（末见第${p.last}回）`:'')+`</div>`).join('');
  $('rside').innerHTML=t;
}

function obj(l){
  let t=`<h3>${esc(l.name)}</h3><p class="small">${esc(l.cat)} · 现身 ${l.n} 处`
    +`（脂本 ${l.n_main} ／ 续写 ${l.n_xu}）· 第${l.first}回起</p>`
    +`<p>${esc(l.symbol||'')}</p><p class="small">传承：${esc(l.owner||'—')}</p>`
    +l.hits.slice(0,10).map(h=>`<div style="border-bottom:1px dotted #e9ddc7;padding:2px 0">`
      +`<span class="tag">第${h.ch}回</span><span class="tag">${h.src==='续'?'续写':'脂本'}</span>`
      +`<br><span class="small">…${esc(h.ctx)}…</span></div>`).join('');
  $('rside').innerHTML=t;
}

fetch('data/relics.json').then(r=>r.json()).then(d=>{D=d;draw();});
"""
