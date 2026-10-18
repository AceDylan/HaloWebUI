#!/usr/bin/env python3
"""Daily Hermes script: inspect native model responses, update only profile metadata.

Install this file as ~/.hermes/scripts/halowebui-model-profiles.py. The host only
handles locking and reports; credentials remain in the HaloWebUI container.
"""
import argparse
import base64
import copy
from contextlib import closing
import datetime as dt
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo

MODELS = {
    'gpt-chat': ('gpt', ['方案统筹', '逻辑复核', '结论整合']),
    'deepseek-chat': ('deepseek', ['推理复核', '实现检查', '方案比较']),
    'claude-chat': ('claude', ['方案评审', '边界检查', '表达整理']),
    'gemini-chat': ('gemini', ['独立分析', '备选方案', '跨角度复核']),
    'grok-chat': ('grok', ['独立评审', '反方质询', '风险检查']),
    'glm-chat': ('glm', ['实现方案', '基础代码检查', '中文说明']),
    'kimi-chat': ('kimi', ['资料归纳', '需求梳理', '交叉复核']),
}
PROMPT = ('只输出 JSON，不要 Markdown，字段 answer、summary、python_result。'
          'answer：1 到 10 的整数和，数值。summary：用中文一句话概括'
          '“项目周五发布。数据库迁移尚未验证，发布前必须完成验证。”。'
          'python_result：Python 表达式 sorted(set([3,1,3,2])) 的结果，JSON 数组。')
LIMITS = ['仅基础文本探测，未验证复杂推理、长上下文、视觉、联网或工具能力',
          '版本由上游自报，别名可能换路由；建议角色不代表能力排名']
STATE = Path('/app/backend/data/.model-profile-refresh')
TAG = '[每日核验] '


def safe_error(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return 'HTTP ' + str(exc.code)
    return type(exc).__name__  # Never include URLs, headers or upstream error bodies.


def request_spec(provider, base, key, cfg, alias, user_agent=''):
    headers = {'Content-Type': 'application/json'}
    if user_agent:
        headers['User-Agent'] = user_agent
    base = base.rstrip('/')
    auth = cfg.get('auth_type')
    if provider == 'anthropic':
        headers['Authorization' if auth == 'bearer' else 'x-api-key'] = ('Bearer ' if auth == 'bearer' else '') + key
        headers['anthropic-version'] = cfg.get('anthropic_version') or '2023-06-01'
        return base + '/messages', headers, {
            'model': alias, 'max_tokens': 2048, 'stream': False,
            'messages': [{'role': 'user', 'content': PROMPT}]}
    if provider == 'gemini':
        headers['Authorization' if auth == 'bearer' else 'x-goog-api-key'] = ('Bearer ' if auth == 'bearer' else '') + key
        return base + '/models/' + urllib.parse.quote(alias, safe='') + ':generateContent', headers, {
            'contents': [{'role': 'user', 'parts': [{'text': PROMPT}]}],
            'generationConfig': {'maxOutputTokens': 2048}}
    if provider != 'openai':
        raise ValueError('unsupported provider')
    headers['Authorization'] = 'Bearer ' + key
    if cfg.get('use_responses_api'):
        return base + '/responses', headers, {
            'model': alias, 'input': [{'role': 'user', 'content': PROMPT}],
            'max_output_tokens': 2048, 'stream': False}
    return base + '/chat/completions', headers, {
        'model': alias, 'messages': [{'role': 'user', 'content': PROMPT}],
        'max_tokens': 2048, 'stream': False}


def observation(data, alias):
    """Only structured protocol identity is evidence; never ask a model who it is."""
    raw = data.get('modelVersion') or data.get('model') or ''
    version = raw if (isinstance(raw, str) and raw != alias and len(raw) <= 120
                      and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/\-]*', raw)
                      and re.search(r'\d', raw)) else None
    chunks = []
    for choice in data.get('choices') or []:
        content = (choice.get('message') or {}).get('content')
        if isinstance(content, str):
            chunks.append(content)
    for block in data.get('content') or []:
        if isinstance(block, dict) and block.get('type') == 'text':
            chunks.append(block.get('text', ''))
    for candidate in data.get('candidates') or []:
        chunks += [p.get('text', '') for p in candidate.get('content', {}).get('parts', []) if not p.get('thought')]
    for item in data.get('output') or []:
        if item.get('type') == 'message':
            chunks += [p.get('text', '') for p in item.get('content', []) if p.get('type') == 'output_text']
    text = ''.join(c for c in chunks if isinstance(c, str)).strip()
    result = {}
    try:
        start = text.index('{')
        result, _ = json.JSONDecoder().raw_decode(text[start:])
        if not isinstance(result, dict):
            result = {}
    except (ValueError, TypeError):
        pass
    passed = []
    if result.get('answer') == 55:
        passed.append('最小整数求和题通过')
    summary = result.get('summary')
    if isinstance(summary, str) and all(x in summary for x in ('周五', '迁移', '验证')):
        passed.append('最小中文摘要要点检查通过')
    if result.get('python_result') == [1, 2, 3]:
        passed.append('基础 Python 表达式结果题通过')
    return {'version': version, 'passed': passed, 'has_text': bool(text),
            'error': None if version and len(passed) == 3 else '版本缺失或基础探测未全部通过'}


