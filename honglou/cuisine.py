"""食单与茶酒谱：红楼满纸皆是吃喝，把名物逐回钩出，见其由盛转淡。

名物分八类：茶汤、酒醴、粥饭、点心糕饵、荤鲜、补养膏饵、果品、药饵。
每种名物的每一次现身，连同前后原文、在场说话者与节候一并录入；
另以「宴席词」（摆饭、开宴、入席、酒席、摆酒、吃酒、斟酒、行令、赏月……）
逐回计数，于是食事由密转疏之迹自现——前七十回满案酒肉，其后渐渐地只剩粥露。

产物：docs/data/cuisine.json
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import db, paths

FOODS = [
    # 茶汤
    ('枫露茶', '茶汤'), ('老君眉', '茶汤'), ('六安茶', '茶汤'), ('暹罗茶', '茶汤'),
    ('杏仁茶', '茶汤'), ('酸梅汤', '茶汤'), ('合欢汤', '茶汤'),
    ('虾丸鸡皮汤', '茶汤'), ('野鸡崽子汤', '茶汤'), ('火肉白菜汤', '茶汤'),
    ('建莲红枣汤', '茶汤'),
    # 酒醴
    ('黄酒', '酒醴'), ('烧酒', '酒醴'), ('惠泉酒', '酒醴'), ('合欢花酒', '酒醴'),
    # 粥饭
    ('碧粳粥', '粥饭'), ('燕窝粥', '粥饭'), ('鸭子肉粥', '粥饭'),
    ('枣儿粳米粥', '粥饭'),
    # 点心糕饵
    ('奶油松瓤卷酥', '点心'), ('卷酥', '点心'), ('枣泥山药糕', '点心'),
    ('桂花糖蒸栗粉糕', '点心'), ('藕粉桂糖糕', '点心'), ('菱粉糕', '点心'),
    ('如意糕', '点心'), ('鸡油卷儿', '点心'), ('豆腐皮包子', '点心'),
    ('月饼', '点心'), ('粽子', '点心'), ('元宵', '点心'), ('糕点', '点心'),
    # 荤鲜
    ('螃蟹', '荤鲜'), ('火腿炖肘子', '荤鲜'), ('火腿', '荤鲜'),
    ('牛乳蒸羊羔', '荤鲜'), ('蒸羊羔', '荤鲜'), ('鹿肉', '荤鲜'),
    ('鹿筋', '荤鲜'), ('风腌果子狸', '荤鲜'), ('糟鹅掌', '荤鲜'), ('鸭信', '荤鲜'),
    ('酸笋鸡皮汤', '荤鲜'), ('炸鹌鹑', '荤鲜'), ('酒酿清蒸鸭子', '荤鲜'),
    ('虾丸鸡皮汤', '荤鲜'), ('鸡髓笋', '荤鲜'), ('鸽子蛋', '荤鲜'),
    ('茄鲞', '荤鲜'),
    # 补养膏饵
    ('燕窝', '补养'), ('茯苓霜', '补养'), ('玫瑰露', '补养'),
    ('玫瑰清露', '补养'), ('木樨清露', '补养'), ('桂圆', '补养'),
    ('荔枝', '补养'), ('人参养荣丸', '补养'), ('冷香丸', '补养'),
    # 果品
    ('藕', '果品'), ('菱角', '果品'), ('西瓜', '果品'),
]

CATS = ['茶汤', '酒醴', '粥饭', '点心', '荤鲜', '补养', '果品']
CAT_COLOR = {'茶汤': '#3f6b5e', '酒醴': '#b08d57', '粥饭': '#8a7f6d',
             '点心': '#c2504a', '荤鲜': '#9e2b25', '补养': '#3b4a6b',
             '果品': '#6b8a3f'}

BANQUET = ('摆饭', '开宴', '上席', '入席', '酒席', '摆酒', '吃酒', '斟酒',
           '行令', '行酒令', '家宴', '请客', '赏月', '赏桂花', '接风', '宴息')

SEASON = {'元宵': '元宵', '灯节': '元宵', '上元': '元宵', '端午': '端午',
          '中秋': '中秋', '重阳': '重阳', '除夕': '除夕', '年下': '除夕',
          '腊月': '腊月', '冬至': '冬至', '芒种': '芒种', '立冬': '立冬',
          '赏桂花': '秋', '吃螃蟹': '秋', '烤鹿肉': '冬', '雪': '冬'}

# 分四段看构成：一案到底如何从满桌菜蔬退到几色供月之果
SEGS = [(1, 40, '前四十回'), (41, 60, '四十一至六十'),
        (61, 70, '六十一至七十'), (71, 80, '七十一至八十')]


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


def _who(text: str, i: int, j: int, names: list[str]) -> str:
    win = text[max(0, i - 46):j + 20]
    best = ''
    for nm in names:
        if nm in win and len(nm) > len(best):
            best = nm
    return best


def build(dst: Path | None = None) -> Path:
    out = dst or (paths.SITE_DIR / 'data')
    out.mkdir(parents=True, exist_ok=True)
    rows = db.q('SELECT chapter, text FROM v_main ORDER BY chapter, id')
    names = _persons()

    hits, per_cat = [], Counter()
    for row in rows:
        ch, text = row['chapter'], row['text'] or ''
        for name, cat in FOODS:
            for m in re.finditer(re.escape(name), text):
                i, j = m.start(), m.end()
                win = text[max(0, i - 40):j + 40]
                season = next((v for k, v in SEASON.items() if k in win), '')
                hits.append(dict(ch=ch, name=name, cat=cat,
                                 ctx=text[max(0, i - 44):j + 44].replace('\n', ''),
                                 who=_who(text, i, j, names), season=season))
                per_cat[name] += 1
    # 逐回：宴席词与名物（另备千字密度，以除回目长短之差）
    foods_by_ch, bang_by_ch, chlen = Counter(), Counter(), Counter()
    for row in rows:
        ch, text = row['chapter'], row['text'] or ''
        if not ch:
            continue
        bang_by_ch[ch] += sum(text.count(w) for w in BANQUET)
        chlen[ch] += len(text)
    for h in hits:
        foods_by_ch[h['ch']] += 1
    series = []
    for ch in sorted(set(list(bang_by_ch) + list(foods_by_ch))):
        ln = max(1, chlen.get(ch, 0))
        series.append(dict(ch=ch, feast=bang_by_ch.get(ch, 0),
                           food=foods_by_ch.get(ch, 0),
                           feast_d=round(bang_by_ch.get(ch, 0) / ln * 1000, 3),
                           food_d=round(foods_by_ch.get(ch, 0) / ln * 1000, 3),
                           len=ln))

    items = []
    for name, cat in FOODS:
        sel = [h for h in hits if h['name'] == name]
        if not sel:
            continue
        items.append(dict(name=name, cat=cat, n=len(sel),
                          chapters=sorted({h['ch'] for h in sel}),
                          hits=sel))
    items.sort(key=lambda it: (-it['n'], it['cat'], it['name']))

    cats = [dict(name=c, n=sum(it['n'] for it in items if it['cat'] == c),
                 kinds=[it['name'] for it in items if it['cat'] == c])
            for c in CATS]
    top_ch = sorted(bang_by_ch.items(), key=lambda kv: -kv[1])[:8]

    segs = []
    for lo, hi, name in SEGS:
        sel = [h for h in hits if lo <= h['ch'] <= hi and h['ch'] > 0]
        if not sel:
            continue
        kinds = Counter(h['name'] for h in sel)
        cats_c = Counter(h['cat'] for h in sel)
        chars = sum(chlen[c] for c in range(lo, hi + 1) if c in chlen)
        top3 = sum(n for _, n in kinds.most_common(3))
        segs.append(dict(name=name, lo=lo, hi=hi, n=len(sel), kinds=len(kinds),
                         density=round(len(kinds) / max(1, chars) * 10000, 2),
                         conc=round(top3 / len(sel), 2),
                         cats=[[c, cats_c.get(c, 0)] for c in CATS],
                         top=kinds.most_common(5)))

    doc = dict(items=items, cats=cats, series=series, top=top_ch, segs=segs,
               colors=CAT_COLOR,
               stats=dict(kinds=len(items), n=len(hits),
                          chaps=len({h['ch'] for h in hits if h['ch']}),
                          feast=sum(bang_by_ch.values()),
                          foodmax=(max(foods_by_ch.items(), key=lambda kv: kv[1])
                                   if foods_by_ch else (0, 0))[0]))
    fp = out / 'cuisine.json'
    fp.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    return fp


BODY = """
<h2>食单与茶酒谱 · 由盛转淡的一桌饭</h2>
<div class="card small">
八类名物——茶汤、酒醴、粥饭、点心、荤鲜、补养膏饵、果品——逐回钩出每一次现身，
连前后原文、在场说话者与节候一并录入。另以「摆饭、开宴、入席、酒席、摆酒、吃酒、
斟酒、行令、赏月、赏桂花……」为宴席之辞，逐回点数。
<b>须辩白一句</b>：宴席之辞的密度并不随回次衰减（每千字自 0.21 升至 0.49），
真正退场的是<b>名物的种类</b>——由中段的 1.6 种／万字降到后段的 0.96，
而集中度由 0.58 升到 0.67。桌子照旧摆着，摆来摆去却只剩那几样了。
</div>
<div class="grid" id="food-cards"></div>
<h2>四段构成</h2>
<div class="card"><svg id="segs" viewBox="0 0 1080 210"
  preserveAspectRatio="xMidYMid meet"></svg></div>
