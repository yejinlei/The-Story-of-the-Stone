"""站点冒烟：起本地服务，检查各页面与数据文件可访问、JSON 可解析。"""
import http.server
import json
import socketserver
import threading
import urllib.request
from functools import partial

ROOT = 'docs'
PORT = 8765

handler = partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
httpd = socketserver.TCPServer(('127.0.0.1', PORT), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

urls = ['index.html', 'read.html', 'entities.html', 'poems.html',
        'debate.html', 'continuation.html', 'graph.html', 'mirror.html',
        'climate.html', 'garden.html', 'clues.html', 'imagery.html',
        'annotators.html',
        'assets/app.css', 'data/poems.json', 'data/entities.json',
        'data/graph.json', 'data/debates.json', 'data/continuations.json',
        'data/mirror.json', 'data/stats.json',
        'data/climate.json', 'data/garden.json', 'data/clues.json',
        'data/imagery.json', 'data/annotators.json',
        'data/chapters/001.json', 'data/chapters/080.json']
ok = True
for u in urls:
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/{u}', timeout=5) as r:
            body = r.read()
            if u.endswith('.json'):
                json.loads(body)
            print(f'200  {u}  {len(body) / 1024:.1f} KB')
    except Exception as e:
        ok = False
        print(f'FAIL {u}  {e}')
httpd.shutdown()
print('SMOKE', 'OK' if ok else 'FAILED')
