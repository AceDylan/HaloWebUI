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
    monkeypatch.setattr(api.Chats, 'get_chat_by_id_and_user_id', lambda *args: SimpleNamespace(meta={}, title="New Chat"))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=SimpleNamespace(ENABLE_WEB_SEARCH=True))))
    yield request
    engine.dispose()


async def settle(id):
    job = api._jobs.get(id)
    if job:
        await job


def test_durable_retry_and_ownership(env, monkeypatch):
    calls = []
    async def select(*args, **kw):
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
        async def select(*args, **kw):
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


def test_a_team_from_telegram_or_qq_carries_that_chat(env, monkeypatch):
    """/auto from Telegram / QQ: the team it starts records the chat, so its plan goes back there."""
    from open_webui.routers import teams
    from open_webui.utils import agent_teams
    captured = []
    async def target(*args): return object()
    async def start(*args, **kw):
        captured.append(kw)
        kw['on_created']('t1')
    async def select(*args, **kw):
        return ({'mode': 'team', 'reason': '执行', 'execution_requested': True}, {}, set(), [], {})
    monkeypatch.setattr(agent_teams, 'hermes_target', target)
    monkeypatch.setattr(agent_teams, 'input_files', lambda *args: [])
    monkeypatch.setattr(teams, '_enabled', lambda: None)
    monkeypatch.setattr(teams, '_start', start)
    monkeypatch.setattr(api, 'select', select)
    remote = {'platform': 'qqbot', 'chat_id': 'Q1', 'user_id': 'Q1'}
    async def run():
        row = await api.start(env, USER, api.CreateForm(question='做个工具', client_key='remote:q'), remote=remote)
        await settle(row['id'])
        assert captured[-1]['origin'] == remote
        # the browser's own 分流 starts a team of no outside chat
        row = await api.start(env, USER, api.CreateForm(question='做个工具', client_key='web'))
        await settle(row['id'])
        assert captured[-1]['origin'] is None
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
    async def dispatch(request, form, user, metadata, model_id, **kw):
        seen.append((form['messages'], metadata['chat_id']))
        return {'status': True, 'task_id': 'auto-task'}
    monkeypatch.setattr(auto_dispatch, 'run_auto_dispatch', dispatch)
    form = {'model': 'hermes-agent', 'messages': [{'role': 'user', 'content': '比较方案'}], 'hermes_options': {'dispatch': 'auto'}}
    result = asyncio.run(hermes_agent.run_hermes_agent(None, form, USER,
        {'session_id': 's', 'chat_id': 'c1', 'message_id': 'm1'}, {'id': 'hermes-agent'}, []))
    assert result['task_id'] == 'auto-task'
    assert seen == [(form['messages'], 'c1')]


@pytest.mark.parametrize("raw", [None, [], "team", 12, True, {"mode": []}, {"mode": {}}])
def test_non_object_decisions_are_rejected(raw):
    with pytest.raises(ValueError):
        normalize_selection(raw, question="实现功能")


def test_preferred_router_uses_accessible_gpt_chat_with_scoped_identity():
    from open_webui.utils.auto_routing import preferred_routing_model
    bases = [{"id": "claude", "name": "Claude"}, {"id": "scoped", "name": "自定义名称"}]
    models = {"scoped": {"model_id": "gpt-chat"}, "private": {"id": "gpt-chat"}}
    assert preferred_routing_model(bases, models) == "scoped"
    assert preferred_routing_model(bases[:1], models) is None


def test_cursor_pages_are_bounded_stable_and_search_is_literal(env):
    for i in range(65):
        row, _ = records.AutoRoutes.create(USER.id, str(i), str(i),
            {"input": {"question": f"问题 {i} 100%"}})
        records.AutoRoutes.update(row["id"], USER.id, status="dispatched", mode="answer")
    records.AutoRoutes.create(OTHER.id, "other", "other", {"input": {"question": "other"}})
    first = records.AutoRoutes.page(USER.id, limit=30)
    cursor = (first[-1]["created_at"], first[-1]["id"])
    records.AutoRoutes.create(USER.id, "new", "new", {"input": {"question": "new"}})
    second = records.AutoRoutes.page(USER.id, limit=30, before=cursor)
    assert len(first) == len(second) == 30
    assert not {r["id"] for r in first} & {r["id"] for r in second}
    assert len(records.AutoRoutes.page(USER.id, limit=100, query="100%", mode="answer")) == 65
    assert records.AutoRoutes.page(USER.id, query="100_") == []
    assert records.AutoRoutes.page(USER.id, mode="team") == []


def test_history_returns_cursor_and_bounded_question(env):
    for i in range(3):
        records.AutoRoutes.create(USER.id, str(i), str(i), {"input": {"question": "长" * 8000}})
    first = asyncio.run(api.history(offset=0, limit=2, before=None, q="", mode=None, user=USER))
    assert len(first["items"]) == 2 and first["more"] and first["next"]
    assert all(len(r["question"]) == 300 for r in first["items"])
    second = asyncio.run(api.history(offset=0, limit=2, before=first["next"], q="", mode=None, user=USER))
    assert len(second["items"]) == 1 and second["next"] is None
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.history(offset=0, limit=2, before="bad", q="", mode=None, user=USER))
    assert error.value.status_code == 400


