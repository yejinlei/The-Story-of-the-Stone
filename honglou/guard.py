"""本体论校验器：续写稿必须可接地于本体，不得违反脂批所定的时序与人物结局。

五道闸门
--------
G1 程高本禁例：中举、兰桂齐芳、焚稿、魂游、还魂、沐皇恩、延世泽…
G2 时序：本回尚未发生的大事不得提前出现（依据 outline 时序索引）
G3 已故人物：前八十回已亡者与续写中已亡者，不得再出场理事/说话
G4 诗风：某人作诗须合其诗风画像，犯其禁忌者驳回
G5 接地：正文中的人名与地名须在本体库中可查，查不到即为幻觉候选

另：collect_dead() 从成稿中抽取本回新亡人物，写入滚动状态。
"""
from __future__ import annotations

import json
import re

from . import db, outline as outline_mod

# G1 程高本后四十回的情节标记，一见即驳
CHENG_GAO = ['中举', '中乡魁', '兰桂齐芳', '焚稿', '断痴情', '魂游', '还魂',
             '沐皇恩', '延世泽', '重沐天恩', '高中', '状元及第', '复职',
             '家道中兴', '重振家声', '宝玉哭灵', '黛玉归天']

# G3 前八十回已亡者
DEAD80 = ['秦可卿', '秦钟', '贾瑞', '林如海', '金钏', '贾敬', '尤二姐',
          '尤三姐', '晴雯', '贾珠', '冯渊', '张金哥', '贾敏', '贾敷']

DEATH_RE = re.compile(
    r'([\u4e00-\u9fff]{2,4})(?:已死|死了|身死|病故|咽了气|咽气|殡天|亡故|'
    r'自缢|自尽|投井|吞金|赴黄粱|归太虚|归离恨|没了|气绝|仙逝|寿终|'
    r'命丧|送了命|一命呜呼|撒手)')

# 说话人须紧跟句读、引号或行首，避免「口中喃喃道」「宝玉又叹道」之类误切
SPEAK_RE = re.compile(
    r'(?:^|[。！？；，、：\n「」『』“”"\'])([\u4e00-\u9fff]{2,3})'
    r'(?:笑|哭|叹|冷笑|忙|因|又|便|遂|也|低|悄|含|点头|摇头)?'
    r'(?:道|说|问|答)')

# 人名里不可能出现的虚词（出现即说明切错了）
NOT_NAME = set('又也便遂因并却就都还已曾正方才忽闻听得着了过在被把让使')

# 追述语境：提到已故者不算犯规
RETRO = ('想起', '忆起', '忆及', '昔日', '当年', '从前', '往日', '梦见', '梦',
         '曾', '记得', '说的', '提到的', '如同', '好似', '竟如', '恍如',
         '那年', '那时', '死后', '已故', '亡故', '生前')

# 批判语境：点名程高本情节是为了排除它，不算犯规
DENY = ('不', '未', '无', '非', '岂', '哪', '莫', '休', '除', '摒弃', '断无',
        '何曾', '程高', '后四十回', '伪', '妄', '删去', '不取')
GENERIC = {'众人', '大家', '婆子', '媳妇', '丫鬟', '丫头', '小厮', '妈妈', '奶奶',
           '老爷', '太太', '姐姐', '妹妹', '哥哥', '弟弟', '姑娘', '嬷嬷', '老嬷',
           '媳妇们', '婆子们', '众人道', '一面', '这里', '那里', '一时', '谁知',
           '只见', '因见', '听说', '且说', '却说', '话说', '原来', '当下', '次日',
           '贾母之', '王夫人', '邢夫人', '尤氏', '薛姨妈'}

_PERSONS: dict[str, str] | None = None
_NAMES: set[str] | None = None
_PLACES: set[str] | None = None
_STYLE: dict[str, dict] | None = None


def _load() -> None:
    global _PERSONS, _NAMES, _PLACES, _STYLE
    if _PERSONS is not None:
        return
    _PERSONS, _NAMES = {}, set()
    for p in db.q('SELECT name, aliases FROM persons'):
        _PERSONS[p['name']] = p['name']
        _NAMES.add(p['name'])
        if len(p['name']) >= 3:          # 简称（宝钗、黛玉、凤姐、巧姐…）
            _NAMES.add(p['name'][-2:])
        try:
            for a in json.loads(p['aliases'] or '[]'):
                if a and a != '—':
                    _NAMES.add(a)
                    _PERSONS[a] = p['name']
        except Exception:
            pass
    _PLACES = {p['name'] for p in db.q('SELECT name FROM places')}
    _STYLE = {s['person']: s for s in db.q('SELECT * FROM poet_style')}


