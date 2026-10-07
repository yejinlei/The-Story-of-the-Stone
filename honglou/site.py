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
mirror.html       字镜：字符三元组模型，可拟笔、可辨体、可作全书光谱
climate.html      冷暖谱：色彩字与情绪字逐回曲线，叠字镜困惑度
garden.html       大观园图：空间本体铺成可游的园图
clues.html        草蛇灰线：埋线 → 脂批点破 → 续写应验 三栏对账
imagery.html      意象星座：四十九类意象的星野与共现
annotators.html   批者群像：八本脂批的六维画像与版本亲缘

数据全部由 DuckDB 导出为静态 JSON，浏览器不需要任何数据库。
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import (annotators, climate, db, garden, graph, imagery,
               mirror, paths, theme)
from . import clues as ledger      # 避让 build_site 内的同名局部变量 clues

SITE = paths.SITE_DIR
DATA = SITE / 'data'
ASSET = SITE / 'assets'
for d in (SITE, DATA, ASSET, DATA / 'chapters'):
    d.mkdir(parents=True, exist_ok=True)

CSS = theme.CSS   # 视觉主题（宣纸·朱印·诗笺·手稿纸）见 honglou/theme.py

JS_READ = """
const state={chap:1,eds:new Set(),types:new Set(),onlyAnno:false,baihua:true};
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
  if(state.baihua){
    const v=(window.VN||{})[d.no]||(window.VN||{})[String(d.no)];
    if(v&&v.text){
      const w=document.createElement('div');w.className='card baihua';
      w.innerHTML='<h3>白话文 · 本回故事</h3>'+
        v.text.split(/\\n+/).map(x=>x.trim()).filter(Boolean)
          .map(x=>`<p>${esc(x)}</p>`).join('');
      box.appendChild(w);
    }
  }
  document.getElementById('title').textContent=`第${d.no}回　${d.title}`;
}
function esc(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function toggle(set,v,btn){
  if(set.has(v)){set.delete(v);btn.classList.remove('on')}else{set.add(v);btn.classList.add('on')}
  apply();
}
function apply(){render(window.CUR);}
window.onload=async()=>{
  let c0=1;const h=parseInt((location.hash||'').replace('#',''),10);
  if(h>=1&&h<=110)c0=h;
  const d=await load(c0);window.CUR=d;render(d);
  document.getElementById('chap').value=c0;
  document.getElementById('chap').onchange=async e=>{
    const n=+e.target.value;location.hash='#'+n;
    const d=await load(n);window.CUR=d;render(d);};
  document.querySelectorAll('[data-ed]').forEach(b=>{
    b.onclick=()=>{const v=b.dataset.ed;
      state.eds.has(v)?state.eds.delete(v):state.eds.add(v);
      b.classList.toggle('on');render(window.CUR);};});
  document.getElementById('onlyAnno').onchange=e=>{
    state.onlyAnno=e.target.checked;render(window.CUR);};
  const bh=document.getElementById('baihuaOn');
  bh.onchange=e=>{state.baihua=e.target.checked;render(window.CUR);};
  fetch('data/vernacular.json').then(r=>r.json()).then(v=>{
    window.VN=v;if(window.CUR)render(window.CUR);}).catch(()=>{});
};
"""

JS_POEMS = """
function esc(s){return String(s==null?'':s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
fetch('data/poems.json').then(r=>r.json()).then(ps=>{
  const box=document.getElementById('list'),gsel=document.getElementById('genre'),
        asel=document.getElementById('author'),kw=document.getElementById('kw'),
        cnt=document.getElementById('count');
  [...new Set(ps.map(p=>p.genre))].sort().forEach(g=>gsel.add(new Option(g,g)));
  const authors=[...new Set(ps.map(p=>(p.author||'').trim()).filter(Boolean))].sort();
  authors.forEach(a=>asel.add(new Option(a,a)));
  function show(){
    const g=gsel.value,a=asel.value,k=kw.value.trim();
    const hit=ps.filter(p=>(!g||p.genre===g)&&(!a||(p.author||'').trim()===a)
      &&(!k||(p.text||'').includes(k)||(p.title||'').includes(k)
         ||(p.lines||[]).join('').includes(k)||(p.images||[]).some(x=>x.includes(k))));
    cnt.textContent=`共 ${ps.length} 首，当前显示 ${hit.length} 首`;
    box.innerHTML=hit.map(p=>{
      const lines=(p.lines&&p.lines.length)?p.lines:[p.text||''];
      const body=lines.map(l=>`<div>${esc(l)}</div>`).join('');
      const img=(p.images||[]).map(x=>`<span class="tag">${esc(x)}</span>`).join('');
      const st=(p.voice||p.taboo)?`<div class="small">诗风画像：${esc(p.voice||'')}`
        +(p.taboo?`　禁忌：${esc(p.taboo)}`:'')+`</div>`:'';
      return `<div class="card"><h3>${esc(p.title||'(无题)')}　<span class="small">`
        +`${esc(p.genre)}·${esc(p.author||'未详')}·第${p.chapter}回</span></h3>`
        +`<div class="poem">${body}</div>`
        +(img?`<div>意象：${img}</div>`:'')
        +`<div class="small">句数 ${p.n_lines}　齐言 ${p.main_len}　`
        +`韵基一致率 ${(p.rhyme||0).toFixed(2)}　虚词率 ${(p.xu||0).toFixed(2)}</div>${st}</div>`;
    }).join('')||'<p class="small">没有符合条件的诗词。</p>';
  }
  gsel.onchange=show;asel.onchange=show;kw.oninput=show;show();
});
"""


