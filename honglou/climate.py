"""冷暖谱：以字为候，量「悲凉之雾」如何遍被华林。

逐回统计正文（脂本前八十回）与本次续写（八十一回以下）中的
**色彩字**、**情绪字**、**繁华字**的密度（每千字），并把字镜的字符困惑度叠在同一条轴上；

* 暖色：红 朱 绛 茜 丹 彤 绯 霞 锦 绣 —— 富贵温柔之乡；
* 素色：雪 霜 缟 银 冰（并「洁白」「白茫」）—— 白茫茫大地真干净；
* 笑 / 泪 / 死丧 / 喜乐 / 空幻 / 繁华（宴 戏 灯）。

素色与泪、死、空幻的上行，暖色与笑的下行，即为「散」的计量。
另附脂批自身的悲喜（批者在哪里先哭起来）。

产物：docs/data/climate.json。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import db, paths

_HAN = re.compile(r'[^一-鿿]')

# key, 名, 色, 单字, 词组（词组不含已计单字，免重复计数）
SERIES = [
    dict(key='warm', name='暖色', color='#9e2b25',
         s='红朱绛茜丹彤绯霞锦绣', p=(),
         note='红 朱 绛 茜 丹 彤 绯 霞 锦 绣'),
    dict(key='cool', name='素色', color='#3b4a6b',
         s='雪霜缟银冰', p=('洁白', '素白', '白茫'),
         note='雪 霜 缟 银 冰 及「洁白／素白／白茫」'),
    dict(key='laugh', name='笑', color='#b08d57', s='笑', p=(),
         note='「笑道」「笑说」皆归此'),
    dict(key='tear', name='泪', color='#3f6b5e', s='泪哭泣啼', p=(),
         note='泪 哭 泣 啼'),
    dict(key='death', name='死丧', color='#5d5449', s='死亡丧殁殡', p=(),
         note='死 亡 丧 殁 殡'),
    dict(key='joy', name='喜乐', color='#c2504a', s='喜乐欢兴', p=(),
         note='喜 乐 欢 兴'),
    dict(key='void', name='空幻', color='#6b5b95', s='空幻梦', p=(),
         note='空 幻 梦'),
    dict(key='feast', name='繁华', color='#8a7f6d', s='宴戏灯', p=(),
         note='宴 戏 灯'),
]

ANNO_SAD = '哭泪泣悲痛伤叹'
ANNO_JOY = '奇妙趣隽喜赞'


def _hanzi(t: str) -> str:
    return _HAN.sub('', t or '')


def _count(t: str, s: str, p: tuple) -> int:
    n = sum(t.count(c) for c in s)
    n += sum(t.count(w) for w in p)
    return n


def chapter_texts() -> dict[int, str]:
    """回次 → 净字正文（脂本取 v_main，续书取 continuations）。"""
    out: dict[int, str] = {}
    for r in db.q('SELECT chapter, text FROM v_main WHERE chapter > 0 ORDER BY id'):
        out.setdefault(r['chapter'], '')
        out[r['chapter']] += _hanzi(r['text'])
    for r in db.q('SELECT chapter, text FROM continuations ORDER BY chapter'):
        out[r['chapter']] = _hanzi(r['text'])
    return out


def anno_texts() -> dict[int, str]:
    out: dict[int, str] = {}
    for r in db.q('SELECT chapter, text FROM v_anno ORDER BY id'):
        out.setdefault(r['chapter'], '')
        out[r['chapter']] += _hanzi(r['text'])
    return out


def _ppl_map(dst: Path | None) -> dict[int, float]:
    """复用字镜的逐回困惑度（若已生成）。"""
    f = (dst or (paths.SITE_DIR / 'data')) / 'mirror.json'
    if not f.exists():
        return {}
    try:
        doc = json.loads(f.read_text(encoding='utf-8'))
    except Exception:
        return {}
    return {r['chapter']: r['ppl'] for r in doc.get('spectrum', [])}


def _festivals() -> list[dict]:
    out = []
    for r in db.q('SELECT chapter, solar_term, event FROM festivals ORDER BY id'):
        m = re.findall(r'\d+', r['chapter'] or '')
        if not m:
            continue
        out.append(dict(c=int(m[0]), c2=int(m[-1]), term=r['solar_term'],
                        event=r['event']))
    return out


def _smooth(v: list[float], w: int = 5) -> list[float]:
    out = []
    for i in range(len(v)):
        a = max(0, i - w // 2)
        b = min(len(v), i + w // 2 + 1)
        seg = v[a:b]
        out.append(sum(seg) / len(seg))
    return out


def turns(pts: list[dict], key: str, top: int = 3) -> list[dict]:
    """平滑后下降（或上升）最陡处，即拐点。"""
    seq = [p for p in pts if p['kind'] == '脂本']
    xs = [p['c'] for p in seq]
    v = _smooth([p.get(key, 0.0) for p in seq])
    if len(v) < 12:
        return []
    cand = []
    for i in range(2, len(v) - 2):
        d = v[i + 2] - v[i - 2]
        cand.append((d, xs[i]))
    cand.sort()
    picked: list[dict] = []
    for d, c in cand[:top]:
        if any(abs(c - q['c']) <= 6 for q in picked):
            continue
        picked.append(dict(c=c, delta=round(d, 3), key=key))
        if len(picked) >= top:
            break
    return picked


def build(dst: Path | None = None) -> Path:
    out = dst or (paths.SITE_DIR / 'data')
    out.mkdir(parents=True, exist_ok=True)
    texts = chapter_texts()
    annos = anno_texts()
    ppl = _ppl_map(out)
    titles = {r['chapter']: r['title'] for r in
              db.q('SELECT chapter, title FROM chapters WHERE chapter > 0')}
    for r in db.q('SELECT chapter, title FROM continuations'):
        titles.setdefault(r['chapter'], r['title'])

    pts = []
    for c in sorted(texts):
        t = texts[c]
        n = max(1, len(t))
        row = dict(c=c, kind='脂本' if c <= 80 else '续写',
                   chars=n, title=titles.get(c, ''))
        for se in SERIES:
            row[se['key']] = round(_count(t, se['s'], se['p']) * 1000 / n, 3)
        row['tint'] = round(
            (row['warm'] - row['cool']) / max(1.0, row['warm'] + row['cool']), 3)
        row['gloom'] = round(
            (row['tear'] + row['death'] + row['void'])
            / max(1.0, row['laugh'] + row['joy']), 3)
        a = annos.get(c, '')
        if a:
            na = max(1, len(a))
            row['as_sad'] = round(sum(a.count(ch) for ch in ANNO_SAD) * 1000 / na, 2)
            row['as_joy'] = round(sum(a.count(ch) for ch in ANNO_JOY) * 1000 / na, 2)
        else:
            row['as_sad'] = row['as_joy'] = 0
        row['ppl'] = ppl.get(c, 0)
        pts.append(row)

    doc = dict(
        series=[dict(key=s['key'], name=s['name'], color=s['color'], note=s['note'])
                for s in SERIES],
        points=pts,
        festivals=_festivals(),
        turns=dict(laugh=turns(pts, 'laugh'), tint=turns(pts, 'tint'),
                   feast=turns(pts, 'feast')),
    )
    (out / 'climate.json').write_text(
        json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    return out / 'climate.json'


BODY = """
<h2>冷暖谱 · 悲凉之雾如何遍被华林</h2>
<div class="card small">
逐回统计正文与续书中的<b>色彩字</b>（红朱绛茜 ↔ 雪霜缟银冰）、
<b>情绪字</b>（笑／泪／死丧／喜乐／空幻）与<b>繁华字</b>（宴戏灯）的密度（每千字），
并把字镜的<b>字符困惑度</b>叠在同一条轴上。
纵轴为密度，可点图例开关各条曲线；<span style="color:#b08d57">▲</span> 为节令（悬停见其事）；
点任一回即跳去读那一回。
曲线在何处转折，读数栏自会说明（「↑↓」为前四十回与后四十回之变）。
此谱只计字面，不计笔法：以乐景写哀之处，笑声反而最密——故读谱须与回目互参。
</div>
<div class="card gcanvas"><svg id="cv" viewBox="0 0 1080 440"
  preserveAspectRatio="xMidYMid meet"></svg></div>