# G2 大事 → 判词/关键词（时序闸门据此定位该事落在第几回）
EVENT_KW = {
    '元春薨逝': ['元妃薨', '元春薨', '凤楼空', '大梦归'],
    '黛玉泪尽': ['泪尽', '绛珠归', '归离恨', '黛玉死', '黛玉亡', '颦儿死'],
    '金玉成婚': ['成婚', '合卺', '结缡', '洞房'],
    '贾府抄没': ['抄没', '锦衣卫', '籍没', '查抄', '封门'],
    '凤姐身死': ['哭向金陵', '凤姐死', '凤姐亡', '回首惨淡'],
    '迎春身死': ['赴黄粱', '迎春死', '迎春亡'],
    '探春远嫁': ['远嫁', '海疆', '一帆', '千里东风'],
    '惜春出家': ['缁衣', '削发', '古佛旁'],
    '妙玉遭劫': ['遭劫', '陷淖', '淖泥'],
    '巧姐得救': ['搭救', '纺绩', '板儿'],
    '宝玉穷途': ['噎酸齑', '破毡', '寒冬噎'],
    '宝玉撒手': ['悬崖撒手', '撒手', '青埂峰'],
    '末回情榜': ['情榜', '警幻', '诸艳'],
}


def event_index() -> dict[str, int]:
    """大事 → 发生回次（由骨架清单反查，用于时序闸门）。"""
    o = outline_mod.load_outline() or {}
    idx = {}
    for r in o.get('chapters', []):
        blob = r['title'] + r['brief']
        for ev, kws in EVENT_KW.items():
            if ev in idx:
                continue
            if any(k in blob for k in kws):
                idx[ev] = r['chapter']
    return idx


def collect_dead(text: str, chapter: int, state: dict) -> list[str]:
    """从成稿抽取本回新亡人物，写入滚动状态。"""
    dead = set(state.get('dead', []))
    found = []
    for m in DEATH_RE.finditer(text):
        name = m.group(1)
        if name in _known() and name not in dead:
            dead.add(name)
            found.append(name)
    if found:
        state['dead'] = sorted(dead)
        state.setdefault('dead_at', {})
        for n in found:
            state['dead_at'][n] = chapter
    return found


def _known() -> set[str]:
    _load()
    return _NAMES or set()


def check(chapter: int, text: str, oitem: dict | None = None,
          state: dict | None = None, light: bool = False) -> list[str]:
    """本体论校验，返回问题清单（空即通过）。

    light=True 只跑硬闸门 G1/G2/G3（用于判定旧稿是否须重写），
    避免 G4 诗风与 G5 接地的误报引发大面积重写。
    """
    _load()
    st = state or {}
    issues = []

    # G1 程高本禁例（点名批判者豁免）
    for w in CHENG_GAO:
        for m in re.finditer(re.escape(w), text):
            before = text[max(0, m.start() - 8):m.start()]
            if any(d in before for d in DENY):
                continue
            issues.append(f'[G1] 出现程高本情节标记「{w}」，后四十回一概不取')
            break

    # G3 已故人物：只禁「出场说话理事」，追述不算
    dead = set(DEAD80) | set(st.get('dead', []))
    for name in dead:
        for m in re.finditer(re.escape(name), text):
            before = text[max(0, m.start() - 14):m.start()]
            if any(r in before for r in RETRO):
                continue
            if re.match(name + r'(道|笑|说|问|答|哭|叹|听|看|接|忙|便|起|进|出)',
                        text[m.start():]):
                issues.append(
                    f'[G3] {name} 已亡故，不得再出场说话理事（只可作追述）')
                break

    # G2 时序：本回之前的回次不得出现此后才发生的大事
    idx = event_index()
    for ev, ch in idx.items():
        if ch - chapter >= 3:                     # 允许提前二回作铺垫
            for kw in EVENT_KW[ev]:
                if kw in text:
                    issues.append(f'[G2] 「{ev}」在第 {ch} 回，本回第 {chapter} 回'
                                  f'不得提前写到「{kw}」')
                    break
    if light:
        return issues

    # G4 诗风禁忌
    for person, s in (_STYLE or {}).items():
        taboo = (s.get('taboo') or '').replace('、', '|').strip('|')
        if not taboo or person not in text:
            continue
        for t in taboo.split('|'):
            t = t.strip()
            if len(t) >= 2 and t in text:
                issues.append(f'[G4] {person} 犯其诗风禁忌「{t}」，'
                              f'诗风当为：{s.get("style", "")[:24]}')

    # G5 接地：说话人须可查
    unknown = set()
    for m in SPEAK_RE.finditer(text):
        w = m.group(1)
        if w in GENERIC or len(w) < 2 or w in _NAMES or w in _PLACES:
            continue
        if w.endswith('们') or any(c in NOT_NAME for c in w):
            continue
        unknown.add(w)
    # G5 只作接地告警（误报代价高），不参与驳回
    global WARN
    WARN = ['[G5] 接地提示·本体外称谓：' + '、'.join(sorted(unknown)[:6])] \
        if unknown else []
    return issues


WARN: list[str] = []


def report(chapter: int, text: str, oitem: dict | None = None,
           state: dict | None = None) -> dict:
    issues = check(chapter, text, oitem, state)
    return dict(chapter=chapter, pass_=not issues, issues=issues)