def test_opening_legacy_auto_card_repairs_metadata_once(env, monkeypatch):
    from open_webui.utils import mode_chats
    chat = SimpleNamespace(id="origin", title="New Chat", meta={}, chat={"models": ["hermes-agent"], "history": {"messages": {}}})
    monkeypatch.setattr(api.Chats, "get_chat_by_id_and_user_id", lambda *args: chat)
    monkeypatch.setattr(api.Chats, "set_chat_meta_value_by_id", lambda id, key, value: chat.meta.update({key: value}))
    jobs = []
    monkeypatch.setattr(mode_chats, "schedule_chat_metadata", lambda *args, **kwargs: jobs.append((args, kwargs)))
    row, _ = records.AutoRoutes.create(USER.id, "legacy", "hash", {"input": {"question": "比较数据库"}, "origin": {"chatId": "origin", "messageId": "reply"}})
    records.AutoRoutes.update(row["id"], USER.id, mode="discuss", status="dispatched")
    asyncio.run(api.detail(row["id"], USER, env))
    asyncio.run(api.detail(row["id"], USER, env))
    assert chat.meta["auto_route"] == {"id": row["id"], "mode": "discuss"}
    assert len(jobs) == 1 and jobs[0][1]["message_id"] == "reply"


@pytest.mark.parametrize("question", [
    "请修复这个函数并运行测试，不要部署",
    "修复登录 bug，不要修改数据库",
    "先分析原因再修复并提交",
    "don't deploy, just fix the test",
    "不改变接口的前提下重构这个模块",
])
def test_forbidding_one_action_is_a_constraint_not_analysis_only(question):
    decision = choice("team", question)
    assert decision["mode"] == "team" and decision["execution_requested"]


def test_only_the_users_own_words_in_the_background_constrain():
    assert choice("team", "继续", context="用户：帮我修复登录\n\nHermes：我先分析一下原因")["mode"] == "team"
    assert choice("team", "继续", context="用户：只分析，不要动手\n\nHermes：好的")["mode"] == "answer"


def test_failed_request_is_routed_again_from_its_card(env, monkeypatch):
    posted = []
    monkeypatch.setattr(api.Chats, "upsert_message_to_chat_by_id_and_message_id",
                        lambda chat_id, message_id, fields, **kw: posted.append((chat_id, message_id, fields, kw)))
    async def failing(*args, **kw):
        raise HTTPException(503, "暂时不可用")
    async def ok(request, user, form, file_info, **kw):
        return ({"mode": form.mode if form.mode != "auto" else "answer", "reason": "重试",
                 "execution_requested": False}, {}, set(), [], {})
    async def dispatch(request, user, row, *args):
        records.AutoRoutes.update(row["id"], user.id, status="dispatched", target_id="answer-2")
    monkeypatch.setattr(api, "dispatch", dispatch)
    async def run():
        monkeypatch.setattr(api, "select", failing)
        origin = {"chatId": "chat-1", "messageId": "reply-1"}
        first = await api.start(env, USER, api.CreateForm(question="解释报错", client_key="c1"), origin=origin)
        await settle(first["id"])
        assert api._own(first["id"], USER)["status"] == "error"
        with pytest.raises(HTTPException) as err:
            await api.retry(env, first["id"], api.RetryForm(), OTHER)
        assert err.value.status_code == 404
        monkeypatch.setattr(api, "select", ok)
        again = await api.retry(env, first["id"], api.RetryForm(mode="discuss"), USER)
        assert again["id"] != first["id"]
        await settle(again["id"])
        stored = records.AutoRoutes.get(again["id"], USER.id)
        assert stored["data"]["origin"] == origin and stored["data"]["input"]["mode"] == "discuss"
        # the card follows the new receipt without moving the chat's current message
        assert posted[0] == ("chat-1", "reply-1", {"auto_route": {"id": again["id"]}}, {"set_current": False})
        # a second press joins the retry instead of routing a third time
        assert (await api.retry(env, first["id"], api.RetryForm(), USER))["id"] == again["id"]
        with pytest.raises(HTTPException) as err:
            await api.retry(env, again["id"], api.RetryForm(), USER)
        assert err.value.status_code == 409
    asyncio.run(run())


def test_the_chat_reply_says_what_was_chosen(monkeypatch):
    posted = []
    monkeypatch.setattr(api.Chats, "upsert_message_to_chat_by_id_and_message_id",
                        lambda chat_id, message_id, fields, **kw: posted.append((chat_id, message_id, fields, kw)))
    origin = {"chatId": "chat-1", "messageId": "reply-1"}
    api._settle_reply(origin, "team", "需要改仓库并运行测试。")
    assert posted == [("chat-1", "reply-1", {"content": "🔀 自动分流交给了协作台：需要改仓库并运行测试。进度在下面的卡片里，结果会发回这个对话。"},
                       {"set_current": False})]
    # an older reply is corrected only while it still says the pending text
    chat = lambda content: SimpleNamespace(chat={"history": {"messages": {"reply-1": {"content": content}}}})
    monkeypatch.setattr(api.Chats, "get_chat_by_id", lambda id: chat("用户改过的内容"))
    api._settle_reply(origin, "answer", "", only_if=api._PENDING_REPLY)
    assert len(posted) == 1
    monkeypatch.setattr(api.Chats, "get_chat_by_id", lambda id: chat(api._PENDING_REPLY))
    api._settle_reply(origin, "answer", "", only_if=api._PENDING_REPLY)
    assert posted[1][2] == {"content": "🔀 自动分流交给了精答。进度在下面的卡片里，结果会发回这个对话。"}


# --- 需要工具 ≠ 允许修改；正常选择 ≠ 临时改用；查不了就报阻塞 ---------------------------------


def tooled(mode, question, execution=False, **kwargs):
    kwargs.setdefault("teams_available", True)
    kwargs.setdefault("discussion_available", True)
    return normalize_selection({"mode": mode, "reason": "按目标处理", "needs_tools": True,
        "execution_requested": execution}, question=question, **kwargs)


