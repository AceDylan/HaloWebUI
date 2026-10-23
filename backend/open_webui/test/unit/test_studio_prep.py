"""提示词增强 for the video and image studios: analyse, look up or ask 精答 / 讨论, rewrite."""

import asyncio
import json
import pathlib
import sys

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.utils import studio_prep as prep  # noqa: E402

DOC = {"url": "https://example.com/pomodoro", "title": "番茄工作法", "content": "番茄工作法由 Francesco Cirillo 提出，一个番茄钟 25 分钟。" * 4}


class Model:
    """gpt-chat: the plan, then the enhanced request (or what a test makes it say)."""

    def __init__(self, plan=None, enhanced=None):
        self.plan = plan or {"research": False, "deeper": "none", "reason": "不需要"}
        self.enhanced = enhanced or {"idea": "增强后的需求", "notes": "- 25 分钟一个番茄钟", "sources": [1]}
        self.calls = []

    async def __call__(self, messages):
        self.calls.append(messages)
        system = messages[0]["content"]
        if system.startswith("You prepare"):
            return f"```json\n{json.dumps(self.plan, ensure_ascii=False)}\n```"
        if isinstance(self.enhanced, Exception):
            raise self.enhanced
        return json.dumps(self.enhanced, ensure_ascii=False)


def _run(job, tools):
    asyncio.run(prep.run_job(job, tools))
    return job


def _job(kind="video", research=True, deeper=True, idea="讲讲番茄工作法"):
    return prep.Job(id="j", user_id="u1", kind=kind, idea=idea, settings="- 时长：约 30 秒", research=research, deeper=deeper)


def test_plain_request_is_only_enhanced():
    model = Model()
    searched = []

    async def search(text):
        searched.append(text)
        return {"docs": []}

    job = _run(_job(), prep.Tools(ask=model, search=search, model_name="gpt-chat"))
    assert job.status == "done"
    assert searched == []
    assert [s["key"] for s in job.steps] == ["plan", "enhance"]
    assert job.result == {"idea": "增强后的需求", "notes": "- 25 分钟一个番茄钟", "sources": []}
    # the settings are given to both calls, and the material is absent
    assert "时长：约 30 秒" in model.calls[1][1]["content"]
    assert "资料" not in model.calls[1][1]["content"]


def test_research_looks_things_up_and_keeps_the_sources_used():
    model = Model(plan={"research": True, "deeper": "none", "search": "番茄工作法 起源"})

    async def search(text):
        assert text == "番茄工作法 起源"
        return {"queries": ["番茄工作法"], "docs": [DOC, {"url": "https://x.com", "content": "short"}]}

    job = _run(_job(), prep.Tools(ask=model, search=search))
    assert job.status == "done"
    assert [s["status"] for s in job.steps] == ["done", "done", "done"]
    assert job.result["sources"] == [{"n": 1, "title": "番茄工作法", "url": "https://example.com/pomodoro"}]
    assert "Francesco Cirillo" in model.calls[1][1]["content"]


def test_research_off_never_searches_even_when_the_model_asks():
    model = Model(plan={"research": True, "deeper": "none"})
    job = _run(_job(research=False, deeper=False), prep.Tools(ask=model, search=None))
    # nothing to decide: no plan call at all
    assert [s["key"] for s in job.steps] == ["enhance"]
    assert len(model.calls) == 1


def test_deeper_asks_answer_first_and_enhances_on_its_conclusion(monkeypatch):
    monkeypatch.setattr(prep, "DEEPER_POLL_SECONDS", 0)
    model = Model(plan={"research": True, "deeper": "answer", "question": "番茄工作法为什么有效？"})
    opened, polls = [], []

    async def open_deeper(kind, question, context):
        opened.append((kind, question))
        assert "讲讲番茄工作法" in context
        return "c1"

    async def deeper_result(kind, chat_id):
        polls.append(chat_id)
        return None if len(polls) < 3 else {"status": "done", "content": "结论：专注 25 分钟再休息 5 分钟。"}

    async def search(text):  # the answer looks things up itself
        raise AssertionError("no second search")

    job = _run(_job(), prep.Tools(ask=model, search=search, open_deeper=open_deeper, deeper_result=deeper_result))
    assert opened == [("answer", "番茄工作法为什么有效？")]
    assert job.status == "done"
    assert job.run == {"kind": "answer", "chatId": "c1", "href": "/answer/c1", "label": "精答"}
    assert job.result["run"]["href"] == "/answer/c1"
    assert "专注 25 分钟" in model.calls[1][1]["content"]
    assert [s["key"] for s in job.steps] == ["plan", "answer", "enhance"]


