"""诗词深析：诗谶、雅集、意象指纹、诗风度量、逐回密度、抽取置信。

这一层不重复「诗词本体」页的罗列，只回答四问：
一・诗里藏了多少谶？——诗谶谱，逐句回原文核对，验不中的不显示；
二・谁在哪一回、与谁一起作诗？——雅集年表；
三・各人笔下的世界有何不同？——意象指纹与诗风度量（算法）；
四・作者的呼吸停在哪里？——逐回密度与前后半之别。
凡算法所得的「诗意」指标，皆与本体论里人工著录的诗风画像并列，两相对照，
读者自可判断哪一句是机器的揣度，哪一句是人的定评。
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import db, paths
from . import ontology_seed as seed
from .poems import HAO, xuci_density, yixiang_density

OMEN_CATS = ['判词', '曲', '诗', '词', '联句', '诔', '灯谜', '花签', '谶语']
PUNCT = re.compile(r'[，。！？；：、“”‘’（）《》,!?;:…—]')

# 本非齐言韵文之体：判词、花签、灯谜之类一句即止，本无所谓「偶句同韵」，
# 若仍以同韵率责之，则存疑榜尽是花签，而真正的散文误判反而不见。
NON_RHYME_GENRES = {'花签': 0.30, '判词': 0.20, '灯谜': 0.20, '对联': 0.25,
                    '酒令': 0.25, '偈': 0.15, '四言谜': 0.20, '诔': 0.10,
                    '词/曲': 0.10, '曲': 0.10, '歌行': 0.05}


def _canon_names() -> dict[str, str]:
    """正文里的称呼 → 本名。底本只写「宝玉」「黛玉」，全名反而不见。"""
    canon: dict[str, str] = {}
    for r in seed._rows(seed.LOCAL_NAMES):
        full = r[0]
        canon.setdefault(full, full)
        for short in r[1].split(','):
            if short:
                canon.setdefault(short, full)
    for p in seed.persons():
        canon.setdefault(p['name'], p['name'])
        try:
            als = json.loads(p['aliases'] or '[]')
        except Exception:
            als = []
        for a in als:
            if len(a) >= 2:
                canon.setdefault(a, p['name'])
    return canon


# 本无署名之体：册籍判词、太虚曲、花签灯谜，多出集体场合或神话之笔，
# 若按上文最近的人名硬派，则第 5 回的判词会分给晴雯妙玉、第 37 回的诗会
# 全落到主持评诗的李纨头上，其谬甚矣。
NO_AUTHOR_GENRES = {'判词', '曲', '词/曲', '花签', '灯谜', '对联', '酒令',
                    '谣谚', '四言谜', '偈'}

# 与某人相关而非某人所作之体，不计入其诗风统计（灯谜则是各人自作，故不在此列）
POET_EXCLUDE = {'判词', '花签', '谣谚', '对联', '酒令', '四言谜', '偈',
                '曲', '词/曲'}


def _guess_author(ctx: str, canon: dict[str, str]) -> str:
    """空作者者，只认一种证据：别号（蘅芜君、潇湘妃子、蕉下客……）。

    社诗本以别号署名，这是最可靠的证据；至于「某人道：」式的上文，
    在评诗的场合里多半只是评者而非作者（李纨即因此曾误得十首），故不用。
    证据不足便留「未详」——派错一个人，他的意象指纹与诗风度量就都脏了。
    """
    blob = (ctx or '')[-260:]
    for hao, who in HAO.items():
        if hao in blob:
            return who
    return ''


def _books() -> tuple[dict[int, str], Counter]:
    main: dict[int, str] = {}
    lens: Counter = Counter()
    for r in db.q("SELECT chapter, text FROM blocks WHERE kind='正文' "
                  "AND chapter > 0 ORDER BY id"):
        ch = int(r['chapter'])
        t = (r['text'] or '').replace('\n', '').replace('\r', '')
        main[ch] = main.get(ch, '') + t
        lens[ch] += len(t)
    return main, lens


def _poems() -> tuple[list[dict], int]:
    canon = _canon_names()
    lines: dict[str, list[str]] = defaultdict(list)
    for r in db.q('SELECT poem_id, line FROM poem_lines ORDER BY poem_id, seq'):
        lines[str(r['poem_id'])].append(r['line'] or '')
    imgs: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for r in db.q('SELECT poem_id, image, SUM(n) n FROM poem_images '
                  'GROUP BY poem_id, image ORDER BY n DESC'):
        imgs[str(r['poem_id'])].append((r['image'], r['n']))
    out, filled = [], 0
    for p in db.q('SELECT * FROM poems'):
        ch = int(p['chapter'])
        ls = lines.get(str(p['id']), [])
        txt = p['text'] or ''.join(ls)
        yix = yixiang_density(txt)
        xu = float(p['xu'] or 0.0)
        rh = float(p['rhyme'] or 0.0)
        # 置信：偶句同韵率最重，虚词密度（散文气）次之，意象密度又次之
        conf = 0.5 * rh + 0.3 * max(0.0, 1 - xu / 0.28) + 0.2 * min(1.0, yix / 0.30)
        conf = min(1.0, conf + NON_RHYME_GENRES.get(p['genre'] or '', 0.0))
        conf = round(conf, 3)
        author = (p['author'] or '').strip()
        if ch == 5 and (p['genre'] or '') == '判词':
            author = ''            # 册籍所载，无所谓谁作——不当算作此人之诗
        if (not author or author == '（未详）') \
                and (p['genre'] or '') not in NO_AUTHOR_GENRES:
            author = _guess_author(p['prev_ctx'], canon)
            if author:
                filled += 1
        out.append(dict(id=str(p['id']), ch=ch, title=p['title'] or '',
                        genre=p['genre'] or '', author=author,
                        lines=ls, text=txt, n=len(ls),
                        main_len=int(p['main_len'] or 0),
                        yix=round(yix, 4), xu=round(xu, 4), rhyme=round(rh, 3),
                        conf=conf, images=imgs.get(str(p['id']), []),
                        route=p['route'] or ''))
    out.sort(key=lambda p: (p['ch'], p['id']))
    return out, filled


def build(out: Path | None = None) -> Path:
    out = Path(out) if out else paths.SITE_DIR / 'data'
    out.mkdir(parents=True, exist_ok=True)
    main, lens = _books()
    poems, filled = _poems()

    # ---- 一・诗谶谱：逐句回原文核对，验不中的不显示
    omens = []
    for o in db.q('SELECT * FROM verse_omens ORDER BY chapter'):
        ch = int(o['chapter'])
        text = main.get(ch, '')
        i = text.find(o['verse'])
        if i < 0:                       # 宁缺毋滥：验不中即不录
            continue
        omens.append(dict(verse=o['verse'], ch=ch, piece=o['piece'],
                          who=o['who'], omen=o['omen'], fulfill=o['fulfill'],
                          cat=o['category'],
                          ctx=text[max(0, i - 42):i + len(o['verse']) + 42]))
    omens.sort(key=lambda x: (OMEN_CATS.index(x['cat'])
                              if x['cat'] in OMEN_CATS else 99, x['ch']))

    # ---- 二・雅集年表
    by_ch: dict[int, list[dict]] = defaultdict(list)
    for p in poems:
        by_ch[p['ch']].append(p)
    salons = []
    for s in db.q('SELECT * FROM salons ORDER BY chapter'):
        ch = int(s['chapter'])
        ps = by_ch.get(ch, [])
        # 库内的署名者：括号名（「（秦可卿房）」之类场景标注）不列
        poets = sorted({p['author'] for p in ps
                        if p['author'] and not p['author'].startswith('（')})
        salons.append(dict(ch=ch, name=s['name'], cast=s['participants'],
                           genre=s['genre'], note=s['note'], n=len(ps),
                           poets=poets,
                           genres=[[g, n] for g, n in
                                   Counter(p['genre'] for p in ps).most_common(4)]))
    salons.sort(key=lambda s: s['ch'])

    # ---- 三・逐回密度与前后半
    cnt = Counter(p['ch'] for p in poems)
    nlines = Counter()
    for p in poems:
        nlines[p['ch']] += max(1, p['n'])
    density = []
    for ch in sorted(lens):
        ln = max(1, lens[ch])
        density.append(dict(ch=ch, n=cnt.get(ch, 0), lines=nlines.get(ch, 0),
                            len=ln, dens=round(cnt.get(ch, 0) / ln * 10000, 2)))

    def _half(a: int, b: int) -> dict:
        ps = [p for p in poems if a <= p['ch'] <= b]
        l = max(1, sum(lens[c] for c in lens if a <= c <= b))
        return dict(a=a, b=b, n=len(ps),
                    lines=sum(max(1, p['n']) for p in ps),
                    chaps=sum(1 for c in lens if a <= c <= b),
                    dens=round(len(ps) / l * 10000, 2))
    halves = [_half(1, 40), _half(41, 80)]

    # ---- 四・意象指纹与诗风度量（作者聚合）
    rows: dict[str, list[dict]] = defaultdict(list)
    for p in poems:
        # 判词、花签、太虚曲之类：与某人相关，却不是某人所作，不入诗风统计，
        # 否则李纨会因一条判词与一支花签而平添两首「自己的诗」。
        if not p['author'] or p['genre'] in POET_EXCLUDE:
            continue
        rows[p['author']].append(p)
    styles = {s['person']: s for s in db.q('SELECT * FROM poet_style')}
    # 独用字：此人有而他作者无之字（去虚词、去标点）
    words: dict[str, Counter] = {}
    for a, ps in rows.items():
        c = Counter()
        for p in ps:
            for chx in p['text']:
                if '\u4e00' <= chx <= '\u9fff' and chx not in '的了着过是就在与和为':
                    c[chx] += 1
        words[a] = c
    poets = []
    for a, ps in rows.items():
        if a == '（未详）' and len(ps) < 2:
            pass
        txt = ''.join(p['text'] for p in ps)
        nl = sum(max(1, p['n']) for p in ps)
        imgs: Counter = Counter()
        for p in ps:
            for im, n in p['images']:
                imgs[im] += n
        others = Counter()
        for b, c in words.items():
            if b != a:
                others.update(c)
        own = [w for w, n in words[a].most_common(400)
               if others.get(w, 0) == 0 and n >= 2][:10]
        st = styles.get(a)
        poets.append(dict(name=a, n=len(ps), lines=nl,
                          avg=round(nl / max(1, len(ps)), 2),
                          len_avg=round(len(txt) / max(1, nl), 2),
                          yix=round(yixiang_density(txt), 4),
                          xu=round(xuci_density(txt), 4),
                          rhyme=round(sum(p['rhyme'] for p in ps) / len(ps), 3),
                          images=[[k, v] for k, v in imgs.most_common(8)],
                          own=own,
                          style=(st or {}).get('style', ''),
                          voice=(st or {}).get('voice', ''),
                          taboo=(st or {}).get('taboo', ''),
                          chaps=sorted({p['ch'] for p in ps})))
    # 「未详」「警幻新制」之类非人之作者，列于其后
    poets.sort(key=lambda x: (x['name'].startswith('（'), -x['n'], -x['lines'],
                              x['name']))
    poets = poets[:16]

    # ---- 五・意象总谱（全库）
    itot: Counter = Counter()
    icat: dict[str, str] = {}
    for r in db.q('SELECT poem_id, image, category, SUM(n) n FROM poem_images '
                  'GROUP BY poem_id, image, category'):
        itot[r['image']] += r['n']
        icat[r['image']] = r['category']
    images = [[k, icat.get(k, ''), v] for k, v in itot.most_common(24)]

    # ---- 六・韵脚：只取偶数句末字（奇数句本不入韵）
    tail: Counter = Counter()
    for p in poems:
        for k, ln in enumerate(p['lines']):
            if k % 2 == 0:          # 第 2、4、6… 句（下标为奇数）
                continue
            s = PUNCT.sub('', ln)
            if s:
                tail[s[-1]] += 1
    rhymes = [[k, v] for k, v in tail.most_common(24)]

    # ---- 七・算法的自知之明：置信最低者
    doubt = sorted(poems, key=lambda p: (p['conf'], -p['n']))[:14]
    doubt = [dict(id=p['id'], ch=p['ch'], title=p['title'], genre=p['genre'],
                  conf=p['conf'], text=p['text'][:26], n=p['n'],
                  xu=p['xu'], yix=p['yix'], rhyme=p['rhyme'])
             for p in doubt]

    stats = dict(poems=len(poems), lines=sum(max(1, p['n']) for p in poems),
                 omens=len(omens),
                 omen_all=db.q('SELECT COUNT(*) n FROM verse_omens')[0]['n'],
                 salons=len(salons), poets=len([p for p in poets
                                                if p['name'] != '（未详）']),
                 chaps=len({p['ch'] for p in poems}),
                 halves=halves,
                 images=len(itot),
                 conf_avg=round(sum(p['conf'] for p in poems) / max(1, len(poems)), 3),
                 doubt=len(doubt), filled=filled,
                 no_author=sum(1 for p in poems if not p['author']))

    doc = dict(omens=omens, salons=salons, density=density, poets=poets,
               images=images, rhymes=rhymes, doubt=doubt, stats=stats,
               cats=[c for c in OMEN_CATS
                     if any(o['cat'] == c for o in omens)])
    fp = out / 'poetics.json'
    fp.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    return fp


BODY = """
<h2>诗谶 · 诗里先说出的结局</h2>
<div class="card small">
《红楼》的诗不是点缀，是判词：一个人的下场，往往先在他的诗里说完，本人才姗姗走去。
此处逐句回到原文核过——<b>核不中的句子不入谱</b>（本体录 <span id="poOmenAll">…</span> 条，
核得 <span id="poOmenN">…</span> 条）。点一行即见它与前后原文连读的样子。
谶有两类：一类是册籍与曲子，由警幻说出，众人听不懂；一类是本人自作，
如黛玉的葬花吟、宝钗的柳絮词——<b>自己写自己的结局，而自己并不知道</b>。
</div>
<div class="card"><div class="gtools" id="poOmenCats"></div></div>
<div class="gwrap">
  <div class="card samples" id="poOmens"></div>
  <aside class="card gside" id="poOmenSide"><p class="small">点一句看它的谶意与应验。</p></aside>
