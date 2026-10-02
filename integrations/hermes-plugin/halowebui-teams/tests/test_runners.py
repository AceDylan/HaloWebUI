"""Runner registry, task kinds, availability layers, fallback (plan / launch / runtime / retry),
assistant templates and the lead's model."""

import json
import os
import time
import uuid

import pytest

from test_reclaude import FakeRunner, _cst, _kb


@pytest.fixture
def override(pkg):
    path = pkg.runners.OVERRIDE_FILE

    def write(data):
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.utime(path, (time.time() + 1, time.time() + 1))  # a new mtime even within the same second

    yield write
    if path.exists():
        path.unlink()


# --- chain / kinds / selection ------------------------------------------------------------------

def test_chain_starts_where_the_default_is_and_always_ends_with_hermes(pkg):
    r = pkg.runners
    assert r.chain_from("reclaude") == ["reclaude", "cchclaude", "anyclaude", "codex", "agy", "hermes"]
    assert r.chain_from("cchclaude") == ["cchclaude", "anyclaude", "codex", "agy", "hermes"]
    assert r.chain_from("codex") == ["codex", "agy", "hermes"]
    assert r.chain_from("agy") == ["agy", "hermes"]
    assert r.chain_from("hermes") == ["hermes"]


def test_kind_defaults(pkg):
    r = pkg.runners
    assert {k: r.recommend(k)["default"] for k in ("code", "ui", "complex", "research", "writing")} == {
        "code": "cchclaude", "ui": "agy", "complex": "reclaude", "research": "hermes", "writing": "hermes"}
    assert r.normalize_kind("frontend") == "ui" and r.normalize_kind("backend") == "code"
    assert r.normalize_kind("nonsense") == ""


@pytest.mark.parametrize("down,expected", [
    ([], "cchclaude"),
    (["cchclaude"], "anyclaude"),
    (["cchclaude", "anyclaude"], "codex"),
    (["cchclaude", "anyclaude", "codex"], "agy"),
    (["cchclaude", "anyclaude", "codex", "agy"], "hermes"),
    (["cchclaude", "anyclaude", "codex", "agy", "hermes"], None),
])
def test_backend_task_walks_the_chain(pkg, availability, down, expected):
    for name in down:
        availability.down[name] = f"{name} 演练不可用"
    picked = pkg.runners.recommend("code")
    assert picked["default"] == "cchclaude" and picked["executor"] == expected
    assert [s["name"] for s in picked["skipped"]] == down
    if down:
        assert "演练不可用" in pkg.runners.fallback_reason(picked)


def test_ui_task_goes_agy_then_hermes(pkg, availability):
    assert pkg.runners.recommend("ui")["executor"] == "agy"
    availability.down["agy"] = "agy 没登录"
    assert pkg.runners.recommend("ui")["executor"] == "hermes"


def test_select_after_only_moves_forward(pkg, availability):
    r = pkg.runners
    # chosen cchclaude (down at plan time), now on codex; codex fails → agy, never back to cchclaude
    assert r.select_after("cchclaude", "codex")["executor"] == "agy"
    availability.down["agy"] = "x"
    assert r.select_after("cchclaude", "codex")["executor"] == "hermes"
    assert r.select_after("hermes", "hermes")["executor"] is None


def test_override_file_changes_defaults_order_and_marks_runners(pkg, override):
    r = pkg.runners
    override({"kinds": {"code": "codex"}, "order": ["codex", "reclaude"], "unavailable": {"agy": "维护中"},
              "disabled": ["anyclaude"]})
    assert r.kind_default("code") == "codex"
    assert r.fallback_order() == ("codex", "reclaude", "hermes")
    now = time.time()
    agy = r._check_one(r.BY_NAME["agy"], now)
    assert not agy["available"] and agy["state"] == "manual" and "维护中" in agy["reason"]
    anyc = r._check_one(r.BY_NAME["anyclaude"], now)
    assert not anyc["available"] and anyc["state"] == "not_configured"
    override({})
    assert r.fallback_order() == r.DEFAULT_ORDER


