"""生成静态站点到 docs/（GitHub Pages 直接托管）。

页面
----
index.html        总览：三恨、本体论规模、入口
read.html         正文与脂批对照（按回切换，可按版本/批注类型过滤）
entities.html     实体浏览：人物 / 地点 / 物件 / 概念 / 意象 / 典故
poems.html        诗词本体：体裁、作者、意象、谶应
debate.html       多 Agent 推演全过程（含技术组的统计证据）
continuation.html 续写正文 + 风格门禁 + 脂砚斋批点
graph.html        本体图谱（自绘力导向图，无外部依赖）

数据全部由 DuckDB 导出为静态 JSON，浏览器不需要任何数据库。
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import db, paths, theme

SITE = paths.SITE_DIR
DATA = SITE / 'data'
ASSET = SITE / 'assets'
for d in (SITE, DATA, ASSET, DATA / 'chapters'):
    d.mkdir(parents=True, exist_ok=True)

CSS = theme.CSS   # 视觉主题（宣纸·朱印·诗笺·手稿纸）见 honglou/theme.py

JS_READ = """
const state={chap:1,eds:new Set(),types:new Set(),onlyAnno:false};
async function load(n){
  const r=await fetch(`data/chapters/${String(n).padStart(3,'0')}.json`);
  return r.json();
}
function render(d){
  const box=document.getElementById('content');
  box.innerHTML='';
  const hd=document.createElement('div');hd.className='hd';
  hd.textContent=`第${d.no}回　${d.title}`;box.appendChild(hd);
  d.blocks.forEach(b=>{
    const p=document.createElement('div');
    if(b.kind==='批语'||b.kind==='回前批'||b.kind==='回后批'){
      if(!state.eds.size||b.editions.some(e=>state.eds.has(e))){
        if(!state.types.size||state.types.has(b.atype||'批语')){
          p.className='anno '+b.ink;
          p.innerHTML=`<span class="src">${b.editions.join('·')||'批'}${b.atype?'·'+b.atype:''}</span>${esc(b.text)}`;
        } else return;
      } else return;
    }else if(b.kind==='校记'){
      p.className='note';p.textContent='〔校〕'+b.text;
    }else if(b.kind==='回目'){
      p.className='hd';p.textContent=b.text;
    }else{
      if(state.onlyAnno) return;
      p.className='main-p';p.textContent=b.text;
    }
    box.appendChild(p);
  });
  document.getElementById('title').textContent=`第${d.no}回　${d.title}`;
}
function esc(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function toggle(set,v,btn){
  if(set.has(v)){set.delete(v);btn.classList.remove('on')}else{set.add(v);btn.classList.add('on')}
  apply();
}
function apply(){render(window.CUR);}
window.onload=async()=>{
  const d=await load(1);window.CUR=d;render(d);
  document.getElementById('chap').onchange=async e=>{
    const d=await load(+e.target.value);window.CUR=d;render(d);};
  document.querySelectorAll('[data-ed]').forEach(b=>{
    b.onclick=()=>{const v=b.dataset.ed;
      state.eds.has(v)?state.eds.delete(v):state.eds.add(v);
      b.classList.toggle('on');render(window.CUR);};});
  document.getElementById('onlyAnno').onchange=e=>{
    state.onlyAnno=e.target.checked;render(window.CUR);};
};
"""

JS_GRAPH = """
const el=document.getElementById('graph');
let nodes=[],links=[],pos=[],vel=[];
fetch('data/graph.json').then(r=>r.json()).then(g=>{
  nodes=g.nodes;links=g.links;
  const idx={};nodes.forEach((n,i)=>idx[n.id]=i);
  links=links.filter(l=>idx[l.source]!==undefined&&idx[l.target]!==undefined);
  pos=nodes.map(()=>({x:Math.random()*700+50,y:Math.random()*450+50}));
  vel=nodes.map(()=>({x:0,y:0}));
  const adj=nodes.map(()=>[]);
  links.forEach(l=>{adj[idx[l.source]].push(idx[l.target]);adj[idx[l.target]].push(idx[l.source]);});
  const deg=nodes.map((_,i)=>adj[i].length);
  function step(){
    for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){
      let dx=pos[j].x-pos[i].x,dy=pos[j].y-pos[i].y;
      let d2=dx*dx+dy*dy||1,d=Math.sqrt(d2);
      const rep=1200/d2;
      vel[i].x-=rep*dx/d;vel[i].y-=rep*dy/d;
      vel[j].x+=rep*dx/d;vel[j].y+=rep*dy/d;
    }
    links.forEach(l=>{
      const a=idx[l.source],b=idx[l.target];
      let dx=pos[b].x-pos[a].x,dy=pos[b].y-pos[a].y;
      let d=Math.sqrt(dx*dx+dy*dy)||1;
      const f=(d-70)*0.02;
      vel[a].x+=f*dx/d;vel[a].y+=f*dy/d;
      vel[b].x-=f*dx/d;vel[b].y-=f*dy/d;
    });
    pos.forEach((p,i)=>{
      vel[i].x*=0.85;vel[i].y*=0.85;
      p.x+=Math.max(-8,Math.min(8,vel[i].x));
      p.y+=Math.max(-8,Math.min(8,vel[i].y));
      p.x=Math.max(20,Math.min(780,p.x));p.y=Math.max(20,Math.min(480,p.y));
    });
    draw();requestAnimationFrame(step);
  }
  function draw(){
    let s=`<svg width="800" height="500">`;
    links.forEach(l=>{const a=pos[idx[l.source]],b=pos[idx[l.target]];
      s+=`<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="rgba(158,43,37,.22)" stroke-width="0.6"/>`;});
    nodes.forEach((n,i)=>{const p=pos[i];const r=3+Math.min(9,deg[i]*0.7);
      s+=`<circle cx="${p.x}" cy="${p.y}" r="${r}" fill="${n.color||'#8b6914'}" opacity="0.8"/>`;
      if(deg[i]>6)s+=`<text x="${p.x+6}" y="${p.y+4}" font-size="11" fill="#4a4438">${n.name}</text>`;});
    s+='</svg>';el.innerHTML=s;
  }
  step();
});
"""

JS_POEMS = """
fetch('data/poems.json').then(r=>r.json()).then(ps=>{
  const box=document.getElementById('list');
  const genres=[...new Set(ps.map(p=>p.genre))].sort();
  const gsel=document.getElementById('genre');
  genres.forEach(g=>gsel.add(new Option(g,g)));
  function show(){
    const g=gsel.value,k=document.getElementById('kw').value.trim();
    box.innerHTML='';
    ps.filter(p=>(!g||p.genre===g)&&(!k||p.text.includes(k)||(p.title||'').includes(k)))
      .forEach(p=>{
        const d=document.createElement('div');d.className='card';
        d.innerHTML=`<h3>${p.title||'(无题)'}　<span class="small">${p.genre}·${p.author||'未详'}·第${p.chapter}回</span></h3>
        <div class="poem">${p.lines.map(l=>l).join('｜')}</div>
        <div class="small">意象：${(p.images||[]).join('、')||'—'}　句数 ${p.n_lines}　齐言 ${p.main_len}　韵基一致率 ${(p.rhyme||0).toFixed(2)}</div>`;
        box.appendChild(d);
      });
  }
  gsel.onchange=show;document.getElementById('kw').oninput=show;show();
});
"""


def _page(title: str, body: str, active: str = '', extra_js: str = '') -> str:
    return theme.page(title, body, active, extra_js)


def _paras(text: str) -> str:
    """续写正文分段落（空行分段，单行则按句读断行）。"""
    parts = [p.strip() for p in re.split(r'\n\s*\n', text.strip()) if p.strip()]
    if len(parts) == 1:
        parts = [p.strip() for p in re.split(r'\n', text.strip()) if p.strip()]
    return ''.join(f'<p>{esc_html(p)}</p>' for p in parts)


def esc_html(s: str) -> str:
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def _outline_html() -> str:
    """全书骨架（后三十回回目清单）渲染成诗笺式表格。"""
    f = DATA / 'outline.json'
    if not f.exists():
        return ''
    doc = json.loads(f.read_text(encoding='utf-8'))
    rows = ''.join(
        f"<tr><td>{r['chapter']}</td><td style='font-family:var(--kai);"
        f"font-size:15.5px'>{esc_html(r['title'])}</td>"
        f"<td class='small'>{esc_html(r.get('brief', ''))}</td></tr>"
        for r in doc['chapters'])
    res = esc_html((doc.get('resolution') or '')[:1200])
    return (f"<h2>全书骨架 · 后三十回</h2>"
            f"<div class='card small'>共 {doc.get('total', 110)} 回，"
            f"第 {doc.get('start', 81)} 回起为推演所得。"
            f"回目由「曹雪芹」Agent 依诸家裁决拟定，知识图谱工程师查其约束违反。</div>"
            f"<table><tr><th>回</th><th>回目</th><th>要点与伏线</th></tr>{rows}</table>"
            + (f"<div class='card'><h3>推演决议</h3><pre>{res}</pre></div>"
               if res else ''))


def export_data() -> None:
    from . import style as _style  # noqa: F401

    # --- 逐回正文 + 批注
    for row in db.q('SELECT * FROM chapters ORDER BY chapter'):
        ch = row['chapter']
        blocks = db.q('SELECT * FROM blocks WHERE chapter = ? ORDER BY id', [ch])
        for b in blocks:
            try:
                b['editions'] = json.loads(b['editions'] or '[]')
            except Exception:
                b['editions'] = []
        (DATA / 'chapters' / f'{ch:03d}.json').write_text(
            json.dumps(dict(no=ch, title=row['title'], blocks=blocks),
                       ensure_ascii=False), encoding='utf-8')

    # --- 实体
    ents = dict(
        persons=db.q('SELECT * FROM persons'),
        places=db.q('SELECT * FROM places'),
        objects=db.q('SELECT * FROM objects'),
        concepts=db.q('SELECT * FROM concepts'),
        imagery=db.q('SELECT * FROM imagery'),
        allusions=db.q('SELECT * FROM allusions'),
        poet_style=db.q('SELECT * FROM poet_style'),
        families=db.q('SELECT * FROM families'),
        clubs=db.q('SELECT * FROM clubs'),
        relations=db.q('SELECT * FROM relations'),
        festivals=db.q('SELECT * FROM festivals ORDER BY id'),
        lost_clues=db.q('SELECT * FROM lost_clues ORDER BY id'),
    )
    (DATA / 'entities.json').write_text(
        json.dumps(ents, ensure_ascii=False), encoding='utf-8')

    # --- 人物提及统计
    hot = db.q("""SELECT person, SUM(n) AS total FROM mentions
                  GROUP BY person ORDER BY total DESC LIMIT 80""")
    (DATA / 'mentions.json').write_text(
        json.dumps(hot, ensure_ascii=False), encoding='utf-8')

    # --- 诗词
    imgs = defaultdict(list)
    for r in db.q('SELECT poem_id, image FROM poem_images ORDER BY n DESC'):
        imgs[r['poem_id']].append(r['image'])
    poems = db.q('SELECT * FROM poems ORDER BY chapter, id')
    for p in poems:
        p['images'] = imgs.get(p['id'], [])[:8]
    (DATA / 'poems.json').write_text(
        json.dumps(poems, ensure_ascii=False), encoding='utf-8')

    # --- 推演
    deb_dir = paths.data('debates')
    debates = []
    if deb_dir.exists():
        for f in sorted(deb_dir.glob('*.json')):
            debates.append(json.loads(f.read_text(encoding='utf-8')))
    claims = db.q('SELECT * FROM claims')
    (DATA / 'debates.json').write_text(
        json.dumps(dict(debates=debates, claims=claims), ensure_ascii=False),
        encoding='utf-8')

    # --- 续写
    conts = db.q('SELECT * FROM continuations ORDER BY chapter')
    (DATA / 'continuations.json').write_text(
        json.dumps(conts, ensure_ascii=False), encoding='utf-8')

    # --- 全书骨架（后三十回回目清单）
    of = paths.data('outline.json')
    if of.exists():
        (DATA / 'outline.json').write_text(
            of.read_text(encoding='utf-8'), encoding='utf-8')

    # --- 图谱（人物关系 + 人物居所）
    nodes, links, seen = [], [], set()

    def add(nid, name, cat, color):
        if nid in seen:
            return
        seen.add(nid)
        nodes.append(dict(id=nid, name=name, cat=cat, color=color))

    for r in db.q('SELECT source, rel, target FROM relations'):
        a, b = f'P:{r["source"]}', f'P:{r["target"]}'
        if not db.q('SELECT 1 FROM persons WHERE name=?', [r['source']]):
            continue
        add(a, r['source'], 'person', '#a03c3c')
        add(b, r['target'], 'person', '#8b6914')
        links.append(dict(source=a, target=b, rel=r['rel']))
    for p in db.q('SELECT name, residence FROM persons'):
        if p['residence'] and p['residence'] not in ('—', '（无固定居所）'):
            rid = f'L:{p["residence"]}'
            add(rid, p['residence'], 'place', '#3c5a3c')
            add(f'P:{p["name"]}', p['name'], 'person', '#a03c3c')
            links.append(dict(source=f'P:{p["name"]}', target=rid, rel='居'))
    (DATA / 'graph.json').write_text(
        json.dumps(dict(nodes=nodes, links=links), ensure_ascii=False),
        encoding='utf-8')

    # --- 统计概览
    stats = dict(
        chapters=db.q('SELECT COUNT(*) n FROM chapters WHERE chapter>0')[0]['n'],
        blocks=db.q('SELECT COUNT(*) n FROM blocks')[0]['n'],
        anno=db.q('SELECT COUNT(*) n FROM v_anno')[0]['n'],
        poems=db.q('SELECT COUNT(*) n FROM poems')[0]['n'],
        persons=db.q('SELECT COUNT(*) n FROM persons')[0]['n'],
        places=db.q('SELECT COUNT(*) n FROM places')[0]['n'],
        objects=db.q('SELECT COUNT(*) n FROM objects')[0]['n'],
        concepts=db.q('SELECT COUNT(*) n FROM concepts')[0]['n'],
        relations=db.q('SELECT COUNT(*) n FROM relations')[0]['n'],
        imagery=db.q('SELECT COUNT(*) n FROM imagery')[0]['n'],
        allusions=db.q('SELECT COUNT(*) n FROM allusions')[0]['n'],
        mentions=db.q('SELECT COUNT(*) n FROM mentions')[0]['n'],
        claims=db.q('SELECT COUNT(*) n FROM claims')[0]['n'],
        continuations=db.q('SELECT COUNT(*) n FROM continuations')[0]['n'],
        editions=db.analytic('edition_dist'),
        anno_top=db.analytic('anno_density', 8),
    )
    (DATA / 'stats.json').write_text(
        json.dumps(stats, ensure_ascii=False), encoding='utf-8')
    return stats


def build_site() -> Path:
    stats = export_data()
    (ASSET / 'app.css').write_text(CSS, encoding='utf-8')

    # ---------- index
    ed = '、'.join(f'{r["edition"]} {r["n"]}' for r in stats['editions'][:6])
    idx = f"""
