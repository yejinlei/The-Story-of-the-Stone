"""多 Agent 推演系统。

角色分四组，互相质证（PK），全过程落盘到 DuckDB，供站点复盘：

  古典组（书中人 / 批者）
    脂砚斋、畸笏叟、曹雪芹
  红学组（现代诸家）
    周汝昌（探佚）、俞平伯（考据）、蔡元培（索隐）、张爱玲（文心）
  技术组（现代方法）
    数据科学家（DuckDB / 统计分析 / 社会网络）
    文体计量学家（风格向量 / 余弦相似度 / 作者归属）
    知识图谱工程师（本体一致性 / 约束求解）
  仲裁
    主持人（综合裁决，形成可用于续写的决议）

技术组不是点缀：它们先用 SQL / 统计在语料上算出证据，再带着证据发言，
其结论可被他人质询，也可被他人（如周汝昌）以文献学理由推翻。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

from . import db, llm, paths

# ---------------------------------------------------------------- 角色


@dataclass
class Agent:
    key: str
    name: str
    group: str
    era: str
    stance: str
    system: str
    color: str = '#7a5c3e'
    tools: dict = field(default_factory=dict)

    def speak(self, prompt: str, temperature: float = 0.85, tag: str = '') -> str:
        msgs = [
            {'role': 'system', 'content': self.system},
            {'role': 'user', 'content': prompt},
        ]
        return llm.chat(msgs, temperature=temperature, tag=tag or self.key)


BASE_RULE = """你是参与《红楼梦》续写推演的一位发言者。
铁律：
1. 只允许使用「脂评本前八十回 + 脂批」的证据，程高本后四十回（含「宝玉中举」
   「兰桂齐芳」「黛玉焚稿」等）一律不得作为依据，只能作为被批判的对象。
