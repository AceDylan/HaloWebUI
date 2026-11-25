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

def test_family_chains_and_explicit_choice_no_auto_fallback(pkg):
    r = pkg.runners
    # Auto mode walks strictly within the engine family.
    assert r.chain_from("officlaude", auto=True) == ["officlaude", "cchclaude", "anyclaude", "reclaude"]
    assert r.chain_from("cchclaude", auto=True) == ["cchclaude", "anyclaude", "reclaude"]
    assert r.chain_from("reclaude", auto=True) == ["reclaude"]
    assert r.chain_from("codex", auto=True) == ["codex"]
    assert r.chain_from("offiagy", auto=True) == ["offiagy", "agy"]
    assert r.chain_from("agy", auto=True) == ["agy"]
    assert r.chain_from("hermes", auto=True) == ["hermes"]
    # Explicit choice (auto=False) NEVER auto-falls back: user picks another runner when down.
    for name in r.NAMES:
        assert r.chain_from(name, auto=False) == [name]


def test_kind_defaults(pkg):
    r = pkg.runners
    assert {k: r.recommend(k)["default"] for k in ("code", "codex", "ui", "complex", "research", "writing")} == {
        "code": "officlaude", "codex": "codex", "ui": "offiagy", "complex": "officlaude",
        "research": "hermes", "writing": "hermes"}
    assert r.normalize_kind("frontend") == "ui" and r.normalize_kind("backend") == "code"
    assert r.normalize_kind("review") == "codex" and r.normalize_kind("codex") == "codex"
    assert r.normalize_kind("nonsense") == ""


@pytest.mark.parametrize("down,expected", [
    ([], "officlaude"),
    (["officlaude"], "cchclaude"),
    (["officlaude", "cchclaude"], "anyclaude"),
    (["officlaude", "cchclaude", "anyclaude"], "reclaude"),
    (["officlaude", "cchclaude", "anyclaude", "reclaude"], None),
])
def test_claude_code_task_walks_claude_family_only(pkg, availability, down, expected):
    for name in down:
        availability.down[name] = f"{name} 演练不可用"
    picked = pkg.runners.recommend("code")
    assert picked["default"] == "officlaude" and picked["executor"] == expected
    assert [s["name"] for s in picked["skipped"]] == down
    if down:
        assert "演练不可用" in pkg.runners.fallback_reason(picked)


def test_ui_task_goes_offiagy_then_agy_without_drifting_across_families(pkg, availability):
    r = pkg.runners
    assert r.recommend("ui")["executor"] == "offiagy"
    assert r.recommend("ui")["chain"] == ["offiagy", "agy"]
    availability.down["offiagy"] = "offiagy 没有登录"
    picked = r.recommend("ui")
    assert picked["executor"] == "agy" and "offiagy 没有登录" in r.fallback_reason(picked)
    availability.down["agy"] = "agy 网关不可用"
    assert r.recommend("ui")["executor"] is None
    # Explicit choice never falls back even when agy is up.
    availability.down.pop("agy", None)
    assert r.chain_from("offiagy") == ["offiagy"] and r.select("offiagy")["executor"] is None
    assert r.select_after("offiagy", "offiagy", auto=True)["executor"] == "agy"
    assert r.select_after("offiagy", "offiagy")["executor"] is None


def test_auto_offiagy_login_failure_at_runtime_moves_to_agy(pkg, availability, bridge):
    offiagy = pkg.reclaude.RUNNERS["offiagy"]
    t = bridge.team([{"name": "ui-dev", "role": "前端", "kind": "ui"}])
    assert t.task().assignee == "offiagy"
    t.tick()
    run_id = t.run_meta()["runner_run_id"]
    bridge.fake.write(run_id, status="error", _root=str(offiagy.runs_root))
    json.dump({"error": "401 Unauthorized: token expired"}, open(offiagy.runs_root / run_id / "result.json", "w"))
    t.tick()
    assert t.task().assignee == "agy" and t.task().status == "running"
    snap = t.snap()
    assert snap["chosen"] == "offiagy" and snap["trail"][-1]["fail_kind"] == "auth"


def test_select_after_only_moves_forward_within_family(pkg, availability):
    r = pkg.runners
    assert r.select_after("officlaude", "cchclaude", auto=True)["executor"] == "anyclaude"
    availability.down["anyclaude"] = "x"
    assert r.select_after("officlaude", "cchclaude", auto=True)["executor"] == "reclaude"
    assert r.select_after("officlaude", "reclaude", auto=True)["executor"] is None
    # Explicit choice never moves forward.
    assert r.select_after("cchclaude", "cchclaude", auto=False)["executor"] is None