def test_missing_script_or_command_is_not_installed(pkg, monkeypatch):
    r = pkg.runners
    monkeypatch.setenv("HALO_TEAMS_CODEX_RUNNER", "/nonexistent/codex-run.sh")
    out = r._check_one(r.BY_NAME["codex"], time.time())
    assert not out["available"] and out["state"] == "not_installed"
    assert out["layers"][-1]["layer"] == "installed" and not out["layers"][-1]["ok"]


def test_failures_are_classified_only_when_the_runner_itself_is_down(pkg):
    c = pkg.runners.classify_failure
    assert c("AGY could not start or stream: No such file or directory") == "missing"
    assert c("API Error: 401 Unauthorized") == "auth"
    assert c("You've hit your usage limit · resets 5pm") == "quota"
    assert c("connect ECONNREFUSED 127.0.0.1:443") == "network"
    assert c("error: FAILED_PRECONDITION (code 400): User location is not supported for the API use.") == "account"
    assert c("", "quota_window") == "quota" and c("", "device_unbound") == "auth"
    assert c("", None, "quota_blocked") == "quota"
    assert c("测试没有通过：test_login 断言失败") is None
    assert c("x" * 700 + " quota 401") is None  # only the head of the text counts


def test_agy_region_failure_in_stderr_marks_it_down(pkg, tmp_path, monkeypatch):
    """agy writes an empty error and the reason only to stderr (seen live 2026-10-02)."""
    r = pkg.runners
    monkeypatch.setenv("HALO_TEAMS_AGY_RUNS_ROOT", str(tmp_path))
    run = tmp_path / "20261002-120849-444d98dd"
    run.mkdir()
    (run / "meta.json").write_text(json.dumps({"status": "error", "ended_at": "2026-10-02T04:08:52.704917+00:00"}))
    (run / "result.json").write_text(json.dumps({"status": "error", "response": "", "error": "", "agy_exit_code": 3}))
    (run / "stderr.log").write_text("error: FAILED_PRECONDITION (code 400): User location is not supported for the API use.\n")
    now = r._iso_or_text_ts("2026-10-02T04:10:00+00:00")
    found = r._recent_failure(r.BY_NAME["agy"], now)
    assert found and found[0] == "account" and "地区" in found[1]


def test_recent_quota_failure_marks_a_runner_down(pkg, tmp_path, monkeypatch):
    r = pkg.runners
    monkeypatch.setenv("HALO_TEAMS_AGY_RUNS_ROOT", str(tmp_path))
    run = tmp_path / "20261002-103509-0170961a"
    run.mkdir()
    ended = time.strftime("%Y-%m-%d %H:%M:%S +0800", time.gmtime(time.time() + 8 * 3600 - 60))
    (run / "meta.json").write_text(json.dumps({"status": "error", "ended_at": ended}))
    (run / "result.json").write_text(json.dumps({"error": "AGY could not start or stream: No such file or directory"}))
    found = r._recent_failure(r.BY_NAME["agy"], time.time())
    assert found and found[0] == "missing" and "命令或脚本不存在" in found[1]
    newer = tmp_path / "20261002-113509-0170961b"
    newer.mkdir()
    (newer / "meta.json").write_text(json.dumps({"status": "success"}))
    assert r._recent_failure(r.BY_NAME["agy"], time.time()) is None


# --- plan: assistants, kinds, runners -----------------------------------------------------------

def _members_plan(members, tasks=None):
    return {"members": members,
            "tasks": tasks or [{"key": f"T{i}", "title": m.get("role", "x"), "member": m["name"]}
                               for i, m in enumerate(members, 1)]}


