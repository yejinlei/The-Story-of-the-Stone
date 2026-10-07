"""探测：语料中的诗词分布形态（临时脚本）。"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from honglou import paths  # noqa: E402

corpus = json.loads(paths.data('corpus.json').read_text(encoding='utf-8'))


def show(kw, before=120, after=520, limit=2):
    n = 0
    for ch in corpus['chapters']:
        for b in ch['blocks']:
            if b['kind'] != '正文':
                continue
            m = re.search(kw, b['text'])
            if not m:
                continue
            print(f"=== [{kw}] 第{ch['no']}回 block{b['id']} p{b['page']}")
            print(b['text'][max(0, m.start() - before): m.start() + after])
            print()
            n += 1
            if n >= limit:
                return


for kw in ['又副册', '红楼梦', '终身误', '题曰', '口占', '咏白海棠', '菊花诗',
           '秋窗风雨夕', '芦雪庵', '联句', '花名', '牙牌令']:
    show(kw, limit=1)