<div class="card"><table id="segtab"></table></div>
<h2>宴席疏密</h2>
<div class="card gcanvas">
  <div class="gtools">
    <button id="fDens" class="on">千字密度</button>
    <button id="fAbs">绝对次数</button>
    <span class="gstat" id="fstat"></span>
  </div>
  <svg id="feast" viewBox="0 0 1080 300" preserveAspectRatio="xMidYMid meet"></svg>
</div>
<h2>名物</h2>
<div class="card">
  <div class="gtools" id="fcats"></div>
  <div class="legend" id="flegend"></div>
</div>
<div class="gwrap">
  <div class="card samples" id="flist"></div>
  <aside class="card gside" id="fside"><p class="small">点一条看原文。</p></aside>
</div>
"""

JS = r"""
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
let D=null,CAT='全部',MODE='dens',SEL=null;

function cards(){
  const rows=[['录入名物',`${D.stats.kinds} 种`],['现身次数',`${D.stats.n} 处`],
    ['涉回',`${D.stats.chaps} 回`],['宴席词总计',`${D.stats.feast} 次`],
    ['名物最密回',`第 ${D.stats.foodmax} 回`],
    ['宴席最密回',D.top.slice(0,3).map(t=>`第${t[0]}回（${t[1]}）`).join('　')]];
  $('food-cards').innerHTML=rows.map(r=>
    `<div class="card"><div class="small">${esc(r[0])}</div><big>${esc(r[1])}</big></div>`).join('');
}