def test_plan_members_get_assistant_kind_and_runner(pkg, availability):
    plan, errors = pkg.plan.validate_plan(_members_plan([
        {"name": "backend-dev", "role": "后端开发", "assistant": "17"},
        {"name": "ui-dev", "role": "界面", "assistant": "前端工程师"},
        {"name": "analyst", "role": "竞品调研", "assistant": None, "kind": "research"},
        {"name": "refactor", "role": "重构", "kind": "complex", "assistant": "999999"},
    ]))
    assert not errors
    by = {m["name"]: m for m in plan["members"]}
    assert by["backend-dev"]["assistant"]["name"] == "开发工程师" and by["backend-dev"]["kind"] == "code"
    assert by["backend-dev"]["executor"] == "cchclaude" == by["backend-dev"]["runner"]
    assert by["backend-dev"]["executor_source"] == "auto" and by["backend-dev"]["runner_note"] == ""
    assert by["ui-dev"]["assistant"]["id"] == "15" and by["ui-dev"]["kind"] == "ui" and by["ui-dev"]["runner"] == "agy"
    assert by["analyst"]["assistant"] is None and by["analyst"]["runner"] == "hermes"
    assert by["refactor"]["assistant"] is None and by["refactor"]["runner"] == "reclaude"


def test_plan_runner_falls_back_and_says_why(pkg, availability):
    availability.down["cchclaude"] = "cchclaude 连不上：best.acedylan.us 超时"
    plan, _ = pkg.plan.validate_plan(_members_plan([{"name": "backend-dev", "role": "后端开发", "kind": "code"}]))
    m = plan["members"][0]
    assert m["recommended"] == "cchclaude" and m["executor"] == "cchclaude" and m["runner"] == "anyclaude"
    assert "超时" in m["runner_note"]
    assert plan["executors"] == ["anyclaude"]


def test_user_choice_is_kept_but_still_falls_back(pkg, availability):
    member = {"name": "backend-dev", "role": "后端开发", "kind": "code", "executor": "codex", "executor_source": "user"}
    plan, _ = pkg.plan.validate_plan(_members_plan([member]))
    assert plan["members"][0]["executor"] == "codex" and plan["members"][0]["runner"] == "codex"
    availability.down["codex"] = "codex 没登录"
    plan, _ = pkg.plan.validate_plan(_members_plan([dict(member)]))
    m = plan["members"][0]
    assert m["executor"] == "codex" and m["executor_source"] == "user" and m["runner"] == "agy"
    assert "没登录" in m["runner_note"]


def test_every_runner_down_is_reported(pkg, availability):
    for name in pkg.runners.NAMES:
        availability.down[name] = f"{name} 坏了"
    plan, _ = pkg.plan.validate_plan(_members_plan([{"name": "backend-dev", "role": "后端", "kind": "code"}]))
    m = plan["members"][0]
    assert m["runner"] is None and "没有可用的 runner" in m["runner_note"]


def test_lead_prompt_lists_collaboration_templates_and_kinds(pkg):
    prompt = pkg.plan.system_prompt()
    assert "17：开发工程师（code）" in prompt and "782：代码审查员（code）" in prompt
    assert '"ui"' in prompt and "{catalog}" not in prompt and '"title"' in prompt
    catalog = pkg.assistants.catalog()
    assert len(catalog) >= 15 and all(item["kind"] in pkg.runners.KINDS for item in catalog)
    assert all("我的第一个请求" not in item["prompt"] for item in catalog)


def test_lead_follows_hermes_default_model_and_its_fallbacks(pkg):
    cfg = {"model": {"default": "gpt-chat", "provider": "custom:best"},
           "custom_providers": [{"name": "deepseek-chat", "model": "deepseek-chat"}, {"name": "gemini-chat", "model": "gemini-chat"}],
           "fallback_providers": [{"provider": "custom", "model": "deepseek-chat"}, {"provider": "custom", "model": "gemini-chat"}]}
    routes = pkg.plan.lead_routes(cfg)
    assert [(r["provider"], r["model"], r["source"]) for r in routes] == [
        ("custom:best", "gpt-chat", "hermes_default"),
        ("custom:deepseek-chat", "deepseek-chat", "hermes_fallback"),
        ("custom:gemini-chat", "gemini-chat", "hermes_fallback")]
    cfg["model"]["default"] = "claude-chat"  # Hermes switched models: the lead follows, nothing pinned
    assert pkg.plan.lead_routes(cfg)[0]["model"] == "claude-chat"
    cfg["auxiliary"] = {"halo_team_lead": {"provider": "custom:gemini-chat", "model": "gemini-chat"}}
    assert pkg.plan.lead_routes(cfg)[0] == {"provider": "custom:gemini-chat", "model": "gemini-chat", "source": "config"}
    info = pkg.plan.lead_model_info(cfg)
    assert info["model"] == "gemini-chat" and info["label"] == "协作台配置"


