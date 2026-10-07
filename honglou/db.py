"""《红楼》知识库：DuckDB 单文件库（构建期 OLAP 引擎 + 推演落盘）。

选型说明
--------
数据量：正文约 60 万字、正文块 ~1 万、脂批 ~4 千、诗词 ~200 首、本体实体 ~500。
这种「单机、只读、分析型」负载正是 DuckDB 的主场：

* 零服务、单文件，随构建脚本重建，不需要起数据库进程；
* 列存 + 向量化，对「按回聚合 / 共现矩阵 / 词频统计 / 风格向量」这类
  扫描型查询比 SQLite 快一个量级；
* 原生 SQL 与窗口函数，数据专家 Agent 可直接写 SQL 取证，
  不必把中间结果搬进 Python；
* 可直接挂 parquet / csv / json，便于外部数据（如人物表）联查。

前端（GitHub Pages）是纯静态站点，浏览器里跑不了服务端 DB，
因此构建期从 DuckDB 导出 JSON 快照供页面使用；
若日后需要交互查询，可改用 DuckDB-WASM 直接加载导出的 parquet。

推演过程（claim / debate / continuation）也写进同一库，
便于「数据专家」用 SQL 复核各 Agent 的论证强度。
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import paths
from .bootstrap import ensure_pylibs

ensure_pylibs()
import duckdb  # noqa: E402

DB_PATH = paths.DATA_DIR / 'honglou.duckdb'

DDL = """
CREATE TABLE IF NOT EXISTS meta(key VARCHAR PRIMARY KEY, value VARCHAR);

CREATE TABLE IF NOT EXISTS chapters(
    chapter INTEGER PRIMARY KEY, title VARCHAR,
    page_start INTEGER, page_end INTEGER,
    n_main INTEGER, n_anno INTEGER, n_note INTEGER);

CREATE TABLE IF NOT EXISTS blocks(
    id BIGINT PRIMARY KEY, chapter INTEGER, kind VARCHAR,
    text VARCHAR, page INTEGER,
    editions VARCHAR, atype VARCHAR, ink VARCHAR);

CREATE TABLE IF NOT EXISTS poems(
    id VARCHAR PRIMARY KEY, chapter INTEGER, title VARCHAR, genre VARCHAR,
    author VARCHAR, text VARCHAR, n_lines INTEGER, main_len INTEGER,
    xu DOUBLE, rhyme DOUBLE, route VARCHAR, blocks VARCHAR,
    prev_ctx VARCHAR);

CREATE TABLE IF NOT EXISTS poem_lines(
    poem_id VARCHAR, seq INTEGER, line VARCHAR);

CREATE TABLE IF NOT EXISTS poem_images(
    poem_id VARCHAR, image VARCHAR, category VARCHAR, n INTEGER);

CREATE TABLE IF NOT EXISTS persons(
    name VARCHAR PRIMARY KEY, gender VARCHAR, role VARCHAR, residence VARCHAR,
    qingbang VARCHAR, fate VARCHAR, traits VARCHAR, aliases VARCHAR,
    registry VARCHAR);

CREATE TABLE IF NOT EXISTS places(name VARCHAR PRIMARY KEY, category VARCHAR,
    belongs VARCHAR, note VARCHAR);

CREATE TABLE IF NOT EXISTS objects(name VARCHAR PRIMARY KEY, owner VARCHAR,
    category VARCHAR, symbol VARCHAR);

CREATE TABLE IF NOT EXISTS concepts(name VARCHAR PRIMARY KEY,
    category VARCHAR, gloss VARCHAR);

CREATE TABLE IF NOT EXISTS relations(source VARCHAR, rel VARCHAR, target VARCHAR);

CREATE TABLE IF NOT EXISTS families(name VARCHAR PRIMARY KEY, origin VARCHAR,
    seat VARCHAR, note VARCHAR);

CREATE TABLE IF NOT EXISTS clubs(name VARCHAR PRIMARY KEY, place VARCHAR,
    founder VARCHAR, officers VARCHAR, theme VARCHAR);

CREATE TABLE IF NOT EXISTS imagery(image VARCHAR PRIMARY KEY, category VARCHAR,
    emotion VARCHAR, context VARCHAR);

CREATE TABLE IF NOT EXISTS allusions(name VARCHAR PRIMARY KEY, source VARCHAR,
    usage VARCHAR, person VARCHAR, gloss VARCHAR);

CREATE TABLE IF NOT EXISTS poet_style(person VARCHAR PRIMARY KEY, style VARCHAR,
    images VARCHAR, voice VARCHAR, taboo VARCHAR);

CREATE TABLE IF NOT EXISTS festivals(id INTEGER, chapter VARCHAR,
    solar_term VARCHAR, event VARCHAR);