</div>

<h2>雅集 · 谁在哪一回与谁作诗</h2>
<div class="card small">
大观园的诗不是一人独吟，是一群人凑在一处比才情：起社、限韵、联句、掣签。
下表按回次排开每一场，写明谁在场、作什么体裁、库内该回录得几首；
<b>末一列是这一场在全书里的分量</b>——海棠社定钗黛之高下，
芦雪庵联句是众人最后一次热闹，中秋联句只剩黛玉湘云妙玉三人。
</div>
<div class="card"><table id="poSalonTab"></table></div>

<h2>呼吸 · 诗在第几回停了</h2>
<div class="card small">
诗词是作者的呼吸。前四十回几乎回回有诗，后四十回却越来越稀——
不是大观园的人不会作诗了，是<b>作者不再让他们作</b>。
下图每回一根，高者为诗数；下方两栏是前后半之别，一并算出每万字的密度。
</div>
<div class="card gcanvas">
  <div class="gtools"><span class="gstat" id="poDensStat"></span></div>
  <svg id="poDens" viewBox="0 0 1080 240" preserveAspectRatio="xMidYMid meet"></svg>
</div>
<div class="grid" id="poHalves"></div>

<h2>意象指纹 · 各人笔下的世界</h2>
<div class="card small">
同一个大观园，各人眼里的事物不同：黛玉满纸是泪是花是秋，
宝钗偏要写淡写雪写青云，湘云嘴里是鹿肉是鹤是醉。
下图每人一条，按意象出现的次数摊开；<b>右侧一列是本体论里人工著录的诗风画像</b>，
算法与定评并列，读者自可比对。<br>
<span class="small">此处的统计只取<b>确可能出于此人之手</b>的诗（判词、花签、太虚曲虽系于此人，
却是册籍与签上旧诗，不作数，故不列入）。</span>
</div>
<div class="card"><div class="legend" id="poImgLegend"></div>
  <svg id="poImg" viewBox="0 0 1080 420" preserveAspectRatio="xMidYMin meet"></svg></div>