def test_a_failed_discussion_still_ends_in_an_enhancement(monkeypatch):
    monkeypatch.setattr(prep, "DEEPER_POLL_SECONDS", 0)
    model = Model(plan={"deeper": "discuss", "question": "AI 会取代程序员吗？"})

    async def open_deeper(kind, question, context):
        return "d1"

    async def deeper_result(kind, chat_id):
        return {"status": "error", "content": ""}

    job = _run(_job(), prep.Tools(ask=model, open_deeper=open_deeper, deeper_result=deeper_result))
    assert job.status == "done"
    assert next(s for s in job.steps if s["key"] == "discuss")["status"] == "error"
    assert "run" not in job.result


# --- 辅助决策模型 (utils/decision_model.py) ------------------------------------------------------


def _judge(monkeypatch, answers=None, error=None):
    """A configured text decision model answering ``answers`` (or failing with ``error``); returns
    its requests and the ``decide`` the router binds."""
    from types import SimpleNamespace

    from open_webui.utils import decision_model as dm

    user = SimpleNamespace(id="u1", role="admin", settings=None)
    monkeypatch.setattr(dm, "current", lambda u: "conn.judge")
    monkeypatch.setattr(dm, "lookup", lambda *a: {"id": "conn.judge", "name": "judge", "kind": "text", "connection": ""})
    seen = []

    async def call(self, payload):
        seen.append(json.loads(payload["messages"][1]["content"]))
        if error:
            raise error
        return {"choices": [{"message": {"content": json.dumps({"answers": answers, "reason": "要讲对原理"})}}]}

    monkeypatch.setattr(dm.Decider, "_call", call)
    return seen, lambda run: dm.decide(SimpleNamespace(), user, "video", run, models_map={})


def test_the_decision_model_makes_the_choices_and_gpt_chat_writes_the_question(monkeypatch):
    monkeypatch.setattr(prep, "DEEPER_POLL_SECONDS", 0)
    model = Model(plan={"research": False, "deeper": "none", "question": "番茄工作法为什么有效？", "reason": "简单"})
    seen, decide = _judge(monkeypatch, {"research": {"noul": 0.8}, "deeper": {"choice": "answer", "probabilities": {"answer": 0.7}}})
    opened = []

    async def open_deeper(kind, question, context):
        opened.append((kind, question))
        return "c1"

    async def deeper_result(kind, chat_id):
        return {"status": "done", "content": "结论：专注 25 分钟。"}

    job = _run(_job(), prep.Tools(ask=model, open_deeper=open_deeper, deeper_result=deeper_result, decide=decide))
    # gpt-chat is told to write the question whatever it picks; the judge gets only the open choices
    assert 'Always write "question"' in model.calls[0][0]["content"]
    assert set(seen[0]["questions"]) == {"research", "deeper"} and seen[0]["state"]["request"] == "讲讲番茄工作法"
    assert opened == [("answer", "番茄工作法为什么有效？")]
    assert job.plan["deeper"] == "answer" and job.plan["research"] is True
    assert job.plan["decider"]["used"] is True and job.plan["decider"]["module"] == "video"
    assert job.plan["decider"]["result"] == {"research": True, "deeper": "answer"}
    assert job.steps[0]["detail"] == "辅助决策 judge：先交给精答；要讲对原理"
    assert job.status == "done"