@pytest.mark.parametrize("question", ["检查仓库最近几次提交，只分析别改", "只看看最近 7 次提交改了什么", "核对一下线上配置，不要修改任何文件"])
def test_checking_real_files_is_a_read_only_team_not_a_text_answer(question):
    decision = tooled("team", question, execution=True)
    assert decision["mode"] == "team" and decision["read_only"] and not decision["execution_requested"]


def test_execution_team_is_not_read_only():
    decision = tooled("team", "按方案实现并跑测试", execution=True)
    assert decision["mode"] == "team" and decision["execution_requested"] and not decision.get("read_only")


def test_advice_without_tools_or_execution_is_a_normal_answer_choice():
    decision = normalize_selection({"mode": "team", "needs_tools": False, "execution_requested": False},
        question="CI 该怎么设计", teams_available=True, discussion_available=True)
    assert decision["mode"] == "answer" and not decision.get("degraded")


def test_needing_real_files_without_team_is_blocked_not_answered_from_memory():
    decision = tooled("team", "检查仓库近几次提交", teams_available=False)
    assert decision["blocked"] and decision["mode"] is None and "协作台现在不可用" in decision["reason"]


def test_unavailable_modes_are_marked_as_stand_ins():
    team = normalize_selection({"mode": "team", "execution_requested": True}, question="写个脚本算日期差",
        teams_available=False, discussion_available=True)
    assert team["mode"] == "answer" and team["degraded"] == "team" and "临时" in team["reason"]
    discuss = normalize_selection({"mode": "discuss"}, question="选哪个", teams_available=True, discussion_available=False)
    assert discuss["mode"] == "answer" and discuss["degraded"] == "discuss" and "讨论不可用" in discuss["reason"]
    assert not normalize_selection({"mode": "discuss"}, question="选哪个", discussion_available=True).get("degraded")


def test_follow_ups_are_judged_by_their_own_intent():
    background = "用户：介绍一下 PostgreSQL 和 MySQL\n\nHermes：🔀 自动分流交给了精答"
    # the classifier picks discuss for the follow-up; earlier turns do not lock the mode
    assert normalize_selection({"mode": "discuss"}, question="结合我的业务到底选哪个", context=background,
        discussion_available=True)["mode"] == "discuss"
    checked = background + "\n\n用户：检查仓库最近的提交，只分析别改"
    # 「继续」 grants nothing: still read-only; an explicit request to implement does
    assert tooled("team", "继续", execution=True, context=checked)["read_only"]
    implemented = tooled("team", "现在按方案实现", execution=True, context=checked)
    assert implemented["execution_requested"] and not implemented.get("read_only")


def test_both_deciders_get_the_boundary_examples_and_follow_up_rule():
    from open_webui.utils.auto_routing import EXAMPLES, decision_request, selection_from_answers
    prompt = selection_messages("q", "", [], teams_available=True)[0]["content"]
    assert EXAMPLES in prompt and "needs_tools" in prompt and "follow-up" in prompt
    _, questions = decision_request("q", "", [], teams_available=False, discussion_available=True)
    assert EXAMPLES in questions["mode"]["instructions"] and "tools" in questions and "execution" not in questions
    raw = selection_from_answers({"mode": {"choice": "answer"}, "tools": {"noul": 0.9}}, "", "jev")
    assert raw["needs_tools"] is True and raw["execution_requested"] is False


def test_classifier_failure_is_marked_as_a_stand_in(env, monkeypatch):
    from open_webui.routers import answers
    from open_webui.utils import assistant_library, chat
    async def models_for(*args): return {'gpt': {'id': 'gpt', 'name': 'gpt'}}, set()
    async def completion(*args): raise RuntimeError('down')
    monkeypatch.setattr(answers, '_models', models_for)
    monkeypatch.setattr(answers, '_resolve_planner', lambda *a: {'model': 'gpt', 'name': 'GPT'})
    monkeypatch.setattr(assistant_library, 'library', lambda *a: ([], [{'id': 'gpt'}]))
    monkeypatch.setattr(chat, 'generate_chat_completion', completion)
    decision = asyncio.run(api.select(env, USER, api.CreateForm(question='解释报错', client_key='down'), []))[0]
    assert decision['mode'] == 'answer' and decision['degraded'] == 'auto'


def test_blocked_request_is_reported_on_the_receipt_and_in_the_chat(env, monkeypatch):
    posted = []
    monkeypatch.setattr(api.Chats, "upsert_message_to_chat_by_id_and_message_id",
                        lambda chat_id, message_id, fields, **kw: posted.append((chat_id, message_id, fields, kw)))
    async def select(*args, **kw):
        raise api.RouteBlocked("需要查看真实的仓库或文件，但协作台现在不可用")
    monkeypatch.setattr(api, "select", select)
    async def run():
        row = await api.start(env, USER, api.CreateForm(question="检查最近提交", client_key="blocked"),
                              origin={"chatId": "chat-1", "messageId": "reply-1"})
        await settle(row["id"])
        stored = api.public(api._own(row["id"], USER), USER)
        assert stored["status"] == "error" and stored["blocked"] and stored["mode"] is None
        assert posted[0][2]["content"].startswith("⛔ 自动分流没有派发：需要查看真实的仓库")
        assert posted[0][3] == {"set_current": False}
    asyncio.run(run())