function chart(){
  const S=D.series.filter(s=>s.ch>0),W=1080,H=300,PL=44,PB=34;
  const fk=MODE==='dens'?'food_d':'food', bk=MODE==='dens'?'feast_d':'feast';
  const fm=Math.max(...S.map(s=>s[fk]),0.001), bm=Math.max(...S.map(s=>s[bk]),0.001);
  const x=i=>PL+i*(W-PL-16)/(Math.max(1,S.length-1));
  let s='';
  [0,.5,1].forEach(f=>{const yy=16+(H-PB-16)*f;
    s+=`<line x1=${PL} y1=${yy} x2=${W-16} y2=${yy} stroke="#e3d9c4"/>`;});
  S.forEach((d,i)=>{const h=(d[bk]/bm)*(H-PB-24);
    if(h<=0)return;
    s+=`<rect x=${x(i)-3} y=${H-PB-h} width=6 height=${h} fill="#c2504a" opacity=".55"><title>第${d.ch}回：宴席词 ${d.feast}（${d.feast_d}/千字）</title></rect>`;});
  let p='';
  S.forEach((d,i)=>{p+=(p?'L':'M')+x(i)+' '+((H-PB)-(d[fk]/fm)*(H-PB-24));});
  s+=`<path d="${p}" fill="none" stroke="#3f6b5e" stroke-width="1.4" opacity=".8"/>`;
  [1,20,40,60,80].forEach(c=>{const i=S.findIndex(d=>d.ch===c); if(i<0)return;
    s+=`<text x=${x(i)} y=${H-14} text-anchor="middle" font-size=10.5 fill="#8a7f6d" font-family="serif">${c}</text>`;});
  [38,41,49,53,75].forEach(c=>{const i=S.findIndex(d=>d.ch===c); if(i<0)return;
    const d=S[i],yy=(H-PB)-(d[fk]/fm)*(H-PB-24);
    s+=`<circle cx=${x(i)} cy=${yy} r=3 fill="#9e2b25"/>`;
    s+=`<text x=${x(i)} y=${yy-7} text-anchor="middle" font-size=10 fill="#9e2b25" font-family="serif">${c}回</text>`;});
  $('feast').innerHTML=s;
  $('fstat').textContent=MODE==='dens'?'每千字计（除回目长短之差）：红柱＝宴席词，绿线＝名物'
    :'绝对次数：红柱＝宴席词，绿线＝名物';
}

