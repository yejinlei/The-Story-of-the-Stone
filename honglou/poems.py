"""诗词本体：从脂评汇校本正文中抽取诗、词、曲、赋、联句、谜、令、诔、偈、判词等韵文。

抽取流程
--------
1. 逐回拼接正文块（批语块跳过，故相邻正文块语义连续），按韵文标点切分句。
2. 对每个分句算语言学特征：齐言长度、散文虚词密度、韵脚（pypinyin 韵基）。
3. 滑动窗口找「齐言 + 低虚词 + 偶句同韵」的连续段，即诗/联句/判词。
4. 标题路：以「第X支 X」「XX诗/词/诔/偈/赋」等标题块为锚点，覆盖不齐言的词曲诔赋。
5. 体裁、作者、意象、典故、谶应等语义维度由 annotate 阶段（规则 + 大模型）完成。

判据设计要点：散文里「四六骈句」也很齐言，单靠齐言会把叙事误判成诗，
故必须叠加「散文虚词密度」与「偶数句韵基一致率」两道硬指标。
"""
from __future__ import annotations

import json
import re
from collections import Counter

from . import paths
from .bootstrap import ensure_pylibs

ensure_pylibs()
from pypinyin import Style, lazy_pinyin  # noqa: E402

# ---------------------------------------------------------------- 常量

CLOSER = '，。！？；,!?;'
HANZI = re.compile(r'[一-鿿]')
SPEAKER_RE = re.compile(
    r'^(?:[^，。！？；：]{0,10}?)'
    r'(?:忙|笑|也|便|因|遂|又|一面|不觉|于是)?'
    r'(?:联道|笑道|吟道|念道|赞道|说道|答道|哭道|道|说)[：:]')

# 散文高频虚词（诗句中密度低，叙事中密度高）
XUCI = set('的了着过是就在与和为以使所之其而则因故遂乃便又也很都再把被让使从向'
           '对我你他她它们这那个些儿吗呢罢么咱您凡皆俱均忽即曾尚犹却只但且若'
           '虽既抑或于是便道曰来去上下里外时后前中日年月')
# 诗词意象常见实词（用于加权，不作硬判据）
YIXIANG = set('花月风云雪霜春秋江山水竹梅兰菊柳松燕雁莺蝶梦泪香魂影寒清冷烟霞'
              '玉金红绿翠白黄昏晓夜星露苔阶帘窗庭院楼台琴箫笛酒茶灯火舟桥')

QU_PAI = ['红楼梦引子', '终身误', '枉凝眉', '恨无常', '分骨肉', '乐中悲', '世难容',
          '喜冤家', '虚花悟', '聪明累', '留余庆', '晚韶华', '好事终', '飞鸟各投林']
CI_PAI = ['如梦令', '唐多令', '临江仙', '西江月', '好事近', '南柯子', '忆江南',
          '浣溪沙', '蝶恋花', '柳絮词', '点绛唇', '菩萨蛮', '虞美人', '鹊桥仙',
          '念奴娇', '满江红', '水调歌头', '踏莎行', '望江南', '渔家傲']
JU_TOPICS = ['忆菊', '访菊', '种菊', '对菊', '供菊', '咏菊', '画菊', '问菊',
             '簪菊', '菊影', '菊梦', '残菊']
HAO = {'蘅芜君': '薛宝钗', '潇湘妃子': '林黛玉', '蕉下客': '贾探春',
       '枕霞旧友': '史湘云', '绛洞花主': '贾宝玉', '菱洲': '贾迎春',
       '藕榭': '贾惜春', '稻香老农': '李纨'}

# 诗性锚点（出现在上文 200 字内则大幅加分）
ANCHOR = re.compile(
    r'(题一绝|口占|一律|一绝|绝句|律诗|排律|即景联句|联句|联诗|吟成|成一律|'
    r'作诗|赋诗|题诗|咏|诗曰|有诗为证|词曰|其词曰|调寄|写道是|写道|书云|'
    r'判云|其判曰|断语云|歌词云|歌曰|作歌|唱|偈|诔|祭文|灯谜|谜语|酒令|'
    r'牙牌令|占花名|花签|对联|匾额|题额|怀古|即事|感怀|拟.{1,6}之格|'
    r'第[一二三四五六七八九十]{1,3}支|第[一二三四五六七八九十]{1,3}首)')


# ---------------------------------------------------------------- 特征

def _hanzi(s: str) -> str:
    return ''.join(HANZI.findall(s))


_RHYME_CACHE: dict[str, str] = {}