CREATE TABLE IF NOT EXISTS lost_clues(id INTEGER, clue VARCHAR,
    source VARCHAR, meaning VARCHAR);

CREATE TABLE IF NOT EXISTS mentions(
    person VARCHAR, chapter INTEGER, block_id BIGINT, n INTEGER);

CREATE TABLE IF NOT EXISTS claims(
    id VARCHAR PRIMARY KEY, topic VARCHAR, agent VARCHAR, stance VARCHAR,
    content VARCHAR, evidence VARCHAR, confidence DOUBLE, round INTEGER,
    created_at VARCHAR);

CREATE TABLE IF NOT EXISTS debates(
    id VARCHAR PRIMARY KEY, round INTEGER, phase VARCHAR, agent VARCHAR,
    content VARCHAR, targets VARCHAR, evidence VARCHAR, created_at VARCHAR);

CREATE TABLE IF NOT EXISTS continuations(
    chapter INTEGER PRIMARY KEY, title VARCHAR, text VARCHAR,
    style_score DOUBLE, notes VARCHAR, created_at VARCHAR);

CREATE VIEW IF NOT EXISTS v_anno AS
    SELECT * FROM blocks WHERE kind IN ('批语','回前批','回后批');
CREATE VIEW IF NOT EXISTS v_main AS
    SELECT * FROM blocks WHERE kind = '正文';
