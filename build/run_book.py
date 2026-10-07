"""续写整本书：python build/run_book.py [start] [end] [--force] [--no-zhi] [--limit N] [--outline]"""
import sys
import time

sys.path.insert(0, '.')
from honglou import outline as outline_mod  # noqa: E402
from honglou import runner  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith('--')]
flags = {a for a in sys.argv[1:] if a.startswith('--')}

if '--outline' in flags or not outline_mod.load_outline():
    print('== 先做全书骨架推演 ==', flush=True)
    doc = outline_mod.build_outline(debate=True)
    print(doc['resolution'][:400], flush=True)
    for r in doc['chapters']:
        print(f"{r['chapter']:>3} | {r['title']} | {r['brief']}", flush=True)

start = int(args[0]) if args else 81
end = int(args[1]) if len(args) > 1 else 110
limit = None
for a in flags:
    if a.startswith('--limit'):
        limit = int(a.split('=')[-1]) if '=' in a else None

t = time.time()
res = runner.write_book(start, end, do_zhi='--no-zhi' not in flags,
                        force='--force' in flags, limit=limit,
                        deliberate='--no-debate' not in flags)
print('用时 %.1f s，本次新写 %d 回' % (time.time() - t,
                                      sum(1 for r in res if not r.get('skipped'))))
