"""草蛇灰线账本：埋线 → 脂批点破 → 续写应验，三栏对账。

伏线之说，向来只存乎感悟。此页把每一条「草蛇灰线」拆成三件事，各自可查、可对：

1. **埋线**：脂本前八十回正文中，此线最早现身于第几回（原文摘录为证）；
2. **点破**：脂批在哪一回点破它（批语原文为证），或批者对此人结局的洩示；
3. **应验**：本次续写第八十一回以下，在第几回把它接住（原文摘录为证）。

三者俱全曰「已应」，有埋无应曰「未应」——未应者即续书之欠账，一览无余。

产物：docs/data/clues.json。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import db, paths

_CJK = re.compile(r'[一-鿿]+')
_HAN = re.compile(r'[^一-鿿]')

FUTURE = ('后文', '后回', '后之', '末回', '后三十回', '后数十回', '结果', '归结',
          '下落', '结局', '后来', '后事', '伏线', '伏', '谶', '应了', '收尾',
          '如何结', '终身', '末回情榜')

# 红楼梦十二支曲 → 所咏之人（引子、收尾不专指一人）
SONG_PERSON = {
    '终身误': '薛宝钗', '枉凝眉': '林黛玉', '恨无常': '贾元春',
    '分骨肉': '贾探春', '乐中悲': '史湘云', '世难容': '妙玉',
    '喜冤家': '贾迎春', '虚花悟': '贾惜春', '聪明累': '王熙凤',
    '留余庆': '贾巧姐', '晚韶华': '李纨', '好事终': '秦可卿',
}


def _cjk(t: str) -> str:
    return ''.join(_CJK.findall(t or ''))


def _names() -> list[str]:
    """本体中所有可当作检索键的名字（含人物别名），长者优先。"""
    out: set[str] = set()
    for p in db.q('SELECT name, aliases FROM persons'):
        out.add(p['name'])
        try:
            for a in json.loads(p['aliases'] or '[]'):
                if len(a) >= 2:
                    out.add(a)
        except Exception:
            pass
    for t in ('places', 'objects'):
        for r in db.q(f'SELECT name FROM {t}'):
            out.add(r['name'])
    return sorted(out, key=lambda s: (-len(s), s))


def _chapter_texts(table: str = 'v_main') -> dict[int, str]:
    d: dict[int, str] = {}
    order = '' if table == 'continuations' else ' ORDER BY id'
    for r in db.q(f'SELECT chapter, text FROM {table}{order}'):
        d[r['chapter']] = d.get(r['chapter'], '') + (r['text'] or '')
    return d


def _snip(text: str, i: int, n: int, pad: int = 42) -> str:
    a = max(0, i - pad)
    b = min(len(text), i + n + pad)
    return text[a:i] + '【' + text[i:i + n] + '】' + text[i + n:b]


def _find(texts: dict[int, str], key: str) -> tuple[int, str] | None:
    for c in sorted(texts):
        if c <= 0:
            continue
        i = texts[c].find(key)
        if i >= 0:
            return c, _snip(texts[c], i, len(key))
    return None


def _df(texts: dict[int, str], key: str) -> int:
    return sum(1 for t in texts.values() if key in t)


def build(dst: Path | None = None) -> Path:
    out = dst or (paths.SITE_DIR / 'data')
    out.mkdir(parents=True, exist_ok=True)

    main = _chapter_texts('v_main')
    anno = _chapter_texts('v_anno')
    cont = _chapter_texts('continuations')
    names = _names()
    persons = db.q('SELECT name, role, fate FROM persons')
    pname = {p['name']: p for p in persons}

    def keys_of(text: str) -> list[str]:
        t = _cjk(text)
        ks: list[str] = []
        if len(t) >= 3:
            ks.append(t)
        ks += [n for n in names if n in text]
        if len(t) >= 2:
            ks += [t[i:i + 2] for i in range(len(t) - 1)]
        seen, o = set(), []
        for k in ks:
            if k in seen or len(k) < 2:
                continue
            seen.add(k)
            o.append(k)
        return o

    entries: list[dict] = []

    # ---------------- 一、脂批明示的后文线索
    for r in db.q('SELECT id, clue, source, meaning FROM lost_clues ORDER BY id'):
        text = f"{r['clue']}　{r['meaning']}"
        ks = [k for k in keys_of(text) if _df(main, k) <= 50 and _df(main, k) > 0]
        planted = anno_hit = None
        for k in ks:
            if planted is None:
                planted = _find(main, k)
            if anno_hit is None:
                anno_hit = _find(anno, k)
            if planted and anno_hit:
                break
        ful = None
        for k in ks:
            ful = _find(cont, k)
            if ful:
                break
        status = '已应' if ful else ('埋而未应' if planted else '未应')
        entries.append(dict(
            kind='脂批线索', title=r['clue'], text=r['meaning'],
            src=r['source'], src_c='', persons=_people_in(text, names),
            planted=dict(ch=planted[0], snip=planted[1]) if planted else None,
            anno=dict(ch=anno_hit[0], snip=anno_hit[1]) if anno_hit else None,
            fulfilled=dict(ch=ful[0], snip=ful[1]) if ful else None,
            status=status))

    # ---------------- 二、判词 / 十二支曲 / 花签
    future_anno = []
    for r in db.q('SELECT chapter, text, editions FROM v_anno ORDER BY id'):
        future_anno.append(r)

    for p in db.q("SELECT id, chapter, title, genre, author, text FROM poems "
                  "WHERE genre IN ('判词','曲','花签','四言谜') ORDER BY chapter, id"):
        title = p['title'] or ''
        who: list[str] = []
        if p['genre'] == '曲':
            for sng, per in SONG_PERSON.items():
                if sng in title:
                    who = [per]
                    break
        if not who:
            who = _people_in(title, names)
        if not who and p['author'] and not p['author'].startswith('（'):
            who = [a.strip() for a in re.split(r'[、/]', p['author']) if a.strip()]
        if not who:
            continue
        body = (p['text'] or '').strip()
        key = who[0]
        k2 = key[-2:] if len(key) > 2 else key
        planted = dict(ch=p['chapter'],
                       snip=(body[:60] + ('…' if len(body) > 60 else '')))
        ah = None
        for r in future_anno:
            t = r['text']
            i, kk = t.find(key), key
            if i < 0:
                i, kk = t.find(k2), k2
            if i >= 0 and any(f in t for f in FUTURE):
                ah = dict(ch=r['chapter'], snip=_snip(t, i, len(kk)))
                break
        ful = None
        for k in (key, k2):
            hit = _find(cont, k)
            if hit:
                ful = dict(ch=hit[0], snip=hit[1])
                break
        n_chaps = sum(1 for t in cont.values() if key in t)
        pf = pname.get(key)
        entries.append(dict(
            kind=p['genre'], title=title, text=body[:120],
            src=f"第{p['chapter']}回", src_c=p['chapter'], persons=who,
            fate=(pf or {}).get('fate', ''),
            planted=planted, anno=ah, fulfilled=ful,
            n_ful=n_chaps,
            status='已应' if ful else '未应'))

    ok = sum(1 for e in entries if e['status'] == '已应')
    doc = dict(entries=entries,
               stats=dict(total=len(entries), ok=ok, pending=len(entries) - ok))
    (out / 'clues.json').write_text(
        json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    return out / 'clues.json'


def _people_in(text: str, names: list[str]) -> list[str]:
    """识别文本中提到的人物（长名优先，短名被其吞并者不计）。"""
    hits = [n for n in names if n in text]
    out = []
    for n in hits:
        if any(n != m and n in m and m in hits for m in hits):
            continue
        out.append(n)
    canon = []
    for n in out:
        c = _canon(n)
        if c and c not in canon:
            canon.append(c)
    return canon[:3]


_CANON: dict[str, str] | None = None


def _canon(alias: str) -> str:
    global _CANON
    if _CANON is None:
        _CANON = {}
        for p in db.q('SELECT name, aliases FROM persons'):
            _CANON[p['name']] = p['name']
            try:
                for a in json.loads(p['aliases'] or '[]'):
                    _CANON.setdefault(a, p['name'])
            except Exception:
                pass
    return _CANON.get(alias, alias if alias in set(_CANON.values()) else '')


BODY = """
<h2>草蛇灰线 · 三栏对账</h2>
<div class="card small">
伏线之说向来只存乎感悟。此页把每条线拆成三件可查的事：
<b>埋线</b>（脂本正文最早现身于第几回，摘录为证）、
<b>点破</b>（脂批在哪一回说破，批语原文为证）、
<b>应验</b>（本次续写第八十一回以下在哪一回接住，摘录为证）。
三者俱全曰<b>已应</b>，有埋无应曰<b>未应</b>——未应者即续书之欠账。
右栏以「人名或关键语在续书中重现」为准，摘录即其所在句；是否真算应了，点去那一回自判。
点摘录即跳去读那一回（前八十回去「正文·脂批」，续书去「续写」）。
</div>
<div class="card"><div class="gtools">
  <span id="stat" class="small"></span>
  <button data-f="全部" class="on">全部</button>
  <button data-f="已应">已应</button>
  <button data-f="未应">未应</button>
  <button data-f="判词">判词</button>
  <button data-f="曲">十二支曲</button>
  <button data-f="脂批线索">脂批线索</button>
