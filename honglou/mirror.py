"""字镜：以字为镜 —— 拟笔、辨体、光谱。

拟笔
    把三种语料（正文 / 脂批 / 韵语）压成字符三元组模型，连同句读标点一起建模，
    浏览器端即可马尔可夫接笔。**此非创作，是原书碎片的重拼**，玩的是「像不像」，
    读者不当以其为真笔——它与本体论、门禁检查不是一回事。

辨体
    同一模型给任意文本算字符困惑度（perplexity，越小越「顺」此书的笔路），
    合以句长、对话率、虚词率、型例比四项指纹，与脂本前八十回基准对照画雷达图，
    并查出「笔意最近的回」。粘贴一段文字，即刻知道它离脂本多远。

光谱
    前八十回做**八折交叉校验**：留一组（十回）不参与建模，用它去算那一组的困惑度，
    以免「原著参与建模而自证其真」；续写八十一回以下用全量模型，
    因此对续写是有利条件——若续写仍然偏高，则其远离之结论更稳固。

产物：docs/data/mirror.json（n-gram 表 + 逐回光谱 + 基准指纹）。
"""
from __future__ import annotations

import json
import math
import random
import re
from collections import Counter
from pathlib import Path

from . import db, paths, style
from .poems import XUCI

PUNCT = '，。！？；：、…—·《》〈〉（）「」『』“”‘’?!,.;:'
_KEEP = re.compile('[^一-鿿' + re.escape(PUNCT) + ']')

VOICES = {
    'main':  dict(name='雪芹正文', tri=20000, bi=20000, uni=4200,
                  hint='脂本前八十回正文：叙事、白描、对白。学的是它的呼吸。'),
    'anno':  dict(name='脂砚斋批', tri=8000, bi=8000, uni=3500,
                  hint='脂批四千六百余条：评点口吻，多洩后文。'),
    'verse': dict(name='韵语判词', tri=4000, bi=4000, uni=2200,
                  hint='诗词曲赋、判词、灯谜、花签。字数最少，接笔最易见支离。'),
}

_B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'

W3, W2, W1, FLOOR = 0.55, 0.30, 0.15, 0.02   # 与 JS 端 JS_MODEL 常量须一致
FOLDS = 8                                    # 前八十回交叉校验折数
CHUNK = 1500                                 # 指纹按等长片段统计，免长文本占便宜


# ---------------------------------------------------------------- 语料

def clean(t: str) -> str:
    """只留汉字与本书所用标点，其余（页码、校记符号、西文）悉数剔去。"""
    return _KEEP.sub('', t or '')


def _rows(exclude=()):
    sql = 'SELECT chapter, text FROM v_main WHERE chapter > 0'
    if exclude:
        sql += ' AND chapter NOT IN (%s)' % ','.join(str(int(c)) for c in exclude)
    return db.q(sql + ' ORDER BY id')


def main_text(exclude=()) -> str:
    return clean(''.join(r['text'] for r in _rows(exclude)))


def chapter_texts() -> dict[int, str]:
    out: dict[int, str] = {}
    for r in _rows():
        out.setdefault(r['chapter'], '')
        out[r['chapter']] += clean(r['text'])
    return out


def anno_text() -> str:
    return clean(''.join(r['text'] for r in db.q('SELECT text FROM v_anno')))


def verse_text() -> str:
    """诗词曲赋：逐句之间补上句读（诗本身无标点，不补则接笔全无句读）。"""
    lines: dict[str, list[str]] = {}
    for r in db.q('SELECT poem_id, seq, line FROM poem_lines ORDER BY poem_id, seq'):
        lines.setdefault(r['poem_id'], []).append(clean(r['line']))
    out = []
    for pid in sorted(lines):
        ls = [l for l in lines[pid] if l]
        if not ls:
            continue
        out.append(''.join(l + ('，' if i % 2 == 0 else '。')
                           for i, l in enumerate(ls)))
    return ''.join(out)


# ---------------------------------------------------------------- n-gram 表

def _enc(v: int) -> str:
    """频次 → 单字符。对数分桶，相对权重足够用，省去五分之四体积。"""
    return _B64[min(63, int(round(math.log(1 + v) * 6)))]


def _items(g: dict):
    """(ngram, weight)：键按定长拼接，权重与之一一对应。"""
    o, k, c = g['n'], g['k'], g['c']
    return [(k[i * o:(i + 1) * o], math.exp(_B64.index(c[i]) / 6) - 1)
            for i in range(len(c))]


def grams(text: str, order: int, top: int) -> dict:
    c = Counter(text[i:i + order] for i in range(len(text) - order + 1))
    items = c.most_common(top)
    return dict(n=order, total=sum(c.values()),
                k=''.join(k for k, _ in items),
                c=''.join(_enc(v) for _, v in items),
                kept=sum(v for _, v in items))


