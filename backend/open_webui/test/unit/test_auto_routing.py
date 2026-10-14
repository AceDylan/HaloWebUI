"""Automatic routing boundaries, durable retries, cancellation and mode adapters."""
import asyncio
import importlib.util
import json
import pathlib
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from open_webui.models import auto_routes as records
from open_webui.routers import auto as api
from open_webui.utils.auto_routing import normalize_selection, selection_messages

USER = SimpleNamespace(id="u1", role="admin")
OTHER = SimpleNamespace(id="u2", role="admin")


def choice(mode, question="请修改项目并测试", **kwargs):
    return normalize_selection({"mode": mode, "reason": "按目标处理", "execution_requested": True},
        question=question, teams_available=True, discussion_available=True, **kwargs)


@pytest.mark.parametrize("question", ["只分析，不实际操作：怎么实现", "不要修改代码，解释方案", "analysis only: plan a deployment", "先出方案"])
def test_analysis_never_starts_team(question):
    assert choice("team", question)["mode"] == "answer"
    assert not choice("team", question)["execution_requested"]


def test_context_constraints_are_respected():
    assert choice("team", "继续", context="用户要求：不要执行")['mode'] == 'answer'


def test_explicit_new_execution_supersedes_earlier_analysis_only():
    assert choice('team', '现在按方案实现并测试', context='之前用户说：只分析，不实际操作')['mode'] == 'team'
    assert choice('team', '继续', context='用户要求：只分析')['mode'] == 'answer'


def test_unavailable_modes_fall_back_and_complex_answers_stay_answers():
    assert normalize_selection({"mode": "discuss"}, question="比较架构")['mode'] == 'answer'
    assert normalize_selection({"mode": "team", "execution_requested": True}, question="修改项目")['mode'] == 'answer'
    assert choice("answer", "证明一个复杂的定理")['mode'] == 'answer'
    with pytest.raises(ValueError):
        choice("shell")


def test_classifier_receives_bounded_context_and_attachment_metadata_as_data():
    messages = selection_messages("比较方案", "只分析", [{"name": "a.pdf", "type": "application/pdf"}], teams_available=True)
    assert json.loads(messages[1]["content"])["context"] == "只分析"
    assert "not merely advice" in messages[0]["content"]


@pytest.fixture
def env(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/routes.db")
    records.AutoRoute.__table__.create(engine)
    session = sessionmaker(bind=engine)
    @contextmanager
    def db():
        with session() as s:
            yield s
    monkeypatch.setattr(records, 'get_db', db)
    monkeypatch.setattr(api.Chats, 'get_chat_by_id_and_user_id', lambda *args: SimpleNamespace(meta={}))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=SimpleNamespace(ENABLE_WEB_SEARCH=True))))
    yield request
    engine.dispose()


async def settle(id):
    job = api._jobs.get(id)
    if job:
        await job


def test_durable_retry_and_ownership(env, monkeypatch):
    calls = []
    async def select(*args):
        return ({'mode': 'answer', 'reason': '普通问题', 'execution_requested': False}, {}, set(), [], {})
    async def dispatch(request, user, row, *args):
        calls.append(row['id'])
        records.AutoRoutes.update(row['id'], user.id, status='dispatched', mode='answer', target_id='answer-1')
    monkeypatch.setattr(api, 'select', select)
    monkeypatch.setattr(api, 'dispatch', dispatch)
    async def run():
        form = api.CreateForm(question='解释报错', client_key='same')
        a, b = await asyncio.gather(api.start(env, USER, form), api.start(env, USER, form))
        assert a['id'] == b['id']
        await settle(a['id'])
        # Survives loss of in-memory job state / reload.
        again = await api.start(env, USER, form)
        assert again['target_id'] == 'answer-1' and len(calls) == 1
        with pytest.raises(HTTPException) as err:
            await api.detail(a['id'], OTHER)
        assert err.value.status_code == 404
        with pytest.raises(HTTPException) as err:
            await api.start(env, USER, form.model_copy(update={'question': 'changed'}))
        assert err.value.status_code == 409
    asyncio.run(run())