def test_read_only_team_carries_the_constraint_and_says_so_in_the_chat(env, monkeypatch):
    from open_webui.routers import teams
    from open_webui.utils import agent_teams
    captured = []
    async def target(*args): return object()
    async def start(request, user, goal, *args, **kw):
        captured.append((goal, kw))
        kw['on_created']('t1')
    monkeypatch.setattr(agent_teams, 'hermes_target', target)
    monkeypatch.setattr(agent_teams, 'input_files', lambda *args: [])
    monkeypatch.setattr(teams, '_enabled', lambda: None)
    monkeypatch.setattr(teams, '_start', start)
    async def run():
        form = api.CreateForm(question='检查最近 7 次提交，只分析', client_key='ro', auto_start=True)
        row, _ = records.AutoRoutes.create(USER.id, form.client_key, 'hash', {'input': form.model_dump()})
        await api.dispatch(env, USER, row, form, {'mode': 'team', 'reason': '要看仓库', 'execution_requested': False,
            'read_only': True}, {}, set(), [], {})
        goal, kw = captured[0]
        assert '只读任务' in goal and '不要创建、修改或删除' in goal
        assert kw['auto_start'] is True
        assert api.public(api._own(row['id'], USER), USER)['read_only'] is True
    asyncio.run(run())
    assert api._chosen_reply("team", "要看仓库", read_only=True).startswith("🔀 自动分流交给了协作台（只读）：要看仓库")
    assert api._chosen_reply("answer", "讨论不可用", degraded="discuss").startswith("🔀 自动分流临时改用精答：讨论不可用")


def test_real_files_go_to_a_read_only_team_unless_the_mode_is_named():
    raw = {"mode": "answer", "reason": "咨询", "needs_tools": True, "execution_requested": False}
    out = normalize_selection(raw, question="当前 halowebui 自动分流有优化空间吗", teams_available=True, discussion_available=True)
    assert out["mode"] == "team" and out["read_only"] is True and "精答看不到" in out["reason"]
    out = normalize_selection({**raw, "mode": "discuss"}, question="看看仓库里的分流代码怎么改", teams_available=True,
                              discussion_available=True)
    assert out["mode"] == "team" and out["read_only"] is True
    # the user named the mode, or no 协作 to send it to: it stays
    assert normalize_selection(raw, question="用精答说说 halowebui 的分流", teams_available=True,
                               discussion_available=True)["mode"] == "answer"
    assert normalize_selection({**raw, "mode": "discuss"}, question="讨论下仓库的分流架构", teams_available=True,
                               discussion_available=True)["mode"] == "discuss"
    assert normalize_selection(raw, question="分流有优化空间吗", teams_available=False,
                               discussion_available=True)["mode"] == "answer"
    # general knowledge stays with 精答
    assert normalize_selection({**raw, "needs_tools": False}, question="Redis 和 Memcached 区别", teams_available=True,
                               discussion_available=True)["mode"] == "answer"


def test_an_unsure_decision_model_leaves_the_choice_to_the_classifier():
    from open_webui.utils.auto_routing import selection_from_answers
    from open_webui.utils.decision_model import DecisionError, _brief

    with pytest.raises(DecisionError) as unsure:
        selection_from_answers({"mode": {"choice": "answer", "confidence": 0.18}, "tools": {"noul": 0.9}}, "", "jev-chat")
    assert _brief(unsure.value) == "选精答的把握只有 18%，改由分类模型判断"
    sure = selection_from_answers({"mode": {"choice": "answer", "confidence": 0.8}, "tools": {"noul": 0.1}}, "", "jev-chat")
    assert sure["mode"] == "answer" and "把握 80%" in sure["reason"]


# --- 交给 Hermes：日常与本机小事；精答/讨论看不到的先给 Hermes；Hermes 不在时有替补 -----------------


def hermes(raw, question="看下 nginx 最近有没有报错", **kwargs):
    kwargs.setdefault("teams_available", True)
    kwargs.setdefault("discussion_available", True)
    kwargs.setdefault("hermes_available", True)
    return normalize_selection({"reason": "按目标处理", **raw}, question=question, **kwargs)


def test_hermes_takes_quick_work_and_what_answer_or_discussion_cannot_see():
    assert hermes({"mode": "hermes", "needs_tools": True})["mode"] == "hermes"
    looked = hermes({"mode": "answer", "needs_tools": True}, question="halowebui 容器起来没有")
    assert looked["mode"] == "hermes" and "Hermes 直接查看" in looked["reason"] and not looked.get("degraded")
    assert hermes({"mode": "discuss", "needs_tools": True}, question="看看仓库里的分流代码")["mode"] == "hermes"
    # big work still goes to the team, read-only when only asked to look
    team = hermes({"mode": "team", "needs_tools": True}, question="全面审查这个仓库的安全问题，只分析别改")
    assert team["mode"] == "team" and team["read_only"]
    assert hermes({"mode": "team", "execution_requested": True}, question="加导出按钮并提交")["mode"] == "team"
    # without 协作 a team's work stands in with Hermes, which can still look and act
    stand_in = hermes({"mode": "team", "execution_requested": True}, question="加导出按钮", teams_available=False)
    assert stand_in["mode"] == "hermes" and stand_in["degraded"] == "team"


def test_without_hermes_its_choice_has_a_stand_in():
    looked = hermes({"mode": "hermes", "needs_tools": True}, hermes_available=False)
    assert looked["mode"] == "team" and looked["read_only"] and looked["degraded"] == "hermes"
    chat = hermes({"mode": "hermes"}, question="讲个笑话", hermes_available=False)
    assert chat["mode"] == "answer" and chat["degraded"] == "hermes"
    # the old rules are unchanged where Hermes cannot take it
    assert hermes({"mode": "answer", "needs_tools": True}, hermes_available=False)["mode"] == "team"