def test_call_model_falls_back_along_hermes_routes(pkg, monkeypatch):
    import agent.auxiliary_client as aux

    tried = []

    class Resp:
        def __init__(self, text):
            self.choices = [type("C", (), {"message": type("M", (), {"content": text})()})()]

    def fake_call_llm(task=None, provider=None, model=None, **kw):
        tried.append(model)
        if model == "gpt-chat":
            raise RuntimeError("upstream 502")
        return Resp("好")

    monkeypatch.setattr(aux, "call_llm", fake_call_llm)
    monkeypatch.setattr(pkg.plan, "_config", lambda: {
        "model": {"default": "gpt-chat", "provider": "custom:best"},
        "custom_providers": [{"name": "deepseek-chat", "model": "deepseek-chat"}],
        "fallback_providers": [{"provider": "custom", "model": "deepseek-chat"}]})
    text, reason, used = pkg.plan.call_model([{"role": "user", "content": "hi"}])
    assert text == "好" and tried == ["gpt-chat", "deepseek-chat"]
    assert used["model"] == "deepseek-chat" and used["fallback_from"] == ["gpt-chat"] and "502" in used["fallback_reason"]


# --- execution-time fallback ----------------------------------------------------------------------

@pytest.fixture
def bridge(pkg, monkeypatch):
    fake = FakeRunner(pkg.reclaude.RUNNERS)
    monkeypatch.setitem(pkg.reclaude._launcher, "fn", fake)
    monkeypatch.setattr(pkg.reclaude, "_host_cap", lambda: None)
    stopped = []
    monkeypatch.setattr(pkg.reclaude, "_stop_runner_run", lambda rn, run_id, meta: stopped.append(run_id))
    mine = []
    monkeypatch.setattr(pkg.reclaude, "team_boards", lambda: list(mine))

    def team(members, *, availability_before=None):
        plan, errors = pkg.plan.validate_plan(_members_plan(members))
        assert not errors
        team_id = str(uuid.uuid4())
        created = pkg.teams.create_team(team_id, plan, owner="u1", goal="演练")
        slug = pkg.common.board_slug(team_id)
        mine.append(slug)

        def tick():
            pkg.reclaude.tick_board(slug, pkg.common.read_team(slug))

        def task(key="T1"):
            with pkg.common.board_conn(slug) as conn:
                return _kb().get_task(conn, created["tasks"][key])

        def snap(key="T1"):
            return next(t for t in pkg.teams.snapshot(team_id, "u1")["tasks"] if t["key"] == key)

        def run_meta(key="T1"):
            with pkg.common.board_conn(slug) as conn:
                return pkg.reclaude._run_meta(conn, _kb().get_task(conn, created["tasks"][key]).current_run_id)

        def events(phase=None):
            evs = [e for e in pkg.teams.timeline(team_id, "u1")["events"] if e["type"] == "runner"]
            return [e for e in evs if phase is None or e["data"]["phase"] == phase]

        return type("T", (), dict(team_id=team_id, slug=slug, tasks=created["tasks"], tick=staticmethod(tick),
                                  task=staticmethod(task), snap=staticmethod(snap), run_meta=staticmethod(run_meta),
                                  events=staticmethod(events)))

    return type("B", (), dict(fake=fake, team=staticmethod(team), stopped=stopped))


def test_plan_time_fallback_is_recorded_on_the_task(pkg, availability, bridge):
    availability.down["cchclaude"] = "cchclaude 连不上"
    t = bridge.team([{"name": "backend-dev", "role": "后端开发", "kind": "code"}])
    assert t.task().assignee == "anyclaude"
    snap = t.snap()
    assert snap["executor"] == "anyclaude" and snap["chosen"] == "cchclaude"
    assert snap["trail"][0]["phase"] == "plan" and "连不上" in snap["trail"][0]["reason"]
    ev = t.events("fallback")
    assert len(ev) == 1 and ev[0]["data"]["to"] == "anyclaude"


