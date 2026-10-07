"""全书骨架（后三十回）的推演：先辩论「多少回、什么结局」，再排出回目清单。

流程
----
1. 立案：诸家辩论全书结构与末回（主持人裁决）→ resolution
2. 制目：曹雪芹 Agent 依裁决排出 30 回「回目 | 要点 | 用典/伏线」，
   周汝昌复核、知识图谱工程师查约束违反
3. 落盘 data/outline.json，站点与续写编排共用

硬约束来自脂批明示（db.lost_clues / persons.fate / 判词与十二支曲），
续写不得违反；程高本后四十回情节一律排除。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime

from . import agents, db, paths

# 全书究竟多少回：脂批明言「后三十回」（庚辰、靖藏批语），八十回后尚有三十回，
# 故全书当为一百一十回。另有 108 回（情榜 108 钗）诸说，由诸家辩论裁定。
DEFAULT_TOTAL = 110

# 时序骨架：后三十回诸事的先后（据脂批与判词曲子推得，续写不得颠倒）
TIMELINE = [
    '元春薨逝（虎兕相逢大梦归）',
    '黛玉泪尽夭亡（泪尽而逝，先于抄没）',
    '金玉良缘成婚（举案齐眉，到底意难平）',
    '甄家事发、贾府抄没（树倒猢狲散）',
    '凤姐被休、哭向金陵而亡（一从二令三人木）',
    '迎春被孙绍祖折磨而死（一载赴黄粱）',
    '探春远嫁海疆（清明涕送江边望）',
    '惜春出家（缁衣顿改昔年妆）',
    '妙玉遭劫（风尘肮脏违心愿）',
    '巧姐被卖、赖刘姥姥得救（巧得遇恩人）',
    '宝玉穷途（寒冬噎酸齑，雪夜围破毡）',
    '悬崖撒手（出家）',
    '情榜（末回）',
    '白茫茫大地真干净（收束全书）',
]

# 脂批与靖藏本批语中可确知的后三十回情节/回目，续写必须落地
KNOWN_LOST = [
    '狱神庙慰宝玉（茜雪、红玉）',
    '花袭人有始有终（供奉宝玉宝钗）',
    '卫若兰射圃（金麒麟）',
    '甄宝玉送玉',
    '薛宝钗借词含讽谏 王熙凤知命强英雄（此为确知回目）',
    '悬崖撒手',
    '情榜',
]

STRUCTURE_TOPIC = '全书当止于第几回、末回是何面目'
STRUCTURE_QUESTION = (
    '脂批屡言「后三十回」（庚辰、靖藏批语），又有「情榜」之说，'
    '壬午除夕「书未成，芹为泪尽而逝」。请问：'
    '一、八十回后尚有几回？全书共若干回？'
    '  注意：若主张一百二十回，须先解释脂批「后三十回」当如何读法；'
    '  若主张一百一十回，须说明程高本后四十回的回数从何而来。'
    '二、末回（情榜）当如何写法？'
    '三、八十回后第一桩大事是什么？'
    '四、黛玉之死、贾府抄没、宝玉出家三事，孰先孰后？请给出明确时序。'
    '五、哪些程高本情节必须排除？'
    '六、以下可确知的后三十回情节当分别落在哪几回：'
    '狱神庙慰宝玉、花袭人有始有终、卫若兰射圃、甄宝玉送玉、'
    '薛宝钗借词含讽谏 王熙凤知命强英雄、悬崖撒手、情榜。')

LINE_RE = re.compile(r'^\s*第?\s*(\d{2,3})\s*回?\s*[|｜:：]\s*(.+?)\s*[|｜]\s*(.*)$')

# 前八十回已经亡故者：后三十回不得再安排其死亡或出场理事
DEAD80 = ['秦可卿', '秦钟', '贾瑞', '林如海', '金钏', '金钏儿', '贾敬',
          '尤二姐', '尤三姐', '晴雯', '贾珠', '冯渊', '张金哥', '守备之子',
          '贾敷', '贾敏']
# 只允许出现一次的大事（重复即疑为回目错排）
ONCE_EVENTS = ['薨逝', '抄', '知命强英雄', '悬崖撒手', '情榜', '对景悼颦',
               '狱神庙', '射圃', '送玉', '有始有终', '讽谏', '被休', '遭劫',
               '远嫁', '出家', '被卖', '噎酸齑']


def _sanity(rows: list[dict]) -> list[str]:
    """事实校对：已故人物再现、大事重复。"""
    issues = []
    for r in rows:
        blob = r['title'] + r['brief']
        for name in DEAD80:
            if name in blob:
                issues.append(f"第{r['chapter']}回：{name}已于前八十回亡故，"
                              f'不可再死、不可再理事，须换人或改事')
    for kw in ONCE_EVENTS:
        hit = [r['chapter'] for r in rows if kw in r['title'] + r['brief']]
        if len(hit) > 1:
            issues.append(f'「{kw}」出现在第 {hit} 回，同一大事只可一回')
    return issues


def _fix_rows(rows: list[dict], issues: list[str],
              constraints: list[str]) -> list[dict]:
    """把问题行交回曹雪芹重写。"""
    if not issues or not rows:
        return rows
    listing = '\n'.join(f"{r['chapter']}|{r['title']}|{r['brief']}" for r in rows)
    cons = '\n'.join('- ' + c for c in constraints[:60])
    raw = agents.AGENTS['caoxueqin'].speak(
        f'【全书回目清单】\n{listing}\n\n【纠错意见】\n'
        + '\n'.join('- ' + i for i in issues)
        + f'\n\n【硬约束】\n{cons}\n'
        '请只重写被点名的那几回（其余回目一字不动），'
        '仍用「回次|回目|要点」三栏输出。', tag='outline-fix2')
    fixed = _parse(raw, min(r['chapter'] for r in rows),
                   max(r['chapter'] for r in rows))
    if not fixed:
        return rows
    m = {r['chapter']: r for r in fixed}
    return [m.get(r['chapter'], r) for r in rows]


def hard_constraints() -> list[str]:
    """从脂批明示线索 + 判词/曲/人物探佚结局，生成硬约束清单。"""
    out = []
    for c in db.q('SELECT clue, source, meaning FROM lost_clues ORDER BY id'):
        out.append(f'{c["clue"]}（{c["source"]}）：{c["meaning"]}')
    for p in db.q("SELECT name, fate FROM persons WHERE fate <> '' AND fate <> '—'"):
        out.append(f'{p["name"]}：{p["fate"]}')
    out += [
        '禁：宝玉中举、兰桂齐芳、黛玉焚稿、凤姐魂游、宝黛还魂等程高本情节。',
        '禁：团圆、复生、科举荣身、因果报应的俗套。',
        f'全书共 {DEFAULT_TOTAL} 回（八十回 + 后三十回），不得多亦不得少。',
        '【时序】' + ' → '.join(TIMELINE),
        '【可确知的后三十回情节，必须落地】' + '；'.join(KNOWN_LOST),
    ]
    return out


def debate_structure(dry_run: bool = False) -> dict:
    """第一步：诸家辩论全书结构。"""
    return agents.deliberate(STRUCTURE_TOPIC, STRUCTURE_QUESTION,
                             rounds=1, dry_run=dry_run)


def draft_chapter_list(total: int = DEFAULT_TOTAL, resolution: str = '',
                       start: int = 81, dry_run: bool = False) -> list[dict]:
    """第二步：排出回目清单。返回 [{chapter, title, brief, clues}]。"""
    cons = '\n'.join('- ' + c for c in hard_constraints())
    nos = '、'.join(str(i) for i in range(start, total + 1))
    prompt = (
        f'【任务】为《石头记》{start} 回至第 {total} 回（共 {total - start + 1} 回）'
        f'拟定回目清单。回次为：{nos}。\n'
        f'【推演决议】\n{resolution or "（无）"}\n'
        f'【必须遵守的硬约束】（不得违反任何一条）\n{cons}\n'
        '【输出格式】每行一条，严格用竖线分隔三栏，不要任何多余文字：\n'
        '回次|回目|要点与所用伏线（40 字内）\n'
        '例：81|甄士隐重结红楼梦 贾雨村再遇旧知音|接香菱一线，雨村起复伏线\n'
        '【要求】\n'
        '1. 回目为对仗的八字或七字，须合全书回目体例；\n'
        '2. 情节须由前八十回的伏线自然生出，不得凭空；\n'
        '3. 时序须守硬约束中的【时序】一条，不得颠倒；\n'
        '4. 末两回为情榜与全书收束，情榜须列诸钗考语；\n'
        f'5. 须全部落地可确知的佚文情节（狱神庙慰宝玉、花袭人有始有终、'
        f'卫若兰射圃、甄宝玉送玉、薛宝钗借词含讽谏 王熙凤知命强英雄）。'
    )
    raw = '' if dry_run else agents.AGENTS['caoxueqin'].speak(
        prompt, temperature=0.85, tag='outline')
    rows = _parse(raw, start, total)

    # 模型常会漏回次：针对缺失的回次再补一次
    for _ in range(2):
        miss = [i for i in range(start, total + 1)
                if i not in {r['chapter'] for r in rows}]
        if not miss:
            break
        if dry_run:
            break
        more = _parse(agents.AGENTS['caoxueqin'].speak(
            prompt + f'\n\n【只补以下回次，勿重复已拟者】{miss}',
            temperature=0.85, tag='outline-fix'), start, total)
        have = {r['chapter'] for r in rows}
        rows += [r for r in more if r['chapter'] not in have]
        rows.sort(key=lambda r: r['chapter'])

    if not dry_run:
        rows = _check(rows, dry_run)
    return rows


def _parse(raw: str, start: int, total: int) -> list[dict]:
    rows = []
    for line in raw.splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        no = int(m.group(1))
        if not (start <= no <= total):
            continue
        title = m.group(2).strip()
        brief = m.group(3).strip()
        rows.append(dict(chapter=no, title=title, brief=brief))
    return sorted(rows, key=lambda r: r['chapter'])


def _check(rows: list[dict], dry_run: bool) -> list[dict]:
    """知识图谱工程师：查约束违反，把报告附在 brief 之后。"""
    if not rows or dry_run:
        return rows
    cons = '\n'.join('- ' + c for c in hard_constraints()[:40])
    listing = '\n'.join(f"{r['chapter']}|{r['title']}|{r['brief']}" for r in rows)
    rep = agents.AGENTS['kgengineer'].speak(
        f'【回目清单】\n{listing}\n\n【约束】\n{cons}\n'
        '请检查：时序（谁先死）、已死人物是否再现、伏线是否遗漏、'
        '程高本情节是否混入。只列违反项，每条一行：回次|问题|改法。'
        '若无违反，只写「无」。', tag='outline-check')
    if rep and rep.strip().startswith('无'):
        return rows
    for line in rep.splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        no = int(m.group(1))
        for r in rows:
            if r['chapter'] == no:
                r['brief'] = f"{r['brief']}（修订：{m.group(3)[:40]}）"
    return rows


def build_outline(total: int = DEFAULT_TOTAL, start: int = 81,
                  dry_run: bool = False, debate: bool = True,
                  reuse: bool = True) -> dict:
    resolution = ''
    if reuse and not debate:
        old = load_outline()
        if old:
            resolution = old.get('resolution', '')
    if not resolution and debate:
        resolution = debate_structure(dry_run=dry_run).get('resolution', '')
    cons = hard_constraints()
    rows = draft_chapter_list(total, resolution, start, dry_run=dry_run)
    issues = _sanity(rows)
    if issues and not dry_run:
        rows = _fix_rows(rows, issues, cons)
        issues = _sanity(rows)
    doc = dict(total=total, start=start, created_at=datetime.now().isoformat(
        timespec='seconds'), resolution=resolution, sanity=issues,
        constraints=cons, chapters=rows)
    paths.data('outline.json').write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding='utf-8')
    return doc


def load_outline() -> dict | None:
    f = paths.data('outline.json')
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding='utf-8'))


if __name__ == '__main__':
    debate = '--debate' in sys.argv
    doc = build_outline(debate=debate)
    print('决议：\n', doc['resolution'][:600])
    print('\n回目：')
    for r in doc['chapters']:
        print(f"{r['chapter']:>3} | {r['title']} | {r['brief']}")