def test_the_deciders_offer_hermes_only_where_it_can_take_it():
    from open_webui.utils.auto_routing import HERMES_EXAMPLES, HERMES_RULE, NO_HERMES_EXAMPLES, decision_request
    with_hermes = selection_messages("q", "", [], teams_available=True, hermes_available=True)[0]["content"]
    without = selection_messages("q", "", [], teams_available=True)[0]["content"]
    assert "mode (hermes|answer|discuss|team)" in with_hermes and HERMES_RULE in with_hermes
    assert HERMES_EXAMPLES in with_hermes and NO_HERMES_EXAMPLES not in with_hermes
    assert "mode (answer|discuss|team)" in without and HERMES_RULE not in without
    assert "hermes" not in without and NO_HERMES_EXAMPLES in without
    _, questions = decision_request("q", "", [], teams_available=False, discussion_available=True, hermes_available=True)
    assert "hermes" in questions["mode"]["criteria"] and "execution" in questions


def _select_env(monkeypatch, models, completion):
    from open_webui.routers import answers
    from open_webui.utils import assistant_library, chat
    async def models_for(*args): return models, set()
    monkeypatch.setattr(answers, '_models', models_for)
    monkeypatch.setattr(answers, '_resolve_planner', lambda *a: {'model': 'gpt', 'name': 'GPT'})
    monkeypatch.setattr(assistant_library, 'library', lambda *a: ([], [{'id': 'gpt'}]))
    monkeypatch.setattr(chat, 'generate_chat_completion', completion)


HERMES_MODELS = {'gpt': {'id': 'gpt', 'name': 'gpt'},
                 'hermes-agent': {'id': 'hermes-agent', 'name': 'Hermes', 'owned_by': 'hermes'}}


def test_no_choice_defaults_to_hermes_where_it_answers_and_never_from_telegram(env, monkeypatch):
    from open_webui.utils import hermes_agent
    monkeypatch.setattr(hermes_agent, 'is_hermes_agent_model', lambda m: m.get('id') == 'hermes-agent')
    async def down(*args): raise RuntimeError('down')
    _select_env(monkeypatch, HERMES_MODELS, down)
    decision = asyncio.run(api.select(env, USER, api.CreateForm(question='在吗', client_key='h1'), []))[0]
    assert decision['mode'] == 'hermes' and decision['degraded'] == 'auto'
    decision = asyncio.run(api.select(env, USER, api.CreateForm(question='在吗', client_key='h2'), [], remote=True))[0]
    assert decision['mode'] == 'answer'
    # chosen by hand: Hermes, or a clear error when there is none
    picked = asyncio.run(api.select(env, USER, api.CreateForm(question='在吗', client_key='h3', mode='hermes'), []))[0]
    assert picked['mode'] == 'hermes'
    with pytest.raises(HTTPException) as err:
        asyncio.run(api.select(env, USER, api.CreateForm(question='在吗', client_key='h4', mode='hermes'), [], remote=True))
    assert "没有可用的 Hermes" in err.value.detail


def test_hermes_from_the_auto_page_opens_a_chat_and_from_a_chat_answers_there(env, monkeypatch):
    from open_webui.utils import hermes_route
    opened, answered, meta = [], [], {}
    async def open_chat(request, user, form, route_id, on_created=None):
        opened.append((form.question, route_id))
        on_created('hc1')
        return 'hc1', 'reply-h'
    async def answer_in_chat(request, user, chat_id, message_id, route_id):
        answered.append((chat_id, message_id, route_id))
    monkeypatch.setattr(hermes_route, 'open_chat', open_chat)
    monkeypatch.setattr(hermes_route, 'answer_in_chat', answer_in_chat)
    monkeypatch.setattr(api.Chats, 'set_chat_meta_value_by_id', lambda id, key, value: meta.update({id: value}))
    monkeypatch.setattr(api.Chats, 'get_chat_title_by_id', lambda id: 'T')
    posted = []
    monkeypatch.setattr(api.Chats, 'upsert_message_to_chat_by_id_and_message_id', lambda *a, **k: posted.append(a))
    from open_webui.utils import team_chats
    async def emit(*args): pass
    monkeypatch.setattr(team_chats, 'emit_chat_event', emit)
    decision = {'mode': 'hermes', 'reason': '看日志', 'execution_requested': False}
    async def run():
        form = api.CreateForm(question='看下日志', client_key='page')
        row, _ = records.AutoRoutes.create(USER.id, form.client_key, 'hash', {'input': form.model_dump()})
        await api.dispatch(env, USER, row, form, decision, {}, set(), [], {})
        page = api.public(api._own(row['id'], USER), USER)
        assert opened == [('看下日志', row['id'])] and page['href'] == '/c/hc1' and page['mode'] == 'hermes'
        origin = {'chatId': 'c9', 'messageId': 'm9'}
        for key, turn in (('chat', True), ('card', False)):
            data = {'input': form.model_dump(), 'origin': origin, **({'chat_turn': True} if turn else {})}
            row, _ = records.AutoRoutes.create(USER.id, key, key, data)
            await api.dispatch(env, USER, row, form, decision, {}, set(), [], {})
            stored = records.AutoRoutes.get(row['id'], USER.id)
            assert stored['status'] == 'dispatched' and stored['target_id'] == 'c9'
            assert stored['data']['target_message'] == 'm9'
        # the chat's own reply goes on by itself; only the card's retry starts Hermes here
        assert answered == [('c9', 'm9', row['id'])]
        assert meta['c9'] == {'id': row['id'], 'mode': 'hermes'}
        assert posted == []  # Hermes' reply is not rewritten into a note about where it went
    asyncio.run(run())