def test_launch_time_fallback_moves_the_task_before_it_starts(pkg, availability, bridge):
    t = bridge.team([{"name": "backend-dev", "role": "后端开发", "kind": "code"}])
    assert t.task().assignee == "cchclaude"
    availability.down["cchclaude"] = "cchclaude 中转 502"
    t.tick()  # cchclaude down → anyclaude (ready again)
    assert t.task().assignee == "anyclaude" and t.task().status == "ready"
    t.tick()  # anyclaude starts it
    assert t.task().status == "running"
    argv = bridge.fake.calls[-1]
    assert argv[0] == pkg.reclaude.RUNNERS["anyclaude"].script and argv[1] == "run"
    snap = t.snap()
    assert snap["executor"] == "anyclaude" and snap["chosen"] == "cchclaude" and snap["attempts"] == 1
    assert [s["phase"] for s in snap["trail"]] == ["launch"]
    assert "启动前检查" in t.events("fallback")[0]["text"]


def test_runtime_login_failure_falls_forward_but_ordinary_failure_does_not(pkg, availability, bridge):
    codex = pkg.reclaude.RUNNERS["codex"]
    t = bridge.team([{"name": "coder", "role": "后端", "kind": "code", "executor": "codex", "executor_source": "user"}])
    t.tick()
    run_id = t.run_meta()["runner_run_id"]
    bridge.fake.write(run_id, status="error", _root=str(codex.runs_root))
    json.dump({"error": "401 Unauthorized: token expired"}, open(codex.runs_root / run_id / "result.json", "w"))
    t.tick()  # failed for login → attempt closed, moved to agy, which the same tick starts
    task = t.task()
    assert task.assignee == "agy" and task.status == "running"
    assert bridge.fake.calls[-1][0] == pkg.reclaude.RUNNERS["agy"].script
    snap = t.snap()
    assert snap["chosen"] == "codex" and snap["trail"][-1]["phase"] == "runtime" and snap["trail"][-1]["fail_kind"] == "auth"
    assert snap["attempts"] == 2
    # An ordinary failure of the work itself stays failed on its runner.
    agy = pkg.reclaude.RUNNERS["agy"]
    run2 = t.run_meta()["runner_run_id"]
    bridge.fake.write(run2, status="error", _root=str(agy.runs_root))
    json.dump({"error": "单元测试没有通过：test_login 断言失败"}, open(agy.runs_root / run2 / "result.json", "w"))
    t.tick()
    assert t.task().status == "blocked" and t.task().assignee == "agy"
    assert t.snap()["sub_status"] == "failed"


def test_long_quota_wait_moves_on_short_one_waits(pkg, availability, bridge):
    cch = pkg.reclaude.RUNNERS["cchclaude"]
    t = bridge.team([{"name": "backend-dev", "role": "后端开发", "kind": "code"}])
    t.tick()
    run_id = t.run_meta()["runner_run_id"]
    bridge.fake.write(run_id, status="error", auto_resume="scheduled", auto_resume_pid=os.getpid(),
                      auto_resume_at=_cst(300), auto_resume_run=f"{run_id}-a1", _root=str(cch.runs_root))
    t.tick()
    assert t.snap()["sub_status"] == "quota_wait" and t.task().assignee == "cchclaude"
    bridge.fake.write(run_id, auto_resume_at=_cst(3 * 3600), _root=str(cch.runs_root))
    t.tick()
    assert bridge.stopped == [run_id]
    assert t.task().assignee == "anyclaude" and t.task().status == "running"
    assert t.snap()["trail"][-1]["fail_kind"] == "quota"


def test_quota_blocked_start_moves_on(pkg, availability, bridge):
    rec = pkg.reclaude.RUNNERS["reclaude"]
    t = bridge.team([{"name": "architect", "role": "架构", "kind": "complex"}])
    t.tick()
    run_id = t.run_meta()["runner_run_id"]
    bridge.fake.write(run_id, status="quota_blocked", _root=str(rec.runs_root))
    t.tick()
    assert t.task().assignee == "cchclaude"
    assert any("额度" in e["text"] for e in t.events("fallback"))


