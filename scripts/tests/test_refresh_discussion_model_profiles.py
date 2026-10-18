"""Small offline checks; no Docker, credentials or real model calls."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

SOURCE = Path(__file__).resolve().parents[1] / 'refresh-discussion-model-profiles.py'
spec = importlib.util.spec_from_file_location('refresh_profiles', SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
ANSWER = json.dumps({'answer': 55, 'summary': '周五发布前必须完成数据库迁移验证', 'python_result': [1, 2, 3]}, ensure_ascii=False)


class ProfilesTest(unittest.TestCase):
    def test_protocol_requests_honor_connection_mode(self):
        for provider, cfg, suffix, key in [
            ('openai', {}, '/chat/completions', 'Authorization'),
            ('openai', {'use_responses_api': True}, '/responses', 'Authorization'),
            ('anthropic', {}, '/messages', 'x-api-key'),
            ('gemini', {}, '/models/gemini-chat:generateContent', 'x-goog-api-key'),
        ]:
            with self.subTest(provider=provider, cfg=cfg):
                url, headers, body = m.request_spec(provider, 'https://example.invalid/v1', 'test-only', cfg, 'gemini-chat')
                self.assertTrue(url.endswith(suffix))
                self.assertIn(key, headers)
                self.assertNotIn('test-only', url)
                self.assertNotIn('fallback', str(body))

    def test_native_response_versions_and_capability_checks(self):
        responses = [
            {'model': 'gpt-5', 'choices': [{'message': {'content': ANSWER}}]},
            {'model': 'gpt-5', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': ANSWER}]}]},
            {'model': 'claude-4', 'content': [{'type': 'text', 'text': ANSWER}]},
            {'modelVersion': 'gemini-3', 'candidates': [{'content': {'parts': [{'text': ANSWER}]}}]},
        ]
        for data in responses:
            result = m.observation(data, 'chat-alias')
            self.assertIsNone(result['error'])
            self.assertEqual(len(result['passed']), 3)

    def test_self_report_text_and_alias_are_not_version_evidence(self):
        data = {'model': 'gpt-chat', 'choices': [{'message': {'content': 'I am gpt-5'}}]}
        self.assertIsNone(m.observation(data, 'gpt-chat')['version'])

    def test_failure_retains_verified_evidence_and_manual_description(self):
        meta = {'description': '我自己的说明', 'fallback_model_id': 'other',
                'discussion_profile': {'version': 'gpt-5', 'verified_at': '2026-01-01', 'strengths': ['已有证据']}}
        out = m.updated_meta(meta, 'gpt-chat', {'error': 'TimeoutError'}, '2026-10-18')
        p = out['discussion_profile']
        self.assertEqual(p['verified_at'], '2026-01-01')
        self.assertEqual(p['strengths'], ['已有证据'])
        self.assertEqual(out['description'], '我自己的说明')
        self.assertEqual(out['fallback_model_id'], 'other')
        self.assertEqual(p['automation']['status'], 'partial')

    def test_version_change_drops_old_context_claims_and_updates_owned_description(self):
        observed = {'version': 'gpt-5', 'passed': ['测试通过'], 'error': None}
        first = m.updated_meta({}, 'gpt-chat', observed, '2026-10-18')
        first['discussion_profile']['context_window'] = 999999
        second = m.updated_meta(first, 'gpt-chat', {**observed, 'version': 'gpt-6'}, '2026-10-19')
        self.assertIn('gpt-6', second['description'])
        self.assertNotIn('context_window', second['discussion_profile'])
        self.assertNotIn('gpt-6', first['description'])

    def test_worker_continues_after_failure_preserves_settings_and_can_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dbfile = root / 'test.db'
            real_connect = sqlite3.connect
            db = real_connect(dbfile)
            db.executescript('''CREATE TABLE user(id TEXT,settings TEXT);
                CREATE TABLE model(id TEXT,user_id TEXT,base_model_id TEXT,name TEXT,is_active INTEGER,
                                   params TEXT,access_control TEXT,meta TEXT);
                CREATE TABLE config(id INTEGER,data TEXT);''')
            conn = {'OPENAI_API_CONFIGS': {'0': {'prefix_id': 'test', 'model_ids': list(m.MODELS)}},
                    'OPENAI_API_BASE_URLS': ['https://example.invalid/v1'], 'OPENAI_API_KEYS': ['fixture-only']}
            db.execute('insert into user values(?,?)', ('owner', json.dumps({'ui': {'connections': {'openai': conn}}})))
            available = []
            for alias in m.MODELS:
                ref = 'ref-' + alias
                meta = {'fallback_model_id': 'preserve-me', 'discussion_profile': {'version': 'old-1', 'verified_at': '2026-01-01'}}
                db.execute('insert into model values(?,?,?,?,?,?,?,?)', (ref, 'owner', None, alias, 1, '{}', None, json.dumps(meta)))
                available.append({'id': ref, 'model_id': alias, 'selection_id': ref,
                                  'model_ref': {'provider': 'openai', 'source': 'personal', 'connection_id': 'test'}})
            db.commit()
            probed = []
            def api(url, headers, payload=None, timeout=25):
                if url.startswith('https://'):
                    alias = payload['model']
                    probed.append(alias)
                    if alias == 'gpt-chat':
                        raise TimeoutError('must not print credentials or URL')
                    return {'model': alias + '-2', 'choices': [{'message': {'content': ANSWER}}]}
                if url.endswith('/api/models'):
                    return {'data': available}
                ref = parse_qs(urlsplit(url).query)['id'][0]
                if payload:
                    self.assertTrue(list((root / 'state').glob('*.json')), 'backup must precede mutation')
                    self.assertEqual(payload['meta']['fallback_model_id'], 'preserve-me')
                    self.assertEqual(payload['is_active'], 1)
                    db.execute('update model set meta=? where id=?', (json.dumps(payload['meta']), ref))
                    db.commit()
                return {'meta': json.loads(db.execute('select meta from model where id=?', (ref,)).fetchone()[0])}
            with patch.object(m, 'STATE', root / 'state'), patch.object(m, 'auth', return_value={}), \
                 patch.object(m.signal, 'alarm'), patch.object(m, 'json_call', side_effect=api), \
                 patch.object(m.sqlite3, 'connect', side_effect=lambda *a, **kw: real_connect(dbfile)):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(m.worker('owner'), 1)
                self.assertEqual(probed, list(m.MODELS))
                self.assertIn('6/7', output.getvalue())
                self.assertNotIn('credentials', output.getvalue())
                failed = json.loads(db.execute("select meta from model where name='gpt-chat'").fetchone()[0])
                self.assertEqual(failed['discussion_profile']['version'], 'old-1')
                backup = next((root / 'state').glob('*.json'))
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(m.worker('owner', backup.name), 0)
                self.assertTrue(all(json.loads(r[0])['discussion_profile']['version'] == 'old-1'
                                    for r in db.execute('select meta from model')))
            db.close()


if __name__ == '__main__':
    unittest.main()
