"""按推演决议续写一回，并做风格校验与脂批批点。"""
import json
import sys
import time

sys.path.insert(0, '.')
from honglou import agents  # noqa: E402

chapter = int(sys.argv[1]) if len(sys.argv) > 1 else 81

res_file = 'data/debates/第八十一回当如何开篇.json'
try:
    resolution = json.loads(open(res_file, encoding='utf-8').read())['resolution']
except Exception:
    resolution = ''

brief = ('第八十一回：承接第八十回「美香菱屈受贪夫棒」，'
         '开篇须接香菱一线；基调当由悲转出一线生机；'
         '不得写黛玉之死、宝玉中举等程高本情节；'
         '须为后文「狱神庙慰宝玉」「卫若兰射圃」留伏线；'
         '回中宜有诗词（代人物作诗须合其诗风画像）。')

t = time.time()
out = agents.write_chapter(chapter, brief, resolution)
print('用时 %.1f s，风格距离 %s' % (time.time() - t, out['distance']))
print('== 指标 ==', json.dumps(out['metrics'], ensure_ascii=False)[:400])
print('\n== 正文 ==\n', out['text'])
print('\n== 文体计量学家 ==\n', out['review'])
print('\n== 脂砚斋批点 ==\n', out['zhi'])