def voice_grams(vid: str, exclude=()) -> dict:
    v = VOICES[vid]
    if vid == 'main':
        t = main_text(exclude)
    elif vid == 'anno':
        t = anno_text()
    else:
        t = verse_text()
    g = dict(uni=grams(t, 1, v['uni']), bi=grams(t, 2, v['bi']),
             tri=grams(t, 3, v['tri']))
    g['chars'] = len(t)
    g['cover'] = round(g['tri']['kept'] / max(1, g['tri']['total']), 4)
    return g


def seeds(g: dict, n: int = 48) -> list[str]:
    """接笔起点：取最常见的纯汉字三字组（避掉以标点起头的）。"""
    out, k = [], g['tri']['k']
    for i in range(0, len(k) - 2, 3):
        s = k[i:i + 3]
        if _KEEP.sub('', s) == s:
            out.append(s)
        if len(out) >= n:
            break
    return out


# ---------------------------------------------------------------- 模型（与 JS 端同式）

class Model:
    """字符插值模型：P(c₃|c₁c₂) = 三元组 ⊕ 二元组 ⊕ 一元 ⊕ 平滑地板。"""

    def __init__(self, g: dict):
        self.uni, self.u_t = {}, 0.0
        for k, w in _items(g['uni']):
            self.uni[k] = w
            self.u_t += w
        self.tri, self.tri_s = {}, {}
        for k, w in _items(g['tri']):
            pre, ch = k[:2], k[2]
            self.tri.setdefault(pre, []).append((ch, w))
            self.tri_s[pre] = self.tri_s.get(pre, 0.0) + w
        self.bi, self.bi_s = {}, {}
        for k, w in _items(g['bi']):
            pre, ch = k[0], k[1]
            self.bi.setdefault(pre, []).append((ch, w))
            self.bi_s[pre] = self.bi_s.get(pre, 0.0) + w

    def prob(self, c1: str, c2: str, ch: str) -> float:
        p = W1 * self.uni.get(ch, 0.0) / self.u_t
        arr = self.tri.get(c1 + c2)
        if arr:
            for c, w in arr:
                if c == ch:
                    p += W3 * w / self.tri_s[c1 + c2]
                    break
        arr = self.bi.get(c2)
        if arr:
            for c, w in arr:
                if c == ch:
                    p += W2 * w / self.bi_s[c2]
                    break
        u = self.uni.get(ch, 0.0) / self.u_t
        return (1 - FLOOR) * p + FLOOR * u

    def perplexity(self, text: str) -> float:
        if len(text) < 8:
            return 0.0
        s, n = 0.0, 0
        for i in range(2, len(text)):
            s += math.log(max(self.prob(text[i - 2], text[i - 1], text[i]), 1e-9))
            n += 1
        return math.exp(-s / n)


# ---------------------------------------------------------------- 风格指纹

def metrics(text: str, chunk: int = CHUNK) -> dict:
    """按等长片段统计后取平均，使长短文本可比。"""
    vs = [style.style_vector(text[i:i + chunk]) for i in range(0, len(text), chunk)]
    vs = [v for v in vs if v.get('chars', 0) >= 500] or [style.style_vector(text)]
    keys = ('avg_sent_len', 'dialog_rate', 'xuci_rate', 'type_token')
    return {k: sum(v.get(k, 0) for v in vs) / len(vs) for k in keys}


# ---------------------------------------------------------------- 光谱

def spectrum(sizes: bool = True) -> list[dict]:
    """逐回困惑度与指纹。前八十回 *= 八折交叉校验。"""
    by = chapter_texts()
    chaps = sorted(by)
    step = math.ceil(len(chaps) / FOLDS)
    out: list[dict] = []
    for i in range(0, len(chaps), step):
        hold = chaps[i:i + step]
        m = Model(voice_grams('main', exclude=hold))
        for c in hold:
            t = by[c]
            if len(t) < 300:
                continue
            out.append(_row(c, '脂本', t, m))
    full = Model(voice_grams('main'))
    for r in db.q('SELECT chapter, text FROM continuations ORDER BY chapter'):
        t = clean(r['text'])
        if len(t) < 300:
            continue
        out.append(_row(r['chapter'], '续写', t, full))
    out.sort(key=lambda x: x['chapter'])
    if not sizes:
        for r in out:
            r.pop('chars', None)
    return out


def _row(ch: int, kind: str, t: str, m: Model) -> dict:
    v = metrics(t)
    return dict(chapter=ch, kind=kind, chars=len(t),
                ppl=round(m.perplexity(t), 1),
                sent=round(v['avg_sent_len'], 2),
                dlg=round(v['dialog_rate'], 4),
                xu=round(v['xuci_rate'], 4),
                tt=round(v['type_token'], 4))