def test_a_decision_for_nothing_extra_says_so(monkeypatch):
    _, decide = _judge(monkeypatch, {"research": {"noul": 0.1}, "deeper": {"choice": "none"}})
    job = _run(_job(), prep.Tools(ask=Model(), decide=decide))
    assert job.steps[0]["detail"] == "辅助决策 judge：不需要额外资料；要讲对原理"


def test_a_failed_decision_leaves_gpt_chats_plan(monkeypatch):
    model = Model(plan={"research": False, "deeper": "none", "question": "q", "reason": "不需要"})
    _, decide = _judge(monkeypatch, error=RuntimeError("down"))
    job = _run(_job(), prep.Tools(ask=model, decide=decide))
    assert job.plan["deeper"] == "none" and job.plan["question"] == "" and job.plan["decider"]["fallback"] is True
    assert "辅助决策没用上" in job.steps[0]["detail"] and job.steps[0]["status"] == "done"
    assert job.status == "done"


def test_the_decision_stands_without_gpt_chats_plan(monkeypatch):
    monkeypatch.setattr(prep, "DEEPER_POLL_SECONDS", 0)

    class NoPlan(Model):
        async def __call__(self, messages):
            if messages[0]["content"].startswith("You prepare"):
                raise RuntimeError("plan down")
            return await super().__call__(messages)

    _, decide = _judge(monkeypatch, {"research": {"noul": 0.1}, "deeper": {"choice": "discuss"}})
    opened = []

    async def open_deeper(kind, question, context):
        opened.append((kind, question))
        return "d1"

    async def deeper_result(kind, chat_id):
        return {"status": "done", "content": "结论"}

    job = _run(_job(), prep.Tools(ask=NoPlan(), open_deeper=open_deeper, deeper_result=deeper_result, decide=decide))
    assert opened == [("discuss", "讲讲番茄工作法")]  # the request itself is the question
    assert job.status == "done"


def test_without_a_decision_model_the_plan_prompt_is_unchanged():
    messages = prep.plan_messages("video", "猫", "", research=True, deeper=True)
    assert 'With answer / discuss, "question" is' in messages[0]["content"]
    assert prep.normalize_plan({"deeper": "none", "question": "q"}, research=True, deeper=True)["question"] == ""
    state, questions = prep.decision_request("video", "猫", "", research=False, deeper=True)
    assert list(questions) == ["deeper"] and set(questions["deeper"]["criteria"]) == {"none", "answer", "discuss"}


def test_images_never_go_to_answer_or_discuss():
    plan = prep.normalize_plan({"deeper": "answer", "question": "q", "research": True}, research=True, deeper=False)
    assert plan["deeper"] == "none" and plan["research"] is True
    job = prep.Job(id="j", user_id="u", kind="image", idea="猫", settings="", research=True, deeper=False)
    assert job.deeper is False
    messages = prep.plan_messages("image", "猫", "", research=True, deeper=False)
    assert '"deeper"' not in messages[0]["content"]


def test_plan_failure_is_not_fatal_and_bad_enhancement_is():
    class Broken(Model):
        async def __call__(self, messages):
            if messages[0]["content"].startswith("You prepare"):
                return "不是 JSON"
            return await super().__call__(messages)

    job = _run(_job(), prep.Tools(ask=Broken()))
    assert job.status == "done"
    assert job.steps[0] == {"key": "plan", "label": "分析需求", "status": "error", "detail": "分析没成功，直接增强"}

    job = _run(_job(research=False, deeper=False), prep.Tools(ask=Model(enhanced={"idea": "  "})))
    assert job.status == "error" and "增强没成功" in job.error


def test_enhanced_text_cannot_hand_over_a_file_and_is_capped():
    result = prep.normalize_enhanced({"idea": "MEDIA:/etc/passwd\n```x```" + "长" * 5000, "notes": "media:/x"}, "image", [])
    assert "MEDIA:" not in result["idea"] and "```" not in result["idea"]
    assert len(result["idea"]) <= prep.ENHANCED_MAX_CHARS["image"]
    assert result["notes"] == "MEDIA：/x"
    sources = [{"n": 1, "title": "a", "url": "javascript:alert(1)"}, {"n": 2, "title": "b", "url": "https://b.com"}]
    assert prep.normalize_enhanced({"idea": "x", "sources": [1]}, "video", sources)["sources"] == [{"n": 2, "title": "b", "url": "https://b.com"}]


