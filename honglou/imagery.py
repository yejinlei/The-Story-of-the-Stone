"""意象星座：把四十九类意象铺成一张星图。

同一首诗词中并见的两个意象，即为一线（共现）；星之大小＝入诗处数与正文现身回数，
星之方位按类别分野（植物、天象、器物、禽鸟、地理、时间、心理），
距心之远近＝其出现之疏密（密者居内，疏者居外）。

于是星座自成：竹—泪—潇湘一簇，花—冢—葬花一簇，雪—白—茫茫一簇。
此与「图谱」页之力导向意象谱不同：彼论关系，此论星野与情感之冷暖。

产物：docs/data/imagery.json。
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from . import db, graph, paths

CATS = ['植物', '天象', '器物', '禽鸟', '地理', '时间', '心理']
CAT_COLOR = {'植物': '#3f6b5e', '天象': '#3b4a6b', '器物': '#b08d57',
             '禽鸟': '#c2504a', '地理': '#8a7f6d', '时间': '#6b5b95',
             '心理': '#9e2b25'}

COLD = ('悲', '泪', '哭', '孤', '寂', '寒', '残', '衰', '凄', '死', '埋',
        '散', '空', '幻', '愁', '迟暮', '离', '苦', '怨', '远隔', '阻绝',
        '流逝', '肃杀', '埋骨')
WARM = ('盛', '圆', '喜', '香', '暖', '艳', '富贵', '雅', '知音', '圆满',
        '放达', '通灵', '洁净')

CANVAS = (860, 860)
CENTER = (430, 430)


def _person_tokens() -> list[str]:
    """人物名与别名（二字以上）。单字意象（玉、金、春、云）易与人名相混，须扣除。"""
    out: set[str] = set()
    for p in db.q('SELECT name, aliases FROM persons'):
        out.add(p['name'])
        if len(p['name']) == 3:          # 贾宝玉 → 宝玉，王熙凤 → 熙凤
            out.add(p['name'][1:])
        try:
            for a in json.loads(p['aliases'] or '[]'):
                if len(a) >= 2:
                    out.add(a)
                if len(a) == 3:
                    out.add(a[1:])
        except Exception:
            pass
    for t in ('places',):
        for r in db.q(f'SELECT name FROM {t}'):
            if len(r['name']) >= 2:
                out.add(r['name'])
    return sorted(out, key=lambda s: (-len(s), s))


def _tone(text: str) -> str:
    if any(w in text for w in COLD):
        return '冷'
    if any(w in text for w in WARM):
        return '温'
    return '中'


def build(dst: Path | None = None) -> Path:
    out = dst or (paths.SITE_DIR / 'data')
    out.mkdir(parents=True, exist_ok=True)

    imgs = db.q('SELECT image, category, emotion, context FROM imagery')
    names = [i['image'] for i in imgs]
    texts = graph._main_text()
    toks = _person_tokens()

    def adj(t: str, im: str) -> int:
        """单字意象扣去人名、地名中的同字（如『玉』之宝玉、黛玉、妙玉、玉钏）。"""
        raw = (t or '').count(im)
        if len(im) > 1:
            return raw
        sub = sum((t or '').count(n) for n in toks if im in n)
        return max(0, raw - sub)

    occ: dict[str, list] = {}
    for im in names:
        hit = [[c, adj(texts[c], im)] for c in sorted(texts)
               if 0 < c <= 80 and adj(texts[c], im)]
        if hit:
            occ[im] = hit

    pmeta = {p['id']: p for p in db.q('SELECT id, title, chapter, author, text '
                                      'FROM poems')}
    use = Counter()
    poets: dict[str, Counter] = defaultdict(Counter)
    per_poem: dict[str, set] = defaultdict(set)
    for pid, m in pmeta.items():
        a = (m.get('author') or '').strip()
        for im in names:
            n = adj(m.get('text') or '', im)
            if not n:
                continue
            use[im] += n
            per_poem[pid].add(im)
            if a and not a.startswith('（'):
                poets[im][a] += n

    pair = Counter()
    for ims in per_poem.values():
        xs = sorted(ims)
        for i, a in enumerate(xs):
            for b in xs[i + 1:]:
                pair[(a, b)] += 1

    lines = graph._poem_lines()
    samples: dict[str, list[dict]] = {}
    for pid, ls in lines.items():
        m = pmeta.get(pid, {})
        for ln in ls:
            for im in names:
                if im in ln and len(samples.get(im, [])) < 3 and len(ln) < 44:
                    samples.setdefault(im, []).append(dict(
                        t=m.get('title') or '', c=m.get('chapter') or 0,
                        a=(m.get('author') or '').strip(), line=ln.strip()))

    # 布星：按类别分野，密者居内
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for i in imgs:
        by_cat[i['category'] if i['category'] in CATS else '心理'].append(i)
    stars = []
    for ci, cat in enumerate(CATS):
        items = by_cat.get(cat, [])
        items.sort(key=lambda x: -(use[x['image']] + len(occ.get(x['image'], []))))
        a0 = 2 * math.pi * ci / len(CATS)
        span = 2 * math.pi / len(CATS)
        for k, it in enumerate(items):
            im = it['image']
            hit = occ.get(im, [])
            tot = len(hit)
            f = (k + 0.5) / max(1, len(items))
            ang = a0 + span * (0.12 + 0.76 * f)
            rad = 92 + 288 * (1 - (use[im] + tot) / max(
                1, max(use[x['image']] + len(occ.get(x['image'], []))
                       for x in items)))
            cx, cy = CENTER
            stars.append(dict(
                name=im, cat=cat, color=CAT_COLOR[cat],
                x=round(cx + rad * math.sin(ang), 1),
                y=round(cy - rad * math.cos(ang), 1),
                r=round(2.2 + 1.5 * math.sqrt(use[im]) + 0.7 * math.sqrt(tot), 1),
                use=use[im], chapters=tot, total=sum(n for _, n in hit),
                emotion=it['emotion'] or '', context=it['context'] or '',
                tone=_tone((it['emotion'] or '') + (it['context'] or '')),
                poets=[p for p, _ in poets[im].most_common(5)],
                lines=samples.get(im, []),
                # 逐回分布不可截断：从前 40 条，月只见四十五回，其后三十二回尽失
                ev=[[c, n] for c, n in hit],
            ))

    links = [dict(a=a, b=b, n=n) for (a, b), n in pair.most_common(70) if n >= 2]
    doc = dict(canvas=list(CANVAS), center=list(CENTER),
               cats=[dict(name=c, color=CAT_COLOR[c]) for c in CATS],
               stars=stars, links=links)
    (out / 'imagery.json').write_text(
        json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    return out / 'imagery.json'


BODY = """
<h2>意象星座 · 竹与泪、花与冢、雪与茫茫</h2>
<div class="card small">
四十九类意象按类别分野布星：<b>星之大小</b>＝入诗处数与正文现身回数，
<b>距心之远近</b>＝其疏密（密者居内），<b>细线</b>＝同一首诗词中并见（共现）。
点一颗星，即见它的情感指向、语境、现身于哪些回，以及写到它的诗句。
于是星座自成：竹—泪—潇湘一簇，花—冢—葬花一簇，雪—白—茫茫一簇。
<label><input type="checkbox" id="lkOn" checked> 显示共现细线</label>
</div>
<div class="gwrap">
  <div class="card gcanvas"><svg id="sky" viewBox="0 0 860 860"
    preserveAspectRatio="xMidYMid meet"></svg></div>
  <aside class="card gside" id="side"><p class="small">点一颗星。</p></aside>