"""


# ---------------------------------------------------------------- 连接

def conn(readonly: bool = False):
    return duckdb.connect(str(DB_PATH), read_only=readonly)


def q(sql: str, params: list | None = None, readonly: bool = True) -> list[dict]:
    con = conn(readonly)
    try:
        cur = con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        con.close()


def show(sql: str, n: int = 30) -> None:
    rows = q(sql)
    for r in rows[:n]:
        print(json.dumps(r, ensure_ascii=False))
    print(f'-- {len(rows)} rows')


# ---------------------------------------------------------------- 构建

def _mentions(corpus: dict) -> list[tuple[str, int, int, int]]:
    """统计人物（含别名）在各正文块中的出现次数。"""
    from . import ontology_seed as seed

    alias2name: dict[str, str] = {}
    for p in seed.persons():
        alias2name[p['name']] = p['name']
        for a in p['aliases']:
            if len(a) >= 2:
                alias2name.setdefault(a, p['name'])
    items = sorted(alias2name.items(), key=lambda kv: -len(kv[0]))
    out = []
    for ch in corpus['chapters']:
        if ch['no'] <= 0:
            continue
        for b in ch['blocks']:
            if b['kind'] != '正文':
                continue
            t = b['text']
            cnt: Counter = Counter()
            for alias, name in items:
                c = t.count(alias)
                if c:
                    cnt[name] += c
            for name, c in cnt.items():
                out.append((name, ch['no'], b['id'], c))
    return out


def _poem_images(poems: list[dict]) -> list[tuple[str, str, str, int]]:
    from . import ontology_seed as seed

    imgs = [(i['name'], i['category']) for i in seed.imagery()]
    out = []
    for p in poems:
        t = p['text']
        for name, cat in imgs:
            c = t.count(name)
            if c:
                out.append((p['id'], name, cat, c))
    return out


def build(force: bool = True) -> Path:
    from . import ontology_seed as seed
    from .poems import extract, guess_genre

    # 重建语料/本体时保留推演与续写成果（这些无法从 PDF 重算）
    keep: dict[str, list[tuple]] = {}
    if force and DB_PATH.exists():
        c0 = conn()
        for t in ('claims', 'debates', 'continuations'):
            try:
                rows = c0.execute(f'SELECT * FROM {t}').fetchall()
                keep[t] = rows
            except Exception:
                pass
        c0.close()
    if force and DB_PATH.exists():
        DB_PATH.unlink()
    con = conn()
    con.execute(DDL)

    corpus = json.loads(paths.data('corpus.json').read_text(encoding='utf-8'))

    # --- 回与块
    ch_rows, blk_rows = [], []
    for ch in corpus['chapters']:
        kinds = Counter(b['kind'] for b in ch['blocks'])
        pages = [b['page'] for b in ch['blocks']] or [0]
        ch_rows.append((ch['no'], ch['title'], min(pages), max(pages),
                        kinds.get('正文', 0), kinds.get('批语', 0),
                        kinds.get('校记', 0)))
        for b in ch['blocks']:
            blk_rows.append((b['id'], ch['no'], b['kind'], b['text'], b['page'],
                             json.dumps(b.get('editions', []), ensure_ascii=False),
                             b.get('atype', ''), b.get('ink', '')))
    con.executemany('INSERT INTO chapters VALUES (?,?,?,?,?,?,?)', ch_rows)
    con.executemany('INSERT INTO blocks VALUES (?,?,?,?,?,?,?,?)', blk_rows)

    # --- 本体
    con.executemany('INSERT INTO persons VALUES (?,?,?,?,?,?,?,?,?)', [
        (p['name'], p['gender'], p['role'], p['residence'], p['qingbang'],
         p['fate'], json.dumps(p['traits'], ensure_ascii=False),
         json.dumps(p['aliases'], ensure_ascii=False), p['registry'])
        for p in seed.persons()])
    con.executemany('INSERT INTO places VALUES (?,?,?,?)', [
        (p['name'], p['category'], p['belongs'], p['note']) for p in seed.places()])
    con.executemany('INSERT INTO objects VALUES (?,?,?,?)', [
        (o['name'], o['owner'], o['category'], o['symbol']) for o in seed.objects()])
    con.executemany('INSERT INTO concepts VALUES (?,?,?)', [
        (c['name'], c['category'], c['gloss']) for c in seed.concepts()])
    con.executemany('INSERT INTO relations VALUES (?,?,?)', [
        (r['source'], r['rel'], r['target']) for r in seed.relations()])
    con.executemany('INSERT INTO families VALUES (?,?,?,?)', [
        (f['name'], f['origin'], f['seat'], f['note']) for f in seed.families()])
    con.executemany('INSERT INTO clubs VALUES (?,?,?,?,?)', [
        (c['name'], c['place'], c['founder'], c['officers'], c['theme'])
        for c in seed.clubs()])
    con.executemany('INSERT INTO imagery VALUES (?,?,?,?)', [
        (i['name'], i['category'], i['emotion'], i['context'])
        for i in seed.imagery()])
    con.executemany('INSERT INTO allusions VALUES (?,?,?,?,?)', [
        (a['name'], a['source'], a['usage'], a['person'], a['gloss'])
        for a in seed.allusions()])
    con.executemany('INSERT INTO poet_style VALUES (?,?,?,?,?)', [
        (s['person'], s['style'], json.dumps(s['images'], ensure_ascii=False),
         s['voice'], s['taboo']) for s in seed.poet_styles()])
    con.executemany('INSERT INTO festivals VALUES (?,?,?,?)', [
        (i, f['chapter'], f['solar_term'], f['event'])
        for i, f in enumerate(seed.festivals())])
    con.executemany('INSERT INTO lost_clues VALUES (?,?,?,?)', [
        (i, c['clue'], c['source'], c['meaning'])
        for i, c in enumerate(seed.lost_clues())])

    # --- 诗词
    poems, _ = extract(corpus)
    prows, lrows, irows = [], [], []
    for p in poems:
        g = guess_genre(p)
        m = p.get('metrics', {})
        prows.append((str(p['id']), p['chapter'], p['title'], g,
                      p.get('author') or '', p['text'], len(p['lines']),
                      m.get('main_len', 0), m.get('xu', 0.0), m.get('rhyme', 0.0),
                      p.get('route', ''), json.dumps(p['block_ids']),
                      p.get('prev_context', '')))
        for i, ln in enumerate(p['lines']):
            lrows.append((str(p['id']), i, ln))
    con.executemany('INSERT INTO poems VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', prows)
    con.executemany('INSERT INTO poem_lines VALUES (?,?,?)', lrows)
    irows = _poem_images(poems)
    con.executemany('INSERT INTO poem_images VALUES (?,?,?,?)', irows)

    # --- 人物提及
    con.executemany('INSERT INTO mentions VALUES (?,?,?,?)', _mentions(corpus))

    for t, rows in keep.items():
        if not rows:
            continue
        ncol = con.execute(
            f"SELECT COUNT(*) FROM information_schema.columns WHERE table_name='{t}'"
        ).fetchone()[0]
        con.executemany(
            f'INSERT INTO {t} VALUES ({",".join(["?"] * ncol)})', rows)
        con.execute(f"INSERT INTO meta VALUES ('kept_{t}', ?)", [str(len(rows))])

    con.execute("INSERT INTO meta VALUES ('built_at', ?)",
                [datetime.now().isoformat(timespec='seconds')])
    con.execute("INSERT INTO meta VALUES ('blocks', ?)", [str(len(blk_rows))])
    con.execute("INSERT INTO meta VALUES ('poems', ?)", [str(len(prows))])
    con.close()
    return DB_PATH


# ---------------------------------------------------------------- 数据专家的分析算子

ANALYTICS = {
    # 人物出场热度（按回）
    'person_arc': """
        SELECT chapter, SUM(n) AS hits FROM mentions
        WHERE person = ? GROUP BY chapter ORDER BY chapter""",
    # 人物共现（同回）
    'cooccur': """
        SELECT b.person, SUM(b.n) AS w
        FROM mentions a JOIN mentions b USING (chapter)
        WHERE a.person = ? AND b.person <> a.person
        GROUP BY b.person ORDER BY w DESC LIMIT ?""",
    # 批语密度（脂砚斋对哪一回最用力）
    'anno_density': """
        SELECT chapter, COUNT(*) AS n,
               ROUND(COUNT(*) * 1.0 / NULLIF(MAX(n_main), 0), 3) AS per_block
        FROM v_anno JOIN chapters USING (chapter)
        GROUP BY chapter ORDER BY n DESC LIMIT ?""",
    # 版本批语分布
    'edition_dist': """
        SELECT TRIM(e.value::VARCHAR, '"') AS edition, COUNT(*) AS n
        FROM v_anno, json_each(editions) e
        WHERE editions <> '[]'
        GROUP BY edition ORDER BY n DESC""",
    # 诗词意象谱
    'imagery_by_chapter': """
        SELECT p.chapter, i.image, SUM(i.n) AS n
        FROM poem_images i JOIN poems p ON p.id = i.poem_id
        GROUP BY p.chapter, i.image ORDER BY p.chapter, n DESC""",
    # 人物诗风画像（意象偏好）
    'poet_profile': """
        SELECT p.author, i.image, SUM(i.n) AS n
        FROM poem_images i JOIN poems p ON p.id = i.poem_id
        WHERE p.author <> '' GROUP BY p.author, i.image ORDER BY p.author, n DESC""",
    # 韵脚统计（偶数句末字韵基）
    'rhyme_stats': """
        SELECT p.chapter, p.title, p.genre, p.rhyme
        FROM poems p WHERE p.rhyme > 0 ORDER BY p.chapter""",
    # 谶应密度：判词/曲集中的回
    'omen_chapters': """
        SELECT chapter, COUNT(*) AS n FROM poems
        WHERE genre IN ('判词','曲','花签','灯谜')
        GROUP BY chapter ORDER BY n DESC""",
    # 悲喜词比例（情感曲线）
    'affect_curve': """
        SELECT chapter,
               SUM(CASE WHEN text LIKE '%泪%' OR text LIKE '%死%'
                        OR text LIKE '%哭%' OR text LIKE '%病%' THEN 1 ELSE 0 END) AS sad,
               SUM(CASE WHEN text LIKE '%笑%' OR text LIKE '%喜%'
                        OR text LIKE '%乐%' THEN 1 ELSE 0 END) AS happy,
               COUNT(*) AS blocks
        FROM v_main WHERE chapter > 0 GROUP BY chapter ORDER BY chapter""",
}


def analytic(name: str, *params) -> list[dict]:
    if name not in ANALYTICS:
        raise KeyError(f'未知分析：{name}，可选：{list(ANALYTICS)}')
    return q(ANALYTICS[name], list(params))


def mention_total(person: str) -> int:
    r = q('SELECT SUM(n) AS t FROM mentions WHERE person = ?', [person])
    return int(r[0]['t'] or 0)


# ---------------------------------------------------------------- 推演落盘

def add_claim(topic: str, agent: str, stance: str, content: str,
              evidence: list[str], confidence: float, round_: int = 0) -> str:
    cid = f'C{round_}-{abs(hash((topic, agent, content))) % 10**8}'
    con = conn()
    con.execute('INSERT OR REPLACE INTO claims VALUES (?,?,?,?,?,?,?,?,?)',
                [cid, topic, agent, stance, content,
                 json.dumps(evidence, ensure_ascii=False), confidence, round_,
                 datetime.now().isoformat(timespec='seconds')])
    con.close()
    return cid


def add_debate(round_: int, phase: str, agent: str, content: str,
               targets: list[str], evidence: list[str]) -> str:
    did = f'D{round_}-{phase}-{abs(hash((agent, content))) % 10**8}'
    con = conn()
    con.execute('INSERT OR REPLACE INTO debates VALUES (?,?,?,?,?,?,?,?)',
                [did, round_, phase, agent, content,
                 json.dumps(targets, ensure_ascii=False),
                 json.dumps(evidence, ensure_ascii=False),
                 datetime.now().isoformat(timespec='seconds')])
    con.close()
    return did


def add_continuation(chapter: int, title: str, text: str,
                     style_score: float, notes: str) -> None:
    con = conn()
    con.execute('INSERT OR REPLACE INTO continuations VALUES (?,?,?,?,?,?)',
                [chapter, title, text, style_score, notes,
                 datetime.now().isoformat(timespec='seconds')])
    con.close()


if __name__ == '__main__':
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else 'build'
    if cmd == 'build':
        p = build()
        print('已建库：', p, f'{p.stat().st_size / 1e6:.1f} MB')
        for t in ('chapters', 'blocks', 'poems', 'poem_lines', 'persons',
                  'mentions', 'relations', 'imagery'):
            print(t, q(f'SELECT COUNT(*) AS n FROM {t}')[0]['n'])
    elif cmd == 'sql':
        show(' '.join(sys.argv[2:]))
    else:
        print(__doc__)
