"""大模型网关客户端（OpenAI 兼容）。

踩坑备忘（实测）：
1. 该网关模型默认走「推理模式」，token 全被 reasoning 吃掉、content 恒空，
   必须传 extra_body={'thinking': {'type': 'disabled'}}；
   若网关不认该参数，自动降级重试。
2. 关掉思考后 max_tokens 需要开到 4000，否则 JSON 会被截断。
3. 长 system 提示词容易超时，长 schema 一律放 user 侧。
4. 配额紧张：全局限速 + 429/空响应退避重试。
5. 所有响应落盘缓存，便于离线复盘与重复构建。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from . import paths

paths.load_env()

CACHE_DIR = paths.CACHE_DIR / 'llm'
CACHE_DIR.mkdir(parents=True, exist_ok=True)

MIN_INTERVAL = float(os.environ.get('LLM_MIN_INTERVAL', '1.2'))
MAX_RETRY = int(os.environ.get('LLM_MAX_RETRY', '3'))
DEFAULT_MODEL = os.environ.get('VLM_MODEL', 'sensenova-6.8-flash-lite')
_last_call = 0.0
_client = None


def client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(
            api_key=os.environ.get('VLM_API_KEY') or os.environ.get('OPENAI_API_KEY', ''),
            base_url=os.environ.get('VLM_BASE_URL', 'https://token.sensenova.cn/v1'),
        )
    return _client


def _throttle() -> None:
    global _last_call
    gap = time.time() - _last_call
    if gap < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - gap)
    _last_call = time.time()


def chat(messages: list[dict], model: str | None = None, temperature: float = 0.8,
         max_tokens: int = 4000, json_mode: bool = False, tag: str = '') -> str:
    """调用一次对话；返回 content 文本（已去 thinking）。"""
    key = hashlib.sha1(json.dumps(
        [messages, model, temperature, max_tokens, json_mode], ensure_ascii=False,
        sort_keys=True).encode('utf-8')).hexdigest()[:20]
    cf = CACHE_DIR / f'{tag or "chat"}-{key}.json'
    if cf.exists():
        try:
            return json.loads(cf.read_text(encoding='utf-8'))['content']
        except Exception:
            pass

    c = client()
    kwargs = dict(
        model=model or DEFAULT_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if json_mode:
        kwargs['response_format'] = {'type': 'json_object'}
    last_err = None
    for attempt in range(MAX_RETRY):
        _throttle()
        for thinking in (True, False):
            try:
                kw = dict(kwargs)
                if thinking:
                    kw['extra_body'] = {'thinking': {'type': 'disabled'}}
                r = c.chat.completions.create(**kw)
                content = (r.choices[0].message.content or '').strip()
                if content:
                    cf.write_text(json.dumps(
                        {'content': content, 'model': kw['model']}, ensure_ascii=False),
                        encoding='utf-8')
                    return content
                last_err = 'empty content'
            except Exception as e:  # 网关可能不认 extra_body / 限流
                last_err = str(e)[:300]
                if 'extra_body' in last_err or 'thinking' in last_err:
                    continue
                time.sleep(2 + 3 * attempt)
                break
        else:
            continue
        break
    raise RuntimeError(f'LLM 调用失败（{MAX_RETRY} 次重试）：{last_err}')


def chat_json(messages: list[dict], **kw) -> dict | list:
    """要求模型输出 JSON，并容错解析。"""
    kw.pop('json_mode', None)
    tag = kw.pop('tag', 'json')
    raw = chat(messages, json_mode=True, tag=tag, **kw)
    return parse_json(raw)


def parse_json(raw: str):
    raw = raw.strip()
    if raw.startswith('```'):
        raw = raw.strip('`')
        raw = raw.split('\n', 1)[1] if '\n' in raw else raw
        raw = raw.rsplit('```', 1)[0] if '```' in raw else raw
    try:
        return json.loads(raw)
    except Exception:
        pass
    # 截取第一个完整的 JSON 结构
    for opener, closer in (('{', '}'), ('[', ']')):
        i, j = raw.find(opener), raw.rfind(closer)
        if i >= 0 and j > i:
            try:
                return json.loads(raw[i:j + 1])
            except Exception:
                continue
    raise ValueError(f'无法解析为 JSON：{raw[:200]}...')


def count_calls() -> int:
    return len(list(CACHE_DIR.glob('*.json')))


if __name__ == '__main__':
    print(chat([{'role': 'user', 'content': '用七个字形容《红楼梦》。'}], tag='smoke'))