function segs(){
  const W=1080,H=210,PL=112,PB=26, rowH=(H-PB-14)/D.segs.length;
  let s='';
  D.segs.forEach((g,i)=>{
    const tot=g.cats.reduce((a,c)=>a+c[1],0)||1, y=14+i*rowH;
    s+=`<text x=${PL-10} y=${y+rowH/2} text-anchor="end" font-size=12 fill="#5d5449" font-family="serif">${esc(g.name)}</text>`;
    let cx=PL;
    g.cats.forEach(c=>{
      if(!c[1])return;
      const w=(c[1]/tot)*(W-PL-150);
      const col=D.colors[c[0]]||'#8a7f6d';
      s+=`<rect x=${cx} y=${y+6} width=${w} height=${rowH-20} fill="${col}" opacity=".72"><title>${esc(g.name)}　${esc(c[0])} ${c[1]} 处（${Math.round(c[1]/tot*100)}%）</title></rect>`;
      if(w>34) s+=`<text x=${cx+w/2} y=${y+6+(rowH-20)/2+4} text-anchor="middle" font-size=10.5 fill="#fffdf8" font-family="serif">${esc(c[0])}</text>`;
      cx+=w;
    });
    s+=`<text x=${W-140} y=${y+rowH/2} font-size=11 fill="#8a7f6d" font-family="serif">${g.kinds} 种 / ${g.n} 处　集中 ${g.conc}</text>`;
  });
  $('segs').innerHTML=s;
  $('segtab').innerHTML=`<thead><tr><th>段落</th><th>处数</th><th>种类</th>`
    +`<th>种类密度（种/万字）</th><th>前三名集中度</th><th>最常现身</th></tr></thead><tbody>`
    +D.segs.map(g=>`<tr><td>${esc(g.name)}</td><td>${g.n}</td><td>${g.kinds}</td>`
      +`<td>${g.density}</td><td>${g.conc}</td><td>${g.top.map(t=>esc(t[0])+'·'+t[1]).join('　')}</td></tr>`).join('')
    +`</tbody>`;
}

function list(){
  const items=(CAT==='全部'?D.items:D.items.filter(i=>i.cat===CAT));
  $('flist').innerHTML=items.map(it=>{
    const cookie=D.colors[it.cat]||'#8a7f6d';
    return `<div><span class="tag" style="border-color:${cookie};color:${cookie}">${esc(it.cat)}</span>`
      +`<b>${esc(it.name)}</b><span class="tag red">${it.n} 处</span>`
      +`<span class="tag">第${it.chapters.slice(0,6).join('、')}回${it.chapters.length>6?'…':''}</span>`
      +`<br><span class="small">${esc(it.hits[0].ctx)}</span></div>`;
  }).join('');
  $('flist').querySelectorAll('div').forEach((el,i)=>{el.style.cursor='pointer';el.onclick=()=>side(items[i]);});
}

function side(it){
  SEL=it;
  let h=`<h3>${esc(it.name)}</h3><p class="small">${esc(it.cat)} · 现身 ${it.n} 处 · `
    +`第${it.chapters.join('、')}回</p>`;
  h+=it.hits.slice(0,10).map(x=>`<div style="border-bottom:1px dotted #e9ddc7;padding:3px 0">`
    +`<span class="tag">第${x.ch}回</span>${x.who?`<b>${esc(x.who)}</b>`:''}`
    +(x.season?`<span class="tag">${esc(x.season)}</span>`:'')
    +`<br><span class="small">…${esc(x.ctx)}…</span></div>`).join('');
  $('fside').innerHTML=h;
}

fetch('data/cuisine.json').then(r=>r.json()).then(d=>{
  D=d;cards();chart();segs();list();
  $('fcats').innerHTML=['全部'].concat(D.cats.map(c=>c.name)).map(c=>
    `<button class="${c===CAT?'on':''}" data-c="${esc(c)}">${esc(c)}</button>`).join('');
  $('fcats').querySelectorAll('button').forEach(b=>b.onclick=()=>{CAT=b.dataset.c;list();
    $('fcats').querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));});
  $('flegend').innerHTML=D.cats.map(c=>`<span><i style="background:${D.colors[c.name]}"></i>${esc(c.name)} ${c.kinds.length} 种 / ${c.n} 处</span>`).join('');
  $('fDens').onclick=()=>{MODE='dens';$('fDens').classList.add('on');$('fAbs').classList.remove('on');chart();};
  $('fAbs').onclick=()=>{MODE='abs';$('fAbs').classList.add('on');$('fDens').classList.remove('on');chart();};
});
"""