2. 凡下判断，必须给出证据（回目、原文片段、脂批原文），无证据者视为无效。
3. 语言：文言白话相间，贴合自身身份，但必须让今人读懂。
4. 若同意他人观点，要说出补充；若反对，要指出证据链的断点。
5. 直接发言，不要复述题目，不要自报家门。
"""


def _agent(key, name, group, era, stance, extra, color, tools=None):
    return Agent(key=key, name=name, group=group, era=era, stance=stance,
                 system=BASE_RULE + '\n' + extra.strip(), color=color,
                 tools=tools or {})


# ---- 技术组工具：真正跑在语料上的现代方法

def _t(name):
    return lambda *a, **k: db.analytic(name, *a)


DATA_TOOLS = {
    'person_arc': _t('person_arc'),
    'cooccur': _t('cooccur'),
    'anno_density': _t('anno_density'),
    'edition_dist': _t('edition_dist'),
    'imagery_by_chapter': _t('imagery_by_chapter'),
    'poet_profile': _t('poet_profile'),
    'rhyme_stats': _t('rhyme_stats'),
    'omen_chapters': _t('omen_chapters'),
    'affect_curve': _t('affect_curve'),
    'sql': db.q,
}


def data_evidence(topic: str) -> list[dict]:
    """数据科学家：按议题关键词自动选取分析并算出证据。"""
    out = []
    people = [p['name'] for p in db.q('SELECT name FROM persons')]
    hits = [p for p in people if p in topic]
    for p in hits[:2]:
        arc = db.analytic('person_arc', p)
        tail = arc[-12:] if arc else []
        out.append(dict(
            kind='person_arc', person=p,
            summary=f'{p}在前八十回的提及热度（末十二回）：'
                    + '、'.join(f"{r['chapter']}回{int(r['hits'])}次" for r in tail),
            rows=tail))
        co = db.analytic('cooccur', p, 6)
        out.append(dict(
            kind='cooccur', person=p,
            summary=f'与{p}同回共现最多者：'
                    + '、'.join(f"{r['person']}({int(r['w'])})" for r in co),
            rows=co))
    ac = db.analytic('affect_curve')
    if ac:
        tail_ac = [r for r in ac if r['chapter'] >= 70]
        out.append(dict(
            kind='affect_curve',
            summary='末十一回悲喜词频：'
                    + '；'.join(f"{int(r['chapter'])}回 悲{int(r['sad'])}/喜{int(r['happy'])}"
                                for r in tail_ac),
            rows=tail_ac))
    oc = db.analytic('omen_chapters')
    out.append(dict(kind='omen_chapters',
                    summary='谶应密度：' + '、'.join(
                        f"{int(r['chapter'])}回{int(r['n'])}首" for r in oc[:5]),
                    rows=oc[:5]))
    ed = db.analytic('edition_dist')
    out.append(dict(kind='edition_dist',
                    summary='脂批版本分布：' + '、'.join(
                        f"{r['edition']}{int(r['n'])}条" for r in ed[:6]),
                    rows=ed[:6]))
    return out


def style_evidence(text: str) -> dict:
    """文体计量学家：给一段文字算风格指标（用于续写稿的一致性检验）。"""
    import re
    from collections import Counter

    z = re.findall(r'[一-鿿]', text)
    n = len(z)
    if not n:
        return {}
    # 句读长度分布
    sents = [s for s in re.split(r'[。！？；!?;]', text) if s.strip()]
    sent_len = sum(len(s) for s in sents) / max(1, len(sents))
    # 对话占比
    dialog = len(re.findall(r'[：「"]', text)) / n
    # 虚词比例（与诗性判据同一口径）
    from .poems import XUCI
    xu = sum(1 for c in z if c in XUCI) / n
    # 四字格比例（骈俪度）
    four = len(re.findall(r'[一-鿿]{4}(?=[，。、；])', text))
    # 常用字分布（前 20）
    top = Counter(z).most_common(20)
    return dict(chars=n, sents=len(sents), avg_sent_len=round(sent_len, 2),
                dialog_rate=round(dialog, 4), xuci_rate=round(xu, 4),
                four_char= four, top_chars=top)


def corpus_style_baseline(chapters=(70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80)) -> dict:
    """以脂本末十一回为基准，算「曹雪芹原笔」的风格向量。"""
    rows = db.q('SELECT text FROM v_main WHERE chapter IN (%s)'
                % ','.join(str(c) for c in chapters))
    return style_evidence(''.join(r['text'] for r in rows))


def style_distance(a: dict, b: dict) -> float:
    """风格向量距离（越小越接近原笔）。"""
    keys = ['avg_sent_len', 'dialog_rate', 'xuci_rate']
    va = [a.get(k, 0) for k in keys]
    vb = [b.get(k, 0) for k in keys]
    # 归一化到量级可比
    scale = [30.0, 0.1, 0.1]
    d = sum(((x - y) / s) ** 2 for x, y, s in zip(va, vb, scale))
    return round((d / len(keys)) ** 0.5, 4)


# ---- 角色表

AGENTS: dict[str, Agent] = {
    'zhiyanzai': _agent(
        'zhiyanzai', '脂砚斋', '古典组', '脂批主要作者',
        '掌伏线与「草蛇灰线」，最知作者心事，主张「不写之写」',
        """你是脂砚斋，与作者极亲近，批书时常用「余」「作者」「芹溪」相称。
说话口吻：短句、感叹、好用「妙极」「是极」「哭杀」「叹叹」「一笑」。
你掌握他人不知的内情：抄没、狱神庙、卫若兰射圃、花袭人有始有终、
悬崖撒手、末回情榜、黛玉「泪尽夭亡」、宝玉「寒冬噎酸齑，雪夜围破毡」。
发言时优先引用你自己写过的批语。""", '#a03c3c'),

    'jihusou': _agent(
        'jihusou', '畸笏叟', '古典组', '脂批另一主要作者（多作眉批、回前回后批）',
        '掌「迷失文字」与删改内幕，主张秦可卿「淫丧天香楼」原稿之存在',
        """你是畸笏叟，年辈更长，批语多见「芹溪删去」「姑赦之」「命芹溪删去」
一类口吻，常记「文字迷失」之事：狱神庙、卫若兰射圃、花袭人有始有终等。
说话口吻：老成、扼要、常带数目（如「此回只十页，因删去天香楼一节」）。
你对后三十回的散失最感痛心，主张续写须以「迷失回目」为骨架。""",
        '#8b6914'),

    'caoxueqin': _agent(
        'caoxueqin', '曹雪芹', '古典组', '作者（悼红轩中披阅十载，增删五次）',
        '掌文心与笔法：一击两鸣、背面傅粉、云龙雾雨、不写之写',
        """你是曹雪芹。你写此书是「一把辛酸泪」，末回是「情榜」，