def _page(title: str, body: str, active: str = '', extra_js: str = '') -> str:
    return theme.page(title, body, active, extra_js)


def _cjk(s: str) -> str:
    return re.sub(r'[^一-鿿]', '', s or '')


def _sent_spans(p: str) -> list[tuple[int, int]]:
    """按句读切分，返回每句在段内的 [起, 止)。"""
    spans, start = [], 0
    for m in re.finditer(r'[。！？…；!?;]+[」』”"’）]*', p):
        spans.append((start, m.end()))
        start = m.end()
    if start < len(p):
        spans.append((start, len(p)))
    return spans or [(0, len(p))]


def _lcs(a: str, b: str) -> int:
    """最长公共子串长度（摘句凭记忆略有出入时用）。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for ch in a:
        cur = [0] * (len(b) + 1)
        for j, c2 in enumerate(b, 1):
            if ch == c2:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _anno_div(note: str, quote: str | None = None, fuzzy: bool = False) -> str:
    """朱批：quote 为 None 表示已系于正文某句之后。"""
    note = esc_html(note or '')
    if quote is None:
        tag = '脂砚斋夹批·摘句微异' if fuzzy else '脂砚斋夹批'
        return f"<div class='anno 朱批'><span class='src'>{tag}</span>{note}</div>"
    tail = '（摘句未见于此回正文，附于回末）' if quote else ''
    head = f"「{esc_html(quote)}」{tail}" if quote else ''
    return (f"<div class='anno 朱批'><span class='src'>拟批{head}</span>{note}</div>")


def _chapter_html(text: str, annos: list[dict] | None = None) -> str:
    """续写正文按句分段；夹批去标点定位后，就近系于所批之句之后。"""
    paras = [p.strip() for p in re.split(r'\n\s*\n', (text or '').strip()) if p.strip()]
    if len(paras) == 1:
        paras = [p.strip() for p in re.split(r'\n', (text or '').strip()) if p.strip()]
    if len(paras) > 1 and re.match(r'^第\s*[一二三四五六七八九十百零〇\d]+\s*回', paras[0]):
        paras = paras[1:]                      # 回目已见标题，不再重复
    if not paras:
        return ''

    # 净字索引 → (段序, 段内偏移)，使去标点后的摘句能回落到原串位置
    net, back = [], []
    for pi, p in enumerate(paras):
        for ci, ch in enumerate(p):
            if '一' <= ch <= '鿿':
                net.append(ch)
                back.append((pi, ci))
    nett = ''.join(net)

    spans = [_sent_spans(p) for p in paras]
    hits: dict[tuple[int, int], list[tuple[str, bool]]] = {}
    rest, cursor = [], {}
    for a in annos or []:
        q = _cjk(a.get('quote'))
        note = a.get('note', '')
        k, sent, fuzzy = -1, None, False
        if q:
            start = cursor.get(q, 0)           # 同句反复出现则顺次后移
            k = nett.find(q, start)
            if k < 0:
                k = nett.find(q)
            if k >= 0:
                cursor[q] = k + 1
                pi, ci = back[k + len(q) - 1]  # 落在该句之末字所归的那句
                for si, (x, y) in enumerate(spans[pi]):
                    if x <= ci < y:
                        sent = (pi, si)
                        break
            else:                               # 批者凭记忆引文，按最长公共子串回收
                need = max(4, int(len(q) * 0.6))
                best, tgt = 0, None
                for pi, p in enumerate(paras):
                    for si, (x, y) in enumerate(spans[pi]):
                        common = _lcs(q, _cjk(p[x:y]))
                        if common > best:
                            best, tgt = common, (pi, si)
                if tgt and best >= need:
                    sent, fuzzy = tgt, True
        if sent is None:
            rest.append(_anno_div(note, (a.get('quote') or '').strip()))
        else:
            hits.setdefault(sent, []).append((note, fuzzy))

    out = []
    for pi, p in enumerate(paras):
        buf = ''
        for si, (x, y) in enumerate(spans[pi]):
            buf += p[x:y]
            notes = hits.get((pi, si))
            if not notes:
                continue
            out.append(f'<p>{esc_html(buf)}</p>')
            buf = ''
            out.extend(_anno_div(n, fuzzy=f) for n, f in notes)
        if buf.strip():
            out.append(f'<p>{esc_html(buf)}</p>')
    if rest:
        out.append("<p class='small'>以下批语未能系于正文，附于回末：</p>")
        out.extend(rest)
    return ''.join(out)


def _baihua_card(v: dict | None) -> str:
    """每回白话文串讲（供少年读者入门）。"""
    if not v or not (v.get('text') or '').strip():
        return ''
    paras = ''.join(f"<p>{esc_html(x.strip())}</p>"
                    for x in re.split(r'\n+', v['text']) if x.strip())
    return f"<div class='card baihua'><h3>白话文 · 本回故事</h3>{paras}</div>"


def esc_html(s: str) -> str:
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def _outline_html() -> str:
    """全书骨架（后三十回回目清单）：回目即锚点，点击直达续写正文。"""
    f = DATA / 'outline.json'
    if not f.exists():
        return ''
    doc = json.loads(f.read_text(encoding='utf-8'))
    done = set()
    cf = DATA / 'continuations.json'
    if cf.exists():
        done = {c['chapter'] for c in json.loads(cf.read_text(encoding='utf-8'))}
    rows = []
    for r in doc['chapters']:
        ch = r['chapter']
        title = esc_html(r['title'])
        if ch in done:
            cell = (f"<a href='#c{ch}' style='font-family:var(--kai);"
                    f"font-size:15.5px'>{title}</a>"
                    f"<span class='tag red' style='margin-left:6px'>已续</span>")
        else:
            cell = (f"<span style='font-family:var(--kai);font-size:15.5px;"
                    f"color:var(--ink3)'>{title}</span>"
                    f"<span class='tag' style='margin-left:6px'>待写</span>")
        rows.append(f"<tr><td>{ch}</td><td>{cell}</td>"
                    f"<td class='small'>{esc_html(r.get('brief', ''))}</td></tr>")
    res = esc_html((doc.get('resolution') or '')[:1200])
    return (f"<h2>全书骨架 · 后三十回</h2>"
            f"<div class='card small'>共 {doc.get('total', 110)} 回，"
            f"第 {doc.get('start', 81)} 回起为推演所得。"
            f"回目由「曹雪芹」Agent 依诸家裁决拟定，知识图谱工程师查其约束违反。"
            f"<b>点回目直达该回正文与脂批。</b></div>"
            f"<table><tr><th>回</th><th>回目</th><th>要点与伏线</th></tr>"
            f"{''.join(rows)}</table>"
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
                  GROUP BY person ORDER BY total DESC, person LIMIT 80""")
    (DATA / 'mentions.json').write_text(
        json.dumps(hot, ensure_ascii=False), encoding='utf-8')

    # --- 诗词
    imgs = defaultdict(list)
    for r in db.q('SELECT poem_id, image FROM poem_images ORDER BY n DESC'):
        imgs[r['poem_id']].append(r['image'])
    lines = defaultdict(list)
    for r in db.q('SELECT poem_id, line FROM poem_lines ORDER BY poem_id, seq'):
        lines[r['poem_id']].append(r['line'])
    stylemap = {s['person']: s for s in db.q('SELECT * FROM poet_style')}
    poems = db.q('SELECT * FROM poems ORDER BY chapter, id')
    for p in poems:
        p['images'] = imgs.get(p['id'], [])[:8]
        ls = lines.get(p['id']) or []
        if not ls and p.get('main_len'):          # 兜底：按齐言字数切句
            t = p['text'] or ''
            n = p['main_len']
            ls = [t[i:i + n] for i in range(0, len(t), n)]
        p['lines'] = ls
        st = stylemap.get((p['author'] or '').strip())
        p['voice'] = st['voice'] if st else ''
        p['taboo'] = st['taboo'] if st else ''
        if not p.get('title'):
            p['title'] = (ls[0][:14] + '…') if ls and len(ls[0]) > 14 else (ls[0] if ls else '')
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

    # --- 每回白话文串讲（供少年读者；缺失则站点照常生成）
    vf = paths.data('vernacular.json')
    (DATA / 'vernacular.json').write_text(
        vf.read_text(encoding='utf-8') if vf.exists() else '{}', encoding='utf-8')

    # --- 全书骨架（后三十回回目清单）
    of = paths.data('outline.json')
    if of.exists():
        (DATA / 'outline.json').write_text(
            of.read_text(encoding='utf-8'), encoding='utf-8')

    # --- 图谱（本体论七重视图，见 honglou/graph.py）
    graph.build(DATA)

    # --- 字镜（字符三元组模型、逐回光谱、风格基准，见 honglou/mirror.py）
    mirror.build(DATA)

    # --- 冷暖谱（逐回色彩字与情绪字，叠字镜困惑度，见 honglou/climate.py）
    climate.build(DATA)

    # --- 大观园图（空间本体铺成园图，见 honglou/garden.py）
    garden.build(DATA)

    # --- 草蛇灰线账本（埋线/点破/应验 三栏对账，见 honglou/clues.py）
    ledger.build(DATA)

    # --- 意象星座（见 honglou/imagery.py）与批者群像（见 honglou/annotators.py）
    imagery.build(DATA)
    annotators.build(DATA)

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
<div class="card"><h3>图谱</h3><p class="small">七重视图：人物关系、家族府邸、意象谱、
器物典故、册籍判词探佚、时序长卷、推演脉络。点选即见本体记录与逐回分布。</p>
<a href="graph.html">进入 →</a></div>
<div class="card"><h3>字镜</h3><p class="small">把正文、脂批、诗词压成字符三元组模型：
可<b>拟笔</b>（马尔可夫接笔，仿其口气），可<b>辨体</b>（粘贴任意文本，算困惑度与四项风格指纹，
并查出笔意最近的回），并有前八十回八折交叉校验的<b>全书光谱</b>。</p>
<a href="mirror.html">进入 →</a></div>
<div class="card"><h3>冷暖谱</h3><p class="small">逐回统计色彩字（红朱绛茜 ↔ 雪霜缟银冰）、
情绪字（笑/泪/死丧/喜乐/空幻）与繁华字的密度，叠上字镜困惑度，
看「悲凉之雾」自第几回起遍被华林。</p>
<a href="climate.html">进入 →</a></div>
<div class="card"><h3>大观园图</h3><p class="small">四十六处地点分区落点的可游园图：
院落大小＝正文现身之数，点一处即见居者、现身回次与写到它的诗句。空间即性格。</p>
<a href="garden.html">进入 →</a></div>
<div class="card"><h3>草蛇灰线</h3><p class="small">伏线三栏对账：
<b>埋线</b>（正文最早现身处）→ <b>点破</b>（脂批说破处）→ <b>应验</b>（续写接住处），
未应者即续书之欠账。</p>
<a href="clues.html">进入 →</a></div>
<div class="card"><h3>意象星座</h3><p class="small">四十九类意象按类别分野布星，
细线为同诗共现；竹—泪、花—冢、雪—茫茫，各自成簇。</p>
<a href="imagery.html">进入 →</a></div>
<div class="card"><h3>批者群像</h3><p class="small">甲戌、己卯、庚辰、戚序、蒙府、列藏、
杨藏、甲辰八本批语的六维画像：悲悼、称赏、自道、洩后、篇幅、用力，并附版本亲缘。</p>
<a href="annotators.html">进入 →</a></div>
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
<label><input type="checkbox" id="baihuaOn" checked> 附白话文</label>
<span class="small">（朱红=朱批，墨绿=墨批；略字已还原为版本名与眉/侧/夹批；白话文为每回串讲，供少年读者入门）</span>
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
    poems_all = json.loads((DATA / 'poems.json').read_text(encoding='utf-8'))

    def chips(pairs) -> str:
        return ''.join(f"<span class='tag'>{esc_html(k)} {v}</span>"
                       for k, v in pairs)

    gcnt = Counter(p['genre'] for p in poems_all).most_common()
    acnt = Counter((p['author'] or '').strip() or '未详（叙述者/集体）'
                   for p in poems_all).most_common(16)
    icnt = Counter(i for p in poems_all for i in (p['images'] or [])).most_common(14)
    body = f"""
<h2>诗词本体</h2>
<div class="card small">脂本前八十回共录诗词曲赋 <b>{len(poems_all)}</b> 首
（判词、红楼梦曲、灯谜、花签、联句、诔文一并收录）。
下列分布可点：按体裁、作者筛选，或输入关键词（如 落花、判词、黛玉）。</div>
<div class="grid">
<div class="card"><h3>体裁</h3>{chips(gcnt)}</div>
<div class="card"><h3>作者</h3>{chips(acnt)}</div>
<div class="card"><h3>高频意象</h3>{chips(icnt)}</div>
</div>
<div class="card small">体裁：
<select id="genre"><option value="">全部</option></select>
作者：<select id="author"><option value="">全部</option></select>
关键词：<input id="kw" placeholder="如 落花 / 判词 / 黛玉">
<span id="count" class="small"></span></div>
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
    vern = json.loads((DATA / 'vernacular.json').read_text(encoding='utf-8'))
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
        annos = notes.get('annos') or []
        summary = notes.get('zhi_summary') or notes.get('zhi') or ''
        ch = c['chapter']
        prev_l = (f"<a href='#c{ch - 1}'>上一回</a> · " if ch - 1 >= 81 else '')
        next_l = (f" · <a href='#c{ch + 1}'>下一回</a>" if ch + 1 <= 110 else '')
        segs.append(f"""