<div class="hero">
  <span class="seal solid">三恨</span>
  <div class="verse">一恨鲥鱼多刺　二恨海棠无香<br>三恨《红楼》未完</div>
  <div class="rule"></div>
  <p class="lead">本工程以《红楼梦脂评汇校本》为唯一权威——脂本前八十回，
  益以甲戌、己卯、庚辰、戚序、蒙府、列藏、杨藏、甲辰八本脂批。先立本体论，
  再令多个 Agent（批者、作者、红学诸家，以及数据科学家、文体计量学家、
  知识图谱工程师）互相质证，据推演结论续写第八十一回以下。
  <b>程高本后四十回一概不取，只作被批判的对象。</b></p>
</div>
<h2>规模</h2>
<div class="grid">
<div class="card">正文<big>{stats['blocks']}</big> 块 · 脂批 <big>{stats['anno']}</big> 条</div>
<div class="card">诗词 <big>{stats['poems']}</big> 首 · 意象 <big>{stats['imagery']}</big> 类</div>
<div class="card">人物 <big>{stats['persons']}</big> · 地点 <big>{stats['places']}</big> · 物件 <big>{stats['objects']}</big></div>
<div class="card">关系 <big>{stats['relations']}</big> 条 · 典故 <big>{stats['allusions']}</big> 条</div>
<div class="card">推演发言 <big>{stats['claims']}</big> 条 · 续写 <big>{stats['continuations']}</big> 回</div>
</div>
<h2>脂批版本分布</h2><div class="card">{ed}</div>
<h2>批语最密的回</h2><div class="card">
{'、'.join(f"第{r['chapter']}回({r['n']})" for r in stats['anno_top'])}</div>
<h2>入口</h2>
<div class="grid">
<div class="card"><h3>正文 · 脂批</h3><p class="small">按回阅读，可按版本（甲戌/庚辰…）与批注类型（眉批/侧批/夹批）过滤。</p>
<a href="read.html">进入 →</a></div>
<div class="card"><h3>本体实体</h3><p class="small">人物、居所、物件、概念、意象、典故、诗风画像。</p>
<a href="entities.html">进入 →</a></div>
<div class="card"><h3>诗词</h3><p class="small">判词、十二支曲、菊花诗、联句、灯谜、花签……含意象与韵基统计。</p>
<a href="poems.html">进入 →</a></div>
<div class="card"><h3>推演</h3><p class="small">多 Agent 立论、质证、裁决全过程，含技术组的统计证据。</p>
<a href="debate.html">进入 →</a></div>
<div class="card"><h3>续写</h3><p class="small">第八十一回以下，附风格门禁与脂砚斋批点。</p>
<a href="continuation.html">进入 →</a></div>
<div class="card"><h3>图谱</h3><p class="small">人物关系与居所的力导向图。</p>
<a href="graph.html">进入 →</a></div>
</div>"""
    (SITE / 'index.html').write_text(
        _page('总览', idx, 'index.html'), encoding='utf-8')

    # ---------- read
    chs = db.q('SELECT chapter, title FROM chapters WHERE chapter>0 ORDER BY chapter')
    opts = ''.join(f'<option value="{c["chapter"]}">{c["chapter"]}. {c["title"][:22]}</option>'
                   for c in chs)
    eds = ''.join(f'<button data-ed="{e}">{e}</button>'
                  for e in ['甲戌', '己卯', '庚辰', '戚序', '蒙府', '列藏', '杨藏', '甲辰'])
    body = f"""
