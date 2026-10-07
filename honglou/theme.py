"""站点视觉主题：宣纸、朱印、诗笺、手稿纸。

纯 CSS，无外部依赖、无图片文件（纸纹与落花用 SVG data-URI / 渐变绘制）。
页面结构与类名沿用 site.py，只替换外观。
"""
from __future__ import annotations

NOISE = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
         "width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence "
         "type='fractalNoise' baseFrequency='0.85' numOctaves='4' "
         "stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='160' "
         "height='160' filter='url(%23n)' opacity='0.055'/%3E%3C/svg%3E")

CSS = f"""
:root{{
  --ink:#2f2a25; --ink2:#5d5449; --ink3:#8a7f6d;
  --paper:#f2ebdb; --paper2:#fffdf8;
  --cinnabar:#9e2b25; --cinnabar-d:#7d1f1b; --cinnabar-l:#c2504a;
  --jade:#3f6b5e; --indigo:#3b4a6b; --gold:#b08d57;
  --line:#e3d9c4; --line2:#efe6d3;
  --shadow:0 1px 2px rgba(70,52,28,.05), 0 10px 26px rgba(70,52,28,.07);
  --shadow-h:0 2px 4px rgba(70,52,28,.07), 0 16px 34px rgba(70,52,28,.11);
  --serif:"Songti SC","STSong","Noto Serif CJK SC","Source Han Serif SC","SimSun",serif;
  --kai:"Kaiti SC","STKaiti","KaiTi","Noto Serif CJK SC",serif;
}}
*{{box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{margin:0;color:var(--ink);
  background-color:var(--paper);
  background-image:
    radial-gradient(1100px 560px at 10% -10%, rgba(255,255,255,.85), transparent 62%),
    radial-gradient(900px 520px at 92% 4%, rgba(226,205,172,.5), transparent 66%),
    radial-gradient(600px 420px at 50% 110%, rgba(158,43,37,.05), transparent 70%),
    url("{NOISE}");
  background-attachment:fixed;
  font-family:var(--serif);font-size:15.5px;line-height:1.95;letter-spacing:.02em;
}}
a{{color:var(--indigo);text-decoration:none;transition:color .2s}}
a:hover{{color:var(--cinnabar);text-decoration:none}}

/* ---------- 刊头 ---------- */
header{{position:relative;text-align:center;padding:38px 20px 16px;
  background:linear-gradient(180deg,#f7f0e1 0%,#f3ead8 55%,#ece2cd 100%);
  border-bottom:1px solid var(--line);
  box-shadow:0 1px 0 rgba(255,255,255,.7) inset, 0 6px 18px -14px rgba(70,52,28,.35)}}
header h1{{margin:0;font-size:34px;font-weight:600;letter-spacing:.42em;
  text-indent:.42em;color:#2b2620;text-shadow:0 1px 0 rgba(255,255,255,.85)}}
header .sub{{margin-top:8px;color:var(--ink3);font-size:13px;letter-spacing:.2em}}
header .seal{{position:absolute;right:26px;top:30px}}
nav{{margin-top:16px;padding-top:12px;border-top:1px solid rgba(158,43,37,.16);
  display:flex;justify-content:center;gap:2px;flex-wrap:wrap}}
nav a{{display:inline-block;padding:5px 15px;margin:2px;font-size:15px;letter-spacing:.12em;
  color:var(--ink2);border:1px solid transparent;border-radius:2px;transition:all .22s}}
nav a:hover{{color:var(--cinnabar);border-color:rgba(158,43,37,.3);
  background:rgba(255,255,255,.55)}}
nav a.on{{color:var(--cinnabar);border-color:rgba(158,43,37,.35);
  background:linear-gradient(180deg,#fffdf8,#f6ecd9);font-weight:600}}

/* ---------- 印章 / 题签 ---------- */
.seal{{display:inline-block;padding:5px 9px;font-size:12px;letter-spacing:.2em;
  color:var(--cinnabar);border:1.5px solid var(--cinnabar);border-radius:3px;
  background:rgba(158,43,37,.05);transform:rotate(-3deg);font-family:var(--kai)}}
.seal.solid{{background:var(--cinnabar);color:#fdf6ec;border-color:var(--cinnabar-d)}}

/* ---------- 卷首 ---------- */
.hero{{position:relative;overflow:hidden;text-align:center;margin:2px 0 26px;
  padding:44px 28px 38px;border:1px solid var(--line);border-radius:3px;
  background:linear-gradient(180deg,rgba(255,255,255,.72),rgba(255,253,246,.35)),
    url("{NOISE}");
  box-shadow:var(--shadow)}}
.hero::after{{content:'';position:absolute;inset:0;pointer-events:none;opacity:.5;
  background:
    radial-gradient(7px 5px at 12% 82%, rgba(194,80,74,.28), transparent 60%),
    radial-gradient(6px 4px at 78% 22%, rgba(194,80,74,.22), transparent 60%),
    radial-gradient(5px 7px at 32% 30%, rgba(194,80,74,.16), transparent 60%),
    radial-gradient(8px 6px at 62% 74%, rgba(194,80,74,.18), transparent 60%)}}
.hero .verse{{font-family:var(--kai);font-size:23px;line-height:2.2;letter-spacing:.16em;
  color:#3a322a;margin:14px 0 6px}}
.hero .lead{{max-width:780px;margin:10px auto 0;color:var(--ink2);font-size:14.5px;text-align:justify}}
.hero .rule{{width:120px;height:1px;margin:16px auto 0;
  background:linear-gradient(90deg,transparent,rgba(158,43,37,.5),transparent)}}

/* ---------- 版心 ---------- */
main{{max-width:1120px;margin:0 auto;padding:24px 20px 70px}}
h2{{font-size:20px;letter-spacing:.1em;margin:32px 0 14px;padding-left:13px;
  border-left:3px solid var(--cinnabar);position:relative}}
h2:first-of-type{{margin-top:14px}}
h3{{font-size:17px;letter-spacing:.06em;color:var(--cinnabar-d);margin:4px 0 8px}}
big{{font-family:var(--kai);font-size:26px;color:var(--cinnabar);margin:0 4px}}
.small{{font-size:13px;color:var(--ink3)}}
.muted{{color:var(--ink3)}}

/* ---------- 笺纸卡片 ---------- */
.card{{position:relative;background:linear-gradient(180deg,var(--paper2),#fdf8ee);
  border:1px solid var(--line);border-radius:3px;padding:16px 18px;margin:14px 0;
  box-shadow:var(--shadow);transition:transform .25s ease,box-shadow .25s ease}}
.card:hover{{transform:translateY(-2px);box-shadow:var(--shadow-h)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(268px,1fr));gap:14px}}
.grid>.card{{margin:0}}
.tag{{display:inline-block;background:linear-gradient(180deg,#f6eedd,#efe4cd);
  border:1px solid var(--line);border-radius:11px;padding:1px 9px;font-size:12px;
  margin:2px 5px 2px 0;color:var(--ink2)}}
.tag.red{{color:var(--cinnabar);border-color:rgba(158,43,37,.35);
  background:linear-gradient(180deg,#fdf1ee,#f8e6e2)}}

/* ---------- 表 ---------- */
table{{border-collapse:separate;border-spacing:0;width:100%;font-size:14px;
  border:1px solid var(--line);border-radius:3px;overflow:hidden;
  background:var(--paper2);box-shadow:var(--shadow)}}
th{{background:linear-gradient(180deg,#f2e7d3,#ebdfc8);color:#5b4a33;font-weight:600;
  border-bottom:1px solid var(--line);white-space:nowrap}}
th,td{{padding:6px 10px;text-align:left;vertical-align:top}}
td{{border-bottom:1px dotted #e9ddc7}}
tbody tr:nth-child(even) td{{background:rgba(242,235,219,.35)}}
tbody tr:hover td{{background:rgba(226,205,172,.2)}}

/* ---------- 正文与批注 ---------- */
.body-text{{font-size:17px}}
.main-p{{margin:0 0 3px;text-indent:2em}}
.hd{{font-family:var(--kai);font-size:20px;font-weight:700;letter-spacing:.1em;
  margin:12px 0 10px;color:#332c25}}
.note{{font-size:12.5px;color:var(--ink3);text-indent:0}}
.anno{{font-family:var(--kai);font-size:14.5px;margin:3px 0;padding:2px 0 2px 9px;
  border-left:2px solid transparent;border-radius:0 2px 2px 0}}
.anno.朱批{{color:var(--cinnabar);border-left-color:rgba(158,43,37,.4);
  background:linear-gradient(90deg,rgba(158,43,37,.055),rgba(158,43,37,0) 70%)}}
.anno.墨批{{color:var(--jade);border-left-color:rgba(63,107,94,.35);
  background:linear-gradient(90deg,rgba(63,107,94,.055),rgba(63,107,94,0) 70%)}}
.anno .src{{font-size:11.5px;background:#f0e6d1;border-radius:8px;padding:0 6px;
  margin-right:7px;color:#6b6155}}

/* ---------- 诗笺 ---------- */
.poem{{position:relative;background:linear-gradient(180deg,#fffdf6,#fbf5e8);
  border:1px solid var(--line);border-radius:2px;padding:14px 20px;margin:10px 0;
  font-family:var(--kai);font-size:16.5px;line-height:2.15;letter-spacing:.06em;
  box-shadow:inset 0 0 0 1px rgba(255,255,255,.65), var(--shadow)}}
.poem::before{{content:'✽';position:absolute;right:12px;top:5px;
  color:rgba(158,43,37,.16);font-size:17px}}

/* ---------- 手稿纸（续写） ---------- */
.manuscript{{background:
    repeating-linear-gradient(180deg,transparent,transparent 33px,
      rgba(59,74,107,.06) 33px,rgba(59,74,107,.06) 34px),
    linear-gradient(180deg,#fffdf7,#fcf6ea);
  border:1px solid var(--line);border-radius:2px;padding:24px 28px;margin:14px 0;
  box-shadow:var(--shadow);font-size:17px;line-height:34px}}
.manuscript p{{margin:0 0 4px;text-indent:2em}}

/* ---------- 论辩 ---------- */
.speech{{position:relative;border-left:3px solid var(--indigo);padding:10px 14px 10px 16px;
  margin:12px 0;border-radius:0 3px 3px 0;
  background:linear-gradient(90deg,rgba(255,255,255,.85),rgba(253,248,238,.5));
  box-shadow:var(--shadow);transition:transform .2s ease}}
.speech:hover{{transform:translateX(2px)}}
.speech .who{{font-weight:700;margin-right:8px;font-size:16px}}
pre{{white-space:pre-wrap;font-family:var(--kai);font-size:14.5px;margin:6px 0 0}}

/* ---------- 控件 ---------- */
button{{font-family:inherit;cursor:pointer;background:linear-gradient(180deg,#fffdf8,#f7f0e2);
  border:1px solid var(--line);border-radius:2px;padding:4px 11px;font-size:13.5px;
  color:var(--ink2);letter-spacing:.06em;transition:all .2s}}
button:hover{{border-color:var(--cinnabar);color:var(--cinnabar)}}
button.on{{background:linear-gradient(180deg,var(--cinnabar-l),var(--cinnabar));
  border-color:var(--cinnabar-d);color:#fdf6ec}}
input,select{{font-family:inherit;font-size:14px;padding:4px 9px;border:1px solid var(--line);
  border-radius:2px;background:var(--paper2);color:var(--ink)}}
input:focus,select:focus{{outline:none;border-color:var(--cinnabar)}}

/* ---------- 页脚 ---------- */
footer{{border-top:1px solid var(--line);padding:26px 20px 40px;text-align:center;
  font-size:13px;color:var(--ink3);
  background:linear-gradient(180deg,rgba(247,241,227,0),rgba(236,226,205,.55))}}
footer .seal{{position:static;margin-bottom:10px}}

@keyframes rise{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:none}}}}
main>*{{animation:rise .55s ease both}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important;transition:none!important}}}}
@media (max-width:640px){{
  header h1{{font-size:25px;letter-spacing:.28em;text-indent:.28em}}
  header .seal{{display:none}}
  main{{padding:16px 13px 60px}}
  .hero{{padding:30px 16px 26px}}
  .hero .verse{{font-size:18px}}
  .manuscript{{padding:16px 14px;line-height:32px}}
  table{{font-size:13px}}
}}
"""

