"""批者群像：八本脂批，各是一副面孔。

甲戌、己卯、庚辰、戚序、蒙府、列藏、杨藏、甲辰——八本批语并非一人之手，亦非一副心肠。
此页按本分别统计：批语之数、篇幅之长短、批型（眉/侧/夹）之好尚、
以及四类语气的密度（每千字）：

* **悲悼**：哭 泪 泣 悲 痛 伤 叹 —— 批者在哪里先哭起来；
* **称赏**：奇 妙 趣 隽 神 —— 以赏鉴家自居者；
* **自道**：余 予 我 —— 现身说法、以亲历者自居者（畸笏叟之流）；
* **洩后**：后文 后回 末回 后三十回 迷失 伏 谶 —— 知后事而故作吞吞吐吐者。

另有**版本亲缘**：同回、同批型、起首相同的批语，若并为两本所载，则两本有缘；
其重合之数即为八本的血缘矩阵（戚序、蒙府之相亲可由此见）。

产物：docs/data/annotators.json。
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import db, paths

EDS = ['甲戌', '己卯', '庚辰', '戚序', '蒙府', '列藏', '杨藏', '甲辰']

_HAN = re.compile(r'[^一-鿿]')
_CJK = re.compile(r'[一-鿿]+')

MOODS = [
    dict(key='sad', name='悲悼', color='#9e2b25', s='哭泪泣悲痛伤叹'),
    dict(key='praise', name='称赏', color='#b08d57', s='奇妙趣隽神'),
    dict(key='self', name='自道', color='#3b4a6b', s='余予我'),
    dict(key='future', name='洩后', color='#6b5b95',
         p=('后文', '后回', '后之', '末回', '后三十回', '后数十回', '迷失', '伏线', '谶')),
]

AXES = [dict(key='sad', name='悲悼'), dict(key='praise', name='称赏'),
        dict(key='self', name='自道'), dict(key='future', name='洩后'),
        dict(key='len', name='篇幅'), dict(key='dens', name='用力')]


def _hanzi(t: str) -> str:
    return _HAN.sub('', t or '')


def _mood(t: str, m: dict) -> int:
    n = sum(t.count(c) for c in m.get('s', ''))
    n += sum(t.count(w) for w in m.get('p', ()))
    return n


def build(dst: Path | None = None) -> Path:
    out = dst or (paths.SITE_DIR / 'data')
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for r in db.q('SELECT chapter, text, editions, atype, ink FROM v_anno ORDER BY id'):
        try:
            eds = json.loads(r['editions'] or '[]')
        except Exception:
            eds = []
        rows.append(dict(ch=r['chapter'], text=r['text'] or '', eds=eds,
                         atype=r['atype'] or '', ink=r['ink'] or ''))

    stats = []
    for e in EDS:
        rs = [r for r in rows if e in r['eds']]
        if not rs:
            stats.append(dict(name=e, n=0))
            continue
        chars = sum(len(_hanzi(r['text'])) for r in rs)
        hz = ''.join(_hanzi(r['text']) for r in rs)
        k = max(1, len(hz)) / 1000
        den = {m['key']: round(_mood(hz, m) / k, 2) for m in MOODS}
        types = Counter(r['atype'] or '未标' for r in rs)
        curve = Counter(r['ch'] for r in rs if r['ch'] and r['ch'] > 0)
        samples = []
        for r in sorted(rs, key=lambda x: -len(x['text']))[:3]:
            samples.append(dict(ch=r['ch'], kind='最长', text=r['text'][:220]))
        for m in MOODS[:2]:
            hit = [r for r in rs if _mood(_hanzi(r['text']), m)]
            for r in sorted(hit, key=lambda x: -_mood(_hanzi(x['text']), m))[:2]:
                samples.append(dict(ch=r['ch'], kind=m['name'], text=r['text'][:200]))
        stats.append(dict(
            name=e, n=len(rs), chars=chars,
            avg=round(chars / len(rs), 1),
            chapters=len(curve),
            dens=round(len(rs) / 80, 2),
            types=dict(types), den=den,
            curve=[[c, curve[c]] for c in sorted(curve)],
            samples=samples))

    # 版本亲缘：同回、同批型、起首八字相同者视为同一条批语
    sig: dict[tuple, set] = defaultdict(set)
    for r in rows:
        head = ''.join(_CJK.findall(r['text']))[:8]
        if len(head) < 4 or not r['eds']:
            continue
        sig[(r['ch'], r['atype'], head)] |= set(r['eds'])
    matrix = [[0] * len(EDS) for _ in EDS]
    for s in sig.values():
        for i, a in enumerate(EDS):
            if a not in s:
                continue
            for j, b in enumerate(EDS):
                if b in s:
                    matrix[i][j] += 1

    # 雷达：各轴按八本之最大值归一
    live = [s for s in stats if s.get('n')]
    norm = {}
    for ax in AXES:
        k = ax['key']
        vals = []
        for s in live:
            if k in ('len', 'dens'):
                vals.append(s[k if k == 'dens' else 'avg'])
            else:
                vals.append(s['den'][k])
        mx = max(vals) or 1
        for s in live:
            v = s['avg'] if k == 'len' else (s['dens'] if k == 'dens' else s['den'][k])
            norm.setdefault(s['name'], {}).update({k: v, k + '_r': round(v / mx, 3)})

    for s in stats:
        if s.get('n'):
            s['ax'] = norm[s['name']]

    doc = dict(eds=EDS, axes=AXES, moods=[dict(key=m['key'], name=m['name'],
                                               color=m['color']) for m in MOODS],
               stats=stats, matrix=matrix)
    (out / 'annotators.json').write_text(
        json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    return out / 'annotators.json'


BODY = """
<h2>批者群像 · 八本脂批，各是一副心肠</h2>
<div class="card small">
甲戌、己卯、庚辰、戚序、蒙府、列藏、杨藏、甲辰八本批语，向以为一人之手，其实不然。
按本统计批语之数、篇幅长短、批型好尚，以及四类语气的<b>每千字密度</b>：
<b>悲悼</b>（哭泪泣悲痛伤叹）、<b>称赏</b>（奇妙趣隽神）、<b>自道</b>（余予我，以亲历者自居）、
<b>洩后</b>（后文、末回、迷失、伏、谶——知后事而故作吞吐）。
左为六维画像（篇幅＝平均字数，用力＝每回批语数），右为所点之本的细目。
</div>
<div class="gwrap">
  <div class="card gcanvas"><svg id="rd" viewBox="0 0 440 420"
    preserveAspectRatio="xMidYMid meet"></svg></div>
  <aside class="card gside">
    <div class="gtools"><span class="small">本　</span><span id="pick"></span></div>
    <div id="info" class="small"></div>
  </aside>