def updated_meta(meta, alias, observed, date):
    out = copy.deepcopy(meta)
    old = out.get('discussion_profile') or {}
    profile = copy.deepcopy(old)
    auto = profile.get('automation') or {}
    profile.setdefault('family', MODELS[alias][0])
    profile.setdefault('suggested_roles', MODELS[alias][1])
    profile.setdefault('version', 'unknown')
    old_version = profile['version']
    if observed.get('version'):
        profile.update(version=observed['version'], verified_at=date,
                       version_source='原生 API 响应 model/modelVersion；上游自报，未审计路由配置',
                       capability_source=f'{date} 基础文本探测（求和/中文摘要要点/Python表达式），非能力排名',
                       strengths=observed.get('passed') or (['最小文本响应返回'] if observed.get('has_text') else []))
        if old_version != observed['version']:
            profile.pop('context_window', None)
        profile['limitations'] = list(LIMITS)
    else:
        profile.setdefault('strengths', [])
        profile.setdefault('limitations', list(LIMITS))
    limitations = [v for v in profile['limitations'] if isinstance(v, str) and not v.startswith(TAG)]
    if observed.get('error'):
        limitations.insert(0, TAG + date + '：' + observed['error'] + '；未确认的信息保留上次资料')
    profile['limitations'] = limitations[:6]
    desc = (f"当前上游自报版本 {profile['version']}。建议讨论分工：" +
            '、'.join(profile['suggested_roles']) + '；建议不是性能排名。版本日期、验证范围和最新状态见讨论模型资料。')
    old_generated = (f"当前上游自报版本 {old.get('version')}（{old.get('verified_at')}）。建议讨论分工：" +
                     '、'.join(old.get('suggested_roles', [])) + '；建议不是性能排名。验证范围与限制见讨论模型资料。')
    if not out.get('description') or out['description'] in (auto.get('description'), old_generated):
        out['description'] = desc
        auto['description'] = desc
    auto.update(last_checked_at=date, status='ok' if not observed.get('error') else 'partial',
                last_error=observed.get('error'), managed_by='halowebui-model-profiles-v1')
    profile['automation'] = auto
    out['discussion_profile'] = profile
    return out


def json_call(url, headers, payload=None, timeout=25):
    req = urllib.request.Request(url, headers=headers,
                                 data=json.dumps(payload).encode() if payload is not None else None)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def fields(meta):
    return {k: {'present': k in meta, 'value': meta.get(k)} for k in ('description', 'discussion_profile')}