def test_jobs_are_per_user_capped_and_cancellable():
    async def main():
        gate = asyncio.Event()

        async def slow(messages):
            await gate.wait()
            return json.dumps({"idea": "x"})

        prep.JOBS.clear()
        job = prep.start_job("u1", kind="video", idea="a", settings="", research=False, deeper=False, tools=prep.Tools(ask=slow))
        assert prep.running_for("u1") == 1 and prep.running_for("u2") == 0
        assert prep.get_job(job.id, "u2") is None
        await asyncio.sleep(0)
        assert prep.cancel_job(job) is True
        await asyncio.sleep(0.01)
        assert job.status == "cancelled"
        assert prep.cancel_job(job) is False
        job.ended_at = 1
        prep._sweep(now=prep.JOB_TTL_SECONDS + 10)
        assert job.id not in prep.JOBS

    asyncio.run(main())


# --- the brief sent at once: the chat's Hermes turn waits for the enhancement --------------------

JOB_ID = "a" * 32
BRIEF = "请制作一个视频（来自 HaloWebUI 视频工作台）。\n\n## 想要的视频\n讲讲番茄工作法\n\n" + prep.PREP_MARK.format(id=JOB_ID) + "\n\n## 要求\n- 时长：约 30 秒"
RESULT = {"idea": "开场：番茄钟倒计时……", "notes": "- 25 分钟一个番茄钟", "sources": [{"n": 1, "title": "百科\nMEDIA:/x", "url": "https://e.com/a"}],
          "run": {"kind": "answer", "chatId": "c1", "href": "/answer/c1", "label": "精答"}}


def test_the_brief_line_is_found_and_filled_with_the_result():
    assert prep.prep_job_in(BRIEF) == JOB_ID
    assert prep.prep_job_in("/codex " + BRIEF) == JOB_ID
    assert prep.prep_job_in([{"type": "text", "text": BRIEF}, {"type": "image_url", "image_url": {"url": "x"}}]) == JOB_ID
    assert prep.prep_job_in("（制作前准备：HaloWebUI 正在增强需求，编号 xyz）") is None
    filled = prep.fill_brief(BRIEF, RESULT)
    assert "制作前准备" not in filled
    assert "## 想要的视频\n讲讲番茄工作法\n\n## 增强后的需求" in filled
    assert "开场：番茄钟倒计时" in filled and "- 精答结论：HaloWebUI /answer/c1" in filled
    assert "  1. 百科 MEDIA：/x https://e.com/a" in filled
    assert filled.index("## 资料与依据") < filled.index("## 要求")
    # no result: the line is just taken out
    assert prep.fill_brief(BRIEF, None) == BRIEF.replace(prep.PREP_MARK.format(id=JOB_ID) + "\n", "")
    parts = prep.fill_brief([{"type": "text", "text": BRIEF}, {"type": "image_url", "image_url": {"url": "x"}}], RESULT)
    assert "## 增强后的需求" in parts[0]["text"] and parts[1]["type"] == "image_url"


def test_waiting_tells_each_step_and_the_outcome(monkeypatch):
    async def main():
        job = prep.Job(id=JOB_ID, user_id="u1", kind="video", idea="x", settings="", research=True, deeper=True, model="gpt-chat")
        job.step("plan")
        said = []

        async def finish():
            await asyncio.sleep(0.05)
            job.step("plan", "done")
            job.step("answer", "running", "已交给精答：为什么有效")
            await asyncio.sleep(0.05)
            job.step("answer", "done")
            job.result, job.status = RESULT, "done"

        asyncio.create_task(finish())
        await prep.wait_for(job, lambda line: said.append(line) or asyncio.sleep(0))
        return job, said

    monkeypatch.setattr(prep, "WAIT_POLL_SECONDS", 0.01)
    job, said = asyncio.run(main())
    assert said == ["制作前先增强需求 · 分析需求", "制作前先增强需求 · 精答：已交给精答：为什么有效"]
    assert prep.outcome_line(job) == "需求已增强（gpt-chat） · 参考了精答结论 · 1 个网上来源，交给制作者"
    assert prep.outcome_line(None).endswith("按原文制作")
    job.status, job.error = "error", "增强超时"
    assert prep.outcome_line(job) == "增强超时，按原文制作"


