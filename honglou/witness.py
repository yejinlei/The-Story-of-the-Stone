"""多版本「见证本」语料的抓取、清洗与本地缓存。

来源为维基文库的可 freely-licensed 转录本，保留 manifest（URL + sha256）
以便重建。之所以不用底本 PDF：那里只有八十回脂用以校；要谈程高本，
非得有一百二十回的另一条谱系不可。

见证本一览（ key → 系统 / 回数 / 语体 ）

    chengjia  程甲本（萃文书屋木活字，乾隆五十六年）  120 回  繁体
    chengyi   程乙本（乾隆五十七年重订）             120 回  繁体
    zhiqi     脂砚斋重评石头记（维基文库录本）        80 回   繁体，内附诸家脂批
    jiaxu     脂砚斋重评石头记甲戌本                 16 回   繁体

另有两条不从此 сюда来：
    hui       本地《红楼梦脂评汇校本》                80 回   简体 + 脂批 + 校记
    ai        本项目多 Agent 续写                    30 回   简体
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.parse as up
import urllib.request as u
from html.parser import HTMLParser
from pathlib import Path

from . import paths

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36 (hlm-version-study; local)")

API = "https://zh.wikisource.org/w/api.php"
INDEX = "https://zh.wikisource.org/w/index.php"

CN = {'零': 0, '〇': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
      '六': 6, '七': 7, '八': 8, '九': 9}


def cn2int(s: str) -> int | None:
    """中文数字 → 整数。

    转录本的写法并不一律：「九十九」「一百二十」之外，还有用圈号的
    「一○○」（百回）、「一○一」（百零一回）、「一一一」（百十一回），
    三者都得认。
    """
    s = s.strip().replace(' ', '').replace('〇', '○').replace('零', '○')
    if not s:
        return None
    if '百' in s:
        a, _, b = s.partition('百')
        hi = _digits(a)
        hi = 1 if hi in (None, 0) else hi
        return hi * 100 + (cn2int(b) or 0)
    if '十' in s:
        a, _, b = s.partition('十')
        hi = _digits(a)
        hi = 1 if hi is None else hi
        return hi * 10 + (_digits(b) or 0)
    return _digits(s)


def _digits(s: str) -> int | None:
    """纯数字串 → 整数，圈号作零位。空串返回 None。"""
    if not s:
        return None
    v = 0
    for c in s:
        if c == '○':
            v *= 10
        elif c in CN:
            v = v * 10 + CN[c]
        else:
            return None
    return v


# ---------------------------------------------------------------- 抓取层

def _http(url: str, retry: int = 4, sleep: float = 1.2) -> bytes:
    last = None
    for i in range(retry):
        try:
            return u.urlopen(u.Request(url, headers={"User-Agent": UA}),
                             timeout=40).read()
        except Exception as e:              # 网络不稳，歇口气再来
            last = e
            time.sleep(sleep * (i + 1))
    raise RuntimeError(f"抓取失败 {url}：{last}")


def raw_wikitext(title: str) -> str:
    return _http(f"{INDEX}?title={up.quote(title)}&action=raw").decode("utf-8")


def rendered_html(title: str) -> str:
    url = (f"{API}?action=parse&format=json&prop=text&redirects=1"
           f"&page={up.quote(title)}")
    d = json.loads(_http(url).decode("utf-8"))
    return d["parse"]["text"]["*"]


class _Text(HTMLParser):
    """剥标签取文本：跳过 style/script/引注/批复 tooltip 之类。"""

    SKIP = {"style", "script", "sup", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.buf: list[str] = []
        self._skip = 0
        self._drop = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self._skip += 1
            return
        cls = a.get("class", "")
        if "variant-tooltip" in cls or "mw-editsection" in cls or "noprint" in cls:
            self._drop += 1
        if tag in ("p", "div", "br", "li", "dd"):
            self.buf.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag in ("div", "li", "dd"):
            self.buf.append("\n")

    def handle_data(self, data):
        if self._skip or self._drop:
            return
        self.buf.append(data)

    def text(self) -> str:
        return "".join(self.buf)


def html2text(h: str) -> str:
    """标签 ⇢ 文本。

    不用 HTMLParser：电子书页面里 `<style>` 与未闭合的行内标签会把解析器带进
    CDATA 模式，后半篇全被吞掉；正则反过来更稳。
    """
    h = re.sub(r"<style[^>]*>.*?</style>", " ", h, flags=re.S | re.I)
    h = re.sub(r"<script[^>]*>.*?</script>", " ", h, flags=re.S | re.I)
    # 转写本的「某字各抄本均作某」浮层，重复剥到不再有为止
    for _ in range(4):
        h2 = re.sub(r'<span class="variant-tooltip"[^>]*>[^<]*</span>', "", h)
        if h2 == h:
            break
        h = h2
    h = re.sub(r'<sup[^>]*class="[^"]*reference[^"]*"[^>]*>.*?</sup>', "", h,
               flags=re.S | re.I)
    h = re.sub(r"</p\s*>", "\n", h, flags=re.I)
    h = re.sub(r"<br\s*/?\s*>", "\n", h, flags=re.I)
    h = re.sub(r"</(?:div|li|dd|tr|h[1-6]|blockquote)\s*>", "\n", h, flags=re.I)
    h = re.sub(r"<[^>]+>", "", h)
    t = html.unescape(h).replace("\u200b", "")
    t = re.sub(r"[ \t\r]+", " ", t)
    t = re.sub(r"\n\s*\n\s*\n+", "\n\n", t)
    return "\n".join(ln.strip() for ln in t.split("\n"))


# ---------------------------------------------------------------- 清洗层

NAV_RE = re.compile(r"^(?:目錄|目录|繡像|绣像|◀.*|.*▶|.*回目錄|.*回目录"
                    r"|紅樓夢（.*）|红楼梦（.*）|全書始|全书始|首頁|首页)$")
TITLE_RE = re.compile(r"^第([〇○零一二三四五六七八九十百]{1,5})回[ 　]*"
                      r"([^\n]{4,40})$")

# 古籍常见的异写字，opencc 不管，统计学前须先归一
VAR_MAP = {ord('囬'): '回', ord('龢'): '和', ord('寳'): '宝',
           ord('靣'): '面', ord('従'): '从', ord('遅'): '迟',
           ord('敎'): '教', ord('歴'): '历', ord('歴'): '历',
           ord('㑹'): '会', ord('㑹'): '会', ord('唘'): '启',
           ord('冊'): '册', ord('茲'): '兹', ord('卽'): '即',
           ord('舘'): '馆', ord('畧'): '略', ord('冩'): '写',
           ord('円'): '圆', ord('沒'): '没', ord('峯'): '峰'}


def varmap() -> dict[str, str]:
    """data/variant_map.json：一眼而定不可再有二层曲折者皆在焉。"""
    if not varmap._cache:                               # type: ignore
        p = paths.data("variant_map.json")
        varmap._cache = (json.loads(                    # type: ignore
            p.read_text(encoding="utf-8"))["map"] if p.exists() else {})
    return varmap._cache                                # type: ignore


varmap._cache = None                                    # type: ignore


def normalize(s: str) -> str:
    """统一为正体简体：繁转简 + 抄本异写字归位。

    幂等，重复调用无妨——所以 analyse 时可以先 san[r]=再归一一次。
    """
    s = s.translate(VAR_MAP)
    try:
        from opencc import OpenCC                       # 延迟导入
        if normalize._cc is None:                       # type: ignore
            normalize._cc = OpenCC('t2s')               # type: ignore
        s = normalize._cc.convert(s)                    # type: ignore
    except Exception:
        pass
    return s.translate(str.maketrans(varmap()))


normalize._cc = None                                    # type: ignore


def strip_body(text: str) -> str:
    """去掉篇首导航，只留正文。"""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    start = 0
    for i, ln in enumerate(lines):
        if len(ln) >= 40:
            start = i
            break
    out = []
    for ln in lines[start:]:
        if NAV_RE.match(ln.strip()) or len(ln.strip()) <= 2:
            continue
        out.append(ln)
    return "\n".join(out)


def pick_title(text: str, no: int) -> str:
    """回目：整行冠于篇首者最佳，退而求其次可在句以内（header 里常如此）。"""
    for ln in text.split("\n")[:80]:
        m = TITLE_RE.match(ln.strip())
        if m and cn2int(m.group(1)) == no:
            return re.sub(r"['\"《》,，。；;：:]", "", m.group(2)).strip()
    m = TITLE_RE.search(text[:1200] if len(text) < 20000 else text[:20000])
    if m and cn2int(m.group(1)) == no:
        return re.sub(r"['\"《》]", "", m.group(2)).strip()
    return ""


def clean(text: str, no: int) -> tuple[str, str]:
    norm = normalize(text)
    title = pick_title(norm, no)
    return title, strip_body(norm)


# ---------------------------------------------------------------- 各本定义

def _cj_title(n: int) -> str:
    """程甲本 Pagename 用的中文数字（一 … 一百二十）。"""
    return CN_NUM_ZH(n)


def CN_NUM_ZH(n: int) -> str:
    """中文数字：一 … 一百二十（维基文库目录字样的写法）。"""
    d = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九']
    if n < 10:
        return d[n]
    if n < 20:
        return '十' + (d[n % 10] if n % 10 else '')
    if n < 100:
        return d[n // 10] + '十' + (d[n % 10] if n % 10 else '')
    if n == 100:
        return '一百'
    if n < 110:
        return '一百零' + d[n % 10]
    if n < 120:
        return '一百一十' + (d[n % 10] if n % 10 else '')
    return '一百二十'


SOURCES = {
    "chengjia": dict(
        name="程甲本", family="程高本", mode="render",
        full="《绣像红楼梦》，程伟元、高鹗排印，萃文书屋木活字本，乾隆五十六年（1791）",
        note="一百二十回首次以印刷的形式完整行世；前八十回已经过整理改写。",
        year=1791, first=1, last=120, zh_name=True),
    "chengyi": dict(
        name="程乙本", family="程高本",
        full="《绣像红楼梦》重订本，萃文书屋，乾隆五十七年（1792）",
        note="程甲本刊行次年即改版，增删改以数万字计。",
        year=1792, first=1, last=120, bundle=10),
    "zhiqi": dict(
        name="脂砚斋重评石头记", family="脂评本", mode="raw",
        full="脂砚斋重评石头记（维基文库转录本，诸家脂批夹入正文）",
        note="八十回，内嵌甲、蒙、戚、靖诸本脂批，可与此间底本互相印证。",
        year=0, first=1, last=80),
    "jiaxu": dict(
        name="甲戌本", family="脂评本", mode="raw",
        full="脂砚斋重评石头记甲戌本（乾隆十九年脂砚斋抄阅再评本）",
        note="仅存十六回，批语最富，文字亦最近原笔。",
        year=1754, first=0, last=16, existent=list(range(1, 9)) +
        list(range(13, 17)) + list(range(25, 29))),
}


def _title_of(key: str, n: int, src: dict) -> str:
    if key == "chengjia":
        return f"紅樓夢（程甲本）/{CN_NUM_ZH(n)}"
    if key == "zhiqi":
        return f"脂硯齋重評石頭記/第{CN_NUM_ZH(n)}回"
    if key == "jiaxu":
        return f"脂硯齋重評石頭記甲戌本/第{CN_NUM_ZH(n)}回"
    return ""


# ---------------------------------------------------------------- 抓取

def _chengyi_pages() -> dict[int, str]:
    """程乙本按十回一分卷：先问 API 拿到卷名，再逐卷取回、按回目切开。"""
    import urllib.parse as _up
    d = json.loads(_http(
        f"{API}?action=query&list=allpages&apnamespace=0&aplimit=50&format=json"
        f"&apprefix={_up.quote('紅樓夢（程乙本）/')}").decode("utf-8"))
    out: dict[int, str] = {}
    for p in d["query"]["allpages"]:
        tail = p["title"].split("/", 1)[1]
        if "至" not in tail:
            continue
        wt = raw_wikitext(p["title"])
        parts = re.split(r"\n==+\s*(第[〇○零一二三四五六七八九十百]{1,6}回)", wt)
        # parts: [前言, '第一回', 文本, '第二回', …]
        for i in range(1, len(parts), 2):
            head = parts[i]
            body = parts[i + 1] if i + 1 < len(parts) else ""
            n = cn2int(head.replace("第", "", 1).replace("回", ""))
            if n:
                out[n] = f"{head}{body}"
        time.sleep(0.2)
    return out


def fetch(keys: list[str] | None = None, force: bool = False,
          pause: float = 0.25) -> dict[str, Path]:
    """抓取各本全文，落到 data/witnesses/<key>.json。"""
    store = paths.DATA_DIR / "witnesses"
    store.mkdir(parents=True, exist_ok=True)
    keys = keys or list(SOURCES)
    written: dict[str, Path] = {}
    manifest = {}
    mpath = store / "manifest.json"
    if mpath.exists():
        manifest = json.loads(mpath.read_text(encoding="utf-8"))

    for key in keys:
        src = SOURCES[key]
        tgt = store / f"{key}.json"
        if tgt.exists() and not force:
            written[key] = tgt
            continue
        chapters = {}
        if src.get("bundle"):
            pages = _chengyi_pages()
            for n in range(src["first"], src["last"] + 1):
                body = pages.get(n, "")
                if not body:
                    continue
                chapters[n] = _clean_page(body, n, "raw")
        else:
            ns = src.get("existent") or range(src["first"], src["last"] + 1)
            mode = src.get("mode", "render")
            for n in ns:
                title = _title_of(key, n, src)
                body = None
                for attempt in range(3):
                    try:
                        body = (raw_wikitext(title) if mode == "raw"
                                else rendered_html(title))
                        break
                    except Exception:
                        time.sleep(1.0 * (attempt + 1))
                if not body:
                    continue
                chapters[n] = _clean_page(body, n, mode, key)
                time.sleep(pause)
        rec = dict(meta=dict(key=key, **{k: v for k, v in src.items()
                                         if k in ("name", "family", "full",
                                                  "note", "year", "first", "last")}),
                   chapters=chapters)
        # 清洗的有效性自检：回数与字数
        rec["meta"]["fetched"] = time.strftime("%Y-%m-%d")
        rec["meta"]["chapters_ok"] = len(chapters)
        tgt.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        manifest[key] = dict(source="zh.wikisource.org",
                             titles=_sample_titles(key, n) if chapters else [],
                             chapters=len(chapters),
                             sha256=hashlib.sha256(tgt.read_bytes()).hexdigest(),
                             fetched=rec["meta"]["fetched"])
        written[key] = tgt
        print(f"  {key}: {len(chapters)} 回")
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    return written


def _sample_titles(key: str, n: int) -> list[str]:
    return [_title_of(key, 1, SOURCES[key]), _title_of(key, n, SOURCES[key])]


_ED = "甲庚己戚蒙列楊杨舒覺觉靖程"
ANNO_HEAD = re.compile(
    rf"([{_ED}]{{1,2}}(?:、[{_ED}]{{1,2}})*)"
    r"([回前後后眉側侧雙双夾夹批總总評评语]{0,5})[：:]")
ED_SHORT = {"甲": "甲戌", "庚": "庚辰", "己": "己卯", "戚": "戚序",
            "蒙": "蒙府", "列": "列藏", "楊": "杨藏", "杨": "杨藏",
            "舒": "舒序", "覺": "甲辰", "觉": "甲辰", "靖": "靖藏",
            "程": "程高"}
TYPE_MAP = {"側": "侧批", "侧": "侧批", "眉": "眉批", "雙": "夹批",
            "双": "夹批", "夾": "夹批", "夹": "夹批",
            "回前": "回前批", "回后": "回后批", "回後": "回后批",
            "回前總批": "回前批", "回前總評": "回前批",
            "批": "批语", "總批": "回前批", "總評": "回后批", "" : "批语"}


def harvest_annos(wt: str, default_ed: list[str] | None = None) -> list[dict]:
    """钩出内嵌脂批，作第二重谱系。

    【甲側：…】者标明版本与位置；单纯套在 [ ] 里的（如甲戌本）只得认作
    该本自有之批，由调用者给出 default_ed。
    """
    out: list[dict] = []
    for m in re.finditer(r"【([^】]{2,300})】", wt):
        out += _split_annos(m.group(1), default_ed)
    for m in re.finditer(r"\{\{[^{}]*?\[([^\[\]{}]{2,300})\][^{}]*?\}\}", wt):
        t = m.group(1).strip()
        if t:
            out.append(dict(editions=list(default_ed or []),
                            atype="夹批", text=t))
    return out


def _split_annos(seg: str, default_ed: list[str] | None) -> list[dict]:
    parts = ANNO_HEAD.split(seg)
    # 形如 ['', '甲', '側', '自佔地步…', '蒙', '雙', '…']
    out = []
    for i in range(1, len(parts) - 2, 3):
        eds_raw, typ, tail = parts[i], parts[i + 1], parts[i + 2]
        if not tail.strip():
            continue
        eds = [ED_SHORT.get(e.strip(), e.strip())
               for e in eds_raw.split("、")]
        out.append(dict(editions=eds, atype=TYPE_MAP.get(typ, "批语"),
                        text=tail.strip()))
    if len(parts) == 1 and seg.strip() and default_ed:
        out.append(dict(editions=list(default_ed), atype="批语",
                        text=seg.strip()))
    return out


# 录本自身属某本者，未标版本的夹批归该本所有
SRC_DEFAULT_ED = {"jiaxu": ["甲戌"], "zhiqi": []}


def _clean_page(body: str, no: int, mode: str, key: str = "") -> dict:
    if mode == "render":
        raw = html2text(body)
        annos: list[dict] = []
    else:
        # 回目常写在 header 的 section 参数里，须在剥模板之前截出。
        # 第三回的回目被一条脂批拦腰截断（「荣国府收养」【甲侧：…】「林黛玉」），
        # 故先把夹批抹去再取。
        # 不能先把模板剥掉再找 section：header 本身就是一层模板，
        # 一剥就连同回目一起没了。故先取参数值，再收拾其中的夹批与引号。
        # 回目有 Writing在下一行者（如第三十九回），故须跨行取到下一个参数为止
        m = re.search(r"\|\s*section\s*=\s*第([〇○零一二三四五六七八九十百]{1,5})"
                      r"\s*回\s*(.{4,160}?)\n\s*\|", body, re.S)
        head_title = ""
        if m and cn2int(m.group(1)) == no:
            ht = re.sub(r"【[^】]*】", "", m.group(2))
            for _ in range(6):                    # 嵌套模板逐层去
                ht = re.sub(r"\{\{[^{}]*\}\}", "", ht)
            ht = re.sub(r"\{\{|\}\}|~+\|", "", ht)   # 残余碎屑
            ht = re.sub(r"\[[^\[\]]{0,60}\]", "", ht)
            head_title = re.sub(r"['\"《》]", "",
                                re.sub(r"[\s　]+", " ", ht)).strip()
        annos = harvest_annos(body, SRC_DEFAULT_ED.get(key, []))
        clean_body = _strip_wikitext(re.sub(r"【[^】]*】", "", body))
        # 转录本以方括号记夹批，模板展开后会漏进正文
        clean_body = re.sub(r"\[[^\[\]]{0,200}\]", "", clean_body)
        raw = clean_body
        if head_title and head_title not in raw:
            raw = f"第{CN_NUM_ZH(no)}回　{head_title}\n" + raw
    title, text = clean(raw, no)
    rec = dict(title=title, text=text)
    if annos:
        rec["annos"] = annos
    return rec


def _expand_templates(s: str) -> str:
    """逐个剥掉模板：带无名参数的（如 center|回目）留其中最长的那个，
    只留参数名的（如 Novel|…|回目|上一回|下一回）则不留。

    嵌套模板由外而内解，最多八层。
    """
    for _ in range(8):
        if "{{" not in s:
            break
        out, i, changed = [], 0, False
        while i < len(s):
            if s.startswith("{{", i):
                d, j = 0, i
                while j < len(s):
                    if s.startswith("{{", j):
                        d += 1
                        j += 2
                    elif s.startswith("}}", j):
                        d -= 1
                        j += 2
                        if d == 0:
                            break
                    else:
                        j += 1
                inner = s[i + 2:j - 2]
                parts, depth, cur = [], 0, ''
                for c in inner:
                    if c in "[{":
                        depth += 1
                    elif c in "]}":
                        depth -= 1
                    if c == "|" and depth == 0:
                        parts.append(cur)
                        cur = ''
                    else:
                        cur += c
                parts.append(cur)
                keep = [p.strip() for p in parts[1:] if "=" not in p and p.strip()]
                out.append(max(keep, key=len) if keep else '')
                i = j
                changed = True
            else:
                out.append(s[i])
                i += 1
        s = "".join(out)
        if not changed:
            break
    return s


def _strip_wikitext(wt: str) -> str:
    """剥除维基标记：模板、链接、注释、标题记号。"""
    s = wt
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"<ref[^>]*/>", "", s)
    s = re.sub(r"</?font[^>]*>", "", s)     # 转录本里的隐字号残余
    s = re.sub(r"<br\s*/?\s*>", "\n", s)
    s = _expand_templates(s)
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"''+", "", s)
    s = re.sub(r"={2,}\s*", "\n", s)
    s = re.sub(r"\[https?://\S+\s+([^\]]*)\]", r"\1", s)
    s = s.replace("&nbsp;", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s


# ---------------------------------------------------------------- 读取

def load(key: str) -> dict | None:
    p = paths.DATA_DIR / "witnesses" / f"{key}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def texts(key: str) -> dict[int, str]:
    """回次 → 正文（不含回目行）。"""
    rec = load(key)
    if not rec:
        return {}
    out = {}
    for k, v in rec["chapters"].items():
        out[int(k)] = v["text"]
    return out


def titles(key: str) -> dict[int, str]:
    rec = load(key)
    if not rec:
        return {}
    return {int(k): v["title"] for k, v in rec["chapters"].items()}


if __name__ == "__main__":
    import sys
    ks = sys.argv[1:] or None
    fetch(ks)