<h2 id="title">正文 · 脂批</h2>
<div class="card small">
回目：<select id="chap">{opts}</select>　
版本：{eds}　
<label><input type="checkbox" id="onlyAnno"> 只看批语</label>
<span class="small">（朱红=朱批，墨绿=墨批；略字已还原为版本名与眉/侧/夹批）</span>
</div>
<div class="card body-text" id="content"></div>"""
    (SITE / 'read.html').write_text(
        _page('正文·脂批', body, 'read.html', JS_READ), encoding='utf-8')

    # ---------- entities（服务端渲染，静态可读）
    ents = json.loads((DATA / 'entities.json').read_text(encoding='utf-8'))
    hot = json.loads((DATA / 'mentions.json').read_text(encoding='utf-8'))
    hotmap = {h['person']: h['total'] for h in hot}
    rows = ''.join(
        f"<tr><td><b>{p['name']}</b></td><td>{p['role']}</td><td>{p['residence']}</td>"
        f"<td>{p['qingbang'] or '—'}</td><td>{p['fate'] or '—'}</td>"
        f"<td>{hotmap.get(p['name'], 0)}</td></tr>"
        for p in ents['persons'])
    places = ''.join(f"<tr><td>{p['name']}</td><td>{p['category']}</td>"
                     f"<td>{p['belongs']}</td><td>{p['note']}</td></tr>"
                     for p in ents['places'])
    objs = ''.join(f"<tr><td>{o['name']}</td><td>{o['owner']}</td>"
                   f"<td>{o['category']}</td><td>{o['symbol']}</td></tr>"
                   for o in ents['objects'])
    cons = ''.join(f"<tr><td>{c['name']}</td><td>{c['category']}</td><td>{c['gloss']}</td></tr>"
                   for c in ents['concepts'])
    img = ''.join(f"<tr><td>{i['image']}</td><td>{i['category']}</td>"
                  f"<td>{i['emotion']}</td><td>{i['context']}</td></tr>"
                  for i in ents['imagery'])
    allu = ''.join(f"<tr><td>{a['name']}</td><td>{a['source']}</td>"
                   f"<td>{a['usage']}</td><td>{a['person']}</td><td>{a['gloss']}</td></tr>"
                   for a in ents['allusions'])
    pstyle = ''.join(f"<tr><td>{s['person']}</td><td>{s['style']}</td>"
                     f"<td>{s['voice']}</td><td>{s['taboo']}</td></tr>"
                     for s in ents['poet_style'])
    clues = ''.join(f"<tr><td>{c['clue']}</td><td>{c['source']}</td><td>{c['meaning']}</td></tr>"
                    for c in ents['lost_clues'])
    fest = ''.join(f"<tr><td>{f['chapter']}</td><td>{f['solar_term']}</td><td>{f['event']}</td></tr>"
                   for f in ents['festivals'])
    body = f"""