<h2 id="c{ch}">第 {ch} 回　{c['title'] or ''}</h2>
<div class="card small"><a href="#">↑ 回骨架</a> · {prev_l}
<a href="read.html">前八十回正文·脂批</a>{next_l}<br>
<span class="{cls}">{act} 段推演</span>
<span class="tag">{'未过门禁' if notes.get('failed') else '已成稿'}</span>
风格距离 <b>{c['style_score']}</b>（越小越近原笔） ·
句长均值 {metrics.get('avg_sent_len')} · 对话率 {metrics.get('dialog_rate')} ·
虚词率 {metrics.get('xuci_rate')} · 现代腔：{lint or '无'}</div>
<div class="card small">本体论校验：{esc_html(gchk)}<br>
接地提示：{esc_html(warn) or '无'}　自动禁例修正：{esc_html(auto) or '无'}</div>
<div class="manuscript body-text">{_chapter_html(c['text'], annos)}</div>
{_baihua_card(vern.get(str(ch)) or vern.get(ch))}
<div class="card"><h3>文体计量学家</h3><pre>{notes.get('review','')}</pre></div>
<div class="card"><h3>脂砚斋回末总评</h3><pre>{summary}</pre></div>""")
    outline_html = _outline_html()
    body = (outline_html +
            '<h2>续写</h2><div class="card small">续写由「曹雪芹」Agent 执笔，'
            '经文体门禁（句长、对话率、虚词率、现代词禁例）检验，'
            '再由「脂砚斋」批点。凡未通过门禁者自动重写一稿。</div>'
            + (''.join(segs) or '<p class="small">尚无续写。</p>'))
    (SITE / 'continuation.html').write_text(
        _page('续写', body, 'continuation.html'), encoding='utf-8')

    # ---------- graph
    (SITE / 'graph.html').write_text(
        _page('图谱', graph.BODY, 'graph.html', graph.JS), encoding='utf-8')

    # ---------- mirror（字镜）
    ver = hashlib.md5((DATA / 'mirror.json').read_bytes()).hexdigest()[:8]
    (SITE / 'mirror.html').write_text(
        _page('字镜', mirror.BODY, 'mirror.html', mirror.js(ver)), encoding='utf-8')

    # ---------- climate（冷暖谱）
    (SITE / 'climate.html').write_text(
        _page('冷暖谱', climate.BODY, 'climate.html', climate.JS), encoding='utf-8')

    # ---------- garden（大观园图）
    (SITE / 'garden.html').write_text(
        _page('大观园图', garden.BODY, 'garden.html', garden.JS), encoding='utf-8')

    # ---------- clues（草蛇灰线账本）
    (SITE / 'clues.html').write_text(
        _page('草蛇灰线', ledger.BODY, 'clues.html', ledger.JS), encoding='utf-8')

    # ---------- imagery（意象星座）
    (SITE / 'imagery.html').write_text(
        _page('意象星座', imagery.BODY, 'imagery.html', imagery.JS), encoding='utf-8')

    # ---------- annotators（批者群像）
    (SITE / 'annotators.html').write_text(
        _page('批者群像', annotators.BODY, 'annotators.html', annotators.JS),
        encoding='utf-8')
    return SITE


if __name__ == '__main__':
    s = build_site()
    print('站点已生成：', s)
    for f in sorted(s.rglob('*')):
        if f.is_file():
            print(f'  {f.relative_to(s)}  {f.stat().st_size / 1024:.0f} KB')