def test_cancel_during_selection_prevents_creation(env, monkeypatch):
    from open_webui.routers import answers
    opened = []
    monkeypatch.setattr(answers, '_open', lambda *a, **kw: opened.append(kw))
    async def run():
        gate = asyncio.Event()
        async def select(*args):
            await gate.wait()
            return ({'mode': 'answer', 'reason': '普通问题', 'execution_requested': False}, {}, set(), [], {})
        monkeypatch.setattr(api, 'select', select)
        row = await api.start(env, USER, api.CreateForm(question='解释', client_key='cancel'))
        await api.cancel(row['id'], USER)
        gate.set()
        await settle(row['id'])
        assert records.AutoRoutes.get(row['id'], USER.id)['status'] == 'cancelled'
        assert opened == []
    asyncio.run(run())


def test_attachments_are_owner_checked_before_any_job(env, monkeypatch):
    monkeypatch.setattr(api.Files, 'get_file_by_id', lambda id: SimpleNamespace(user_id='other'))
    async def run():
        with pytest.raises(HTTPException) as err:
            await api.start(env, USER, api.CreateForm(question='读附件', client_key='files', files=['foreign']))
        assert err.value.status_code == 404
        assert not records.AutoRoutes.page(USER.id)
    asyncio.run(run())


def test_answer_adapter_preserves_context_files_and_web_setting(env, monkeypatch):
    from open_webui.routers import answers, discussions
    captured = []
    monkeypatch.setattr(discussions, '_load_files', lambda ids, user: [{'id': id} for id in ids])
    monkeypatch.setattr(answers, '_check_capacity', lambda user: None)
    def open_answer(*args, **kw):
        captured.append(kw)
        kw['on_created']('a1')
    monkeypatch.setattr(answers, '_open', open_answer)
    async def run():
        form = api.CreateForm(question='解释附件', client_key='adapter', files=['f1'], context='背景', research=False)
        row, _ = records.AutoRoutes.create(USER.id, form.client_key, 'hash', {'input': form.model_dump()})
        await api.dispatch(env, USER, row, form, {'mode': 'answer', 'reason': '解释', 'execution_requested': False}, {}, set(), [], {})
        assert captured[0]['context'] == {'text': '背景'}
        assert captured[0]['files'] == [{'id': 'f1'}]
        assert captured[0]['web_allowed'] is False
        assert records.AutoRoutes.get(row['id'], USER.id)['target_id'] == 'a1'
    asyncio.run(run())


def test_discussion_adapter_uses_bounded_budget_not_previous_setup(env, monkeypatch):
    from open_webui.routers import discussions
    from open_webui.utils import discussion_room as room
    captured = []
    monkeypatch.setattr(discussions, '_load_files', lambda *args: [])
    monkeypatch.setattr(discussions, '_check_capacity', lambda user: None)
    monkeypatch.setattr(room, 'normalize_setup', lambda setup, *args: setup)
    def open_discussion(*args, **kw):
        captured.append(kw)
        kw['on_created']('d1')
    monkeypatch.setattr(discussions, '_open', open_discussion)
    async def run():
        form = api.CreateForm(question='比较方案', client_key='discussion', preference='economy', research=False)
        row, _ = records.AutoRoutes.create(USER.id, form.client_key, 'hash', {'input': form.model_dump()})
        await api.dispatch(env, USER, row, form, {'mode': 'discuss', 'reason': '比较', 'execution_requested': False}, {}, set(),
            [{'id': x, 'name': x} for x in ('gpt', 'claude', 'deepseek')], {'model': 'gpt'})
        assert len(captured[0]['setup']['seats']) == 2
        assert captured[0]['setup']['rounds'] == 1
        assert captured[0]['setup']['research'] is False
    asyncio.run(run())


@pytest.mark.parametrize('allow', [False, True])
def test_team_auto_start_requires_explicit_option(env, monkeypatch, allow):
    from open_webui.routers import teams
    from open_webui.utils import agent_teams
    captured = []
    async def target(*args): return object()
    async def start(*args, **kw):
        captured.append(kw)
        kw['on_created']('t1')
    monkeypatch.setattr(agent_teams, 'hermes_target', target)
    monkeypatch.setattr(agent_teams, 'input_files', lambda *args: [])
    monkeypatch.setattr(teams, '_enabled', lambda: None)
    monkeypatch.setattr(teams, '_start', start)
    async def run():
        form = api.CreateForm(question='实现功能并验证', client_key='team', auto_start=allow)
        row, _ = records.AutoRoutes.create(USER.id, form.client_key, 'hash', {'input': form.model_dump()})
        await api.dispatch(env, USER, row, form, {'mode': 'team', 'reason': '执行', 'execution_requested': True}, {}, set(), [], {})
        assert captured[0]['auto_start'] is allow
    asyncio.run(run())


