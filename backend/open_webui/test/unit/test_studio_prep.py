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