</div>
<div class="card"><h3>语气密度（每千字）</h3><div id="tbl"></div></div>
<div class="card"><h3>批语随回次分布</h3>
  <div class="gtools"><span class="small">叠放　</span><span id="cpick"></span></div>
  <svg id="cv" viewBox="0 0 1080 260" preserveAspectRatio="xMidYMid meet"></svg></div>
<div class="card"><h3>版本亲缘</h3><div class="small">同回、同批型、起首八字相同的批语，
  若并为两本所载，则两本有缘。<b>对角＝该本独载之数，非对角＝与他本重合之数。</b>
  此书体例「后出版本的批语与前面某本文字相同的，不再列出」，故非对角多为空——
  <b>八本批语重合之少，本身即一发现</b>：可见汇校者已先行去重，今人所见各本之数即其独有之数。</div>
  <div id="mx"></div></div>
<div class="card"><h3>批语样例</h3><div id="samp"></div></div>
"""

JS = r"""
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const nf=(v,n)=>(Math.round(v*Math.pow(10,n))/Math.pow(10,n)).toFixed(n);
let D=null,SEL=new Set(),CUR=null;

function drawRadar(){
  const R=140,cx=220,cy=210,n=D.axes.length;
  const pt=(i,r)=>[cx+r*Math.sin(i/n*2*Math.PI),cy-r*Math.cos(i/n*2*Math.PI)];
  let s='';
  [0.5,1].forEach(f=>{s+='<polygon points="'+D.axes.map((_,i)=>pt(i,R*f).map(x=>Math.round(x)).join(',')).join(' ')+
    '" fill="none" stroke="#e3d9c4"/>';});
  for(let i=0;i<n;i++){const [x,y]=pt(i,R);
    s+=`<line x1=${cx} y1=${cy} x2=${Math.round(x)} y2=${Math.round(y)} stroke="#e3d9c4"/>`;
    const [lx,ly]=pt(i,R+24);
    s+=`<text x=${Math.round(lx)} y=${Math.round(ly)} text-anchor="middle" fill="#5d5449" font-size="13" font-family="serif">${D.axes[i].name}</text>`;}
  D.stats.forEach(st=>{
    if(!st.n||!st.ax)return;
    const on=SEL.has(st.name);
    const pts=D.axes.map((a,i)=>pt(i,R*Math.max(.03,st.ax[a.key+'_r'])).map(x=>Math.round(x)).join(',')).join(' ');
    s+=`<polygon points="${pts}" fill="${on?col(st.name):'none'}" fill-opacity="${on?.10:0}" stroke="${col(st.name)}" stroke-opacity="${on?.95:.22}" stroke-width="${on?2:1}"/>`;
    if(on)D.axes.forEach((a,i)=>{const [x,y]=pt(i,R*Math.max(.03,st.ax[a.key+'_r']));
      s+=`<circle cx=${Math.round(x)} cy=${Math.round(y)} r=2.6 fill="${col(st.name)}"/>`;});
  });
  $('rd').innerHTML=s;
}
const PAL={'甲戌':'#9e2b25','己卯':'#3b4a6b','庚辰':'#3f6b5e','戚序':'#b08d57',
  '蒙府':'#6b5b95','列藏':'#c2504a','杨藏':'#7d1f1b','甲辰':'#8a7f6d'};