def test_override_file_changes_defaults_order_and_marks_runners(pkg, override):
    r = pkg.runners
    override({"kinds": {"code": "codex"}, "order": ["codex", "reclaude"], "unavailable": {"agy": "维护中"},
              "disabled": ["anyclaude"]})
    assert r.kind_default("code") == "codex"
    assert r.fallback_order() == ("codex", "reclaude")
    now = time.time()
    agy = r._check_one(r.BY_NAME["agy"], now)
    assert not agy["available"] and agy["state"] == "manual" and "维护中" in agy["reason"]
    anyc = r._check_one(r.BY_NAME["anyclaude"], now)
    assert not anyc["available"] and anyc["state"] == "not_configured"
    override({"families": {"claude": ["cchclaude", "officlaude"]}})
    assert r.chain_from("cchclaude", auto=True) == ["cchclaude", "officlaude"]
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
        {"name": "codex-dev", "role": "后端模块", "kind": "codex", "assistant": None},
    ]))
    assert not errors
    by = {m["name"]: m for m in plan["members"]}
    assert by["backend-dev"]["assistant"]["name"] == "开发工程师" and by["backend-dev"]["kind"] == "code"
    assert by["backend-dev"]["executor"] == "officlaude" == by["backend-dev"]["runner"]
    assert by["backend-dev"]["executor_source"] == "auto" and by["backend-dev"]["runner_note"] == ""
    assert by["ui-dev"]["assistant"]["id"] == "15" and by["ui-dev"]["kind"] == "ui" and by["ui-dev"]["runner"] == "offiagy"
    assert by["analyst"]["assistant"] is None and by["analyst"]["runner"] == "hermes"
    assert by["codex-dev"]["assistant"] is None and by["codex-dev"]["runner"] == "codex"


def test_plan_runner_falls_back_within_family_and_says_why(pkg, availability):
    availability.down["officlaude"] = "官方 Claude 额度不足"
    plan, _ = pkg.plan.validate_plan(_members_plan([{"name": "backend-dev", "role": "后端开发", "kind": "code"}]))
    m = plan["members"][0]
    assert m["recommended"] == "officlaude" and m["executor"] == "officlaude" and m["runner"] == "cchclaude"
    assert "额度不足" in m["runner_note"]
    assert plan["executors"] == ["cchclaude"]


def test_user_choice_is_locked_and_never_auto_falls_back(pkg, availability):
    member = {"name": "backend-dev", "role": "后端开发", "kind": "code", "executor": "cchclaude", "executor_source": "user"}
    plan, _ = pkg.plan.validate_plan(_members_plan([member]))
    assert plan["members"][0]["executor"] == "cchclaude" and plan["members"][0]["runner"] == "cchclaude"
    availability.down["cchclaude"] = "cchclaude 中转 502"
    plan, _ = pkg.plan.validate_plan(_members_plan([dict(member)]))
    m = plan["members"][0]
    assert m["executor"] == "cchclaude" and m["executor_source"] == "user" and m["runner"] is None
    assert "502" in m["runner_note"]


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
    availability.down["officlaude"] = "官方 Claude 额度不足"
    t = bridge.team([{"name": "backend-dev", "role": "后端开发", "kind": "code"}])
    assert t.task().assignee == "cchclaude"
    snap = t.snap()
    assert snap["executor"] == "cchclaude" and snap["chosen"] == "officlaude"
    assert snap["trail"][0]["phase"] == "plan" and "额度不足" in snap["trail"][0]["reason"]
    ev = t.events("fallback")
    assert len(ev) == 1 and ev[0]["data"]["to"] == "cchclaude"


def test_launch_time_fallback_moves_the_task_before_it_starts(pkg, availability, bridge):
    t = bridge.team([{"name": "backend-dev", "role": "后端开发", "kind": "code"}])
    assert t.task().assignee == "officlaude"
    availability.down["officlaude"] = "官方 Claude 限流"
    t.tick()  # officlaude down → cchclaude (ready again)
    assert t.task().assignee == "cchclaude" and t.task().status == "ready"
    t.tick()  # cchclaude starts it
    assert t.task().status == "running"
    argv = bridge.fake.calls[-1]
    assert argv[0] == pkg.reclaude.RUNNERS["cchclaude"].script and argv[1] == "run"
    snap = t.snap()
    assert snap["executor"] == "cchclaude" and snap["chosen"] == "officlaude" and snap["attempts"] == 1
    assert [s["phase"] for s in snap["trail"]] == ["launch"]
    assert "启动前检查" in t.events("fallback")[0]["text"]