def test_hermes_status_follows_its_reply():
    chat = lambda message: SimpleNamespace(chat={"history": {"messages": {"r": message}}})
    assert api._hermes_status(chat({"done": False}), "r") == "answering"
    assert api._hermes_status(chat({"done": True}), "r") == "done"
    assert api._hermes_status(chat({"done": True, "stopped": True}), "r") == "stopped"
    assert api._hermes_status(chat({"done": True, "error": {"content": "x"}}), "r") == "error"
    assert api._hermes_status(chat({}), "missing") is None


def test_answer_in_chat_rebuilds_the_branch_for_hermes(monkeypatch):
    from open_webui.utils import hermes_route
    from open_webui.socket import main as socket_main
    messages = {
        "u1": {"id": "u1", "parentId": None, "role": "user", "content": "第一问"},
        "a1": {"id": "a1", "parentId": "u1", "role": "assistant", "content": "第一答", "stopped": True},
        "u2": {"id": "u2", "parentId": "a1", "role": "user", "content": "看下日志",
               "files": [{"type": "image", "id": "img"}, {"type": "file", "id": "doc"}]},
        "r": {"id": "r", "parentId": "u2", "role": "assistant", "content": "旧的", "model": "hermes-agent", "stopped": True},
        "other": {"id": "other", "parentId": "u1", "role": "user", "content": "另一分支"},
    }
    chat = SimpleNamespace(chat={"history": {"messages": messages}, "params": {"system": "背景"}, "models": ["hermes-agent"]})
    monkeypatch.setattr(hermes_route.Chats, "get_chat_by_id_and_user_id", lambda *a: chat)
    written = []
    monkeypatch.setattr(hermes_route.Chats, "upsert_message_to_chat_by_id_and_message_id",
                        lambda chat_id, mid, fields, **kw: written.append((mid, fields, kw)))
    async def model(request, user, model_id=None): return {"id": model_id or "hermes-agent", "name": "Hermes"}
    monkeypatch.setattr(hermes_route, "_hermes_model", model)
    events = []
    monkeypatch.setattr(socket_main, "get_event_emitter", lambda meta, update_db=True: (lambda e: _async(events.append(e))))
    runs = []
    async def run_turn(request, form, user, metadata, model, events=None, wait=False):
        runs.append((form, metadata))
        return {"status": True, "task_id": "t"}
    monkeypatch.setattr(hermes_route, "run_turn", run_turn)
    asyncio.run(hermes_route.answer_in_chat(None, USER, "c1", "r", "route-1"))
    form, metadata = runs[0]
    assert [m["content"] for m in form["messages"]] == ["背景", "第一问", "第一答", "看下日志"]
    assert form["messages"][2]["stopped"] is True
    assert metadata["message_id"] == "r" and metadata["files"] == [{"type": "file", "id": "img"}, {"type": "file", "id": "doc"}]
    mid, fields, kw = written[0]
    assert mid == "r" and fields["content"] == "" and fields["stopped"] is False and kw == {"set_current": False}
    assert fields["auto_route"] == {"id": "route-1", "mode": "hermes"}
    assert events[0]["data"]["auto_route"]["mode"] == "hermes"


async def _async(value):
    return value


def test_without_dispatch_keeps_the_model_choice():
    from open_webui.utils.hermes_route import without_dispatch
    form = {"model": "h", "hermes_options": {"dispatch": "auto", "model": "m", "provider": "p"}}
    assert without_dispatch(form)["hermes_options"] == {"model": "m", "provider": "p"}
    assert form["hermes_options"]["dispatch"] == "auto"
    assert without_dispatch({"model": "h"})["hermes_options"] is None


def _chat_dispatch_env(monkeypatch, chosen):
    """The chat's 自动分流 reply with select/dispatch replaced: ``chosen`` is the mode picked."""
    from open_webui.utils import auto_dispatch, hermes_route, mode_chats, team_chats, dispatch_files
    from open_webui.socket import main as socket_main
    from open_webui import tasks
    store = {}
    monkeypatch.setattr(api.Chats, 'upsert_message_to_chat_by_id_and_message_id',
                        lambda cid, mid, fields, **kw: store.setdefault(mid, {}).update(fields))
    monkeypatch.setattr(api.Chats, 'get_message_by_id_and_message_id', lambda cid, mid: store.get(mid))
    monkeypatch.setattr(api.Chats, 'set_chat_meta_value_by_id', lambda *a: None)
    monkeypatch.setattr(api.Chats, 'get_chat_title_by_id', lambda id: 'T')
    monkeypatch.setattr(api.Chats, 'get_chat_by_id_and_user_id', lambda *a: SimpleNamespace(meta={}, title='T'))
    async def emit(*args): pass
    monkeypatch.setattr(team_chats, 'emit_chat_event', emit)
    monkeypatch.setattr(mode_chats, 'schedule_chat_metadata', lambda *a, **k: None)
    monkeypatch.setattr(dispatch_files, 'conversation_file_ids', lambda *a: [])
    events = []
    monkeypatch.setattr(socket_main, 'get_event_emitter', lambda meta, update_db=True: (lambda e: _async(events.append(e))))
    async def select(*args, **kw):
        return ({'mode': chosen, 'reason': '按目标', 'execution_requested': False}, {}, set(), [], {})
    async def dispatch(request, user, row, *args):
        if chosen != 'hermes':
            store['m1']['content'] = f'🔀 自动分流交给了{chosen}'
        records.AutoRoutes.update(row['id'], user.id, status='dispatched', mode=chosen, target_id='x')
    monkeypatch.setattr(api, 'select', select)
    monkeypatch.setattr(api, 'dispatch', dispatch)
    turns = []
    async def run_turn(request, form, user, metadata, model, events=None, wait=False):
        turns.append((form, metadata, wait))
        return {'status': True, 'task_id': 'hermes-task'}
    monkeypatch.setattr(hermes_route, 'run_turn', run_turn)
    started = []
    real_create = tasks.create_task
    def create_task(coro, **kw):
        task_id, task = real_create(coro, **kw)
        started.append(task)
        return task_id, task
    monkeypatch.setattr(tasks, 'create_task', create_task)
    return auto_dispatch, store, events, turns, started