const col=e=>PAL[e]||'#5d5449';

function picks(){
  $('pick').innerHTML=D.eds.map(e=>{const st=D.stats.find(x=>x.name===e)||{n:0};
    return `<button data-e="${e}" style="border-color:${col(e)};color:${SEL.has(e)?col(e):'#8a7f6d'};opacity:${st.n?1:.4}" ${st.n?'':'disabled'}>${e} ${st.n}</button>`;}).join(' ');
  $('pick').querySelectorAll('button').forEach(b=>{b.onclick=()=>{const e=b.dataset.e;
    SEL.has(e)?SEL.delete(e):SEL.add(e);CUR=e;picks();drawRadar();info(CUR);curve();samp();};});
  $('cpick').innerHTML=D.eds.map(e=>`<button data-c="${e}" style="border-color:${col(e)};color:${SEL.has(e)?col(e):'#8a7f6d'}">${e}</button>`).join(' ');
  $('cpick').querySelectorAll('button').forEach(b=>{b.onclick=()=>{const e=b.dataset.c;
    SEL.has(e)?SEL.delete(e):SEL.add(e);picks();drawRadar();curve();samp();};});
}
function info(e){
  const st=D.stats.find(x=>x.name===e);
  if(!st||!st.n){$('info').innerHTML='<p class="small">此本无批语入库。</p>';return;}
  const ty=Object.entries(st.types||{}).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<span class="tag">${esc(k)} ${v}</span>`).join('');
  $('info').innerHTML=`<h3>${esc(st.name)}</h3>`+
    `<table class="kv"><tr><td>批语</td><td>${st.n} 条 · ${st.chars.toLocaleString()} 字</td></tr>`+
    `<tr><td>平均</td><td>${st.avg} 字／条</td></tr>`+
    `<tr><td>覆盖</td><td>${st.chapters} 回（每回 ${st.dens} 条）</td></tr></table>`+
    `<div>批型　${ty}</div>`+
    `<p class="small">悲悼 ${nf(st.den.sad,2)}　称赏 ${nf(st.den.praise,2)}　自道 ${nf(st.den.self,2)}　洩后 ${nf(st.den.future,2)}　（每千字）</p>`+
    (st.n < 30 ? '<p class="small">此本存批甚少（' + st.n + ' 条），各项比例不足为据，聊备一格。</p>' : '');
}
function tbl(){
  const rows=D.stats.filter(s=>s.n).map(st=>{
    const bar=(v,mx,c)=>`<span style="display:inline-block;height:8px;width:${Math.max(1,Math.round(v/mx*70))}px;background:${c};margin-right:5px"></span>`;
    const mxs=Math.max(...D.stats.filter(s=>s.n).map(s=>s.den.sad))||1;
    const mxp=Math.max(...D.stats.filter(s=>s.n).map(s=>s.den.praise))||1;
    const mxf=Math.max(...D.stats.filter(s=>s.n).map(s=>s.den.future))||1;
    return `<tr><td><b style="color:${col(st.name)}">${esc(st.name)}</b></td>`+
      `<td>${st.n}</td><td>${nf(st.avg,1)}</td>`+
      `<td>${bar(st.den.sad,mxs,'#9e2b25')}${nf(st.den.sad,1)}</td>`+
      `<td>${bar(st.den.praise,mxp,'#b08d57')}${nf(st.den.praise,1)}</td>`+
      `<td>${bar(st.den.future,mxf,'#6b5b95')}${nf(st.den.future,1)}</td>`+
      `<td>${nf(st.den.self,1)}</td></tr>`;}).join('');
  $('tbl').innerHTML=`<table><tr><th>本</th><th>批语</th><th>均字</th><th>悲悼</th><th>称赏</th><th>洩后</th><th>自道</th></tr>${rows}</table>`;
}
function curve(){
  const W=1080,H=260,PL=42,PR=14,PT=14,PB=34;
  let mx=1;
  D.stats.forEach(st=>{if(!st.n||!SEL.has(st.name))return;
    st.curve.forEach(([c,n])=>{if(n>mx)mx=n;});});
  const X=c=>PL+c/80*(W-PL-PR), Y=v=>H-PB-v/mx*(H-PT-PB);
  let s='';
  for(let f=0;f<=3;f++){const y=PT+(H-PT-PB)*f/3;
    s+=`<line x1=${PL} y1=${y} x2=${W-PR} y2=${y} stroke="#e3d9c4"/>`+
       `<text x=${PL-6} y=${y+4} text-anchor="end" fill="#8a7f6d" font-size="11">${Math.round(mx*(1-f/3))}</text>`;}
  D.stats.forEach(st=>{if(!st.n||!SEL.has(st.name))return;
    const d=st.curve.map(([c,n],i)=>(i?'L':'M')+X(c).toFixed(1)+' '+Y(n).toFixed(1)).join(' ');
    s+=`<path d="${d}" fill="none" stroke="${col(st.name)}" stroke-width="1.6" opacity=".9"/>`;});
  for(let c=10;c<=80;c+=10)s+=`<text x=${X(c)} y=${H-PB+16} text-anchor="middle" fill="#8a7f6d" font-size="11">${c}</text>`;
  $('cv').innerHTML=s;
}
function mx(){
  let m=Math.max(...[].concat(...D.matrix));
  let s='<table><tr><th></th>'+D.eds.map(e=>`<th>${e}</th>`).join('')+'</tr>';
  D.matrix.forEach((row,i)=>{
    s+='<tr><th>'+D.eds[i]+'</th>'+row.map((v,j)=>{
      const bg=i===j?`background:${col(D.eds[i])};color:#fff`:`background:rgba(158,43,37,${(v/m*0.75).toFixed(2)})`;
      return `<td style="${bg};text-align:center">${v||''}</td>`;}).join('')+'</tr>';});
  $('mx').innerHTML=s+'</table>';
}
function samp(){
  const es=[...SEL];
  $('samp').innerHTML=es.length?es.map(e=>{const st=D.stats.find(x=>x.name===e);
    if(!st||!st.n)return '';
    return `<div class="card"><h3 style="color:${col(e)}">${esc(e)}</h3>`+
      (st.samples||[]).map(s=>`<p><span class="tag">第${s.ch}回·${esc(s.kind)}</span><br>${esc(s.text)}</p>`).join('')+
      '</div>';}).join(''):'<p class="small">选一本。</p>';
}
fetch('data/annotators.json').then(r=>r.json()).then(d=>{
  D=d;['庚辰','甲戌','戚序'].forEach(e=>{const st=D.stats.find(x=>x.name===e);if(st&&st.n)SEL.add(e);});
  CUR='庚辰';picks();drawRadar();info(CUR);tbl();curve();mx();samp();
}).catch(e=>{$('info').textContent='批者数据加载失败：'+e;});
"""

if __name__ == '__main__':
    print(build())
