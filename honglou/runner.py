"""整本书续写编排：按骨架逐回写，滚动维护情节状态，逐回过风格门禁。

每回流程
--------
1. 取材：回目清单条目 + 前二回提要 + 未用伏线 + 硬约束 + 原笔样板
2. 执笔：曹雪芹 Agent 输出 <<<回目>>> / <<<正文>>> / <<<提要>>>
3. 成稿校验（_body_issues）：篇幅、对话密度、结尾套语、拒答/议论跑题
4. 风格门禁（style.gate）：句长、对话率、虚词率、现代词禁例
5. 3、4 不过则请文体计量学家给指令，重写；最多三稿
6. 批点：脂砚斋夹批与回末总评（可关）
7. 落盘：DuckDB continuations + data/state.json（滚动状态）

断点续跑：已存在且成稿合格的回自动跳过；--force 重写；不合格者自动重来。
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from . import agents, db, guard, outline as outline_mod, paths, style

ACT_SIZE = 5          # 每五回为一「段落」，落笔前诸家先辩一次

STATE_FILE = paths.data('state.json')
SEC_RE = re.compile(r'<<<\s*(回目|正文|提要)\s*>>>(.*?)(?=<<<|\Z)', re.S)
CJK = r'[一-鿿]'

# 拒答 / 议论跑题的标记（模型一旦开始「答疑」，正文即废）
BAD_MARKERS = ['阁下', '所引', '非雪芹', '程高本续作', '不能续写', '无法续写',
               '作为AI', '语言模型', '很抱歉', '我无法', '原著八十回后佚稿',
               '并非曹雪芹', '只好就此', '恕难从命']


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    return dict(summaries={}, pending=[], updated_at='')


def save_state(st: dict) -> None:
    st['updated_at'] = datetime.now().isoformat(timespec='seconds')
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=1),
                          encoding='utf-8')


def _split_sections(text: str) -> dict:
    out = {}
    for m in SEC_RE.finditer(text):
        out[m.group(1)] = m.group(2).strip()
    if '正文' not in out:                      # 模型没按格式输出时的兜底
        lines = [x for x in text.splitlines() if x.strip()]
        if len(lines) >= 2:
            out.setdefault('回目', lines[0].strip())
            out['正文'] = '\n'.join(lines[1:]).strip()
        else:
            out['正文'] = text.strip()
    return out


def _clean_title(t: str, fallback: str) -> str:
    s = re.sub(r'[<>#《》【】\[\]"\'　 ]', '', t or '')
    s = re.sub(r'第\s*\d+\s*回', '', s)
    s = re.sub(r'^(回目|正文|提要)\s*[:：]?', '', s).strip()
    if not (5 <= len(s) <= 24) or '第' in s:
        return fallback
    return s


def _body_issues(text: str) -> list[str]:
    """成稿校验：篇幅、对话、结尾、跑题。"""
    n = len(re.findall(CJK, text))
    iss = []
    if n < 800:
        iss.append(f'正文仅 {n} 字，须写足 1200-1800 字')
    if n > 2000:
        iss.append(f'正文 {n} 字，过长，须压到 1500 字以内')
    for m in BAD_MARKERS:
        if m in text:
            iss.append(f'混入议论文字（「{m}」），须全部删去，只留小说正文')
            break
    if text.lstrip().startswith('#'):
        iss.append('不要用 Markdown 标题')
    if len(re.findall(r'[道曰][：:]', text)) < 6:
        iss.append('对话不足六处，须多用「笑道」「因道」的对话推进')
    if '下回分解' not in text[-160:]:
        iss.append('结尾须有「且听下回分解」')
    return iss


def _context(st: dict, n: int = 2) -> str:
    keys = sorted((int(k) for k in st.get('summaries', {})), reverse=True)[:n]
    return '\n'.join(f'第{k}回提要：{st["summaries"][str(k)]}'
                     for k in reversed(keys))


def _pending_text(st: dict, limit: int = 12) -> str:
    return '；'.join(st.get('pending', [])[:limit])


def _base_prompt(chapter: int, oitem: dict, resolution: str, cons: str,
                 sample: str, prev_text: str, st: dict) -> str:
    title_hint = (oitem or {}).get('title', '')
    brief = (oitem or {}).get('brief', '')
    return f"""【任务】续《石头记》第 {chapter} 回（全书共一百一十回，末回情榜）。

