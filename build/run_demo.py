"""跑一次真实的多 Agent 推演（可选子集）。"""
import sys
import time

sys.path.insert(0, '.')
from honglou import agents  # noqa: E402

TOPIC = '第八十一回当如何开篇'
QUESTION = ('前八十回止于迎春误嫁中山狼、香菱受苦、宝玉病重。'
            '后文第一桩大事应是什么？开篇当如何落笔？')

keys = sys.argv[1:]
if not keys:
    keys = ['zhiyanzai', 'jihusou', 'caoxueqin', 'zhouruchang',
            'zhangailing', 'datascientist', 'stylometrist', 'kgengineer',
            'moderator']

t = time.time()
rec = agents.deliberate(TOPIC, QUESTION, rounds=1, keys=keys)
print('用时 %.1f s' % (time.time() - t))
print('== 证据 ==')
for e in rec['evidence']:
    print(' -', e['summary'][:160])
print('== 发言 ==')
for c in rec['claims']:
    print(f"\n〔{c['agent']}〕{c['content']}")
print('\n== 裁决 ==\n', rec['resolution'])
print('\n落盘：', rec['file'])