<h2>人物（按提及热度）</h2>
<table><tr><th>姓名</th><th>身份</th><th>居所</th><th>情榜</th><th>探佚结局</th><th>提及</th></tr>{rows}</table>
<h2>地点</h2><table><tr><th>名称</th><th>类别</th><th>所属</th><th>说明</th></tr>{places}</table>
<h2>物件</h2><table><tr><th>名称</th><th>持有者</th><th>类别</th><th>象征/谶应</th></tr>{objs}</table>
<h2>概念与笔法</h2><table><tr><th>名称</th><th>类别</th><th>释义</th></tr>{cons}</table>
<h2>意象谱</h2><table><tr><th>意象</th><th>类别</th><th>情感指向</th><th>语境</th></tr>{img}</table>
<h2>典故</h2><table><tr><th>典故</th><th>出处</th><th>红楼用例</th><th>所涉</th><th>寓意</th></tr>{allu}</table>
<h2>诗风画像（续写代笔须守）</h2>
<table><tr><th>人物</th><th>诗风</th><th>声口</th><th>禁忌</th></tr>{pstyle}</table>
<h2>脂批明示的后文线索（硬约束）</h2>
<table><tr><th>线索</th><th>出处</th><th>含义</th></tr>{clues}</table>
<h2>节令时间轴</h2>
<table><tr><th>回</th><th>节令</th><th>事件</th></tr>{fest}</table>"""
    (SITE / 'entities.html').write_text(
        _page('本体实体', body, 'entities.html'), encoding='utf-8')

    # ---------- poems
    body = """