【本回回目已拟】{title_hint}
【本回要点】{brief}
【上文衔接】（第 {chapter - 1} 回末段）
{prev_text}
【前几回提要】
{_context(st)}
【尚未落地的伏线】{_pending_text(st) or '（见硬约束）'}
【必须遵守的硬约束】
{cons}
【推演决议】
{(resolution or '（无）')[:800]}
【原笔样板（脂本第七十六至八十回真文，须摹其腔调）】
{sample}

【写法铁律】
1. 清中叶白话小说语体；禁现代词（梦想、鼓励、关怀、希望、勇敢、未来、
   氛围、情绪、因为…所以、虽然…但是、她/她们等）；人物一律称「他」；
2. 多用「笑道」「因道」「一面」「只见」「遂」「只得」等原书习语；
3. 只写小说正文：叙事与对话，绝不议论、绝不解释、绝不评点版本；
4. 若有人作诗，须合其诗风画像（黛玉哀婉、宝钗含蓄、湘云豪放）；
5. 篇幅 1200-1800 字，对话不少于六处，结尾须留「且听下回分解」；
6. 只写本回情节，不要在文中预告后回。

【输出格式】严格三段，不要任何其它说明：
<<<回目>>>
（八字或七字对仗回目）
<<<正文>>>
（正文）
<<<提要>>>
（本回提要，100 字内；末尾另起一行以「伏线：」开头列出本回新埋的伏线，不超过 3 条）
"""


def write_one(chapter: int, oitem: dict | None, resolution: str = '',
              constraints: list[str] | None = None, do_zhi: bool = True,
              force: bool = False) -> dict:
    st = load_state()
    exist = db.q('SELECT text FROM continuations WHERE chapter = ?', [chapter])
    if exist and not force:
        old = exist[0]['text']
        old_ok = (not _body_issues(old)
                  and not guard.check(chapter, old, oitem, st, light=True)
                  and style.gate(old, style.baseline())['pass_'])
        if old_ok:
            return dict(chapter=chapter, skipped=True, text=old)
        print(f'第{chapter}回 旧稿不合格（成稿/本体论/门禁），重写', flush=True)

    base = style.baseline()
    # 末回为情榜，体例与叙事回不同（少对话、多榜文），门禁特判
    o = outline_mod.load_outline() or {}
    blob = (oitem or {}).get('title', '') + (oitem or {}).get('brief', '')
    is_final = chapter >= int(o.get('total', 110)) or '情榜' in blob
    max_dist = 1.8 if is_final else 1.0
    cons = '\n'.join('- ' + c for c in (constraints or [])[:40])
    sample = style.sample_original(chapters=(76, 77, 78, 79, 80), n=700)
    rows = db.q('SELECT text FROM continuations WHERE chapter = ?', [chapter - 1])
    prev_text = rows[0]['text'][-600:] if rows else ''
    prompt = _base_prompt(chapter, oitem, resolution, cons, sample, prev_text, st)

    fallback_title = (oitem or {}).get('title', '')
    text = title = summ = ''
    gate: dict = {}
    review = ''
    issues: list[str] = []
    gissues: list[str] = []
    auto_fix: list[str] = []
    for attempt in range(3):
        raw = agents.AGENTS['caoxueqin'].speak(
            prompt, temperature=0.9 if attempt == 0 else 0.85,
            tag=f'write-{chapter}')
        sec = _split_sections(raw)
        text = sec.get('正文', '').strip()
        title = _clean_title(sec.get('回目', ''), fallback_title)
        summ = sec.get('提要', '').strip()
        issues = _body_issues(text)
        gissues = guard.check(chapter, text, oitem, st)
        gate = style.gate(text, base, max_dist=max_dist)
        if not issues and not gissues and gate['pass_']:
            break
        allissues = issues + gissues
        rp = (f'第 {chapter} 回第 {attempt + 1} 稿未过。\n'
              f'成稿问题：{"；".join(allissues) or "无"}\n'
              f'风格违例：{gate["lint_text"] or "无"}\n'
              f'基准：{json.dumps({k: v for k, v in base.items() if k != "top_chars"}, ensure_ascii=False)}\n'
              f'本稿：{json.dumps(gate["metrics"], ensure_ascii=False)}\n'
              f'建议：{"；".join(gate["advice"])}\n'
              '请给三条最要紧、可执行的修改指令（100 字内）。')
        review = agents.AGENTS['stylometrist'].speak(rp, tag=f'style-{chapter}')
        prompt = (f'第 {chapter} 回初稿：\n{text}\n\n'
                  f'回目：{title}\n\n'
                  f'文体计量学家指出：{review}\n'
                  f'成稿与本体论问题：{"；".join(allissues)}\n'
                  f'现代词违例：{gate["lint_text"]}\n'
                  '请按意见重写：情节主干不变，只改语言句法、篇幅与违例之处；'
                  '本体论问题（G1 程高本、G2 时序、G3 已故者、G4 诗风、'
                  'G5 本体外人名）必须逐条消去；'
                  '仍按 <<<回目>>> <<<正文>>> <<<提要>>> 三段输出，不要任何说明。')
    # 篇幅失控则压缩：删铺陈、留关捩
    for _ in range(2):
        if not any('过长' in i for i in issues):
            break
        text = agents.AGENTS['caoxueqin'].speak(
            f'下面第 {chapter} 回的正文太长（{len(re.findall(CJK, text))} 字）。\n'
            f'{text}\n\n'
            '请压缩到 1200-1500 字：删去铺陈景物与重复客套，'
            '保留关捩、对话与结尾「且听下回分解」。'
            '只输出压缩后的正文，不要任何说明。',
            temperature=0.8, tag=f'compress-{chapter}')
        issues = _body_issues(text)
        gissues = guard.check(chapter, text, oitem, st)
        gate = style.gate(text, base, max_dist=max_dist)

    # 现代禁例「她」：机械替换（禁例执行，非代笔），并记入 notes
    if '她' in text:
        text = text.replace('她们', '他姊妹').replace('她', '他')
        auto_fix.append('她→他（现代禁例）')
        issues = _body_issues(text)
        gissues = guard.check(chapter, text, oitem, st)
        gate = style.gate(text, base, max_dist=max_dist)

    # 只差结尾套语时，请作者补两句收束（管道不代笔）
    if (not gate.get('pass_', True) or issues) and \
            any('下回分解' in i for i in issues) and len(issues) == 1:
        tail = agents.AGENTS['caoxueqin'].speak(
            f'第 {chapter} 回正文末尾：\n{text[-500:]}\n\n'
            '请接着写一两句收束本回，务必以「且听下回分解」作结。'
            '只输出所补的文字。', temperature=0.8, tag=f'tail-{chapter}')
        if tail and '下回分解' in tail:
            text = text.rstrip() + '\n' + tail.strip()
            issues = _body_issues(text)
            gissues = guard.check(chapter, text, oitem, st)
            gate = style.gate(text, base, max_dist=max_dist)

    failed = bool(issues) or bool(gissues) or not gate.get('pass_', False)

    zhi = ''
    if do_zhi and not failed:
        zhi = agents.AGENTS['zhiyanzai'].speak(
            f'以下是续写第 {chapter} 回（{title}）的正文：\n{text[:1400]}\n\n'
            '请以脂砚斋身份批点：夹批三到五条、回末总评一条，'
            '指出何处合草蛇灰线、何处走了样（200 字内）。',
            tag=f'zhi-{chapter}')

    db.add_continuation(chapter, title, text, gate.get('distance', 9),
                        json.dumps(dict(gate=gate, review=review, zhi=zhi,
                                        summary=summ, failed=failed,
                                        issues=issues, guard=gissues,
                                        warnings=list(guard.WARN),
                                        act=act_key(chapter),
                                        auto_fix=auto_fix),
                                   ensure_ascii=False))
    st.setdefault('summaries', {})[str(chapter)] = summ[:200]
    newly_dead = guard.collect_dead(text, chapter, st)
    _update_pending(st, summ)
    save_state(st)
    return dict(chapter=chapter, title=title, text=text, summary=summ,
                gate=gate, review=review, zhi=zhi, failed=failed,
                issues=issues + gissues, dead=newly_dead, skipped=False)


def act_key(chapter: int) -> str:
    """该回所属的段落（每五回一段）。"""
    start = (chapter - 81) // ACT_SIZE * ACT_SIZE + 81
    return f'{start}-{start + ACT_SIZE - 1}'


def deliberate_act(start: int, end: int, st: dict,
                   total_res: str = '') -> str:
    """落笔前，诸家就这一段如何写辩论一轮，裁决作为该段落笔依据。"""
    st.setdefault('acts', {})
    key = f'{start}-{end}'
    if key in st['acts']:
        return st['acts'][key]
    o = outline_mod.load_outline() or {}
    rows = [r for r in o.get('chapters', []) if start <= r['chapter'] <= end]
    listing = '\n'.join(f"{r['chapter']}|{r['title']}|{r['brief']}" for r in rows)
    done = '\n'.join(f'第{k}回：{v}' for k, v in sorted(
        st.get('summaries', {}).items(), key=lambda x: int(x[0]))
        if int(k) < start)
    dead = '、'.join(st.get('dead', [])) or '（无）'
    cons = '\n'.join('- ' + c for c in (o.get('constraints') or [])[:30])
    rec = agents.deliberate(
        f'第 {start} 至 {end} 回当如何落笔',
        f'【本段已拟回目】\n{listing}\n\n'
        f'【全书推演决议】\n{(total_res or "（无）")[:600]}\n\n'
        f'【已写前文提要】\n{done or "（首段）"}\n\n'
        f'【此时已亡故之人】{dead}\n'
        f'【硬约束】\n{cons}\n\n'
        '请问：本段五回，何处为关捩？孰为主脑？'
        '哪些伏线须在此埋、哪些须在此收？'
        '宝玉、黛玉、宝钗、凤姐各自的心境当如何推移？'
        '有无程高本的路数须严防？请各依所据发言。',
        rounds=1)
    st['acts'][key] = rec.get('resolution', '')
    save_state(st)
    return st['acts'][key]


def _update_pending(st: dict, summ: str) -> None:
    """从提要的「伏线：」行抽取新伏线，并入待办。"""
    pend = list(st.get('pending', []))
    for line in summ.splitlines():
        if line.strip().startswith('伏线：'):
            for item in re.split(r'[；;、]', line.replace('伏线：', '')):
                item = item.strip()
                if item and item not in pend:
                    pend.append(item)
    st['pending'] = pend[-20:]


def write_book(start: int = 81, end: int = 110, resolution: str = '',
               constraints: list[str] | None = None, do_zhi: bool = True,
               force: bool = False, limit: int | None = None,
               deliberate: bool = True) -> list[dict]:
    """按骨架逐回续写（可分批、可断点续跑）。"""
    o = outline_mod.load_outline()
    omap = {r['chapter']: r for r in (o or {}).get('chapters', [])}
    cons = constraints or (o or {}).get('constraints') or outline_mod.hard_constraints()
    total_res = resolution or (o or {}).get('resolution', '')
    st = load_state()
    out = []
    n = 0
    for ch in range(start, end + 1):
        if deliberate:
            a0, a1 = (int(x) for x in act_key(ch).split('-'))
            res = deliberate_act(a0, a1, st, total_res) or total_res
        else:
            res = total_res
        r = write_one(ch, omap.get(ch), res, cons, do_zhi=do_zhi, force=force)
        out.append(r)
        if r.get('skipped'):
            print(f'第{ch}回 已存在，跳过', flush=True)
            continue
        n += 1
        flag = '未过门禁' if r['failed'] else '通过'
        print(f'第{ch}回 {r["title"]} 距离{r["gate"]["distance"]} {flag} '
              f'字数{len(re.findall(CJK, r["text"]))}', flush=True)
        if limit and n >= limit:
            break
    return out


ANNO_PROMPT = """你是脂砚斋。下面是后人续写的《石头记》第 {chapter} 回（{title}）。