<div class="card samples" id="poPoets"></div>

<h2>诗风度量 · 算法算出来的脾气</h2>
<div class="card small">
下列四项皆由文本算出，不假人手：<b>均句长</b>（一句几字）、
<b>意象密度</b>（意象字占比）、<b>虚词密度</b>（愈高则愈近散文）、
<b>偶句同韵率</b>（愈高则愈是诗）。末一列「独用字」是此人有而他作者全无之字，
最见个人脾性；惟其人所存之诗愈少，这一栏愈不可当真，只作参证。<br>
<span class="small">原未署作者的那些，只凭<b>别号署名</b>一种证据补判（蘅芜君、潇湘妃子、蕉下客……
社诗本是这样署名的）；<b>证据不足者仍作「未详」，不硬派</b>——
派错一个人，他的意象指纹与诗风度量就都脏了。此次共补
<b id="poFilled">…</b> 首，读者可逐首自核。</span>
</div>
<div class="card"><table id="poStyleTab"></table></div>

<h2>韵脚 · 全书诗里最常落在这几个字上</h2>
<div class="card small">
不分词牌韵部，只数各句末字落谁最多。这些字本身就是大观园的底色。
</div>
<div class="card"><div id="poRhyme" class="legend"></div></div>

<h2>自知之明 · 算法也会看走眼</h2>
<div class="card small">
抽取诗词靠「齐言 + 低虚词 + 偶句同韵」三道判据，散文里的骈句也会被误认。
下表列出置信最低的一十四首：其中确有散文误判（如混入的「十斤五钱」一流），
也有真诗被切碎者（如曲子的散句）——<b>低置信未必是错，只是尚待人工一断</b>。
与其装作全对，不如把疑处摆出来。
</div>
<div class="card"><table id="poDoubtTab"></table></div>
"""


JS = r"""
(function(){
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
let D=null,CAT=null;

function omens(){
  const cats=['全部'].concat(D.cats);
  $('poOmenCats').innerHTML=cats.map(c=>
    `<button data-c="${esc(c)}">${esc(c)}</button>`).join('');
  $('poOmenCats').querySelectorAll('button').forEach(b=>b.onclick=()=>{
    CAT=b.dataset.c;omens();});
  $('poOmenCats').querySelectorAll('button').forEach((b,i)=>{
    b.className=((CAT===null&&i===0)||CAT===b.dataset.c)?'on':'';});
  drawOmens();
}
function drawOmens(){
  const list=D.omens.filter(o=>CAT===null||CAT==='全部'||o.cat===CAT);
  $('poOmens').innerHTML=list.map((o,i)=>
    `<div data-i="${i}"><span class="tag">${esc(o.cat)}</span>`
    +`<span class="tag">第${o.ch}回</span><b>${esc(o.verse)}</b>`
    +`<br><span class="small">${esc(o.piece)} · ${esc(o.who)}</span></div>`).join('')
    ||'<p class="small">此类别暂无。</p>';
  $('poOmens').querySelectorAll('div[data-i]').forEach(el=>el.onclick=()=>{
    const o=list[+el.dataset.i];
    $('poOmenSide').innerHTML=`<h3>${esc(o.verse)}</h3>`
      +`<p class="small">${esc(o.piece)} · 第${o.ch}回 · 所指 ${esc(o.who)}</p>`
      +`<p><b>谶意</b>：${esc(o.omen)}</p>`
      +`<p><b>应验</b>：${esc(o.fulfill)}</p>`
      +`<p class="small">…${esc(o.ctx)}…</p>`;
  });
  $('poOmenN').textContent=D.omens.length;
  $('poOmenAll').textContent=D.stats.omen_all;
}

function salons(){
  let h='<thead><tr><th>回</th><th>名目</th><th>在场</th><th>体裁</th>'
    +'<th>诗数</th><th>按语</th></tr></thead><tbody>';
  D.salons.forEach(s=>{
    h+=`<tr><td>第${s.ch}回</td><td><b>${esc(s.name)}</b></td>`
      +`<td class="small">${esc(s.cast)}</td><td>${esc(s.genre)}</td>`
      +`<td>${s.n}${s.poets.length?'<br><span class="small">'+esc(s.poets.slice(0,6).join('、'))+'</span>':''}</td>`
      +`<td class="small">${esc(s.note)}</td></tr>`;});
  $('poSalonTab').innerHTML=h+'</tbody>';
}

function density(){
  const W=1080,H=240,PL=34,PB=26,PT=8;
  const mx=Math.max(1,...D.density.map(d=>d.n));
  const bw=(W-PL-10)/D.density.length;
  let s='';
  D.density.forEach((d,i)=>{
    const h=(H-PB-PT)*(d.n/mx), x=PL+i*bw, y=H-PB-h;
    s+=`<rect x=${x.toFixed(1)} y=${y.toFixed(1)} width=${(bw-1.2).toFixed(1)} height=${Math.max(0.6,h).toFixed(1)} `
      +`fill="${d.ch>40?'#9e2b25':'#3b4a6b'}" opacity=".8"><title>第${d.ch}回 · ${d.n} 首</title></rect>`;
    if(d.ch%10===0||d.n===mx) s+=`<text x=${(x+bw/2).toFixed(1)} y=${H-12} font-size=9 fill="#8a7f6d" text-anchor="middle" font-family="serif">${d.ch}</text>`;
  });
  s+=`<line x1=${PL} y1=${H-PB} x2=${W-6} y2=${H-PB} stroke="#e0d5c0"/>`;
  s+=`<text x=${PL} y=${H-PB-4} font-size=10 fill="#8a7f6d" font-family="serif">最多 ${mx} 首/回</text>`;
  $('poDens').innerHTML=s;
  $('poDensStat').innerHTML=`灰蓝为前四十回，朱红为后四十回 · 共 ${D.stats.poems} 首 / ${D.stats.lines} 句，散在 ${D.stats.chaps} 回`;
  $('poHalves').innerHTML=D.stats.halves.map(hf=>
    `<div class="card"><h3>第${hf.a}—${hf.b}回</h3>`
    +`<big>${hf.n}</big> 首 · ${hf.lines} 句<br>`
    +`<span class="small">${hf.chaps} 回，每万字 <b>${hf.dens}</b> 首</span></div>`).join('');
}

function fingerprint(){
  const ps=D.poets.filter(p=>p.images.length);
  const W=1080,PL=128,PR=250,rowH=Math.min(24,404/Math.max(1,ps.length));
  const pal=['#9e2b25','#3b4a6b','#b08d57','#6b8a3f','#8a7f6d','#c2504a','#4a6b8a','#7d1f1b'];
  // 颜色按全书意象总谱固定，各人同色同物，方可横比
  const top=D.images.slice(0,8).map(i=>i[0]);
  const colorOf=im=>{const k=top.indexOf(im);return k<0?'#d9ceb9':pal[k%pal.length];};
  $('poImgLegend').innerHTML=top.map((t,i)=>
    `<span><i style="background:${pal[i%pal.length]}"></i>${esc(t)}</span>`).join('')
    +'<span><i style="background:#d9ceb9"></i>其他</span>'
    +'<span class="small">（颜色按全书意象总谱固定，每人一行，按次数摊开）</span>';
  let s='';
  ps.forEach((p,i)=>{
    const y=10+i*rowH, tot=p.images.reduce((a,x)=>a+x[1],0)||1;
    s+=`<text x=${PL-8} y=${y+rowH/2+4} text-anchor="end" font-size=12 fill="#3a322a" font-family="serif">${esc(p.name)}</text>`;
    let x=PL;
    p.images.slice(0,8).forEach(im=>{
      const w=(im[1]/tot)*(W-PL-PR);
      s+=`<rect x=${x.toFixed(1)} y=${y+3} width=${Math.max(0.5,w).toFixed(1)} height=${rowH-8} `
        +`fill="${colorOf(im[0])}" opacity=".78"><title>${esc(p.name)} · ${esc(im[0])} ${im[1]}</title></rect>`;
      x+=w;});
    s+=`<text x=${W-PR+8} y=${y+rowH/2+4} font-size=10.5 fill="#8a7f6d" font-family="serif">`
      +`${esc((p.style||'').slice(0,18))}</text>`;});
  $('poImg').innerHTML=s;
  $('poPoets').innerHTML=ps.map(p=>
    `<div><b>${esc(p.name)}</b> <span class="tag">${p.n} 首 / ${p.lines} 句</span>`
    +(p.style?`<br><span class="small">画像：${esc(p.style)}</span>`:'')
    +(p.voice?`<br><span class="small">声口：${esc(p.voice)}</span>`:'')
    +(p.taboo?`<br><span class="small">不为：${esc(p.taboo)}</span>`:'')
    +(p.own.length?`<br><span class="small">独用字：${esc(p.own.join('、'))}</span>`:'')
    +`</div>`).join('');
}

function styletab(){
  let h='<thead><tr><th>作者</th><th>首</th><th>句</th><th>均句长</th>'
    +'<th>意象密度</th><th>虚词密度</th><th>偶句同韵率</th><th>独用字</th></tr></thead><tbody>';
  D.poets.forEach(p=>{
    h+=`<tr><td><b>${esc(p.name)}</b></td><td>${p.n}</td><td>${p.lines}</td>`
      +`<td>${p.len_avg}</td><td>${p.yix}</td><td>${p.xu}</td><td>${p.rhyme}</td>`
      +`<td class="small">${esc(p.own.slice(0,6).join('、'))}</td></tr>`;});
  $('poStyleTab').innerHTML=h+'</tbody>';
  $('poFilled').textContent=D.stats.filled;
}

function rhyme(){
  const mx=Math.max(1,...D.rhymes.map(r=>r[1]));
  $('poRhyme').innerHTML=D.rhymes.map(r=>{
    const w=10+Math.round(16*r[1]/mx);
    return `<span class="tag" style="font-size:${w}px">${esc(r[0])} ${r[1]}</span>`;}).join('');
}

function doubt(){
  let h='<thead><tr><th>回</th><th>题</th><th>体裁</th><th>置信</th>'
    +'<th>虚词</th><th>意象</th><th>同韵</th><th>首句</th></tr></thead><tbody>';
  D.doubt.forEach(d=>{
    h+=`<tr><td>第${d.ch}回</td><td>${esc(d.title||'（无题）')}</td><td>${esc(d.genre)}</td>`
      +`<td>${d.conf}</td><td>${d.xu}</td><td>${d.yix}</td><td>${d.rhyme}</td>`
      +`<td class="small">${esc(d.text)}…</td></tr>`;});
  $('poDoubtTab').innerHTML=h+'</tbody>';
}

fetch('data/poetics.json').then(r=>r.json()).then(d=>{
  D=d;
  omens();salons();density();fingerprint();styletab();rhyme();doubt();
}).catch(e=>{console.log('poetics:',e);});
})();
"""