<h2>诗词本体</h2>
<div class="card small">体裁：
<select id="genre"><option value="">全部</option></select>
关键词：<input id="kw" placeholder="如 落花 / 判词 / 黛玉"></div>
<div id="list"></div>"""
    (SITE / 'poems.html').write_text(
        _page('诗词', body, 'poems.html', JS_POEMS), encoding='utf-8')

    # ---------- debate
    dd = json.loads((DATA / 'debates.json').read_text(encoding='utf-8'))
    blocks = []
    for d in dd['debates']:
        ev = ''.join(f"<li class='small'>[{e['kind']}] {e['summary'][:180]}</li>"
                     for e in d.get('evidence', []))
        blocks.append(f"<h2>{d['topic']}</h2><div class='card'><b>问题：</b>{d['question']}"
                      f"<h3>技术组证据（SQL 实算）</h3><ul>{ev}</ul></div>")
        for r in d.get('rounds', []):
            for s in r['speeches']:
                blocks.append(
                    f"<div class='speech' style='border-left-color:{s['color']}'>"
                    f"<span class='who' style='color:{s['color']}'>{s['agent']}</span>"
                    f"<span class='small'>[{s['group']}]</span><br>{s['content']}</div>")
        blocks.append(f"<div class='card'><h3>裁决</h3><pre>{d.get('resolution','')}</pre></div>")
    body = ("<h2>多 Agent 推演</h2>"
            "<div class='card small'>古典组（脂砚斋、畸笏叟、曹雪芹）· "
            "红学组（周汝昌、俞平伯、蔡元培、张爱玲）· "
            "技术组（数据科学家、文体计量学家、知识图谱工程师）· 主持人裁决。"
            "技术组的发言建立在可复算的统计量之上。</div>"
            + (''.join(blocks) or '<p class="small">尚无推演记录。</p>'))
    (SITE / 'debate.html').write_text(
        _page('推演', body, 'debate.html'), encoding='utf-8')

    # ---------- continuation
    conts = json.loads((DATA / 'continuations.json').read_text(encoding='utf-8'))
    segs = []
    for c in conts:
        notes = json.loads(c['notes'] or '{}')
        gate = notes.get('gate', {})
        lint = gate.get('lint_text', '')
        metrics = gate.get('metrics', {})
        gchk = '；'.join(notes.get('guard') or []) or '五道闸门全部通过'
        warn = '；'.join(notes.get('warnings') or [])
        auto = '；'.join(notes.get('auto_fix') or [])
        act = notes.get('act') or '—'
        cls = 'tag red' if notes.get('failed') else 'tag'
        segs.append(f"""