【正文】
{text}

请照脂批体例批点，只批此回，不得改写正文：
一、夹批：从正文中挑 5-7 处，摘取原文（须与正文一字不差，8-22 字），
   各给批语（15-40 字）。批语要点出笔法（草蛇灰线、一击两鸣、背面敷粉、
   不写之写、特犯不犯、自注）或指出失着，语气如脂砚斋。
二、回末总评：60-120 字，评本回得失，须点明与前八十回何处呼应。

【输出格式】每行一条，夹批用两竖线分隔；最后一行以「总评：」开头。不要任何其它文字。
原文摘句||批语
...
总评：……
"""


def annotate(chapter: int, force: bool = False) -> dict | None:
    """为已写的一回出结构化脂批（夹批 + 回末总评），写入 notes。"""
    rows = db.q('SELECT title, text, notes FROM continuations WHERE chapter = ?',
                [chapter])
    if not rows:
        return None
    r = rows[0]
    notes = json.loads(r['notes'] or '{}')
    if notes.get('annos') and not force:
        return dict(chapter=chapter, skipped=True)
    raw = agents.AGENTS['zhiyanzai'].speak(
        ANNO_PROMPT.format(chapter=chapter, title=r['title'] or '',
                           text=r['text'][:2200]),
        temperature=0.8, tag=f'anno2-{chapter}')
    annos, summary = [], ''
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('总评'):
            summary = line.split('：', 1)[-1].split(':', 1)[-1].strip()
            continue
        if re.search(r'[|｜]{2}', line):
            q, n = (x.strip() for x in re.split(r'[|｜]{2}', line, 1))
            q = re.sub(r'^[「『"\']+|[」』"\']+$', '', q).strip()
            if not (4 <= len(q) <= 40):
                continue
            if q in r['text']:
                annos.append(dict(quote=q, note=n))
                continue
            # 容错：忽略标点差异后再定位，回填正文原样片段
            strip = lambda s: re.sub(r'[^一-鿿]', '', s)      # noqa: E731
            t, qq = strip(r['text']), strip(q)
            if qq and qq in t:
                chars = re.findall(r'[一-鿿]', r['text'])
                i = t.find(qq)
                annos.append(dict(quote=''.join(chars[i:i + len(qq)]), note=n))
            else:
                # 摘句与正文不符（批者凭记忆引文）：保留原句，标注为拟批
                annos.append(dict(quote=q, note=n, loose=True))
    notes.update(annos=annos[:8],
                 zhi_summary=summary or notes.get('zhi', ''))
    g = notes.get('gate') if isinstance(notes.get('gate'), dict) else {}
    db.add_continuation(chapter, r['title'], r['text'],
                        g.get('distance', 0), json.dumps(notes, ensure_ascii=False))
    return dict(chapter=chapter, annos=len(annos), summary=summary[:40])


def annotate_all(start: int = 81, end: int = 110, force: bool = False,
                 limit: int | None = None) -> list[dict]:
    out, n = [], 0
    for ch in range(start, end + 1):
        res = annotate(ch, force=force)
        if res:
            out.append(res)
            print(f'第{ch}回 夹批 {res.get("annos", 0)} 条', flush=True)
            if not res.get('skipped'):
                n += 1
        if limit and n >= limit:
            break
    return out


def recheck(start: int = 81, end: int = 110) -> list[dict]:
    """按当前判据重算已写各回的成稿与本体论结论（不重写正文）。"""
    st = load_state()
    base = style.baseline()
    out = []
    for ch in range(start, end + 1):
        rows = db.q('SELECT title, text, notes FROM continuations WHERE chapter = ?',
                    [ch])
        if not rows:
            continue
        r = rows[0]
        notes = json.loads(r['notes'] or '{}')
        text = r['text']
        o = outline_mod.load_outline() or {}
        blob = notes.get('title', '')
        is_final = ch >= int(o.get('total', 110)) or '情榜' in (r['title'] or '')
        issues = _body_issues(text)
        gissues = guard.check(ch, text, None, st)
        gate = style.gate(text, base, max_dist=1.8 if is_final else 1.0)
        failed = bool(issues) or bool(gissues) or not gate['pass_']
        notes.update(gate=gate, guard=gissues, issues=issues, failed=failed,
                     warnings=list(guard.WARN))
        db.add_continuation(ch, r['title'], text, gate['distance'],
                            json.dumps(notes, ensure_ascii=False))
        out.append(dict(chapter=ch, failed=failed, dist=gate['distance'],
                        issues=issues + gissues))
    return out


def status() -> dict:
    rows = db.q('SELECT chapter, title, style_score, length(text) AS n '
                'FROM continuations ORDER BY chapter')
    st = load_state()
    return dict(written=[dict(chapter=r['chapter'], title=r['title'],
                              dist=r['style_score'], chars=r['n']) for r in rows],
                pending=st.get('pending', []),
                updated_at=st.get('updated_at', ''))