def test_runtime_failure_on_user_chosen_runner_blocks_and_lets_user_switch(pkg, availability, bridge):
    codex = pkg.reclaude.RUNNERS["codex"]
    t = bridge.team([{"name": "coder", "role": "后端", "kind": "code", "executor": "codex", "executor_source": "user"}])
    t.tick()
    run_id = t.run_meta()["runner_run_id"]
    bridge.fake.write(run_id, status="error", _root=str(codex.runs_root))
    json.dump({"error": "401 Unauthorized: token expired"}, open(codex.runs_root / run_id / "result.json", "w"))
    t.tick()  # user-chosen runner down -> does NOT auto-fallback; blocks for user to choose
    task = t.task()
    assert task.status == "blocked" and task.assignee == "codex"
    snap = t.snap()
    assert snap["sub_status"] == "failed" and "不自动顺延" in snap["trail"][-1]["reason"]
    # User explicitly switches to cchclaude on retry!
    res = pkg.teams.retry(t.team_id, t.tasks["T1"], owner="u1", executor="cchclaude")
    assert res["retried"] is True and res["executor"] == "cchclaude"
    assert t.task().assignee == "cchclaude" and t.task().status == "ready"
    assert t.snap()["trail"][-1]["phase"] == "user" and t.snap()["trail"][-1]["to"] == "cchclaude"


def test_long_quota_wait_moves_on_short_one_waits(pkg, availability, bridge):
    availability.down["officlaude"] = "官方 Claude 额度不足"
    cch = pkg.reclaude.RUNNERS["cchclaude"]
    t = bridge.team([{"name": "backend-dev", "role": "后端开发", "kind": "code"}])
    assert t.task().assignee == "cchclaude"
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
    offi = pkg.reclaude.RUNNERS["officlaude"]
    t = bridge.team([{"name": "architect", "role": "架构", "kind": "complex"}])
    t.tick()
    run_id = t.run_meta()["runner_run_id"]
    bridge.fake.write(run_id, status="quota_blocked", _root=str(offi.runs_root))
    t.tick()
    assert t.task().assignee == "cchclaude"
    assert any("额度" in e["text"] for e in t.events("fallback"))


def test_whole_chain_down_blocks_with_every_reason(pkg, availability, bridge):
    t = bridge.team([{"name": "ui-dev", "role": "前端", "kind": "ui"}])
    assert t.task().assignee == "offiagy"
    availability.down.update(offiagy="offiagy 没有登录", agy="agy 网关不可用")
    t.tick()
    task = t.task()
    assert task.status == "blocked"
    snap = t.snap()
    assert snap["sub_status"] == "failed" and "所有执行来源都不可用" in snap["block_reason"]
    assert snap["attempts"] == 0  # no attempt was synthesized for a task that never started
    assert t.events("unavailable")[0]["sub_status"] == "failed"


def test_retry_goes_back_to_the_chosen_runner_when_it_is_back(pkg, availability, bridge):
    availability.down["officlaude"] = "官方 Claude 额度不足"
    t = bridge.team([{"name": "backend-dev", "role": "后端开发", "kind": "code"}])
    assert t.task().assignee == "cchclaude"
    t.tick()
    run_id = t.run_meta()["runner_run_id"]
    cch = pkg.reclaude.RUNNERS["cchclaude"]
    bridge.fake.write(run_id, status="error", _root=str(cch.runs_root))
    json.dump({"error": "构建失败：缺少依赖"}, open(cch.runs_root / run_id / "result.json", "w"))
    t.tick()
    assert t.task().status == "blocked"
    availability.down.clear()
    pkg.teams.retry(t.team_id, t.tasks["T1"], owner="u1")
    assert t.task().assignee == "officlaude" and t.task().status == "ready"
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


def test_official_claude_leads_claude_family_and_locks_when_explicit(pkg, availability, override):
    r = pkg.runners
    spec = r.BY_NAME["officlaude"]
    assert spec.label == "官方 Claude" and spec.max_turns and not spec.quota_wait and spec.family == "claude"
    assert r.chain_from("officlaude", auto=True) == ["officlaude", "cchclaude", "anyclaude", "reclaude"]
    assert r.chain_from("officlaude", auto=False) == ["officlaude"]
    assert r.select("officlaude")["executor"] == "officlaude"
    availability.down["officlaude"] = "未登录"
    assert r.select("officlaude", auto=False)["executor"] is None
    assert r.select("officlaude", auto=True)["executor"] == "cchclaude"
    assert r.select_after("officlaude", "officlaude", auto=False)["executor"] is None
    assert r.select_after("officlaude", "officlaude", auto=True)["executor"] == "cchclaude"
    assert r.classify_failure("", "auth_required") == "auth"
    assert r.classify_failure("", "official_limit") == "quota"


