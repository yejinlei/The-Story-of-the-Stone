"""为每回生成白话文串讲：python build/make_vernacular.py [start] [end] [--force] [--limit=N]"""
import sys
import time

sys.path.insert(0, '.')
from honglou import vernacular  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith('--')]
flags = {a for a in sys.argv[1:] if a.startswith('--')}
limit = next((int(a.split('=')[-1]) for a in flags if a.startswith('--limit')), None)

start = int(args[0]) if args else 1
end = int(args[1]) if len(args) > 1 else 110
t = time.time()
res = vernacular.build(start, end, force='--force' in flags, limit=limit,
                       only_long='--fix-long' in flags)
ok = sum(1 for r in res if r['ok'])
print('用时 %.1f s，白话文 %d 回（新增/重生成 %d 回）' % (time.time() - t, len(res), ok))