<h2>第 {c['chapter']} 回　{c['title'] or ''}</h2>
<div class="card small"><span class="{cls}">{act} 段推演</span>
<span class="tag">{'未过门禁' if notes.get('failed') else '已成稿'}</span>
风格距离 <b>{c['style_score']}</b>（越小越近原笔） ·
句长均值 {metrics.get('avg_sent_len')} · 对话率 {metrics.get('dialog_rate')} ·
虚词率 {metrics.get('xuci_rate')} · 现代腔：{lint or '无'}</div>
<div class="card small">本体论校验：{esc_html(gchk)}<br>
接地提示：{esc_html(warn) or '无'}　自动禁例修正：{esc_html(auto) or '无'}</div>
<div class="manuscript body-text">{_paras(c['text'])}</div>
<div class="card"><h3>文体计量学家</h3><pre>{notes.get('review','')}</pre></div>
<div class="card"><h3>脂砚斋批点</h3><pre>{notes.get('zhi','')}</pre></div>""")
    outline_html = _outline_html()
    body = (outline_html +
            '<h2>续写</h2><div class="card small">续写由「曹雪芹」Agent 执笔，'
            '经文体门禁（句长、对话率、虚词率、现代词禁例）检验，'
            '再由「脂砚斋」批点。凡未通过门禁者自动重写一稿。</div>'
            + (''.join(segs) or '<p class="small">尚无续写。</p>'))
    (SITE / 'continuation.html').write_text(
        _page('续写', body, 'continuation.html'), encoding='utf-8')

    # ---------- graph
    body = """<h2>本体图谱</h2>
<div class="card small">节点：人物（红）与居所（绿）；边：亲属 / 主仆 / 情缘 / 居所。
力导向布局，可拖动页面缩放查看。</div>
<div class="card" id="graph"></div>"""
    (SITE / 'graph.html').write_text(
        _page('图谱', body, 'graph.html', JS_GRAPH), encoding='utf-8')
    return SITE


if __name__ == '__main__':
    s = build_site()
    print('站点已生成：', s)
    for f in sorted(s.rglob('*')):
        if f.is_file():
            print(f'  {f.relative_to(s)}  {f.stat().st_size / 1024:.0f} KB')