def test_offiagy_leads_agy_family_and_probes_the_google_sign_in(pkg, availability, override, monkeypatch, tmp_path):
    r = pkg.runners
    spec = r.BY_NAME["offiagy"]
    assert spec.engine == "Antigravity" and spec.script == "offiagy-run.sh" and spec.answer_sets_id
    assert r.chain_from("offiagy", auto=True) == ["offiagy", "agy"]
    assert r.chain_from("offiagy", auto=False) == ["offiagy"]
    assert r.select("offiagy")["executor"] == "offiagy"
    override({"kinds": {"code": "offiagy"}})
    assert r.kind_default("code") == "offiagy" and r.kind_default("ui") == "offiagy"
    token = tmp_path / "token"
    monkeypatch.setenv("HALO_TEAMS_AGY_TOKEN", str(token))
    state, detail, _ = r._probe_account(spec)
    assert state == "account" and "offiagy" in detail
    token.write_text("x")
    assert r._probe_account(spec)[0] == "ok"


@pytest.mark.parametrize("response,rc,quota_out,expected", [
    ({"loggedIn": True, "authMethod": "claude.ai"}, 0, "**官方 Claude 额度**：5 小时 剩余 **80%** · 每周 剩余 **60%**", "ok"),
    ({"loggedIn": True, "authMethod": "claude.ai"}, 0, "**官方 Claude 额度**：5 小时 剩余 **0%**（17:00 重置） · 每周 剩余 **60%**", "quota"),
    ({"loggedIn": True, "authMethod": "claude.ai"}, 0, "**官方 Claude 额度**：5 小时 剩余 **10%**（17:00 重置） · 每周 剩余 **0%**（11-30 22:00 重置）", "quota"),
    ({"loggedIn": False, "authMethod": "none"}, 1, "", "account"),
    ({"loggedIn": True, "authMethod": "api_key"}, 0, "", "account"),
])
def test_official_account_probe_checks_oauth_and_quota(pkg, monkeypatch, response, rc, quota_out, expected):
    calls = []
    monkeypatch.setattr(pkg.runners, "_which", lambda name: "/stub/" + name)

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[0] == "python3":
            return 0, quota_out
        return rc, json.dumps(response)

    monkeypatch.setattr(pkg.runners, "_run", run)
    state, detail, reset = pkg.runners._probe_account(pkg.runners.BY_NAME["officlaude"])
    assert state == expected
    # the window that is used up, not the first one listed
    assert reset == {True: "11-30 22:00", False: "17:00" if expected == "quota" else None}["11-30" in quota_out]
    assert calls[0] == ["/stub/officlaude", "auth", "status", "--json"]
    assert "官方 Claude" in detail


def test_relay_probe_reads_the_settings_file_the_wrapper_passes(pkg, monkeypatch, tmp_path):
    """cchclaude / anyclaude wrappers moved their settings (~/.claude → ~/.claude-thirdparty);
    the probe must follow the wrapper's --settings, not a stale hard-coded path."""
    r = pkg.runners
    settings = tmp_path / "settings-cch.json"
    settings.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "http://relay.test:8081/",
                                            "ANTHROPIC_API_KEY": "k", "HTTPS_PROXY": "http://proxy.test:7890"}}))
    wrapper = tmp_path / "cchclaude"
    wrapper.write_text(f"#!/usr/bin/env bash\nexec claude --settings {settings} --dangerously-skip-permissions \"$@\"\n")
    monkeypatch.setattr(r, "_which", lambda name: str(wrapper))
    seen = {}

    def probe(url, headers, proxy=""):
        seen.update(url=url, proxy=proxy)
        return "ok", "HTTP 200"

    monkeypatch.setattr(r, "_http_probe", probe)
    state, detail, _ = r._probe_account(r.BY_NAME["cchclaude"])
    assert state == "ok" and detail == "relay.test:8081：HTTP 200"
    assert seen == {"url": "http://relay.test:8081/v1/models", "proxy": "http://proxy.test:7890"}

    # A wrapper without --settings (or pointing at a missing file) falls back to the registry default.
    wrapper.write_text("#!/usr/bin/env bash\nexec claude --settings /nonexistent/s.json \"$@\"\n")
    assert r._settings_file(r.BY_NAME["cchclaude"]) == r.BY_NAME["cchclaude"].settings


# --- AGY preferences (HaloWebUI 「Hermes 模型」 page) ------------------------------------------