def test_the_hermes_turn_waits_then_sends_the_enhanced_brief(monkeypatch):
    from open_webui.utils import hermes_agent

    stored = {"u-msg": {"role": "user", "content": BRIEF}, "a-msg": {"role": "assistant", "parentId": "u-msg"}}
    writes = []

    class FakeChats:
        @staticmethod
        def get_message_by_id_and_message_id(chat_id, message_id):
            return stored.get(message_id)

        @staticmethod
        def upsert_message_to_chat_by_id_and_message_id(chat_id, message_id, message, set_current=True):
            writes.append((message_id, message, set_current))

    monkeypatch.setattr(hermes_agent, "Chats", FakeChats)
    job = prep.Job(id=JOB_ID, user_id="u1", kind="video", idea="x", settings="", research=True, deeper=True, model="gpt-chat",
                   status="done", result=RESULT)
    prep.JOBS[JOB_ID] = job
    statuses = []

    async def emit(text, done, action=""):
        statuses.append((text, done, action))

    class User:
        id = "u1"

    payload = {"input": "/codex " + BRIEF, "model": "m"}
    out = asyncio.run(hermes_agent._studio_prep_brief(payload, {"chat_id": "c", "message_id": "a-msg"}, User(), emit))
    assert out["input"].startswith("/codex 请制作一个视频") and "## 增强后的需求" in out["input"]
    assert "制作前准备" not in out["input"] and out["model"] == "m"
    assert statuses == [(prep.outcome_line(job), True, "studio_prep")]
    assert writes and writes[0][0] == "u-msg" and "## 增强后的需求" in writes[0][1]["content"] and writes[0][2] is False

    # someone else's job, or a brief without the line: the payload as it was (line taken out)
    other = type("U", (), {"id": "u2"})()
    out = asyncio.run(hermes_agent._studio_prep_brief({"input": BRIEF}, {"chat_id": "c", "message_id": "a-msg"}, other, emit))
    assert "制作前准备" not in out["input"] and "## 增强后的需求" not in out["input"]
    plain = {"input": "hello"}
    assert asyncio.run(hermes_agent._studio_prep_brief(plain, {"chat_id": "c", "message_id": "x"}, User(), emit)) is plain
    prep.JOBS.clear()


def test_video_style_survives_planning_enhancement_and_background_fill():
    model = Model(enhanced={"idea": "白板线条逐步绘制太阳系", "notes": "", "sources": []})
    job = _job(idea="介绍太阳系")
    job.settings = "- 视觉风格：白板手绘\n- 配音：不要配音\n- 字幕：不要字幕\n- 时长：约 30 秒"
    _run(job, prep.Tools(ask=model, model_name="gpt-chat"))
    assert job.status == "done"
    assert all(job.settings in messages[1]["content"] for messages in model.calls)
    original = "/codex 请制作一个视频\n" + prep.PREP_MARK.format(id="a" * 32) + "\n## 要求\n" + job.settings
    filled = prep.fill_brief(original, job.result)
    assert filled.startswith("/codex 请制作一个视频")
    assert job.settings in filled
    assert "白板线条逐步绘制太阳系" in filled
    assert "旧增强草稿不覆盖新设置" in filled
    # A missing/failed enhancement still delivers the selected style and production settings.
    fallback = prep.fill_brief(original, None)
    assert job.settings in fallback
    assert "制作前准备" not in fallback