def atomic_json(path, value):
    tmp = path.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        os.chmod(tmp, 0o600)
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def auth(owner):
    secret = os.environ.get('WEBUI_SECRET_KEY') or os.environ.get('WEBUI_JWT_SECRET_KEY')
    if not secret:
        env = dict(x.split(b'=', 1) for x in Path('/proc/1/environ').read_bytes().split(b'\0') if b'=' in x)
        secret = env.get(b'WEBUI_SECRET_KEY', b'').decode()
    if not secret:
        secret = Path('/app/backend/.webui_secret_key').read_text().strip()
    enc = lambda x: base64.urlsafe_b64encode(x).rstrip(b'=')
    header = enc(b'{"alg":"HS256","typ":"JWT"}')
    payload = enc(json.dumps({'id': owner, 'exp': int(time.time()) + 1800,
                              'iat': int(time.time()), 'jti': str(uuid.uuid4())}).encode())
    unsigned = header + b'.' + payload
    token = unsigned + b'.' + enc(hmac.new(secret.encode(), unsigned, hashlib.sha256).digest())
    return {'Authorization': 'Bearer ' + token.decode(), 'Content-Type': 'application/json'}


def worker(owner, restore=None):
    signal.alarm(900)  # Also bounds the container worker if its docker-exec client disappears.
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(STATE / '.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with closing(sqlite3.connect('file:/app/backend/data/webui.db?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            return worker_locked(owner, restore, db)


def worker_locked(owner, restore, db):
    def row(ref):
        r = db.execute('select * from model where id=? and user_id=?', (ref, owner)).fetchone()
        return dict(r) if r else None
    def save(r, meta):
        body = {k: r[k] for k in ('id', 'base_model_id', 'name', 'is_active')}
        body.update(meta=meta, params=json.loads(r['params'] or '{}'),
                    access_control=json.loads(r['access_control']) if r['access_control'] else None)
        path = '/api/v1/models/model/update?id=' + urllib.parse.quote(r['id'], safe='')
        saved = json_call(root + path, headers, body)
        assert fields(saved['meta']) == fields(meta), 'save mismatch'
        checked = json_call(root + '/api/v1/models/model?id=' + urllib.parse.quote(r['id'], safe=''), headers)
        assert fields(checked['meta']) == fields(meta), 'read-back mismatch'
    root, headers = 'http://127.0.0.1:8080', auth(owner)
    if restore:
        if not re.fullmatch(r'\d{8}T\d{6}-[a-f0-9]{8}\.json', restore):
            raise ValueError('invalid backup filename')
        backup = json.loads((STATE / restore).read_text())
        assert backup['owner'] == owner
        for entry in reversed(backup['entries']):
            r = row(entry['id'])
            assert r is not None
            meta = json.loads(r['meta'] or '{}')
            if fields(meta) == entry['before']:
                continue
            assert fields(meta) == entry['after'], 'profile edited since backup; refusing overwrite'
            for key, value in entry['before'].items():
                if value['present']:
                    meta[key] = value['value']
                else:
                    meta.pop(key, None)
            save(r, meta)
        print('模型资料已按字段快照恢复；其他模型设置保留。')
        return 0
    user = db.execute('select settings from user where id=?', (owner,)).fetchone()
    assert user is not None
    connections = json.loads(user[0] or '{}').get('ui', {}).get('connections', {})
    config = db.execute('select data from config order by id desc limit 1').fetchone()
    ua = json.loads(config[0] or '{}').get('user_agent', {}) if config else {}
    available = json_call(root + '/api/models', headers).get('data', [])
    date = dt.datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    stamp = dt.datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%dT%H%M%S')
    backup_file = STATE / (stamp + '-' + uuid.uuid4().hex[:8] + '.json')
    backup = {'owner': owner, 'entries': []}
    errors = 0
    print('HaloWebUI 模型资料每日核验 · ' + date, flush=True)
    for alias in MODELS:
        matches = [m for m in available if (m.get('model_id') or m.get('id')) == alias
                   and not (m.get('info') or {}).get('base_model_id')
                   and not ((m.get('info') or {}).get('meta') or {}).get('hidden')]
        if len(matches) != 1:
            errors += 1
            print(alias + '：不可用或同名连接不唯一，未修改', flush=True)
            continue
        model = matches[0]
        ref = model.get('selection_id') or model['id']
        identity = model.get('model_ref') or {}
        provider = identity.get('provider')
        original = row(ref)
        if not original or not original['is_active'] or identity.get('source') != 'personal':
            errors += 1
            print(alias + '：无所属的启用记录，未修改', flush=True)
            continue
        before = json.loads(original['meta'] or '{}')
        try:
            con = connections[provider]
            prefix = provider.upper()
            configs = con[prefix + '_API_CONFIGS']
            choices = [(int(i), cfg) for i, cfg in configs.items()
                       if cfg.get('prefix_id') == identity.get('connection_id') and cfg.get('enable', True)]
            assert len(choices) == 1, 'connection missing or disabled'
            index, cfg = choices[0]
            base, key = con[prefix + '_API_BASE_URLS'][index], con[prefix + '_API_KEYS'][index]
            url, h, body = request_spec(provider, base, key, cfg, alias, ua.get('USER_AGENT_' + {'openai': 'GPT', 'anthropic': 'CLAUDE', 'gemini': 'GEMINI'}[provider], ''))
            observed = observation(json_call(url, h, body, timeout=90), alias)
        except Exception as exc:
            observed = {'version': None, 'passed': [], 'error': safe_error(exc)}
        try:
            fresh = row(ref)
            now_connections = json.loads(db.execute('select settings from user where id=?', (owner,)).fetchone()[0] or '{}').get('ui', {}).get('connections', {})
            assert now_connections.get(provider) == connections.get(provider), 'connection changed during probe'
            assert fresh and fresh['is_active'], 'model disabled during probe'
            meta = json.loads(fresh['meta'] or '{}')
            assert fields(meta) == fields(before), 'profile edited during probe'
            new_meta = updated_meta(meta, alias, observed, date)
            backup['entries'].append({'id': ref, 'before': fields(meta), 'after': fields(new_meta)})
            atomic_json(backup_file, backup)  # durable BEFORE the first mutation
            save(fresh, new_meta)
            version = new_meta['discussion_profile']['version']
            if observed.get('error'):
                errors += 1
                print(f"{alias}：{version}；部分失败（{observed['error']}），旧证据未被当作今日验证", flush=True)
            else:
                old = (meta.get('discussion_profile') or {}).get('version', 'unknown')
                print(f'{alias}：{old} → {version}；3 项基础探测通过，保存并读回确认', flush=True)
        except Exception as exc:
            errors += 1
            print(alias + '：保存未完成（' + safe_error(exc) + '），可用字段快照核对', flush=True)
    # These files contain only profile fields; preserve a bounded history across deployments.
    for stale in sorted(STATE.glob('????????T??????-????????.json'))[:-30]:
        stale.unlink()
    print(f'汇总：{len(MODELS) - errors}/{len(MODELS)} 项完整通过；异常 {errors} 项。')
    print('字段回滚快照：' + backup_file.name)
    return 1 if errors else 0


def host(restore=None):
    state = Path.home() / '.hermes/state/halowebui-model-profiles'
    config = json.loads((state / 'config.json').read_text())
    with open(state / '.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return host_locked(config, restore)


def host_locked(config, restore):
    command = ['docker', 'exec', '-i', config['container'], 'python', '-', '--worker', '--owner-id', config['owner_id']]
    if restore:
        command += ['--restore', restore]
    result = subprocess.run(command, input=Path(__file__).read_text(), capture_output=True,
                            text=True, timeout=1000)
    # Worker catches network errors; never forward arbitrary stderr/tracebacks.
    report = result.stdout.strip()
    if report:
        print(report)
    if result.returncode and not report:
        print('模型资料核验失败：容器、认证或运行环境不可用；未输出凭据，请检查服务。')
    return result.returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--owner-id')
    parser.add_argument('--restore')
    args = parser.parse_args()
    try:
        return worker(args.owner_id, args.restore) if args.worker else host(args.restore)
    except Exception as exc:
        print('模型资料核验未完成：' + safe_error(exc) + '；请检查任务环境。')
        return 1


if __name__ == '__main__':
    sys.exit(main())
