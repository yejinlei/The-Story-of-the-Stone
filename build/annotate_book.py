"""为续写的各回补脂批（夹批 + 回末总评）。

用法：python build/annotate_book.py [start] [end] [--force] [--limit=N]
"""
import sys
import time

sys.path.insert(0, '.')
from honglou import runner  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith('--')]
flags = {a for a in sys.argv[1:] if a.startswith('--')}
limit = next((int(a.split('=')[-1]) for a in flags if a.startswith('--limit')),
             None)

start = int(args[0]) if args else 81
end = int(args[1]) if len(args) > 1 else 110
t = time.time()
res = runner.annotate_all(start, end, force='--force' in flags, limit=limit)
print('用时 %.1f s，批点 %d 回' % (time.time() - t, len(res)))