def test_agy_prefs_roundtrip_keeps_other_override_keys(pkg, override, monkeypatch):
    r = pkg.runners
    monkeypatch.setattr(r, "offiagy_models", lambda **_k: [{"id": "gemini-4-neon-high", "name": "Gemini 4 Neon (High)"}])
    override({"disabled": ["anyclaude"]})
    prefs = r.agy_prefs()
    assert prefs["ui_runner"] == "offiagy" and prefs["ui_chain"] == ["offiagy", "agy"]
    assert prefs["offiagy_model"] == "" and prefs["offiagy_models"][0]["id"] == "gemini-4-neon-high"
    names = [c["name"] for c in prefs["ui_choices"]]
    assert "offiagy" in names and "agy" in names and "hermes" in names and "officlaude" in names
    chains = {c["name"]: c["chain"] for c in prefs["ui_choices"]}
    assert chains["offiagy"] == ["offiagy", "agy"] and chains["codex"] == ["codex"]

    prefs = r.save_agy_prefs("agy", "gemini-4-argon-high")
    assert prefs["ui_runner"] == "agy" and prefs["ui_chain"] == ["agy"]
    assert prefs["offiagy_model"] == "gemini-4-argon-high"
    data = json.loads(r.OVERRIDE_FILE.read_text(encoding="utf-8"))
    assert data == {"disabled": ["anyclaude"], "kinds": {"ui": "agy"}, "offiagy_model": "gemini-4-argon-high"}

    # back to the built-in default and the AGY default model: the keys go away
    prefs = r.save_agy_prefs("offiagy", "")
    assert prefs["ui_runner"] == "offiagy" and prefs["offiagy_model"] == ""
    assert json.loads(r.OVERRIDE_FILE.read_text(encoding="utf-8")) == {"disabled": ["anyclaude"]}


def test_agy_prefs_back_to_defaults_leaves_no_empty_file(pkg, override, monkeypatch):
    r = pkg.runners
    monkeypatch.setattr(r, "offiagy_models", lambda **_k: [])
    if r.OVERRIDE_FILE.exists():
        r.OVERRIDE_FILE.unlink()
    r.save_agy_prefs("hermes", "gemini-4-neon-low")
    assert json.loads(r.OVERRIDE_FILE.read_text(encoding="utf-8")) == {
        "kinds": {"ui": "hermes"}, "offiagy_model": "gemini-4-neon-low"}
    assert r.kind_default("ui") == "hermes"
    r.save_agy_prefs("offiagy", "")
    assert not r.OVERRIDE_FILE.exists() and r.kind_default("ui") == "offiagy"


@pytest.mark.parametrize("ui_runner, model, message", [
    ("nope", None, "不能从"), (None, "bad model; rm -rf", "模型 ID"),
])
def test_agy_prefs_refuses_bad_values(pkg, override, ui_runner, model, message):
    override({"order": ["agy"]})
    with pytest.raises(ValueError, match=message):
        pkg.runners.save_agy_prefs(ui_runner, model)
    assert json.loads(pkg.runners.OVERRIDE_FILE.read_text(encoding="utf-8")) == {"order": ["agy"]}


def test_offiagy_models_parses_and_caches(pkg, monkeypatch):
    r = pkg.runners
    r._offiagy_models_cache.update(at=0.0, models=[], error="")
    calls = []

    class Done:
        returncode = 0
        stderr = ""
        stdout = (
            "\rFetching available models...\n"
            "gemini-4-neon-high\tGemini 4 Neon (High)\n"
            "claude-opus-5-5-high    Claude Opus 5.5 (High)\n"
        )

    def run(argv, **kwargs):
        calls.append(argv)
        return Done()

    monkeypatch.setattr(r, "_which", lambda name: "/stub/" + name)
    monkeypatch.setattr(r.subprocess, "run", run)
    assert [m["id"] for m in r.offiagy_models()] == ["gemini-4-neon-high", "claude-opus-5-5-high"]
    r.offiagy_models()
    assert calls == [["/stub/offiagy", "models"]]  # second call served from the cache
    # force=True bypasses the 1h cache
    r.offiagy_models(force=True)
    assert len(calls) == 2
    assert r._offiagy_models_cache["error"] == ""

    # when refresh fails, stale models stay usable while the error is surfaced
    def fail(argv, **kwargs):
        raise OSError("cli missing")

    monkeypatch.setattr(r.subprocess, "run", fail)
    kept = r.offiagy_models(force=True)
    assert [m["id"] for m in kept] == ["gemini-4-neon-high", "claude-opus-5-5-high"]
    prefs = r.agy_prefs()
    assert "cli missing" in prefs["offiagy_models_error"] and prefs["offiagy_models_at"] > 0
    r._offiagy_models_cache.update(at=0.0, models=[], error="")