def test_interrupted_request_is_not_automatically_repeated(env):
    form = api.CreateForm(question='实现功能', client_key='old')
    row, _ = records.AutoRoutes.create(USER.id, form.client_key, 'hash', {'input': form.model_dump()})
    with records.get_db() as db:
        db.query(records.AutoRoute).filter_by(id=row['id']).update({'updated_at': 0, 'status': 'dispatching'})
        db.commit()
    assert api._own(row['id'], USER)['status'] == 'interrupted'


def test_migration_roundtrip(tmp_path):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    path = pathlib.Path(__file__).parents[2] / 'migrations/versions/a7d93e5f8102_add_auto_route.py'
    spec = importlib.util.spec_from_file_location('auto_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f'sqlite:///{tmp_path}/migration.db')
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert 'auto_route' in inspect(connection).get_table_names()
        migration.downgrade()
        assert 'auto_route' not in inspect(connection).get_table_names()
    engine.dispose()


@pytest.mark.parametrize('response,expected', [
    ({'mode': 'answer', 'reason': '普通问答'}, 'answer'),
    ({'mode': 'discuss', 'reason': '多视角'}, 'discuss'),
    ({'mode': 'invalid'}, 'answer'),
    ('malformed', 'answer'),
])
def test_classifier_result_and_fallback(env, monkeypatch, response, expected):
    from open_webui.routers import answers
    from open_webui.utils import assistant_library, chat
    models = {m: {'id': m, 'name': m} for m in ('gpt', 'claude')}
    async def models_for(*args): return models, set()
    async def completion(request, payload, user):
        assert payload['metadata']['task'] == 'auto_routing'
        return {'choices': [{'message': {'content': json.dumps(response)}}]}
    monkeypatch.setattr(answers, '_models', models_for)
    monkeypatch.setattr(answers, '_resolve_planner', lambda *a: {'model': 'gpt', 'name': 'GPT'})
    monkeypatch.setattr(assistant_library, 'library', lambda *a: ([], list(models.values())))
    monkeypatch.setattr(chat, 'generate_chat_completion', completion)
    result = asyncio.run(api.select(env, USER, api.CreateForm(question='比较方案', client_key='classify'), []))
    assert result[0]['mode'] == expected


def test_provider_failure_uses_answer_without_exposing_response(env, monkeypatch):
    from open_webui.routers import answers
    from open_webui.utils import assistant_library, chat
    async def models_for(*args): return {'gpt': {'id': 'gpt', 'name': 'gpt'}}, set()
    async def completion(*args): raise RuntimeError('private provider diagnostics')
    monkeypatch.setattr(answers, '_models', models_for)
    monkeypatch.setattr(answers, '_resolve_planner', lambda *a: {'model': 'gpt', 'name': 'GPT'})
    monkeypatch.setattr(assistant_library, 'library', lambda *a: ([], [{'id': 'gpt'}]))
    monkeypatch.setattr(chat, 'generate_chat_completion', completion)
    result = asyncio.run(api.select(env, USER, api.CreateForm(question='解释报错', client_key='fallback'), []))
    assert result[0]['mode'] == 'answer'
    assert 'private' not in result[0]['reason']


def test_chat_auto_dispatch_bypasses_normal_hermes_run(monkeypatch):
    from open_webui.utils import auto_dispatch, hermes_agent
    seen = []
    monkeypatch.setattr(hermes_agent, '_resolve_hermes_connection', lambda *args: ('http://hermes.test/v1', '', 'hermes-agent'))
    async def dispatch(request, form, user, metadata, model):
        seen.append((form['messages'], metadata['chat_id']))
        return {'status': True, 'task_id': 'auto-task'}
    monkeypatch.setattr(auto_dispatch, 'run_auto_dispatch', dispatch)
    form = {'model': 'hermes-agent', 'messages': [{'role': 'user', 'content': '比较方案'}], 'hermes_options': {'dispatch': 'auto'}}
    result = asyncio.run(hermes_agent.run_hermes_agent(None, form, USER,
        {'session_id': 's', 'chat_id': 'c1', 'message_id': 'm1'}, {'id': 'hermes-agent'}, []))
    assert result['task_id'] == 'auto-task'
    assert seen == [(form['messages'], 'c1')]