</div></div>
<div id="list"></div>
"""

JS = r"""
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
let D=null,F='全部';
const mark=s=>String(s||'').replace(/【/g,'<span class="tag red">').replace(/】/g,'</span>');
function cell(t,c,snip){
  if(!snip)return '<td class="small">—</td>';
  const href=c<=80?('read.html#'+c):('continuation.html#c'+c);
  return `<td><span class="small">第${c}回</span><br><a href="${href}">${mark(esc(snip))}</a></td>`;
}
function show(){
  const es=D.entries.filter(e=>F==='全部'||e.status===F||e.kind===F);
  $('list').innerHTML=es.map(e=>{
    const ps=(e.persons||[]).map(p=>'<span class="tag">'+esc(p)+'</span>').join('');
    const st=e.status==='已应'?'<span class="tag red">已应</span>':'<span class="tag">'+esc(e.status)+'</span>';
    return `<div class="card"><h3>${esc(e.title)} <span class="small">${esc(e.kind)}　${esc(e.src||'')}</span> ${st}${ps}</h3>`+
      (e.text?`<p class="small">${esc(e.text)}</p>`:'')+
      (e.fate?`<p class="small">探佚结局：${esc(e.fate)}</p>`:'')+
      `<table><tr><th>埋线（脂本正文）</th><th>点破（脂批）</th><th>应验（本次续写）</th></tr><tr>`+
      cell('p',e.planted?e.planted.ch:0,e.planted?e.planted.snip:null)+
      cell('a',e.anno?e.anno.ch:0,e.anno?e.anno.snip:null)+
      cell('f',e.fulfilled?e.fulfilled.ch:0,e.fulfilled?e.fulfilled.snip:null)+
      `</tr></table>`+
      (e.n_ful?`<p class="small">此人在续书中现身于 ${e.n_ful} 回。</p>`:'')+
      `<p class="small">出处：${esc(e.src||'')}</p></div>`;
  }).join('')||'<p class="small">无</p>';
  $('stat').textContent=`共 ${D.stats.total} 条　已应 ${D.stats.ok}　未应 ${D.stats.pending}　当前显示 ${es.length} 条`;
}
fetch('data/clues.json').then(r=>r.json()).then(d=>{D=d;show();
  document.querySelectorAll('[data-f]').forEach(b=>{b.onclick=()=>{F=b.dataset.f;
    document.querySelectorAll('[data-f]').forEach(x=>x.className=(x.dataset.f===F?'on':''));show();};});
}).catch(e=>{$('list').textContent='账本数据加载失败：'+e;});
"""

if __name__ == '__main__':
    print(build())