<div class="card">
  <div class="gtools"><span class="small">曲线　</span><span id="leg"></span>
    <label class="small"><input type="checkbox" id="pplOn"> 叠字镜困惑度</label>
    <label class="small"><input type="checkbox" id="smOn" checked> 五回平滑</label>
  </div>
  <div id="tip" class="small"></div>
</div>
<div class="gwrap">
  <div class="card"><h3>读数</h3><div id="read" class="small"></div></div>
  <div class="card"><h3>脂本四分位（每千字密度）</h3>
    <div id="quart" class="small"></div></div>
</div>
"""

JS = r"""
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const nf=(v,n)=>(Math.round(v*Math.pow(10,n))/Math.pow(10,n)).toFixed(n);
let D=null,ON=null,W=1080,H=440,PL=48,PR=16,PT=16,PB=52;

function smooth(v,w){const o=[];for(let i=0;i<v.length;i++){let a=Math.max(0,i-(w>>1)),b=Math.min(v.length,i+(w>>1)+1),s=0;for(let j=a;j<b;j++)s+=v[j];o.push(s/(b-a));}return o;}

function draw(){
  const pts=D.points,on=ON,sm=$('smOn').checked;
  const W2=W-PL-PR;
  const xs=pts.map(p=>p.c), c0=xs[0], c1=xs[xs.length-1];
  const X=c=>PL+(c-c0)/(c1-c0)*W2;
  let mx=0;
  D.series.forEach(s=>{if(!on[s.key])return;
    const v=pts.map(p=>p[s.key]);(sm?smooth(v,5):v).forEach(y=>{if(y>mx)mx=y;});});
  const pplOn=$('pplOn').checked;
  let pmx=0; if(pplOn){pts.forEach(p=>{if(p.ppl>pmx)pmx=p.ppl;});}
  const Y=v=>H-PB-v/mx*(H-PT-PB-14);
  const YP=v=>H-PB-v/(pmx||1)*(H-PT-PB-14);
  let g='';
  for(let f=0;f<=4;f++){const y=PT+(H-PT-PB-14)*f/4;
    g+=`<line x1=${PL} y1=${y} x2=${W-PR} y2=${y} stroke="#e3d9c4"/>`+
       `<text x=${PL-8} y=${y+4} text-anchor="end" fill="#8a7f6d" font-size="11">${nf(mx*(1-f/4),1)}</text>`;}
  g+=`<text x=${PL-8} y=${PT-2} text-anchor="end" fill="#8a7f6d" font-size="10">每千字</text>`;
  // 续书分界
  const xb=X(80.5);
  g+=`<line x1=${xb} y1=${PT} x2=${xb} y2=${H-PB} stroke="#9e2b25" stroke-dasharray="4,4" opacity=".55"/>`+
     `<text x=${xb+5} y=${PT+12} fill="#9e2b25" font-size="11">续书起</text>`;
  // 节令
  (D.festivals||[]).forEach(f=>{const x=X(f.c);
    g+=`<polygon points="${x},${H-PB+4} ${x-4},${H-PB+12} ${x+4},${H-PB+12}" fill="#b08d57" opacity=".8"><title>第${f.c}回　${esc(f.term)}　${esc(f.event)}</title></polygon>`;});
  // 曲线
  D.series.forEach(s=>{
    if(!on[s.key])return;
    const raw=pts.map(p=>p[s.key]);const v=sm?smooth(raw,5):raw;
    const d=v.map((y,i)=>(i?'L':'M')+X(pts[i].c).toFixed(1)+' '+Y(y).toFixed(1)).join(' ');
    g+=`<path d="${d}" fill="none" stroke="${s.color}" stroke-width="1.7" opacity=".9"/>`;
  });
  if(pplOn){
    const raw=pts.map(p=>p.ppl||0);const v=sm?smooth(raw,5):raw;
    const d=v.map((y,i)=>(i?'L':'M')+X(pts[i].c).toFixed(1)+' '+YP(y).toFixed(1)).join(' ');
    g+=`<path d="${d}" fill="none" stroke="#3b4a6b" stroke-width="1.2" stroke-dasharray="5,3" opacity=".75"/>`;
    g+=`<text x=${W-PR} y=${H-PB+30} text-anchor="end" fill="#3b4a6b" font-size="11">— — 字镜困惑度（右意会，峰 ${nf(pmx,0)}）</text>`;
  }
  // 回次轴
  for(let c=10;c<=c1;c+=10){const x=X(c);
    g+=`<text x=${x} y=${H-PB+26} text-anchor="middle" fill="#8a7f6d" font-size="11">${c}</text>`;}
  g+=`<text x=${PL+W2/2} y=${H-8} text-anchor="middle" fill="#8a7f6d" font-size="11">回次 →</text>`;
  // 探层
  pts.forEach((p,i)=>{const x=X(p.c);
    g+=`<rect x=${(x-W2/(c1-c0)/2).toFixed(1)} y=${PT} width=${(W2/(c1-c0)).toFixed(1)} height=${H-PB-PT} fill="transparent" data-i="${i}" style="cursor:pointer"/>`;});
  g+=`<line id="guide" x1="0" y1=${PT} x2="0" y2=${H-PB} stroke="#9e2b25" stroke-width=".8" opacity="0"/>`;
  $('cv').innerHTML=g;
  $('cv').querySelectorAll('[data-i]').forEach(el=>{
    el.onmouseenter=()=>{const i=+el.dataset.i;show(pts[i]);
      const gl=$('guide');gl.setAttribute('x1',X(pts[i].c));gl.setAttribute('x2',X(pts[i].c));gl.setAttribute('opacity','.6');};
    el.onclick=()=>{const c=pts[+el.dataset.i].c;
      location.href=c<=80?('read.html#'+c):('continuation.html#c'+c);};
  });
}
function show(p){
  const rows=D.series.filter(s=>ON[s.key])
    .map(s=>s.name+' '+nf(p[s.key],2)).join('　');
  let extra='';
  if(p.as_sad)extra=`<br>脂批悲语 ${nf(p.as_sad,1)}　称赏 ${nf(p.as_joy,1)}`;
  if(p.ppl)extra+=`　困惑度 ${nf(p.ppl,0)}`;
  $('tip').innerHTML=`<b>第${p.c}回</b>　${esc(p.title||'')}　<span class="small">${p.kind}　${p.chars} 字</span>`+
    `<br>${rows}${extra}<br><span class="small">色温 ${nf(p.tint,2)}（暖正素负）　悲喜比 ${nf(p.gloom,2)}　点此回可去读它</span>`;
}
function legend(){
  $('leg').innerHTML=D.series.map(s=>
    `<button data-k="${s.key}" style="border-color:${s.color};color:${ON[s.key]?s.color:'#8a7f6d'};opacity:${ON[s.key]?1:.5}" title="${esc(s.note)}">${s.name}</button>`).join(' ');
  $('leg').querySelectorAll('button').forEach(b=>{
    b.onclick=()=>{const k=b.dataset.k;ON[k]=!ON[k];legend();draw();};});
}
function readout(){
  const old=D.points.filter(p=>p.kind==='脂本'),nw=D.points.filter(p=>p.kind==='续写');
  const mean=(a,k)=>a.reduce((s,p)=>s+p[k],0)/Math.max(1,a.length);
  const row=(k,name)=>{
    const a=mean(old.slice(0,40),k),b=mean(old.slice(40),k),c=nw.length?mean(nw,k):0;
    const up=b>=a?'↑':'↓';
    return `<tr><td>${name}</td><td>${nf(a,2)}</td><td>${nf(b,2)} ${up}${nf(Math.abs(b-a),2)}</td><td>${nf(c,2)}</td></tr>`;};
  const tb=`<table><tr><th>项</th><th>前四十回</th><th>后四十回</th><th>续书三十回</th></tr>`+
    D.series.map(s=>row(s.key,s.name)).join('')+
    `<tr><td>色温</td><td>${nf(mean(old.slice(0,40),'tint'),2)}</td><td>${nf(mean(old.slice(40),'tint'),2)}</td><td>${nf(nw.length?mean(nw,'tint'):0,2)}</td></tr>`+
    `<tr><td>悲喜比</td><td>${nf(mean(old.slice(0,40),'gloom'),2)}</td><td>${nf(mean(old.slice(40),'gloom'),2)}</td><td>${nf(nw.length?mean(nw,'gloom'):0,2)}</td></tr></table>`;
  const T=D.turns||{};
  const tl=k=>{const a=(T[k]||[]).map(t=>'第'+t.c+'回').join('、')||'—';return a;};
  $('read').innerHTML=
    `<p><b>笑声最陡的跌落</b>：${tl('laugh')}。<b>色温由暖转素最陡处</b>：${tl('tint')}。`+
    `<b>繁华字（宴戏灯）退潮最陡处</b>：${tl('feast')}。　（五回平滑后取变化最大的三处）</p>`+
    `<p class="small">脂批自身的悲语（哭泪泣悲痛伤叹）密度，最高在第 `+
    old.slice().sort((a,b)=>b.as_sad-a.as_sad).slice(0,3).map(p=>p.c).join('、')+' 回——批者先哭起来了。</p>'+tb;
  const q=k=>{const v=old.map(p=>p[k]).sort((a,b)=>a-b);
    return [0,.25,.5,.75,1].map(f=>nf(v[Math.min(v.length-1,Math.round(f*(v.length-1)))],2)).join(' / ');};
  $('quart').innerHTML=`<table><tr><th>项</th><th>最小/四分一/中位/四分三/最大</th></tr>`+
    D.series.map(s=>`<tr><td>${s.name}</td><td>${q(s.key)}</td></tr>`).join('')+
    `<tr><td>色温</td><td>${q('tint')}</td></tr><tr><td>悲喜比</td><td>${q('gloom')}</td></tr></table>`;
}
fetch('data/climate.json').then(r=>r.json()).then(d=>{
  D=d;ON={};D.series.forEach(s=>ON[s.key]=(s.key==='warm'||s.key==='cool'||s.key==='laugh'||s.key==='tear'));
  legend();draw();readout();
  $('pplOn').onchange=draw;$('smOn').onchange=draw;
}).catch(e=>{$('tip').textContent='冷暖谱数据加载失败：'+e;});
"""

if __name__ == '__main__':
    print(build())