结局是「白茫茫大地真干净」。你不写才子佳人团圆，不写科举荣身。
说话口吻：沉静、克制、偶有自嘲，好用「满纸荒唐言」式的反语。
你最在意的是「真事隐去，假语存焉」，以及人物性格的内在逻辑：
黛玉必泪尽，凤姐必哭向金陵，探春必远嫁，宝玉必悬崖撒手。""",
        '#4a5d7e'),

    'zhouruchang': _agent(
        'zhouruchang', '周汝昌', '红学组', '现代红学·探佚派',
        '主张「探佚学」：以脂批为本，复原后三十回真情节',
        """你是周汝昌，红学探佚派的代表。你坚信脂批是探佚的唯一指南，
主张后半部的关键节点：元春之死、贾府抄没、黛玉泪尽、宝玉宝钗成婚、
探春远嫁、湘云与卫若兰、凤姐被休、巧姐被卖而赖刘姥姥得救、
末回情榜、宝玉悬崖撒手。你激烈反对程高本后四十回。
说话口吻：论断斩截，好用「断然」「决非」「铁证」。""", '#2f6b4f'),

    'yupingbo': _agent(
        'yupingbo', '俞平伯', '红学组', '现代红学·考据派',
        '主张从版本文字差异入手，慎言探佚，强调「不可知者阙疑」',
        """你是俞平伯，新红学的考据大家。你主张「辨伪」先于「探佚」：
先弄清版本异同、文字优劣，再谈情节复原；凡脂批无证者，宁可阙疑。
你对探佚派的过度推论保持警惕，常说「此亦想当然耳」。
说话口吻：平和、严谨、好用「似当」「未可骤断」「此说尚待证据」。""",
        '#5a5a7a'),

    'caiyuanpei': _agent(
        'caiyuanpei', '蔡元培', '红学组', '旧红学·索隐派',
        '主张《红楼》寓「吊明反清」之政治隐义',
        """你是蔡元培，索隐派代表，著《石头记索隐》，主张书中人物影射
明清之际的史事与人物（如「林黛玉」影朱彝尊、「宝钗」影高士奇等）。
你的方法在考据派看来牵强，但你提醒众人：此书确有「真事隐」的政治底色。
说话口吻：温厚而执拗，好用「以史事证之」「此盖影」。""", '#6b4f8b'),

    'zhangailing': _agent(
        'zhangailing', '张爱玲', '红学组', '现代作家·红学随笔',
        '「人生三恨」：鲥鱼多刺、海棠无香、《红楼》未完；主张续书「俗气」',
        """你是张爱玲，著《红楼梦魇》。你说人生三大恨事：一恨鲥鱼多刺，
二恨海棠无香，三恨《红楼梦》未完。你认定后四十回是「附骨之疽」，
「读起来只觉俗气」，续书人「把贾母写成势利，把黛玉写成小性儿」。
你最关心的是细节的真实与语言的质感和分寸，厌恶说教与团圆。
说话口吻：冷峭、精警、好用短促的判断句与俏皮的比喻。""", '#8b3a62'),

    'datascientist': _agent(
        'datascientist', '数据科学家', '技术组', '数字人文 / 计算文学',
        '只用可复算的统计量说话：频次、共现、分布、显著性',
        """你是数据科学家。你面前有一张 DuckDB 表，含前八十回全部正文块、
脂批、诗词与本体实体。你的发言必须包含：至少两项可复算的统计量
（如提及热度、共现权重、谶应密度、悲喜词频、版本批语分布），
并说明该统计量支持或否证了哪个论断。不得凭印象发言。
说话口吻：冷静、精确，先给数字，再给结论，最后给不确定性。""",
        '#1f6f8b', DATA_TOOLS),

    'stylometrist': _agent(
        'stylometrist', '文体计量学家', '技术组', '计量文体学 / 作者归属',
        '用风格向量与距离度量判断续写是否「像」曹雪芹',
        """你是文体计量学家。你用句长分布、对话占比、虚词比例、四字格密度、
常用字谱等指标构成风格向量，以脂本末十一回为基准，度量续写稿的距离。
你的判词必须给出指标数值与距离，不得只说「像」或「不像」。
说话口吻：克制、量化、惯用「在 ±X 范围内」「与基准距离为 X」。""",
        '#1f8b6b'),

    'kgengineer': _agent(
        'kgengineer', '知识图谱工程师', '技术组', '本体工程 / 约束求解',
        '负责本体一致性：时序、亲属、册籍、谶应是否自洽',
        """你是知识图谱工程师。你维护一张本体图谱：人物、居所、亲属关系、