NAV = [('index.html', '总览'), ('read.html', '正文·脂批'),
       ('entities.html', '本体实体'), ('poems.html', '诗词'),
       ('debate.html', '推演'), ('continuation.html', '续写'),
       ('graph.html', '图谱')]


def page(title: str, body: str, active: str = '', extra_js: str = '') -> str:
    """页面外框：刊头 + 版心 + 页脚。"""
    nav_html = ''.join(
        f'<a href="{u}" class="{"on" if u == active else ""}">{t}</a>'
        for u, t in NAV)
    return f"""<!DOCTYPE html>
<html lang="zh-Hans"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · 红楼未完</title>
<link rel="stylesheet" href="assets/app.css"></head>
<body>
<header>
  <span class="seal">未完</span>
  <h1>红楼未完</h1>
  <div class="sub">鲥鱼多刺 · 海棠无香 · 《红楼》未完</div>
  <nav>{nav_html}</nav>
</header>
<main>{body}</main>
<footer>
  <span class="seal">脂本</span>
  <div>底本：吴铭恩《红楼梦脂评汇校本》（脂本前八十回 + 各本脂批）。</div>
  <div>推演与续写由多 Agent 生成，仅供研究玩索，非定本。</div>
</footer>
<script>{extra_js}</script></body></html>"""