</div>
"""

JS = r"""
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
let D=null,SEL=null;

function draw(){
  const [W,H]=D.canvas,[cx,cy]=D.center;
  let s='';
  [80,170,260,350,430].forEach(r=>{s+=`<circle cx=${cx} cy=${cy} r=${r} fill="none" stroke="#e3d9c4" stroke-opacity=".55"/>`;});
  D.cats.forEach((c,i)=>{const a=2*Math.PI*i/D.cats.length+Math.PI/D.cats.length;
    const x=cx+400*Math.sin(a),y=cy-400*Math.cos(a);
    s+=`<line x1=${cx} y1=${cy} x2=${x.toFixed(1)} y2=${y.toFixed(1)} stroke="#e3d9c4" stroke-dasharray="3,6"/>`;
    s+=`<text x=${x.toFixed(1)} y=${y.toFixed(1)} text-anchor="middle" fill="${c.color}" font-size="15" font-family="serif" opacity=".85">${esc(c.name)}</text>`;});
  if($('lkOn').checked){
    const by={};D.stars.forEach(t=>by[t.name]=t);
    D.links.forEach(l=>{const a=by[l.a],b=by[l.b];if(!a||!b)return;
      s+=`<line x1=${a.x} y1=${a.y} x2=${b.x} y2=${b.y} stroke="#9e2b25" stroke-opacity="${Math.min(.28,0.06+l.n*0.04)}" stroke-width="${Math.min(1.6,0.5+l.n*0.2)}"/>`;});}
  D.stars.forEach((t,i)=>{
    const on=SEL&&SEL.name===t.name;
    const gl=on?`<circle cx=${t.x} cy=${t.y} r=${t.r+7} fill="${t.color}" opacity=".18"/>`:'';
    s+=gl+`<circle cx=${t.x} cy=${t.y} r=${t.r} fill="${t.color}" fill-opacity="${on?1:.82}" stroke="${on?'#9e2b25':'#fdf8ee'}" stroke-width="${on?2:.8}" data-i="${i}" style="cursor:pointer">`+
      `<title>${esc(t.name)}　${esc(t.emotion)}　入诗 ${t.use} 处 / 现身 ${t.chapters} 回</title></circle>`+
      ((t.r>5.5||on)?`<text x=${t.x} y=${t.y+t.r+11+(i%2)*9} text-anchor="middle" font-size="12" fill="${on?'#9e2b25':'#3a322a'}" font-family="serif" data-i="${i}" style="cursor:pointer">${esc(t.name)}</text>`:'');
  });
  $('sky').innerHTML=s;
  $('sky').querySelectorAll('[data-i]').forEach(el=>{
    el.onclick=()=>{SEL=D.stars[+el.dataset.i];draw();panel(SEL);};});
}
function spark(ev){
  const m=Math.max(1,...ev.map(x=>x[1])),W=300,H=26;
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}">`+
    ev.map(([c,n])=>{const x=(c-1)/80*W,h=Math.max(2,n/m*(H-4));
      return `<rect x=${x.toFixed(1)} y=${(H-h).toFixed(1)} width="3" height=${h.toFixed(1)} fill="#9e2b25" opacity=".65"><title>第${c}回 ${n} 次</title></rect>`;}).join('')+`</svg>`;
}
function panel(t){
  const ls=t.lines.length?t.lines.map(l=>`<div class="small">「${esc(l.line)}」<br><span class="small">— ${esc(l.t)}　第${l.c}回${l.a?'　'+esc(l.a):''}</span></div>`).join(''):'<span class="small">—</span>';
  const T={冷:'#3b4a6b',温:'#9e2b25',中:'#8a7f6d'}[t.tone];
  $('side').innerHTML=`<h3>${esc(t.name)} <span class="small" style="color:${T}">${t.tone}</span></h3>`+
    `<table class="kv"><tr><td>类别</td><td><span style="color:${t.color}">${esc(t.cat)}</span></td></tr>`+
    `<tr><td>情感</td><td>${esc(t.emotion)}</td></tr>`+
    `<tr><td>入诗</td><td>${t.use} 处 · 正文现身 ${t.chapters} 回（${t.total} 次）</td></tr></table>`+
    `<p class="small">${esc(t.context)}</p>`+
    (t.poets.length?`<p class="small"><b>用它的人</b>：${t.poets.map(esc).join('、')}</p>`:'')+
    `<div class="small">正文现身（回次 →）${spark(t.ev)}</div>`+
    `<div style="margin-top:8px"><b>诗句</b><br>${ls}</div>`;
}
fetch('data/imagery.json').then(r=>r.json()).then(d=>{D=d;draw();
  const best=D.stars.slice().sort((a,b)=>(b.use+b.chapters)-(a.use+a.chapters))[0];
  if(best){SEL=best;draw();panel(best);}
  $('lkOn').onchange=draw;
}).catch(e=>{$('side').textContent='星座数据加载失败：'+e;});
"""

if __name__ == '__main__':
    print(build())
