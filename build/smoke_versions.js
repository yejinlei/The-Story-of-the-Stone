// 在 Node 里把 docs/versions.html 的页面 JS 跑一遍，看有无运行时错误。
const fs = require('fs');
const path = require('path');

const docs = path.resolve(__dirname, '..', 'docs');
const html = fs.readFileSync(path.join(docs, 'versions.html'), 'utf8');
const dataFile = path.join(docs, 'data', 'versions.json');
if (!fs.existsSync(dataFile)) throw new Error('缺 docs/data/versions.json');

const data = JSON.parse(fs.readFileSync(dataFile, 'utf8'));

// 从 HTML 里收集所有 id，用以喂给 JS
const ids = [...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]);
const store = {};
ids.forEach(id => {
  store[id] = {
    id, innerHTML: '', textContent: '', dataset: {}, style: {},
    classList: { add() {}, remove() {}, contains: () => false },
    getAttribute: () => '0 0 1080 320', setAttribute() {},
    querySelectorAll: () => [], appendChild() {}, addEventListener() {},
  };
});

const btns = [];
const mkEl = (extra = {}) => Object.assign({
  dataset: {}, classList: { add() {}, remove() {}, contains: () => false },
  style: {}, setAttribute() {}, getAttribute: () => '0 0 1080 320',
}, extra);

global.document = {
  getElementById: id => store[id] || mkEl(),
  querySelectorAll: sel => {
    if (sel === 'button.met') return [...html.matchAll(/class="met[^"]*" data-f="([^"]+)"/g)]
      .map(m => mkEl({ dataset: { f: m[1] }, id: 'btn-' + m[1] }));
    if (sel === 'button.aped') return [mkEl({ dataset: { e: '全部' } })];
    return [];
  },
  createElement: () => mkEl(),
};
global.window = {};
global.fetch = () => Promise.resolve({ json: () => Promise.resolve(data) });

// 抽出内联 JS
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
if (!scripts.length) throw new Error('页面里没有内联脚本');

let errors = [];
process.on('uncaughtException', e => errors.push(e));

(async () => {
  for (const src of scripts) {
    try {
      await new Function(src)();
    } catch (e) {
      errors.push(e);
    }
  }
  await new Promise(r => setTimeout(r, 50));
  const check = ['vsummary', 'veds', 'vwits', 'vtitletab', 'vlengths', 'vdelta',
    'ventropy', 'vmetrics', 'vaggtab', 'vfront', 'vback', 'vpeopletab',
    'vanno', 'vapptab', 'vvarianttab'];
  let empty = [];
  for (const id of check) {
    const el = store[id];
    if (!el || (!el.innerHTML && !el.textContent)) empty.push(id);
  }
  console.log('errors:', errors.length);
  errors.slice(0, 5).forEach(e => console.log('  ', e.message));
  console.log('empty containers:', empty.length ? empty.join(', ') : '（无）');
  console.log('vsummary len:', (store.vsummary.innerHTML || '').length,
    '| titles rows:', ((store.vtitletab.innerHTML || '').match(/<tr>/g) || []).length);
  console.log('svg paths in vdelta:', ((store.vdelta.innerHTML || '').match(/<path/g) || []).length);
  ['vdeltanote', 'ventropynote', 'vannonote', 'vwordsnote', 'vsummary'].forEach(id => {
    const el = store[id];
    console.log('\n#' + id + ':\n  ' +
      String((el && (el.innerHTML || el.textContent)) || '(空)')
        .replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').slice(0, 900));
  });
  console.log('\n#vfront head:\n  ' +
    String(store.vfront.innerHTML).replace(/<[^>]+>/g, ' ')
      .replace(/\s+/g, ' ').slice(0, 420));
  console.log('\n#vlenlist:\n  ' +
    String(store.vlenlist.innerHTML).replace(/<[^>]+>/g, '|')
      .replace(/\s+/g, ' ').slice(0, 500));
  process.exit(errors.length || empty.length ? 1 : 0);
})();