册籍、诗谶、脂批明示的后文线索。你的职责是指出任何一条剧情设想
是否违反已有约束（如时序冲突、人物已死、册籍位置冲突、脂批明言冲突），
并把冲突写成「约束违反报告」。说话口吻：结构化、条目化、先列冲突再列建议。""",
        '#7a6b1f'),

    'moderator': _agent(
        'moderator', '主持人', '仲裁', '推演主持人',
        '综合各方证据，形成可执行的续写决议',
        """你是主持人。你的职责是：听完各方发言后，指出真正的分歧点，
裁定哪些证据分量更重，最后形成一份「续写决议」：包含必须遵守的
硬约束（脂批明示）、倾向采用的情节走向、以及留白之处。
说话口吻：条理分明，先列「已成立」「未成立」「存疑」三栏。""",
        '#3c3c3c'),
}


# ---------------------------------------------------------------- 推演编排

def _fmt_evidence(ev: list[dict]) -> str:
    if not ev:
        return '（无技术组证据）'
    return '\n'.join(f"- [{e['kind']}] {e['summary']}" for e in ev)


def deliberate(topic: str, question: str, rounds: int = 2,
               keys: list[str] | None = None,
               dry_run: bool = False) -> dict:
    """组织一次多 Agent 推演，全过程落盘并返回结构化记录。"""
    keys = keys or list(AGENTS)
    t0 = datetime.now().isoformat(timespec='seconds')
    ev = data_evidence(topic + question)
    ev_text = _fmt_evidence(ev)

    rec = dict(topic=topic, question=question, started_at=t0,
               evidence=ev, rounds=[], claims=[], resolution='')

    for r in range(1, rounds + 1):
        phase_log = []
        for k in keys:
            a = AGENTS[k]
            others = '' if r == 1 else _peer_summary(rec, k)
            prompt = (
                f'【议题】{topic}\n'
                f'【本轮问题】{question}\n\n'
                f'【技术组在语料上算出的证据】\n{ev_text}\n'
                + (f'\n【上一轮各方要点】\n{others}\n' if others else '')
                + '\n请以你的身份发言（200 字以内），给出你的判断与证据。'
            )
            if dry_run:
                content = f'〔{a.name}·未调用模型〕{a.stance}'
            else:
                content = a.speak(prompt, tag=f'debate-r{r}')
            db.add_claim(topic, a.name, a.stance, content,
                         [e['kind'] for e in ev], 0.5, r)
            db.add_debate(r, '立论' if r == 1 else '质证', a.name, content,
                          [], [e['kind'] for e in ev])
            phase_log.append(dict(agent=a.name, key=k, group=a.group,
                                  color=a.color, content=content))
            rec['claims'].append(dict(agent=a.name, content=content, round=r))
        rec['rounds'].append(dict(round=r, phase='质证' if r > 1 else '立论',
                                  speeches=phase_log))

    # 裁决
    m = AGENTS['moderator']
    allc = '\n'.join(f'〔{c["agent"]}〕{c["content"]}' for c in rec['claims'])
    mprompt = (f'【议题】{topic}\n【问题】{question}\n\n【各方发言】\n{allc}\n\n'
               f'【技术组证据】\n{ev_text}\n\n'
               '请给出裁决：分「已成立」「未成立」「存疑」三栏，'
               '最后列出续写时必须遵守的硬约束（不超过 8 条）。')
    resolution = (f'〔主持人·未调用模型〕议题：{topic}'
                  if dry_run else m.speak(mprompt, tag='resolution'))
    rec['resolution'] = resolution
    db.add_debate(99, '裁决', m.name, resolution, [], [])
    paths.data('debates').mkdir(parents=True, exist_ok=True)
    out = paths.data('debates') / (re.sub(r'[\\/:*?"<>|]', '_', topic)[:40]
                                   + '.json')
    out.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
    rec['file'] = str(out)
    return rec


def _peer_summary(rec: dict, self_key: str) -> str:
    seen = {}
    for c in rec['claims']:
        seen[c['agent']] = c['content']
    return '\n'.join(f'〔{k}〕{v[:120]}…' for k, v in seen.items()
                     if k != AGENTS[self_key].name)


# ---------------------------------------------------------------- 续写

def write_chapter(chapter: int, brief: str, resolution: str = '',
                  dry_run: bool = False, revise: bool = True) -> dict:
    """曹雪芹执笔 → 文体门禁 → 修订 → 脂砚斋批点 → 落盘。"""
    import re as _re

    from . import style

    title = ''
    evidence = data_evidence(brief)
    base = style.baseline()
    sample = style.sample_original()
    prompt = (
        f'【续写任务】续《石头记》{chapter} 回。\n'
        f'【情节要求】{brief}\n'
        f'【推演决议中的硬约束】\n{resolution or "（无）"}\n'
        f'【语料统计】\n{_fmt_evidence(evidence)}\n'
        f'【原笔样板（脂本第七十八至八十回真文，须摹其腔调）】\n{sample}\n'
        '写法铁律：\n'
        '1. 只用清中叶白话小说语体；禁现代词（梦想、鼓励、关怀、希望、'
        '勇敢、未来、写生、氛围、情绪、因为…所以、虽然…但是、她/她们等）；\n'
        '2. 人物称「他」「那人」「姑娘」，不用「她」；\n'
        '3. 多用「笑道」「因道」「一面」「只见」「遂」「只得」等原书习语；\n'
        '4. 回目用对仗的八字或七字句；\n'
        '5. 结尾须留「且听下回分解」；\n'
        '6. 若回中有人作诗，须合其诗风画像（如黛玉哀婉用落花秋雨，'
        '宝钗含蓄不用哀艳字，湘云豪放不作缠绵语）；\n'
        '7. 篇幅 1200-1800 字，不少于 6 段对话。\n'
        '请直接输出：回目 + 正文，不要任何说明。'
    )
    text = '' if dry_run else AGENTS['caoxueqin'].speak(
        prompt, temperature=0.9, tag=f'write-{chapter}')

    gate1 = style.gate(text, base)

    review = ''
    if not dry_run and revise and not gate1['pass_']:
        rp = (f'续写第 {chapter} 回的初稿未通过风格门禁：\n'
              f'基准（脂本末十一回）：{json.dumps(base, ensure_ascii=False)}\n'
              f'初稿指标：{json.dumps(gate1["metrics"], ensure_ascii=False)}\n'
              f'距离：{gate1["distance"]}\n'
              f'违例：{gate1["lint_text"]}\n'
              f'建议：{"；".join(gate1["advice"])}\n'
              '请以文体计量学家身份，给出三条最要紧的修改指令（100 字以内），'
              '每条须可执行。')
        review = AGENTS['stylometrist'].speak(rp, tag=f'style-{chapter}')
        text2 = AGENTS['caoxueqin'].speak(
            f'以下是你写的第 {chapter} 回：\n{text}\n\n'
            f'文体计量学家指出：{review}\n'
            f'现代词违例：{gate1["lint_text"]}\n'
            '请按意见重写一稿（保持情节，只改语言与句法），直接输出回目+正文。',
            temperature=0.85, tag=f'revise-{chapter}')
        if len(text2) > 400:
            text = text2

    gate = style.gate(text, base)
    metrics, dist = gate['metrics'], gate['distance']

    zhi = ''
    if not dry_run:
        zp = (f'以下续写第 {chapter} 回的正文（部分）：\n{text[:1200]}\n\n'
              '请以脂砚斋的身份批点：夹批三到五条，回末总评一条，'
              '并指出何处合「草蛇灰线」、何处走了样（200 字以内）。')
        zhi = AGENTS['zhiyanzai'].speak(zp, tag=f'zhi-{chapter}')

    m = _re.search(r'第[^\n]{0,40}回\s*([^\n]{6,30})', text)
    if m:
        title = m.group(1).strip()
    db.add_continuation(chapter, title, text, dist or 0.0,
                        json.dumps(dict(review=review, zhi=zhi, gate=gate),
                                   ensure_ascii=False))
    return dict(chapter=chapter, title=title, text=text, metrics=metrics,
                distance=dist, gate=gate, review=review, zhi=zhi)


if __name__ == '__main__':
    import sys

    dry = '--dry' in sys.argv
    topic = '第八十一回当如何开篇'
    question = ('前八十回止于迎春误嫁、香菱受苦、宝玉病重。'
                '后文第一桩大事应是什么？如何开篇？')
    rec = deliberate(topic, question, rounds=1, dry_run=dry)
    print('议题：', rec['topic'])
    for c in rec['claims']:
        print(f"\n〔{c['agent']}〕{c['content']}")
    print('\n【裁决】\n', rec['resolution'])
    print('\n落盘：', rec['file'])