# ---------------------------------------------------------------- 导出

def anno_samples(n: int = 24, size: int = 1200) -> list[str]:
    """供「辨体」取用的脂批样本若干段（每段约千二百字，由若干条连缀）。"""
    rnd = random.Random(20241001)
    rows = [clean(r['text']) for r in db.q('SELECT text FROM v_anno')]
    rows = [r for r in rows if len(r) >= 12]
    rnd.shuffle(rows)
    out, buf = [], ''
    for t in rows:
        buf += t + '　'
        if len(buf) >= size:
            out.append(buf.strip())
            buf = ''
        if len(out) >= n:
            break
    if buf.strip() and len(out) < n:
        out.append(buf.strip())
    return out


def build(dst: Path | None = None) -> Path:
    out = dst or (paths.SITE_DIR / 'data')
    out.mkdir(parents=True, exist_ok=True)

    voices = []
    for vid, v in VOICES.items():
        g = voice_grams(vid)
        voices.append(dict(id=vid, name=v['name'], hint=v['hint'], grams=g,
                           seeds=seeds(g), chars=g['chars'],
                           cover=g['cover']))
    spec = spectrum()
    base_main = sorted(r['ppl'] for r in spec if r['kind'] == '脂本')
    # 取中位数：开端数回多诗词匾额（第 1、2、5、17/18 回），均值会被拉偏
    bench_ppl = base_main[len(base_main) // 2] if base_main else 0
    # 样本内中位数：全量模型自算脂本，用作「此文本即出自本书」的下界参照
    full = Model(voice_grams('main'))
    inner = sorted(full.perplexity(t)
                   for t in chapter_texts().values() if len(t) >= 300)
    doc = dict(
        voices=voices,
        spectrum=spec,
        bench=metrics(main_text()),
        bench_ppl=round(bench_ppl, 1),
        bench_ppl_in=round(inner[len(inner) // 2], 1) if inner else 0,
        folds=FOLDS,
        punct=PUNCT,
        xuci=''.join(sorted(XUCI)),
        modern=style.MODERN_WORDS,
        anno_samples=anno_samples(),
    )
    f = out / 'mirror.json'
    f.write_text(json.dumps(doc, ensure_ascii=False, separators=(',', ':')),
                 encoding='utf-8')
    return f


BODY = f"""
<h2>字镜 · 拟笔与辨体</h2>
<div class="card small">
以<b>字</b>为镜。把脂本前八十回正文（59 万字）、脂批四千六百余条、诗词曲赋分别压成
<b>字符三元组模型</b>（连同句读标点一并建模），用它做两件事：<b>拟笔</b>——马尔可夫接笔，
仿其口气；<b>辨体</b>——给任意文本算字符困惑度与四项风格指纹，与脂本基准对照。
前八十回的困惑度经过 <b>{FOLDS} 折交叉校验</b>：留十回不参与建模，再用模型去算那十回，
以免「原著参与建模而自证其真」；续写则用全量模型，对续写是有利条件，
若续写仍偏高，则「不类」之判更稳固。
</div>
<div class="tabs" id="tabs">
  <button data-t="gen" class="on">拟笔</button>
  <button data-t="judge">辨体</button>
  <button data-t="spec">全书光谱</button>
</div>

<div class="pane" id="p-gen">
  <div class="card">
    <div class="gtools"><span class="small">腔调　</span><span id="vbtns"></span></div>
    <div class="gtools">
      起笔 <input id="seed" size="14" placeholder="留空则随机">
      篇幅 <input id="len" type="range" min="60" max="400" step="20" value="150">
      <span id="lenv" class="small">150 字</span>
      奇崛 <input id="temp" type="range" min="5" max="18" step="1" value="6">
      <label class="small"><input type="checkbox" id="anti"> 防回环</label>
      <button id="roll">掷笔</button>
    </div>
    <div class="small" id="vhint"></div>
  </div>
  <div class="card poem" id="out">
    <p class="small">点「掷笔」，看它能骗过几行。
    所得者是本书字句的重新拼缀，纯属统计把戏，并非创作，读者不当以其为真笔。</p>
  </div>
</div>

<div class="pane" id="p-judge" style="display:none">
  <div class="card">
    <textarea id="txt" rows="7"
      placeholder="粘贴一段文字……可以是自己的文言习作、别人的白话译笔，或别处的『红楼续』。"></textarea>
    <div class="gtools">
      <button id="s-old">随机取前八十回</button>
      <button id="s-new">随机取续写</button>
      <button id="s-anno">随机取脂批</button>
      <button id="run" class="on">照镜</button>
      <span class="gstat" id="jstat"></span>
    </div>
  </div>
  <div class="gwrap">
    <div class="card gcanvas">
      <div class="gtools"><span class="small">风格指纹：<b style="color:#9e2b25">实线</b>＝此文，
        <b style="color:#8a7f6d">虚线</b>＝脂本基准（1.0 圈）；离虚线圈越远，与脂本越不同。</span></div>
      <svg id="radar" viewBox="0 0 460 400" preserveAspectRatio="xMidYMid meet"></svg>
    </div>
    <aside class="card gside" id="jside"></aside>
  </div>
</div>

<div class="pane" id="p-spec" style="display:none">
  <div class="card small">纵轴＝字符困惑度，越低越「顺」此书的笔路。
    <b style="color:#3b4a6b">靛</b>＝脂本前八十回（八折交叉校验）；
    <b style="color:#9e2b25">朱</b>＝本次续写八十一至一百十回（全量模型）。
    点任一条，该回即刻被送进「辨体」。</div>
  <div class="card gcanvas">
    <svg id="sp" viewBox="0 0 1040 400" preserveAspectRatio="xMidYMid meet"></svg>
  </div>
  <div class="card" id="spinfo"></div>
</div>
"""

JS = r"""
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const B64='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
const W3=.55,W2=.30,W1=.15,FLOOR=.02;
const CIN='#9e2b25',IND='#3b4a6b',ASH='#8a7f6d',GOLD='#b08d57';
const clamp=v=>Math.max(0,Math.min(2,v));
const nf=(v,n)=>(Math.round(v*Math.pow(10,n))/Math.pow(10,n)).toFixed(n);

let DOC=null,XU=null,CLEAN=null,VM={},CUR='main',FROMGEN=false;

/* ---------------- 字符插值模型（与 Python honglou/mirror.py 的 Model 同式） -------------- */
function items(g){const o=g.n,K=g.k,C=g.c,a=[];
  for(let i=0;i<C.length;i++)a.push([K.substr(i*o,o),Math.exp(B64.indexOf(C[i])/6)-1]);
  return a;}
function mkModel(g){
  const M={uni:{},ut:0,tri:new Map(),triS:new Map(),bi:new Map(),biS:new Map()};
  for(const [k,w] of items(g.uni)){M.uni[k]=w;M.ut+=w;}
  for(const [k,w] of items(g.tri)){const p=k.slice(0,2),c=k[2];
    let a=M.tri.get(p);if(!a)M.tri.set(p,a=[]);a.push([c,w]);
    M.triS.set(p,(M.triS.get(p)||0)+w);}
  for(const [k,w] of items(g.bi)){const p=k[0],c=k[1];
    let a=M.bi.get(p);if(!a)M.bi.set(p,a=[]);a.push([c,w]);
    M.biS.set(p,(M.biS.get(p)||0)+w);}
  return M;
}
function prob(M,c1,c2,c){
  const u=(M.uni[c]||0)/M.ut;let p=W1*u;
  const a=M.tri.get(c1+c2);
  if(a){const s=M.triS.get(c1+c2);for(const [ch,w] of a)if(ch===c){p+=W3*w/s;break;}}
  const b=M.bi.get(c2);
  if(b){const s=M.biS.get(c2);for(const [ch,w] of b)if(ch===c){p+=W2*w/s;break;}}
  return (1-FLOOR)*p+FLOOR*u;
}
function ppl(M,t){
  if(!t||t.length<8)return 0;let s=0;
  for(let i=2;i<t.length;i++)s+=Math.log(Math.max(prob(M,t[i-2],t[i-1],t[i]),1e-9));
  return Math.exp(-s/(t.length-2));
}

/* ---------------- 拟笔 ---------------- */
function roll(){
  const M=VM[CUR],v=DOC.voices.find(x=>x.id===CUR);
  let seed=(($('seed').value||'').replace(CLEAN,'')).slice(0,24);
  if(!seed){
    const ss=v.seeds;seed=ss[Math.floor(Math.random()*ss.length)];
  }
  const want=+$('len').value,T=+$('temp').value/10,anti=$('anti').checked;
  let out=seed;
  for(let step=0;step<want*6&&out.length<want;step++){
    const ctx=out.slice(-2),c2=ctx[1];
    const agg=new Map();
    const add=(ch,w)=>agg.set(ch,(agg.get(ch)||0)+w);
    const a=M.tri.get(ctx);
    if(a){const s=M.triS.get(ctx);for(const [ch,w] of a)add(ch,W3*w/s);}
    const b=M.bi.get(c2);
    if(b){const s=M.biS.get(c2);for(const [ch,w] of b)add(ch,W2*w/s);}
    let arr=[...agg];
    if(!arr.length)arr=Object.keys(M.uni).map(ch=>[ch,W1*(M.uni[ch]||0)/M.ut]);
    arr=arr.map(([ch,w])=>{const u=(M.uni[ch]||0)/M.ut;
      return [ch,(1-FLOOR)*(w+W1*u)+FLOOR*u];});
    if(anti&&out.lastIndexOf(ctx)>out.length-9&&arr.length>3){
      arr.sort((x,y)=>y[1]-x[1]);
      const k=Math.max(3,Math.ceil(arr.length*0.7));
      arr=arr.slice(1,k);
    }
    const ws=arr.map(([ch,w])=>Math.pow(Math.max(w,1e-12),1/T));
    const tot=ws.reduce((x,y)=>x+y,0);
    let r=Math.random()*tot,pick=arr[0][0];
    for(let i=0;i<arr.length;i++){r-=ws[i];if(r<=0){pick=arr[i][0];break;}}
    out+=pick;
  }
  const t=Math.max(out.lastIndexOf('。'),out.lastIndexOf('！'),out.lastIndexOf('？'));
  if(t>want*0.35)out=out.slice(0,t+1);
  const body=out.replace(/([。！？][”』」]?)/g,'$1\n').split('\n')
    .filter(s=>s.trim()).map(s=>'<div>'+esc(s)+'</div>').join('');
  $('out').innerHTML=body+
    '<div class="small" style="margin-top:10px">— '+v.name+' · 字符三元组马尔可夫接笔'+
    '（原书 '+v.chars.toLocaleString()+' 字，三元组覆盖 '+nf(v.cover*100,1)+'%）'+
    '　<a href="javascript:void 0" id="tojudge">把这段送去照镜 →</a></div>';
  $('tojudge').onclick=()=>{if($('txt')){setText(out,'拟笔所得',true);switchTab('judge');}};
}

/* ---------------- 辨体 ---------------- */
function metrics(t,chunk){
  chunk=chunk||1500;
  const vs=[];
  for(let i=0;i<t.length;i+=chunk){
    const v=styleVec(t.slice(i,i+chunk));
    if(v.chars>=500)vs.push(v);
  }
  if(!vs.length)vs.push(styleVec(t));
  const keys=['sent','dlg','xu','tt'];
  const out={};
  keys.forEach(k=>out[k]=vs.reduce((a,v)=>a+v[k],0)/vs.length);
  out.chars=vs.reduce((a,v)=>a+v.chars,0);
  return out;
}
function styleVec(t){
  const han=(t.match(/[一-鿿]/g)||[]).join('');
  const sents=t.split(/[。！？；!?;]+/).filter(s=>s.trim());
  let nx=0;for(const c of han)if(XU.has(c))nx++;
  return {chars:han.length,
    sent:sents.reduce((a,s)=>a+s.length,0)/Math.max(1,sents.length),
    dlg:(t.match(/[：「"“]/g)||[]).length/Math.max(1,han.length),
    xu:nx/Math.max(1,han.length),
    tt:new Set([...han]).size/Math.max(1,han.length)};
}
function lint(t){
  const hits=DOC.modern.filter(w=>t.indexOf(w)>=0).map(w=>w+'×'+(t.split(w).length-1));
  return hits.slice(0,12);
}
function judge(){
  const raw=$('txt').value||'';
  const t=raw.replace(CLEAN,'');
  if(t.length<200){$('jstat').textContent='字数太少（至少 200 字，六百字以上方稳）';return;}
  const M=VM.main,B=DOC.bench,v=metrics(t);
  const p=ppl(M,t);
  const dist=Math.sqrt((Math.pow((v.sent-B.avg_sent_len)/30,2)
    +Math.pow((v.dlg-B.dialog_rate)/0.03,2)
    +Math.pow((v.xu-B.xuci_rate)/0.06,2)
    +Math.pow((v.tt-B.type_token)/0.1,2))/4);
  const near=nearest(v,p);
  $('jstat').textContent=t.length+' 字已照';
  drawRadar(v,p,B);
  const rows=[['句长',nf(v.sent,1)+' 字',nf(B.avg_sent_len,1)],
    ['对话率',nf(v.dlg*100,2)+'%',nf(B.dialog_rate*100,2)+'%'],
    ['虚词率',nf(v.xu*100,1)+'%',nf(B.xuci_rate*100,1)+'%'],
    ['型例比',nf(v.tt,3),nf(B.type_token,3)]];
  const L=lint(t);
  let verdict='';
  if(dist<=1.0)verdict='笔意在脂本邻域之内（距 '+nf(dist,2)+'，门禁以此为通过上限）。';
  else if(dist<=2.0)verdict='似而不似，尚有距离（距 '+nf(dist,2)+'）。';
  else verdict='去雪芹远矣（距 '+nf(dist,2)+'）。';
  const inset=p<=DOC.bench_ppl_in*1.05;
  let pverdict;
  if(inset)pverdict='已低于脂本「样本内」之水线——据此几乎可断定：此段本在书中。';
  else if(p<=DOC.bench_ppl*1.15)pverdict='顺此书笔路，比脂本交叉校验的水线还低，颇为得气。';
  else if(p<=DOC.bench_ppl*1.6)pverdict='略见生涩，尚在同一路数。';
  else pverdict='笔路生疏，此模型不认得它。';
  if(FROMGEN)pverdict='此段本就是接笔所得，模型自然认得自己写的字，故其数偏低乃应有之义，'+
    '不足为奇——要紧的是看那几项指纹，而不是困惑度。';
  $('jside').innerHTML=
    '<h3>照镜结果</h3>'+
    (t.length<600?'<p class="small">本文不足六百字，各项数字跳动甚大，只可看个大概。</p>':'')+
    '<table class="kv"><tr><td>汉字</td><td>'+v.chars.toLocaleString()+'</td></tr>'+
    rows.map(r=>'<tr><td>'+r[0]+'</td><td><b>'+r[1]+'</b>　<span class="small">基准 '+r[2]+'</span></td></tr>').join('')+
    '<tr><td>困惑度</td><td><b>'+nf(p,0)+'</b></td></tr>'+
    '<tr><td>脂本水线</td><td><span class="small">交叉校验（样本外）'+DOC.bench_ppl+
      '　/　样本内 '+DOC.bench_ppl_in+'</span></td></tr>'+
    '</table>'+
    '<p><b>风格距离</b> '+nf(dist,2)+'<br>'+verdict+'</p>'+
    '<p><b>困惑度</b><br>'+pverdict+'</p>'+
    (near?'<p><b>笔意最近</b><br>'+near+'</p>':'')+
    '<p><b>现代腔</b><br>'+(L.length?L.join('、'):'无违例')+
    '<br><span class="small">（此为续写门禁的禁例表，原著偶犯亦不足奇。）</span></p>'+
    '<p class="small">距离口径与「续写」页风格门禁同式。困惑度之两面：交叉校验水线是给<b>书外新文</b>用的尺，'+
    '样本内水线是给「它是否本在书中」用的尺——若你取的正是脂本原文，'+
    '宜以样本内之数相比，否则等于赛跑时给自己让了路。</p>';
}
function nearest(v,p){
  if(!DOC.spectrum.length)return '';
  const S=DOC.spectrum,norm=r=>({sent:r.sent/DOC.bench.avg_sent_len,
    dlg:r.dlg/DOC.bench.dialog_rate,xu:r.xu/DOC.bench.xuci_rate,
    tt:r.tt/DOC.bench.type_token,ppl:r.ppl/DOC.bench_ppl});
  const me=norm({sent:v.sent,dlg:v.dlg,xu:v.xu,tt:v.tt,ppl:p});
  const keys=['sent','dlg','xu','tt','ppl'];
  const d=r=>{const n=norm(r);return Math.sqrt(keys.reduce((a,k)=>a+Math.pow(n[k]-me[k],2),0)/5);};
  const best=S.map(r=>[d(r),r]).sort((a,b)=>a[0]-b[0]).slice(0,3);
  return best.map(([x,r])=>'第 '+r.chapter+' 回（'+(r.kind==='脂本'?'脂本':'本次续写')+
    '，距 '+nf(x,2)+'）').join('<br>');
}
function drawRadar(v,p,B){
  const R=132,cx=230,cy=196,n=5;
  const K=[{k:'句长',v:v.sent/B.avg_sent_len,f:nf(v.sent,1)},
    {k:'对话率',v:v.dlg/B.dialog_rate,f:nf(v.dlg*100,2)+'%'},
    {k:'虚词率',v:v.xu/B.xuci_rate,f:nf(v.xu*100,1)+'%'},
    {k:'型例比',v:v.tt/B.type_token,f:nf(v.tt,3)},
    {k:'困惑度',v:p/DOC.bench_ppl,f:nf(p,0)}];
  const pt=(i,r)=>[cx+r*Math.sin(i/n*2*Math.PI),cy-r*Math.cos(i/n*2*Math.PI)];
  let s='';
  [0.5,1,1.5].forEach(f=>{s+='<polygon points="'+
    K.map((_,i)=>pt(i,R*f/2).map(x=>Math.round(x)).join(',')).join(' ')+
    '" fill="none" stroke="'+(f===1?ASH:'#e3d9c4')+'" stroke-width="'+(f===1?1.4:1)+
    '" stroke-dasharray="'+(f===1?'4,3':'0')+'"/>';});
  for(let i=0;i<n;i++){
    const [x,y]=pt(i,R);
    s+='<line x1="'+cx+'" y1="'+cy+'" x2="'+Math.round(x)+'" y2="'+Math.round(y)+
       '" stroke="#e3d9c4"/>';
    const [lx,ly]=pt(i,R+28);
    s+='<text x="'+Math.round(lx)+'" y="'+Math.round(ly)+'" text-anchor="middle" '+
       'fill="#5d5449" font-size="13">'+K[i].k+'</text>';
    const th=i/n*2*Math.PI,rr=R*(clamp(K[i].v)/2);   // 数值：沿法线让开轴线，免得压住轴名
    const vx=cx+rr*Math.sin(th)+Math.cos(th)*22, vy=cy-rr*Math.cos(th)+Math.sin(th)*22;
    s+='<text x="'+Math.round(vx)+'" y="'+Math.round(vy)+'" text-anchor="middle" '+
       'fill="'+CIN+'" font-size="12">'+K[i].f+'</text>';
  }
  s+='<polygon points="'+K.map((x,i)=>pt(i,R*clamp(x.v)/2).map(q=>Math.round(q)).join(',')).join(' ')+
     '" fill="rgba(158,43,37,.14)" stroke="'+CIN+'" stroke-width="2"/>';
  $('radar').innerHTML=s;
}

/* ---------------- 光谱 ---------------- */
function drawSpec(){
  const S=DOC.spectrum,W=1040,H=400,pl=52,pr=14,pt=18,pb=40;
  const ps=S.map(r=>r.ppl).sort((a,b)=>a-b);
  const cap=ps[Math.floor(ps.length*0.94)]*1.06;
  const iw=(W-pl-pr)/S.length, bw=Math.max(2.5,iw-1.6);
  const y=v=>H-pb-(Math.min(v,cap)/cap)*(H-pt-pb);
  let s='';
  [0,.25,.5,.75,1].forEach(f=>{const yy=y(cap*f);
    s+='<line x1="'+pl+'" y1="'+yy+'" x2="'+(W-pr)+'" y2="'+yy+
       '" stroke="'+(f?'#e3d9c4':'#d8cdb6')+'"/>'+
       '<text x="'+(pl-8)+'" y="'+(yy+4)+'" text-anchor="end" fill="#8a7f6d" font-size="11">'+
       Math.round(cap*f)+'</text>';});
  S.forEach((r,i)=>{
    const x=pl+i*iw+(iw-bw)/2,c=r.kind==='脂本'?IND:CIN;
    s+='<rect x="'+x.toFixed(1)+'" y="'+y(r.ppl).toFixed(1)+'" width="'+bw.toFixed(1)+
       '" height="'+(H-pb-y(r.ppl)).toFixed(1)+'" fill="'+c+'" opacity=".82" rx="1">'+
       '<title>第 '+r.chapter+' 回　'+r.kind+'　困惑度 '+r.ppl+'　句长 '+r.sent+
       '　对话率 '+nf(r.dlg*100,2)+'%　虚词率 '+nf(r.xu*100,1)+'%</title></rect>'+
       '<rect x="'+(x-1.5)+'" y="'+pt+'" width="'+(bw+3)+'" height="'+(H-pb-pt)+
       '" fill="transparent" style="cursor:pointer" data-ch="'+r.chapter+'"/>';
  });
  const my=y(DOC.bench_ppl);
  s+='<line x1="'+pl+'" y1="'+my+'" x2="'+(W-pr)+'" y2="'+my+'" stroke="'+GOLD+
     '" stroke-dasharray="6,4" stroke-width="1.2"/>'+
     '<text x="'+(pl+6)+'" y="'+(my-6)+'" fill="'+GOLD+
     '" font-size="11" stroke="#fffdf8" stroke-width="3" paint-order="stroke">'+
     '脂本中位数 '+DOC.bench_ppl+'</text>';
  for(let c=1;c<=110;c+=10){const i=S.findIndex(r=>r.chapter===c);
    if(i<0)continue;const x=pl+i*iw+iw/2;
    s+='<text x="'+x+'" y="'+(H-pb+15)+'" text-anchor="middle" fill="#8a7f6d" font-size="11">'+c+'</text>';}
  s+='<text x="'+(pl+ (W-pl-pr)/2)+'" y="'+(H-8)+'" text-anchor="middle" fill="#8a7f6d" font-size="11">回次 →　（纵轴已按 94 分位截断，以免开端数回的诗词匾额压平全图）</text>';
  $('sp').innerHTML=s;
  $('sp').querySelectorAll('[data-ch]').forEach(el=>{
    el.onclick=()=>loadChapter(+el.dataset.ch);});
  const old=S.filter(r=>r.kind==='脂本').map(r=>r.ppl).sort((a,b)=>a-b);
  const mo=old[Math.floor(old.length/2)];
  const nw=S.filter(r=>r.kind==='续写');
  const lo=nw.filter(r=>r.ppl<=mo).length;
  $('spinfo').innerHTML='<h3>读数</h3><p class="small">'+
    '脂本前八十回困惑度中位数 <b>'+mo+'</b>（最低 '+old[0]+'，最高 '+old[old.length-1]+
    '；最高者多集中于开篇数回与第十七、十八回，彼处诗词匾额密集，非叙事常调）。'+
    '本次续写三十回之中，有 <b>'+lo+'</b> 回不高于脂本中位数，'+
    '最低 '+Math.min(...nw.map(r=>r.ppl))+'，最高 '+Math.max(...nw.map(r=>r.ppl))+'。'+
    '然此图只是一把写字之尺：它量的是字与字的接续概率，'+
    '量不出人物安顿、伏线收束、情理是否周全，更量不出文章的生气。</p>';
}

/* ---------------- 取样本 ---------------- */
function setText(t,tag,gen){
  FROMGEN=!!gen;$('txt').value=t;$('jstat').textContent=(tag||'')+' '+t.length+' 字';judge();
}
function loadChapter(n,quiet){
  if(n<=80){
    fetch('data/chapters/'+String(n).padStart(3,'0')+'.json').then(r=>r.json()).then(d=>{
      const t=d.blocks.filter(b=>b.kind==='正文').map(b=>b.text).join('');
      const i=Math.max(0,Math.floor((t.length-2600)/2));
      setText(t.slice(i,i+2600),'第 '+n+' 回');
      if(!quiet)switchTab('judge');
    }).catch(()=>{$('jstat').textContent='取第 '+n+' 回失败';});
  }else{
    fetch('data/continuations.json').then(r=>r.json()).then(a=>{
      const c=a.find(x=>x.chapter===n);
      if(c)setText(c.text.slice(0,2600).trim(),'第 '+n+' 回（续写）');
      if(!quiet)switchTab('judge');
    }).catch(()=>{});
  }
}
function pickRandom(kind,quiet){
  if(kind==='anno'){
    const S=DOC.anno_samples||[];
    if(S.length){setText(S[Math.floor(Math.random()*S.length)],'脂批');
      if(!quiet)switchTab('judge');}
    return;
  }
  const n=kind==='old'?1+Math.floor(Math.random()*80):81+Math.floor(Math.random()*30);
  loadChapter(n,quiet);
}

/* ---------------- 版式 ---------------- */
function switchTab(t){
  document.querySelectorAll('#tabs button').forEach(b=>b.className=(b.dataset.t===t?'on':''));
  ['gen','judge','spec'].forEach(k=>{$('p-'+k).style.display=(k===t?'':'none');});
}
function buildVoiceTabs(){
  const box=$('vbtns');
  DOC.voices.forEach(v=>{
    const b=document.createElement('button');
    b.textContent=v.name;b.style.marginRight='6px';
    b.onclick=()=>{CUR=v.id;
      box.querySelectorAll('button').forEach(x=>x.className='');
      b.className='on';$('vhint').textContent=v.hint;
      if(!$('seed').value)$('roll').click();};
    if(v.id===CUR)b.className='on';
    box.appendChild(b);
  });
  const v=DOC.voices[0];
  $('vhint').textContent=v.hint;
}

fetch('data/mirror.json?v=__VER__').then(r=>r.json()).then(d=>{
  DOC=d;XU=new Set(d.xuci);
  CLEAN=new RegExp('[^一-鿿'+d.punct+']','g');
  d.voices.forEach(v=>VM[v.id]=mkModel(v.grams));
  $('len').oninput=e=>$('lenv').textContent=e.target.value+' 字';
  $('roll').onclick=roll;
  $('run').onclick=judge;
  $('s-old').onclick=()=>pickRandom('old');
  $('s-new').onclick=()=>pickRandom('new');
  $('s-anno').onclick=()=>pickRandom('anno');
  document.querySelectorAll('#tabs button').forEach(b=>{b.onclick=()=>switchTab(b.dataset.t);});
  buildVoiceTabs();drawSpec();pickRandom('old',true);roll();
}).catch(e=>{$('out').textContent='字镜数据加载失败：'+e;});
"""

def js(ver: str = '') -> str:
    """页面脚本：__VER__ 换成数据指纹，免浏览器取到旧模型。"""
    return JS.replace('__VER__', ver or '0')


if __name__ == '__main__':
    p = build()
    print('字镜数据：', p, f'{p.stat().st_size / 1024:.0f} KB')