FORM = {'model': 'hermes-agent', 'messages': [{'role': 'user', 'content': '看下日志'}],
        'hermes_options': {'dispatch': 'auto', 'model': 'm'}}
META = {'session_id': 's', 'chat_id': 'c1', 'message_id': 'm1', 'user_id': USER.id}


@pytest.mark.parametrize('chosen', ['hermes', 'answer'])
def test_the_chat_reply_waits_for_the_choice(env, monkeypatch, chosen):
    auto_dispatch, store, events, turns, started = _chat_dispatch_env(monkeypatch, chosen)
    async def run():
        out = await auto_dispatch.run_auto_dispatch(env, FORM, USER, META, 'hermes-agent', model={'id': 'hermes-agent'})
        await started[0]
        return out
    out = asyncio.run(run())
    assert out['task_id']
    assert events[0]['data']['content'] == auto_dispatch.CHOOSING and 'done' not in events[0]['data']
    if chosen == 'hermes':
        # the same reply goes on as Hermes' answer, waited for so stopping the reply stops the run
        assert events[-1]['data'] == {'content': '', 'auto_route': {'id': events[0]['data']['auto_route']['id'], 'mode': 'hermes'}}
        assert turns == [(FORM, META, True)]
        assert store['m1'].get('done') is None
    else:
        assert turns == []
        assert events[-1]['data']['done'] is True and events[-1]['data']['content'] == '🔀 自动分流交给了answer'


def test_a_temporary_chat_is_answered_by_hermes(env, monkeypatch):
    auto_dispatch, store, events, turns, started = _chat_dispatch_env(monkeypatch, 'answer')
    out = asyncio.run(auto_dispatch.run_auto_dispatch(env, FORM, USER, {**META, 'chat_id': 'local'}, 'hermes-agent'))
    assert out == {'status': True, 'task_id': 'hermes-task'} and len(turns) == 1 and not started


# --- Resilient fallback: backup classifier, cooldown bypass, heuristic accuracy, block consistency ---


def test_hermes_needs_tools_without_hermes_or_teams_is_blocked():
    blocked = normalize_selection(
        {"mode": "hermes", "needs_tools": True, "execution_requested": False},
        question="查一下线上配置", teams_available=False, discussion_available=True, hermes_available=False,
    )
    assert blocked["blocked"] is True and blocked["mode"] is None and blocked["degraded"] == "hermes"


def test_classifier_candidates_skip_failed_model_and_prefer_diverse_family():
    from open_webui.utils.auto_routing import classifier_candidates

    bases = [
        {"id": "c1.gpt-chat", "name": "gpt-chat"},
        {"id": "c2.gpt-4o", "name": "gpt-4o"},
        {"id": "c3.gemini-flash", "name": "gemini-flash"},
        {"id": "c4.claude-sonnet", "name": "claude-sonnet"},
    ]
    models = {b["id"]: b for b in bases}
    picked = classifier_candidates(bases, models, preferred="c1.gpt-chat", planner_model="c1.gpt-chat", limit=2)
    assert picked == ["c1.gpt-chat", "c3.gemini-flash"]
    # Excluding a failed gpt-chat moves directly to another family without retrying gpt-chat.
    skipped = classifier_candidates(bases, models, preferred="c1.gpt-chat", planner_model="c1.gpt-chat",
                                    exclude={"c1.gpt-chat"}, limit=2)
    assert "c1.gpt-chat" not in skipped and len(skipped) == 2 and skipped[0] == "c2.gpt-4o" and skipped[1] == "c3.gemini-flash"


@pytest.mark.parametrize("question,hermes_avail,expected_mode,expected_ro", [
    ("结合我们订单量大、要求强一致的业务，PostgreSQL 和 MySQL 到底选哪个", True, "discuss", False),
    ("讨论下这个架构方案的优缺点和取舍", True, "discuss", False),
    ("用精答解释一下 Redis 持久化机制", True, "answer", False),
    ("PostgreSQL 和 MySQL 有什么区别？", True, "answer", False),
    ("帮我把这段文字翻译成英文", True, "answer", False),
    ("看下 nginx 最近有没有报错", True, "hermes", False),
    ("明早 9 点提醒我开会", True, "hermes", False),
    ("画一张橘猫的头像", True, "hermes", False),
    ("给 HaloWebUI 加一个导出按钮，写单测并提交推送部署", True, "team", False),
    ("全面审查这个仓库的安全问题，只分析别改，出一份报告", True, "team", True),
    ("在吗", True, "hermes", False),
    ("在吗", False, "answer", False),
])
def test_heuristic_selection_routes_accurately_when_all_models_fail(question, hermes_avail, expected_mode, expected_ro):
    from open_webui.utils.auto_routing import heuristic_selection

    raw = heuristic_selection(
        question, teams_available=True, discussion_available=True, hermes_available=hermes_avail,
    )
    decision = normalize_selection(
        raw, question=question, teams_available=True, discussion_available=True, hermes_available=hermes_avail,
    )
    assert decision["mode"] == expected_mode
    assert bool(decision.get("read_only")) is expected_ro
    assert raw["degraded"] == "auto"