def test_whole_chain_down_blocks_with_every_reason(pkg, availability, bridge):
    t = bridge.team([{"name": "ui-dev", "role": "前端", "kind": "ui"}])
    assert t.task().assignee == "agy"
    availability.down.update(agy="agy 没登录", hermes="Hermes 停用")
    t.tick()
    task = t.task()
    assert task.status == "blocked"
    snap = t.snap()
    assert snap["sub_status"] == "failed" and "所有执行来源都不可用" in snap["block_reason"]
    assert snap["attempts"] == 0  # no attempt was synthesized for a task that never started
    assert t.events("unavailable")[0]["sub_status"] == "failed"


def test_retry_goes_back_to_the_chosen_runner_when_it_is_back(pkg, availability, bridge):
    availability.down["cchclaude"] = "cchclaude 连不上"
    t = bridge.team([{"name": "backend-dev", "role": "后端开发", "kind": "code"}])
    assert t.task().assignee == "anyclaude"
    t.tick()
    run_id = t.run_meta()["runner_run_id"]
    anyc = pkg.reclaude.RUNNERS["anyclaude"]
    bridge.fake.write(run_id, status="error", _root=str(anyc.runs_root))
    json.dump({"error": "构建失败：缺少依赖"}, open(anyc.runs_root / run_id / "result.json", "w"))
    t.tick()
    assert t.task().status == "blocked"
    availability.down.clear()
    pkg.teams.retry(t.team_id, t.tasks["T1"], owner="u1")
    assert t.task().assignee == "cchclaude" and t.task().status == "ready"
    assert t.snap()["trail"][-1]["phase"] == "retry"


def test_cache_follows_the_override_file(pkg, override, monkeypatch):
    r = pkg.runners
    r.forget()
    calls = []

    def fake_one(spec, now):
        calls.append(spec.name)
        down = (r.overrides().get("unavailable") or {}).get(spec.name)
        return {"name": spec.name, "label": spec.label, "available": not down, "state": "manual" if down else "ok",
                "reason": down or "可用", "checked_at": int(now), "layers": []}

    monkeypatch.setattr(r, "_check_one", fake_one)
    assert r.check_live(["cchclaude"])["cchclaude"]["available"] and calls == ["cchclaude"]
    assert r.check_live(["cchclaude"])["cchclaude"]["available"] and calls == ["cchclaude"]  # cached
    override({"unavailable": {"cchclaude": "维护中"}})
    assert not r.check_live(["cchclaude"])["cchclaude"]["available"] and calls == ["cchclaude", "cchclaude"]
    r.forget()


def test_a_team_can_prefer_another_configured_model(pkg):
    cfg = {"model": {"default": "gpt-chat", "provider": "custom:best"},
           "custom_providers": [{"name": "best", "model": "gpt-chat"}, {"name": "claude-chat", "model": "claude-chat"},
                                {"name": "deepseek-chat", "model": "deepseek-chat"}],
           "fallback_providers": [{"provider": "custom", "model": "deepseek-chat"}]}
    assert [m["model"] for m in pkg.plan.configured_models(cfg)] == ["gpt-chat", "claude-chat", "deepseek-chat"]
    routes = pkg.plan.lead_routes(cfg, preferred="claude-chat")
    assert [(r["model"], r["source"]) for r in routes] == [
        ("claude-chat", "team"), ("gpt-chat", "hermes_default"), ("deepseek-chat", "hermes_fallback")]
    # An unknown model is ignored, not called.
    assert pkg.plan.lead_routes(cfg, preferred="gpt-9")[0]["model"] == "gpt-chat"
    assert pkg.plan.lead_model_info(cfg)["choices"] == ["gpt-chat", "claude-chat", "deepseek-chat"]


def test_failure_line_is_the_readable_part(pkg):
    text = ('error: FAILED_PRECONDITION (code 400): User location is not supported for the API use.\n'
            'AGY_ERROR: {"short_error":"FAILED_PRECONDITION"}')
    assert pkg.runners.failure_line(text) == "FAILED_PRECONDITION (code 400): User location is not supported for the API use."
    assert pkg.runners.failure_line('{"x": 1}\n\n') == ""