def rhyme_of(ch: str) -> str:
    """取单字韵基（去声调、去韵头）。"""
    if ch in _RHYME_CACHE:
        return _RHYME_CACHE[ch]
    try:
        f = lazy_pinyin(ch, style=Style.FINALS_TONE3)[0]
    except Exception:
        f = ''
    f = re.sub(r'\d', '', f)
    f = re.sub(r'^[iuvü]', '', f) or f
    _RHYME_CACHE[ch] = f
    return f


def punct_free(s: str) -> str:
    return re.sub(r'[，。！？；：、“”‘’（）《》,!?;:]', '', s)


def xuci_density(s: str) -> float:
    z = _hanzi(s)
    if not z:
        return 1.0
    return sum(1 for c in z if c in XUCI) / len(z)


def yixiang_density(s: str) -> float:
    z = _hanzi(s)
    if not z:
        return 0.0
    return sum(1 for c in z if c in YIXIANG) / len(z)


def sentences(text: str) -> list[dict]:
    """按韵文标点切分句，剥离「XX道：」类说话人前缀。"""
    buf, raws = [], []
    for ch in text:
        # 块边界（'\n'）同样是语义边界，诗句常独立成块，必须切开
        if ch in CLOSER or ch == '\n':
            raws.append(''.join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        raws.append(''.join(buf))
    res = []
    for raw in raws:
        speaker = ''
        m = SPEAKER_RE.match(raw)
        if m:
            speaker, raw = raw[:m.end()], raw[m.end():]
        body = re.sub(r'[，。！？；：、“”‘’（）《》,!?;:]', '', raw)
        if not body:
            continue
        res.append(dict(text=raw.strip(), body=body, len=len(body),
                        speaker=speaker.strip('：: '),
                        xu=xuci_density(body), rhyme=rhyme_of(body[-1]) if body else ''))
    return res


def _odd_rhyme_rate(sents: list[dict]) -> float:
    """偶数句（第 2、4、6…句）末字韵基一致率。"""
    evens = [sents[i] for i in range(1, len(sents), 2) if sents[i]['rhyme']]
    if len(evens) < 2:
        return 0.0
    c = Counter(e['rhyme'] for e in evens)
    return c.most_common(1)[0][1] / len(evens)


def verse_score(sents: list[dict]) -> dict:
    """给一个候选分句窗口算「诗性」指标。"""
    n = len(sents)
    lens = [s['len'] for s in sents]
    c = Counter(lens)
    main_len, hit = c.most_common(1)[0]
    uniform = hit / n
    xu = sum(s['xu'] * s['len'] for s in sents) / max(1, sum(lens))
    yi = sum(len([1 for ch in s['body'] if ch in YIXIANG]) for s in sents) / max(1, sum(lens))
    return dict(n=n, main_len=main_len, uniform=uniform, xu=xu, yi=yi,
                rhyme=_odd_rhyme_rate(sents))


def is_verse(sc: dict, ctx: str) -> bool:
    """综合判定是否为韵文段。"""
    if sc['n'] < 4:
        return sc['n'] >= 2 and sc['main_len'] in (5, 7) and sc['xu'] <= 0.08 and bool(ANCHOR.search(ctx))
    if sc['main_len'] not in (4, 5, 6, 7):
        return False
    if sc['uniform'] < 0.75:
        return False
    if sc['xu'] > 0.13:
        return False
    anchor = bool(ANCHOR.search(ctx))
    long_form = sc['n'] >= 8
    if sc['main_len'] in (5, 7):
        if long_form:
            ok = sc['rhyme'] >= 0.6 and (sc['xu'] <= 0.11 or anchor)
        else:
            ok = (sc['rhyme'] >= 0.5 and sc['xu'] <= 0.10) or (anchor and sc['xu'] <= 0.07)
    else:                      # 四言、六言：人物赞赋与骈文描写极多，必须见锚点
        ok = (anchor and sc['rhyme'] >= 0.5 and sc['xu'] <= 0.05
              and sc['yi'] >= 0.10)
    return ok


# 叙事尾巴：诗段首尾常粘着「宝玉看了」「众人称奇」之类
NARR_TAIL = re.compile(
    r'(看了|听了|说完|说毕|笑道|说道|众人|不知|且听|正是|看毕|称赏|'
    r'便问|因问|听说|点头|摆手|起身|去了|起来)')


def trim_edges(sents: list[dict]) -> list[dict]:
    """去掉粘连在诗段首尾的叙事分句。"""
    out = list(sents)
    while out and (out[0]['xu'] > 0.22 or NARR_TAIL.search(out[0]['body'])
                   or not (2 <= out[0]['len'] <= 16)):
        out.pop(0)
    while out and (out[-1]['xu'] > 0.22 or NARR_TAIL.search(out[-1]['body'])
                   or not (2 <= out[-1]['len'] <= 16)):
        out.pop()
    return out


# ---------------------------------------------------------------- 拼接

def chapter_stream(ch: dict) -> tuple[str, list[tuple[int, int, int]]]:
    parts, spans = [], []
    pos = 0
    for b in ch['blocks']:
        if b['kind'] != '正文':
            continue
        t = b['text'].strip()
        if not t:
            continue
        parts.append(t)
        spans.append((pos, pos + len(t), b['id']))
        pos += len(t) + 1
        parts.append('\n')
    return ''.join(parts), spans


def _blocks_between(spans, a: int, b: int) -> list[int]:
    return [sid for s, e, sid in spans if not (e < a or s > b)]


def _leading_title(before: str) -> str:
    t = before.strip()
    if not t:
        return ''
    tail = re.split(r'[。！？；]', t)[-1].strip()
    if 0 < len(tail) <= 14 and '道' not in tail:
        return tail
    return ''


# ---------------------------------------------------------------- 抽取

def _segments(sents: list[dict], text: str, pos_of: list[int]) -> list[tuple[int, int]]:
    """滑动窗口：返回满足 is_verse 的最长区间列表。"""
    n = len(sents)
    segs, i = [], 0
    while i < n:
        best = None
        j = i
        bad = 0
        while j < n and j - i < 160:
            sc = verse_score(sents[i:j + 1])
            ctx = text[max(0, pos_of[i] - 240):pos_of[i]]
            ok = (4 <= sc['main_len'] <= 7 and sc['uniform'] >= 0.7 and sc['xu'] <= 0.16
                  and is_verse(sc, ctx))
            if ok:
                best = (i, j)
            if not (4 <= sents[j]['len'] <= 7) or sents[j]['xu'] > 0.20:
                bad += 1
                if bad > 5:
                    break
            else:
                bad = 0
            j += 1
        if best:
            segs.append(best)
            i = best[1] + 1
        else:
            i += 1
    return segs


# ---------------------------------------------------------------- 种子首句路

# (首句片段, 篇名, 体裁, 句数, 作者, 回目提示)  —— 句数 None 表示延至韵文结束
# 依据脂评汇校本前八十回（程高本后四十回一概不取）
SEED_OPENINGS: list[tuple[str, str, str, int | None, str, int | None]] = [
    ('满纸荒唐言', '题石头记一绝', '五绝', 4, '曹雪芹', 1),
    ('未卜三生愿', '对月口占五言一律', '五律', 8, '贾雨村', 1),
    ('时逢三五便团圆', '对月寓怀', '七绝', 4, '贾雨村', 1),
    ('惯养娇生笑你痴', '嘲甄士隐', '七绝', 4, '癞头和尚', 1),
    ('世人都晓神仙好', '好了歌', '歌行', None, '跛足道人', 1),
    ('陋室空堂', '好了歌注', '歌行', None, '甄士隐', 1),
    ('无故寻愁觅恨', '西江月·批宝玉二首（其一）', '词', 8, '（批宝玉）', 3),
    ('富贵不知乐业', '西江月·批宝玉二首（其二）', '词', 8, '（批宝玉）', 3),
    ('贾不假', '护官符', '谣谚', None, '门子', 4),
    ('春困葳蕤拥绣衾', '题曰（第四回末）', '七绝', 4, '（题诗）', 4),
    ('春梦随云散', '警幻仙姑歌', '五绝', 4, '警幻仙姑', 5),
    ('霁月难逢', '又副册判词·晴雯', '判词', 4, '晴雯', 5),
    ('枉自温柔和顺', '又副册判词·袭人', '判词', 4, '花袭人', 5),
    ('根并荷花一茎香', '副册判词·香菱', '判词', 4, '香菱', 5),
    ('可叹停机德', '正册判词·黛玉宝钗', '判词', 4, '林黛玉/薛宝钗', 5),
    ('二十年来辨是非', '正册判词·元春', '判词', 4, '贾元春', 5),
    ('才自精明志自高', '正册判词·探春', '判词', 4, '贾探春', 5),
    ('富贵又何为', '正册判词·湘云', '判词', 4, '史湘云', 5),
    ('欲洁何曾洁', '正册判词·妙玉', '判词', 4, '妙玉', 5),
    ('子系中山狼', '正册判词·迎春', '判词', 4, '贾迎春', 5),
    ('勘破三春景不长', '正册判词·惜春', '判词', 4, '贾惜春', 5),
    ('凡鸟偏从末世来', '正册判词·凤姐', '判词', 4, '王熙凤', 5),
    ('势败休云贵', '正册判词·巧姐', '判词', 4, '贾巧姐', 5),
    ('桃李春风结子完', '正册判词·李纨', '判词', 4, '李纨', 5),
    ('情天情海幻情身', '正册判词·可卿', '判词', 4, '秦可卿', 5),
    ('开辟鸿蒙', '红楼梦十二支曲·引子', '曲', None, '（警幻新制）', 5),
    ('都道是金玉良', '红楼梦十二支曲·终身误', '曲', None, '（警幻新制）', 5),
    ('一个是阆苑仙葩', '红楼梦十二支曲·枉凝眉', '曲', None, '（警幻新制）', 5),
    ('喜荣华正好', '红楼梦十二支曲·恨无常', '曲', None, '（警幻新制）', 5),
    ('一帆风雨路三千', '红楼梦十二支曲·分骨肉', '曲', None, '（警幻新制）', 5),
    ('襁褓中', '红楼梦十二支曲·乐中悲', '曲', None, '（警幻新制）', 5),
    ('气质美如兰', '红楼梦十二支曲·世难容', '曲', None, '（警幻新制）', 5),
    ('中山狼', '红楼梦十二支曲·喜冤家', '曲', None, '（警幻新制）', 5),
    ('将那三春看破', '红楼梦十二支曲·虚花悟', '曲', None, '（警幻新制）', 5),
    ('机关算尽太聪明', '红楼梦十二支曲·聪明累', '曲', None, '（警幻新制）', 5),
    ('留馀庆', '红楼梦十二支曲·留余庆', '曲', None, '（警幻新制）', 5),
    ('镜里恩情', '红楼梦十二支曲·晚韶华', '曲', None, '（警幻新制）', 5),
    ('画梁春尽落香尘', '红楼梦十二支曲·好事终', '曲', None, '（警幻新制）', 5),
    ('为官的', '红楼梦十二支曲·收尾·飞鸟各投林', '曲', None, '（警幻新制）', 5),
    ('嫩寒锁梦因春冷', '秦氏房中对联', '对联', 2, '（秦可卿房）', 5),
    ('秀玉初成实', '大观园题咏·有凤来仪', '五律', 8, '贾宝玉', 18),
    ('蘅芜满净苑', '大观园题咏·蘅芷清芬', '五律', 8, '贾宝玉', 18),
    ('深庭长日静', '大观园题咏·怡红快绿', '五律', 8, '贾宝玉', 18),
    ('名园筑何处', '大观园题咏·世外仙源', '五律', 8, '林黛玉', 18),
    ('杏帘招客饮', '大观园题咏·杏帘在望', '五律', 8, '林黛玉（代宝玉）', 18),
    ('芳园筑向帝城西', '大观园题咏·凝晖钟瑞', '七律', 8, '薛宝钗', 18),
    ('秀水明山抱复回', '大观园题咏·旷性怡情', '七绝', 4, '李纨', 18),
    ('园成景备特精奇', '大观园题咏·旷性怡情', '七绝', 4, '贾迎春', 18),
    ('名园筑出势巍巍', '大观园题咏·万象争辉', '七绝', 4, '贾探春', 18),
    ('山水横拖千里外', '大观园题咏·文章造化', '七绝', 4, '贾惜春', 18),
    ('衔山抱水建来精', '大观园题咏·题大观园', '七绝', 4, '贾元春', 18),
    ('能使妖魔胆尽摧', '灯谜·爆竹', '七绝', 4, '贾元春', 22),
    ('天运人功理不穷', '灯谜·算盘', '七绝', 4, '贾迎春', 22),
    ('阶下儿童仰面时', '灯谜·风筝', '七绝', 4, '贾探春', 22),
    ('前身色相总无成', '灯谜·佛前海灯', '七绝', 4, '贾惜春', 22),
    ('朝罢谁携两袖烟', '灯谜·更香', '七律', 8, '薛宝钗', 22),
    ('身自端方', '灯谜·砚台', '四言谜', 4, '贾政', 22),
    ('霞绡云幄任铺陈', '四时即事·春夜即事', '七律', 8, '贾宝玉', 23),
    ('倦绣佳人幽梦长', '四时即事·夏夜即事', '七律', 8, '贾宝玉', 23),
    ('绛芸轩里绝喧哗', '四时即事·秋夜即事', '七律', 8, '贾宝玉', 23),
    ('梅魂竹梦已三更', '四时即事·冬夜即事', '七律', 8, '贾宝玉', 23),
    ('花谢花飞飞满天', '葬花吟', '歌行', None, '林黛玉', 27),
    ('滴不尽相思血泪抛红豆', '红豆曲', '曲', None, '贾宝玉', 28),
    ('眼空蓄泪泪空垂', '题帕三绝（其一）', '七绝', 4, '林黛玉', 34),
    ('抛珠滚玉只偷潸', '题帕三绝（其二）', '七绝', 4, '林黛玉', 34),
    ('彩线难收面上珠', '题帕三绝（其三）', '七绝', 4, '林黛玉', 34),
    ('斜阳寒草带重门', '咏白海棠（探春）', '七律', 8, '贾探春', 37),
    ('珍重芳姿昼掩门', '咏白海棠（宝钗）', '七律', 8, '薛宝钗', 37),
    ('秋容浅淡映重门', '咏白海棠（宝玉）', '七律', 8, '贾宝玉', 37),
    ('半卷湘帘半掩门', '咏白海棠（黛玉）', '七律', 8, '林黛玉', 37),
    ('神仙昨日降都门', '咏白海棠（湘云其一）', '七律', 8, '史湘云', 37),
    ('蘅芷阶通萝薜门', '咏白海棠（湘云其二）', '七律', 8, '史湘云', 37),
    ('秋花惨淡秋草黄', '秋窗风雨夕', '歌行', None, '林黛玉', 45),
    ('月挂中天夜色寒', '咏月（香菱其一）', '七律', 8, '香菱', 48),
    ('非银非水映窗寒', '咏月（香菱其二）', '七律', 8, '香菱', 48),
    ('精华欲掩料应难', '咏月（香菱其三）', '七律', 8, '香菱', 48),
    ('桃未芳菲杏未红', '咏红梅花（红字·岫烟）', '七律', 8, '邢岫烟', 50),
    ('白梅懒赋赋红梅', '咏红梅花（梅字·李纹）', '七律', 8, '李纹', 50),
    ('疏是枝条艳是花', '咏红梅花（花字·宝琴）', '七律', 8, '薛宝琴', 50),
    ('赤壁沉埋水不流', '怀古绝句·赤壁怀古', '七绝', 4, '薛宝琴', 50),
    ('铜铸金镛振纪纲', '怀古绝句·交趾怀古', '七绝', 4, '薛宝琴', 50),
    ('名利何曾伴汝身', '怀古绝句·钟山怀古', '七绝', 4, '薛宝琴', 50),
    ('壮士须防恶犬欺', '怀古绝句·淮阴怀古', '七绝', 4, '薛宝琴', 50),
    ('蝉噪鸦栖转眼过', '怀古绝句·广陵怀古', '七绝', 4, '薛宝琴', 51),
    ('衰草闲花映浅池', '怀古绝句·桃叶渡怀古', '七绝', 4, '薛宝琴', 51),
    ('黑水茫茫咽不流', '怀古绝句·青冢怀古', '七绝', 4, '薛宝琴', 51),
    ('寂寞脂痕渍汗光', '怀古绝句·马嵬怀古', '七绝', 4, '薛宝琴', 51),
    ('小红骨贱最身轻', '怀古绝句·蒲东寺怀古', '七绝', 4, '薛宝琴', 51),
    ('不在梅边在柳边', '怀古绝句·梅花观怀古', '七绝', 4, '薛宝琴', 51),
    ('昨夜朱楼梦', '真真国女儿诗', '五律', 8, '真真国女儿', 52),
    ('任是无情也动人', '花名签·牡丹（宝钗）', '花签', 1, '薛宝钗', 63),
    ('日边红杏倚云栽', '花名签·杏花（探春）', '花签', 1, '贾探春', 63),
    ('竹篱茅舍自甘心', '花名签·老梅（李纨）', '花签', 1, '李纨', 63),
    ('只恐夜深花睡去', '花名签·海棠（湘云）', '花签', 1, '史湘云', 63),
    ('开到荼縻花事了', '花名签·荼縻（麝月）', '花签', 1, '麝月', 63),
    ('连理枝头花正开', '花名签·并蒂花（香菱）', '花签', 1, '香菱', 63),
    ('莫怨东风当自嗟', '花名签·芙蓉（黛玉）', '花签', 1, '林黛玉', 63),
    ('桃红又是一年春', '花名签·桃花（袭人）', '花签', 1, '花袭人', 63),
    ('一代倾城逐浪花', '五美吟·西施', '七绝', 4, '林黛玉', 64),
    ('肠断乌骓夜啸风', '五美吟·虞姬', '七绝', 4, '林黛玉', 64),
    ('绝艳惊人出汉宫', '五美吟·明妃', '七绝', 4, '林黛玉', 64),
    ('瓦砾明珠一例', '五美吟·绿珠', '七绝', 4, '林黛玉', 64),
    ('长揖雄谈态自殊', '五美吟·红拂', '七绝', 4, '林黛玉', 64),
    ('粉堕百花州', '柳絮词·唐多令', '词', None, '林黛玉', 70),
    ('白玉堂前春解舞', '柳絮词·临江仙', '词', 8, '薛宝钗', 70),
    ('岂是绣绒残吐', '柳絮词·如梦令', '词', None, '史湘云', 70),
    ('空挂纤纤缕', '柳絮词·南柯子', '词', None, '贾探春/贾宝玉', 70),
    ('汉苑零星有限', '柳絮词·西江月', '词', None, '薛宝琴', 70),
    ('三五中秋夕', '凹晶馆中秋联句', '联句', None, '林黛玉/史湘云', 76),
    ('恒王好武兼好色', '姽婳词', '歌行', None, '贾宝玉', 78),
    ('姽婳将军林四娘', '姽婳词（贾兰）', '七绝', 4, '贾兰', 78),
    ('红粉不知愁', '姽婳词（贾环）', '五律', 8, '贾环', 78),
    ('维太平不易之元', '芙蓉女儿诔', '诔', None, '贾宝玉', 78),
    ('池塘一夜秋风冷', '紫菱洲歌', '七律', 8, '贾宝玉', 79),
]


def extract_by_seed(corpus: dict) -> tuple[list[dict], list[str]]:
    """按已知篇目首句定位并按体裁定长截取；返回 (结果, 未命中的首句)。"""
    out: list[dict] = []
    miss: list[str] = []
    for opening, title, genre, nlines, author, chap in SEED_OPENINGS:
        hit = False
        for ch in corpus['chapters']:
            if chap and ch['no'] != chap:
                continue
            text, spans = chapter_stream(ch)
            p = text.find(opening)
            if p < 0:                      # 异文（繁简、形近）时退化为前缀模糊定位
                for n in (4, 3, 2):
                    if len(opening) >= n + 1:
                        p = text.find(opening[:n])
                        if p >= 0:
                            break
            if p < 0:
                continue
            sents = sentences(text)
            pos, pos_of = 0, []
            for s in sents:
                i = text.find(s['text'], pos)
                pos_of.append(i if i >= 0 else pos)
                pos = (i if i >= 0 else pos) + len(s['text'])
            i0 = None
            for i, sp in enumerate(pos_of):
                if sp <= p <= sp + len(sents[i]['text']):
                    i0 = i
                    break
            if i0 is None:
                continue
            if nlines:
                idxs = list(range(i0, min(i0 + nlines, len(sents))))
            else:
                idxs, m = [i0], 0          # 首句必收（曲用词句虚词偏多）
                for i in range(i0 + 1, len(sents)):
                    if _loose_verse_sent(sents[i]):
                        idxs.append(i)
                        m = 0
                    else:
                        m += 1
                        if m >= 2 or len(idxs) >= 70:
                            break
            seg = [sents[i] for i in idxs]
            if not seg:
                continue
            start, end = pos_of[idxs[0]], pos_of[idxs[-1]] + len(seg[-1]['text'])
            ids = _blocks_between(spans, start, end)
            if not ids:
                continue
            out.append(dict(
                id=f'S{len(out) + 1}',
                chapter=ch['no'], chapter_title=ch['title'],
                title=title, genre=genre, author=author,
                text=''.join(s['text'] for s in seg),
                lines=[s['body'] for s in seg],
                speakers=[s['speaker'] for s in seg if s['speaker']],
                block_ids=ids, start=start, end=end,
                metrics=verse_score(seg),
                prev_context=text[max(0, p - 240):p],
                next_context=text[end:end + 60],
                route='seed',
            ))
            hit = True
            break
        if not hit:
            miss.append(opening)
    return out, miss


# ---------------------------------------------------------------- 标题路

# 已知篇目（诗题/词题/曲牌/诔/谜/令），用于定位不齐言的韵文
TITLE_SEEDS = [
    '红楼梦引子', '终身误', '枉凝眉', '恨无常', '分骨肉', '乐中悲', '世难容',
    '喜冤家', '虚花悟', '聪明累', '留余庆', '晚韶华', '好事终', '飞鸟各投林',
    '葬花吟', '葬花辞', '秋窗风雨夕', '代别离', '桃花行', '五美吟', '姽婳词',
    '芙蓉女儿诔', '芙蓉诔', '题帕', '菊花诗', '咏白海棠', '咏红梅花', '柳絮词',
    '怀古绝句', '赤壁怀古', '交趾怀古', '钟山怀古', '淮阴怀古', '广陵怀古',
    '桃叶渡怀古', '青冢怀古', '马嵬怀古', '蒲东寺怀古', '梅花观怀古',
    '春夜即事', '夏夜即事', '秋夜即事', '冬夜即事', '食螃蟹', '螃蟹咏',
    '参禅偈', '寄生草', '红豆曲', '好了歌', '好了歌注', '西江月',
    '世外仙源', '杏帘在望', '凝晖钟瑞', '有凤来仪', '蘅芷清芬', '怡红快绿',
    '旷性怡情', '万象争辉', '文章造化', '文采风流', '凝晖钟瑞',
]
TITLE_SEEDS += JU_TOPICS + QU_PAI + CI_PAI

# 单句可否入韵文（词曲句长不齐，只看是否像叙事）
def _loose_verse_sent(s: dict) -> bool:
    return (2 <= s['len'] <= 20 and s['xu'] <= 0.30
            and not NARR_TAIL.search(s['body']))


def extract_by_title(corpus: dict) -> list[dict]:
    """以篇目题名为锚点截取韵文，覆盖词、曲、诔、赋、谜、令。"""
    out: list[dict] = []
    pid = 0
    for ch in corpus['chapters']:
        if ch['no'] <= 0:
            continue
        text, spans = chapter_stream(ch)
        sents = sentences(text)
        pos, pos_of = 0, []
        for s in sents:
            i = text.find(s['text'], pos)
            pos_of.append(i if i >= 0 else pos)
            pos = (i if i >= 0 else pos) + len(s['text'])
        for seed in TITLE_SEEDS:
            for m in re.finditer(re.escape(seed), text):
                # 起点：题名之后
                start_pos = m.end()
                i0 = next((i for i, p in enumerate(pos_of)
                           if p >= start_pos and p < start_pos + 40), None)
                if i0 is None:
                    continue
                idxs: list[int] = []
                miss = 0
                for i in range(i0, len(sents)):
                    if _loose_verse_sent(sents[i]):
                        idxs.append(i)
                        miss = 0
                    else:
                        miss += 1
                        if miss >= 2 or len(idxs) >= 60:
                            break
                keep = trim_edges([sents[i] for i in idxs])
                keepset = {id(s) for s in keep}
                idxs = [i for i in idxs if id(sents[i]) in keepset]
                if len(idxs) < 3 or sum(sents[i]['len'] for i in idxs) < 20:
                    continue
                seg = [sents[i] for i in idxs]
                a, b = idxs[0], idxs[-1]
                start, end = pos_of[a], pos_of[b] + len(seg[-1]['text'])
                ids = _blocks_between(spans, start, end)
                if not ids:
                    continue
                pid += 1
                out.append(dict(
                    id=f'T{pid}',
                    chapter=ch['no'],
                    chapter_title=ch['title'],
                    title=seed,
                    text=''.join(s['text'] for s in seg),
                    lines=[s['body'] for s in seg],
                    speakers=[s['speaker'] for s in seg if s['speaker']],
                    block_ids=ids,
                    start=start, end=end,
                    metrics=verse_score(seg),
                    prev_context=text[max(0, m.start() - 240):m.start()],
                    next_context=text[end:end + 60],
                    route='title',
                ))
    return out


# ---------------------------------------------------------------- 抽取

def _overlap(a: dict, b: dict) -> bool:
    return a['chapter'] == b['chapter'] and not (a['end'] < b['start']
                                                 or b['end'] < a['start'])


def extract(corpus: dict | None = None) -> tuple[list[dict], list[str]]:
    if corpus is None:
        corpus = json.loads(paths.data('corpus.json').read_text(encoding='utf-8'))
    poems, miss = extract_by_seed(corpus)
    pid = 0
    for ch in corpus['chapters']:
        if ch['no'] <= 0:
            continue
        text, spans = chapter_stream(ch)
        sents = sentences(text)
        pos, pos_of = 0, []
        for s in sents:
            i = text.find(s['text'], pos)
            pos_of.append(i if i >= 0 else pos)
            pos = (i if i >= 0 else pos) + len(s['text'])
        for a, b in _segments(sents, text, pos_of):
            cand = list(range(a, b + 1))
            keep = {id(s) for s in trim_edges([sents[i] for i in cand])}
            cand = [i for i in cand if id(sents[i]) in keep]
            if len(cand) < 4:
                continue
            a, b = cand[0], cand[-1]
            body_sents = [sents[i] for i in cand]
            start, end = pos_of[a], pos_of[b] + len(body_sents[-1]['text'])
            ids = _blocks_between(spans, start, end)
            if not ids:
                continue
            blk_start = next((s for s, e, sid in spans if sid == ids[0]), 0)
            pid += 1
            cand_poem = dict(
                id=pid,
                chapter=ch['no'],
                chapter_title=ch['title'],
                title=_leading_title(text[blk_start:start]),
                text=''.join(s['text'] for s in body_sents),
                lines=[s['body'] for s in body_sents],
                speakers=[s['speaker'] for s in body_sents if s['speaker']],
                block_ids=ids,
                start=start, end=end,
                metrics=verse_score(body_sents),
                prev_context=text[max(0, start - 240):start],
                next_context=text[end:end + 60],
                route='form',
            )
            if any(_overlap(cand_poem, p) for p in poems):
                continue
            poems.append(cand_poem)
    # 标题路：与已有区间重叠者丢弃
    for t in extract_by_title(corpus):
        if any(_overlap(t, p) for p in poems):
            continue
        poems.append(t)
    poems.sort(key=lambda p: (p['chapter'], p['start']))
    return poems, miss


# ---------------------------------------------------------------- 体裁

def guess_genre(p: dict) -> str:
    if p.get('genre'):
        return p['genre']
    title, ctx = p['title'] or '', p['prev_context']
    body = p['text']
    lines = p['lines']
    lens = [len(x) for x in lines]
    n = len(lines)
    main_len = Counter(lens).most_common(1)[0][0]

    if any(q in title for q in QU_PAI) or re.match(r'^第.{1,4}支', title):
        return '曲'
    if any(c in title for c in CI_PAI):
        return '词'
    if '打一' in body or '打一物' in body:
        return '灯谜'
    if '牙牌令' in ctx or '酒令' in ctx or '令官' in ctx:
        return '酒令'
    if '诔' in title or '诔' in ctx:
        return '诔'
    if '偈' in title or '偈' in ctx:
        return '偈'
    if n == 2:
        return '对联'
    if any(k in ctx for k in ['判云', '其判曰', '断语云', '歌词云', '写道是', '书云']) \
            or '判' in title:
        return '判词'
    if '联句' in ctx or '联句' in title or n >= 16:
        return '联句'
    if len(set(lens)) > 2:
        return '词/曲'
    if main_len == 5:
        return '五律' if n >= 8 else '五绝'
    if main_len == 7:
        return '七律' if n >= 8 else '七绝'
    if main_len == 4:
        return '四言'
    if main_len == 6:
        return '六言'
    return '古体'


def _guess_author(p: dict) -> str:
    """从别号、说话人、上文最近出现的人物名推断作者。"""
    from . import ontology_seed as seed

    blob = ' '.join([p['title'] or '', p['prev_context'][-120:]])
    for hao, who in HAO.items():
        if hao in blob:
            return who
    if p.get('speakers'):
        return p['speakers'][0]
    names = [x['name'] for x in seed.persons()]
    best, pos = '', -1
    for n in names:
        i = blob.rfind(n)
        if i > pos:
            best, pos = n, i
    return best or '（未详）'


if __name__ == '__main__':
    ps, miss = extract()
    for p in ps:
        p['genre_guess'] = guess_genre(p)
        p['author'] = p.get('author') or _guess_author(p)
    print('候选诗词：', len(ps))
    print(json.dumps(dict(Counter(p['genre_guess'] for p in ps).most_common()),
                     ensure_ascii=False))
    print('分布：', sorted(Counter(p['chapter'] for p in ps).items()))
    print('未命中种子：', miss)
    paths.data('poems_raw.json').write_text(
        json.dumps(ps, ensure_ascii=False, indent=1), encoding='utf-8')