@pytest.mark.parametrize("question, executes", [
    ("按发布流程做", True),
    ("修复视频选择卡顿，按发布流程做", True),
    ("“按发布流程做”是什么意思？", False),
    ("不要按发布流程做", False),
    ("只分析，按发布流程做是什么意思？", False),
])
def test_release_shortcut_after_read_only_turn(question, executes):
    from open_webui.utils.auto_routing import heuristic_selection

    context = "用户：先只分析"
    raw = heuristic_selection(question, context, teams_available=True, hermes_available=True)
    result = normalize_selection(raw, question=question, context=context, teams_available=True, hermes_available=True)
    assert result["execution_requested"] is executes
    if executes:
        assert result["mode"] == "team"


def test_select_uses_backup_classifier_when_primary_fails_and_skips_dead_decision_model(env, monkeypatch):
    from open_webui.routers import answers
    from open_webui.utils import assistant_library, chat, decision_model as dm

    api._reset_decision_health()
    models = {
        "gpt-chat": {"id": "gpt-chat", "name": "gpt-chat"},
        "gemini-flash": {"id": "gemini-flash", "name": "gemini-flash"},
        "claude-sonnet": {"id": "claude-sonnet", "name": "claude-sonnet"},
    }
    async def models_for(*a): return models, set()
    monkeypatch.setattr(answers, "_models", models_for)
    monkeypatch.setattr(answers, "_resolve_planner", lambda *a: {"model": "gpt-chat", "name": "gpt-chat"})
    monkeypatch.setattr(assistant_library, "library", lambda *a: ([], list(models.values())))
    monkeypatch.setattr(dm, "current", lambda user: "gpt-chat")
    monkeypatch.setattr(dm, "lookup", lambda *a: {"id": "gpt-chat", "name": "gpt-chat", "kind": "text", "connection": ""})

    called = []
    async def completion(request, payload, user):
        called.append((payload["metadata"]["task"], payload["model"]))
        if payload["model"] in ("gpt-chat", "gemini-flash"):
            raise RuntimeError("upstream timeout")
        return {"choices": [{"message": {"content": json.dumps({"mode": "discuss", "reason": "多方案取舍"})}}]}

    monkeypatch.setattr(chat, "generate_chat_completion", completion)
    decision = asyncio.run(api.select(env, USER, api.CreateForm(question="选哪个架构", client_key="b1"), []))[0]
    # gpt-chat failed in decision -> skipped in classifier -> gemini-flash failed -> claude-sonnet succeeded!
    assert called == [("decision", "gpt-chat"), ("auto_routing", "gemini-flash"), ("auto_routing", "claude-sonnet")]
    assert decision["mode"] == "discuss" and decision["routing_model"] == "claude-sonnet"
    assert decision["decision"]["fallback"] is True and not decision.get("degraded")


def test_select_opens_cooldown_after_consecutive_decision_failures_and_falls_back_to_heuristic(env, monkeypatch):
    from open_webui.routers import answers
    from open_webui.utils import assistant_library, chat, decision_model as dm

    api._reset_decision_health()
    models = {
        "jev": {"id": "jev", "name": "jev-latest"},
        "gpt-chat": {"id": "gpt-chat", "name": "gpt-chat"},
        "claude-sonnet": {"id": "claude-sonnet", "name": "claude-sonnet"},
    }
    async def models_for(*a): return models, set()
    monkeypatch.setattr(answers, "_models", models_for)
    monkeypatch.setattr(answers, "_resolve_planner", lambda *a: {"model": "gpt-chat", "name": "gpt-chat"})
    monkeypatch.setattr(assistant_library, "library", lambda *a: ([], [models["gpt-chat"], models["claude-sonnet"]]))
    monkeypatch.setattr(dm, "current", lambda user: "jev")
    monkeypatch.setattr(dm, "lookup", lambda *a: {"id": "jev", "name": "jev-latest", "kind": "system_one", "connection": ""})

    decision_calls = 0
    async def all_down(request, payload, user):
        nonlocal decision_calls
        if payload["metadata"]["task"] == "decision":
            decision_calls += 1
            raise asyncio.TimeoutError()
        raise RuntimeError("classifier down")

    monkeypatch.setattr(chat, "generate_chat_completion", all_down)
    # 1st and 2nd failure hit threshold=2 and open cooldown; heuristic still classifies accurately!
    d1 = asyncio.run(api.select(env, USER, api.CreateForm(question="讨论下 PostgreSQL 和 MySQL 选哪个", client_key="c1"), []))[0]
    d2 = asyncio.run(api.select(env, USER, api.CreateForm(question="PostgreSQL 和 MySQL 有什么区别？", client_key="c2"), []))[0]
    d3 = asyncio.run(api.select(env, USER, api.CreateForm(question="讨论下架构边界怎么定", client_key="c3"), []))[0]
    assert decision_calls == 2  # 3rd call bypassed dead jev immediately via cooldown
    assert d1["mode"] == "discuss" and d1["degraded"] == "auto" and d1["routing_model"] is None
    assert d2["mode"] == "answer" and d2["degraded"] == "auto" and d2["routing_model"] is None
    assert d3["mode"] == "discuss" and d3["decision"]["fallback"] is True and "跳过" in d3["decision"]["reason"]
    api._reset_decision_health()
