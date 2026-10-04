"""讨论台 engine: setup validation, prompts, stream parsing and the parallel runner."""

import asyncio
import json
import pathlib
import sys
from types import SimpleNamespace

import pytest

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.utils import discussion_room as room  # noqa: E402


def _models(*ids):
    return {model_id: {"id": model_id, "name": model_id} for model_id in ids}


def _user(role="admin"):
    return SimpleNamespace(id="u1", role=role)


def _no_exclusion(model):
    return None


def _setup(mode="roundtable", seats=("a", "b"), rounds=None, moderator=None, roles=None):
    raw = {
        "mode": mode,
        "seats": [{"model": seat, "role": (roles or {}).get(index, "")} for index, seat in enumerate(seats)],
        "rounds": rounds,
        "moderator": moderator,
    }
    return room.normalize_setup(raw, _models("a", "b", "c", "hermes", "img"), set(), _user(), _no_exclusion)


# --- setup ------------------------------------------------------------------------------------


def test_setup_needs_two_seats_and_at_most_five():
    with pytest.raises(room.DiscussError) as low:
        _setup(seats=("a",))
    assert low.value.status_code == 400
    with pytest.raises(room.DiscussError):
        _setup(seats=("a", "b", "c", "a", "b", "c"))


def test_setup_rejects_excluded_models_with_their_reason():
    def excluded(model):
        return "Hermes 不参加讨论" if model["id"] == "hermes" else None

    with pytest.raises(room.DiscussError) as err:
        room.normalize_setup({"seats": ["a", "hermes"]}, _models("a", "hermes"), set(), _user(), excluded)
    assert "Hermes" in err.value.detail
    with pytest.raises(room.DiscussError):
        room.normalize_setup(
            {"seats": ["a", "b"], "moderator": "hermes"}, _models("a", "b", "hermes"), set(), _user(), excluded
        )


def test_setup_defaults_and_clamps():
    setup = _setup(rounds=99)
    assert setup["mode"] == "roundtable"
    assert setup["rounds"] == room.MAX_ROUNDS
    assert setup["moderator"] == {"model": "a", "name": "a", "vision": True}  # first seat by default
    assert [seat["id"] for seat in setup["seats"]] == ["s1", "s2"]
    assert _setup(mode="nonsense")["mode"] == "roundtable"
    assert _setup(mode="review", rounds=4)["rounds"] == 2  # answer + review, always


def test_debate_fills_sides_and_duplicate_models_are_told_apart():
    setup = _setup(mode="debate", seats=("a", "a"))
    assert [seat["role"] for seat in setup["seats"]] == ["正方", "反方"]
    assert [seat["label"] for seat in setup["seats"]] == ["a·正方", "a·反方"]
    plain = _setup(seats=("a", "a", "b"))
    assert [seat["label"] for seat in plain["seats"]] == ["a #1", "a #2", "b"]


def test_custom_roles_are_kept_and_trimmed():
    setup = _setup(roles={0: "产品经理" * 20})
    assert setup["seats"][0]["role"] == ("产品经理" * 20)[: room.ROLE_MAX_CHARS]


# --- prompts ----------------------------------------------------------------------------------


def _ask(setup, question="如何选数据库？"):
    return room.new_ask(question=question, setup=setup, user_message_id="u-1", message_id="m-1")


def _done(ask, round_index, seat, content):
    ask["turns"].append({"id": f"r{round_index}-{seat}", "round": round_index, "seat": seat, "status": "done", "content": content})


def test_round_one_is_independent_and_later_rounds_see_the_transcript():
    setup = _setup()
    ask = _ask(setup)
    first = room.build_turn_messages(setup=setup, ask=ask, seat=setup["seats"][0], round_index=1, history=[])
    assert first[0]["role"] == "system" and "Simplified Chinese" in first[0]["content"]
    assert "independent answer" in first[1]["content"]
    assert "Discussion so far" not in first[1]["content"]

    _done(ask, 1, "s1", "用 Postgres")
    _done(ask, 1, "s2", "用 SQLite")
    ask["turns"].append({"id": "r1-x", "round": 1, "seat": "s2", "status": "error", "content": "half"})
    second = room.build_turn_messages(setup=setup, ask=ask, seat=setup["seats"][0], round_index=2, history=[])
    text = second[1]["content"]
    assert "### a\n用 Postgres" in text and "### b\n用 SQLite" in text
    assert "half" not in text  # failed turns are not evidence


def test_review_round_two_is_anonymous():
    setup = _setup(mode="review", seats=("a", "b", "c"))
    ask = _ask(setup)
    for seat, content in (("s1", "答案甲"), ("s2", "答案乙"), ("s3", "答案丙")):
        _done(ask, 1, seat, content)
    text = room.build_turn_messages(setup=setup, ask=ask, seat=setup["seats"][1], round_index=2, history=[])[1]["content"]
    assert "### Your own answer\n答案乙" in text
    assert "### Answer A\n答案甲" in text and "### Answer B\n答案丙" in text
    assert "### a" not in text and "### c" not in text
    assert "score from 1 to 10" in text


def test_interjections_reach_later_rounds_and_the_moderator():
    setup = _setup()
    ask = _ask(setup)
    _done(ask, 1, "s1", "x")
    ask["interjections"].append({"text": "预算只有 100 元", "afterRound": 1})
    in_round_one = room.build_turn_messages(setup=setup, ask=ask, seat=setup["seats"][0], round_index=1, history=[])
    in_round_two = room.build_turn_messages(setup=setup, ask=ask, seat=setup["seats"][0], round_index=2, history=[])
    assert "预算只有 100 元" not in in_round_one[1]["content"]
    assert "预算只有 100 元" in in_round_two[1]["content"]
    conclusion = room.build_conclusion_messages(setup=setup, ask=ask, history=[])
    assert "预算只有 100 元" in conclusion[1]["content"]


def test_follow_ups_carry_earlier_conclusions():
    setup = _setup()
    ask = _ask(setup, "那备份呢？")
    messages = room.build_turn_messages(
        setup=setup, ask=ask, seat=setup["seats"][0], round_index=1,
        history=[{"question": "如何选数据库？", "conclusion": "## 结论\n用 Postgres"}],
    )
    assert "Earlier question: 如何选数据库？" in messages[1]["content"]
    assert "用 Postgres" in messages[1]["content"]


def test_conclusion_headings_follow_the_question_language():
    setup = _setup()
    zh = room.build_conclusion_messages(setup=setup, ask=_ask(setup), history=[])[0]["content"]
    assert "## 结论" in zh and "## 分歧" in zh and "## 各方立场" in zh
    en = room.build_conclusion_messages(setup=setup, ask=_ask(setup, "Which database?"), history=[])[0]["content"]
    assert "## Conclusion" in en and "## Disagreements" in en


def test_parse_conclusion_sections_and_answer():
    content = "## 结论\n用 Postgres。\n\n## 共识\n- 要备份\n## 分歧\n- 无"
    sections = room.parse_conclusion_sections(content)
    assert [s["title"] for s in sections] == ["结论", "共识", "分歧"]
    assert room.conclusion_answer(content) == "用 Postgres。"
    assert room.conclusion_answer("没有标题的回答") == "没有标题的回答"


# --- streams ----------------------------------------------------------------------------------


class _Stream:
    def __init__(self, chunks, delay=0.0):
        self.chunks = chunks
        self.delay = delay

    @property
    def body_iterator(self):
        async def gen():
            for chunk in self.chunks:
                if self.delay:
                    await asyncio.sleep(self.delay)
                yield chunk

        return gen()


def _sse(*items):
    out = []
    for item in items:
        if isinstance(item, str):
            out.append(f'data: {json.dumps({"choices": [{"delta": {"content": item}}]}, ensure_ascii=False)}\n\n')
        else:
            out.append(f"data: {json.dumps(item, ensure_ascii=False)}\n\n")
    out.append("data: [DONE]\n\n")
    return out


def _collect(response):
    async def run():
        return [item async for item in room.iterate_completion(response)]

    return asyncio.run(run())


def test_iterate_completion_reads_sse_split_across_chunks():
    raw = "".join(_sse("你好", {"choices": [{"delta": {"reasoning_content": "想"}}]}, "世界", {"usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}))
    pieces = [raw[i : i + 7].encode() for i in range(0, len(raw), 7)]
    items = _collect(_Stream(pieces))
    assert ("content", "你好") in items and ("content", "世界") in items
    assert ("reasoning", "想") in items
    assert ("usage", {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}) in items


def test_iterate_completion_raises_on_an_error_chunk_and_reads_plain_dicts():
    with pytest.raises(ValueError, match="quota"):
        _collect(_Stream(_sse("a", {"error": {"message": "quota exceeded"}})))
    assert _collect({"choices": [{"message": {"content": "整段"}}]}) == [("content", "整段")]
    with pytest.raises(ValueError):
        _collect({"detail": "Model not found"})


def test_strip_think():
    assert room.strip_think("<think>先想想</think>答案") == "答案"
    assert room.strip_think("<think>还在想") == ""


# --- runner -----------------------------------------------------------------------------------


def _live(setup, replies, *, delay=0.0, persist=None, after_done=None):
    """replies: model -> list of streams/exceptions, consumed in call order."""
    events, calls, saved = [], [], []
    queues = {model: list(items) for model, items in replies.items()}

    async def emit(event):
        events.append(event)

    async def call_model(model, messages):
        calls.append((model, messages))
        item = queues[model].pop(0)
        if isinstance(item, Exception):
            raise item
        return _Stream(_sse(*item), delay=delay) if isinstance(item, list) else item

    live = room.LiveDiscussion(
        chat_id="c1",
        user_id="u1",
        setup=setup,
        ask=_ask(setup),
        history=[],
        emit=emit,
        call_model=call_model,
        persist=persist or (lambda ask: saved.append(json.loads(json.dumps(ask)))),
        after_done=after_done,
        retry_delays=(0, 0, 0),
        stand_in_delays=(0,),
    )
    return live, events, calls, saved


def test_a_discussion_runs_rounds_in_parallel_then_concludes():
    setup = _setup(rounds=2, moderator="c")
    done_hook = []

    async def after_done(ask):
        done_hook.append(ask["status"])

    live, events, calls, saved = _live(
        setup,
        {"a": [["A1"], ["A2"]], "b": [["B", "1"], ["B2"]], "c": [["## 结论\n", "好"]]},
        after_done=after_done,
    )
    asyncio.run(live.run())
    ask = live.ask
    assert ask["status"] == "done"
    assert [(t["id"], t["status"], t["content"]) for t in ask["turns"]] == [
        ("r1-s1", "done", "A1"), ("r1-s2", "done", "B1"), ("r2-s1", "done", "A2"), ("r2-s2", "done", "B2"),
    ]
    assert ask["conclusion"]["status"] == "done" and ask["conclusion"]["content"] == "## 结论\n好"
    assert [model for model, _ in calls] == ["a", "b", "a", "b", "c"]
    kinds = [event["data"]["kind"] for event in events]
    assert kinds[0] == "state" and kinds[-1] == "end" and "delta" in kinds and "turn" in kinds
    versions = [event["data"]["v"] for event in events]
    assert versions == sorted(versions)
    assert saved[-1]["status"] == "done"
    assert done_hook == ["done"]
    assert "c1" not in room.LIVE


def test_a_failing_seat_sits_out_and_the_rest_goes_on():
    setup = _setup(rounds=1)  # the moderator is seat a's model: it fails as a seat, then concludes
    live, events, calls, saved = _live(
        setup, {"a": [RuntimeError("model refused"), ["## 结论\n只有 b 的观点"]], "b": [["B1"]]}
    )
    asyncio.run(live.run())
    statuses = {t["id"]: (t["status"], t.get("error")) for t in live.ask["turns"]}
    assert statuses["r1-s1"] == ("error", "model refused")
    assert statuses["r1-s2"] == ("done", None)
    assert live.ask["status"] == "done"


def test_when_every_seat_fails_round_one_the_question_errors():
    setup = _setup(rounds=2)
    live, events, calls, saved = _live(setup, {"a": [RuntimeError("down")], "b": [RuntimeError("down")]})
    asyncio.run(live.run())
    assert live.ask["status"] == "error"
    assert "第一轮" in live.ask["error"]
    assert events[-1]["data"] == {**events[-1]["data"], "kind": "end", "status": "error"}


def test_stopping_marks_running_turns_stopped():
    setup = _setup(rounds=2)
    live, events, calls, saved = _live(setup, {"a": [["x"] * 50], "b": [["y"] * 50]}, delay=0.02)

    async def scenario():
        task = asyncio.create_task(live.run())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert live.ask["status"] == "stopped"
    assert {t["status"] for t in live.ask["turns"]} == {"stopped"}
    assert saved[-1]["status"] == "stopped"


def test_conclude_only_and_continue_from_a_round():
    setup = _setup(rounds=1)
    live, events, calls, saved = _live(setup, {"a": [["## 结论\n总结"]]})
    _done(live.ask, 1, "s1", "x")
    live.conclude_only = True
    asyncio.run(live.run())
    assert [model for model, _ in calls] == ["a"]
    assert live.ask["status"] == "done"

    live2, _, calls2, _ = _live(setup, {"a": [["A2"], ["## 结论\n新"]], "b": [["B2"]]})
    _done(live2.ask, 1, "s1", "x")
    _done(live2.ask, 1, "s2", "y")
    live2.ask["conclusion"] = {"status": "done", "content": "## 结论\n旧", "model": "a", "name": "a"}
    live2.ask["rounds"] = 2
    live2.from_round = 2
    asyncio.run(live2.run())
    assert [t["id"] for t in live2.ask["turns"]] == ["r1-s1", "r1-s2", "r2-s1", "r2-s2"]
    assert live2.ask["previousConclusions"][0]["content"] == "## 结论\n旧"
    assert live2.ask["conclusion"]["content"] == "## 结论\n新"


def test_queue_delta_appends_and_replaces():
    setup = _setup()
    live, *_ = _live(setup, {})
    live.queue_delta("t", 0, "ab")
    live.queue_delta("t", 2, "cd")
    assert live.pending["t"] == {"t": "t", "o": 0, "x": "abcd"}
    live.queue_delta("t", 1, "Z")
    assert live.pending["t"] == {"t": "t", "o": 0, "x": "aZ"}
    live.queue_delta("t", 0, "new")
    assert live.pending["t"] == {"t": "t", "o": 0, "x": "new"}


def test_summary_meta_previews_the_answer():
    setup = _setup()
    ask = _ask(setup)
    ask["conclusion"]["content"] = "## 结论\n**用 Postgres**，因为……\n## 共识\n- x"
    ask["status"] = "done"
    meta = room.summary_meta(setup, [ask])
    assert meta["status"] == "done" and meta["asks"] == 1
    assert meta["preview"].startswith("用 Postgres")
    assert [seat["name"] for seat in meta["seats"]] == ["a", "b"]


def test_sections_drop_the_separators_between_them():
    content = "## 结论\n用 Postgres。\n\n---\n\n## 共识\n- 要备份\n\n***\n## 分歧\n- 无\n---"
    sections = room.parse_conclusion_sections(content)
    assert [s["body"] for s in sections] == ["用 Postgres。", "- 要备份", "- 无"]


def test_previews_are_plain_text_without_stray_spaces():
    setup = _setup()
    ask = _ask(setup)
    ask["conclusion"]["content"] = "## 结论\n对多数人而言，**手机 App 是更好的选择**。\n- 看 [文档](http://x) 和 `代码`"
    meta = room.summary_meta(setup, [ask])
    assert meta["preview"] == "对多数人而言，手机 App 是更好的选择。 看 文档 和 代码"


# --- research & retry --------------------------------------------------------------------------


def test_research_runs_first_and_every_prompt_carries_the_numbered_notes():
    raw = {"mode": "roundtable", "seats": ["a", "b"], "rounds": 1, "research": True}
    setup = room.normalize_setup(raw, _models("a", "b"), set(), _user(), _no_exclusion)
    assert setup["research"] is True
    live, events, calls, saved = _live(setup, {"a": [["A1"], ["## 结论\n见 [1]"]], "b": [["B1"]]})
    assert live.ask["research"]["status"] == "waiting"
    searched = []

    async def search(question, history):
        searched.append(question)
        long = "Postgres 是一个开源关系数据库。" * 10
        return {
            "queries": ["postgres vs mongodb"],
            "docs": [
                {"url": "https://a.example", "title": "A", "content": long},
                {"url": "https://a.example", "title": "A again", "content": long},
                {"url": "https://b.example", "title": "B", "content": "too short"},
                {"url": "https://c.example", "title": "", "content": long},
            ],
        }

    live.search = search
    asyncio.run(live.run())
    research = live.ask["research"]
    assert searched == ["如何选数据库？"]
    assert research["status"] == "done" and research["queries"] == ["postgres vs mongodb"]
    assert [(s["n"], s["url"]) for s in research["sources"]] == [(1, "https://a.example"), (2, "https://c.example")]
    assert research["sources"][1]["title"] == "https://c.example"
    turn_prompt = calls[0][1][1]["content"]
    assert "[1] A — https://a.example" in turn_prompt and "Cite them as [n]" in turn_prompt
    assert "Beyond the research notes you cannot browse" in calls[0][1][0]["content"]
    moderator = calls[-1][1]
    assert "[2]" in moderator[1]["content"] and "Keep the [n] citations" in moderator[0]["content"]
    assert live.ask["status"] == "done"


def test_a_failed_search_does_not_stop_the_discussion():
    setup = room.normalize_setup({"seats": ["a", "b"], "rounds": 1, "research": True}, _models("a", "b"), set(), _user(), _no_exclusion)
    live, events, calls, saved = _live(setup, {"a": [["A1"], ["## 结论\nok"]], "b": [["B1"]]})

    async def search(question, history):
        raise RuntimeError("smart search down")

    live.search = search
    asyncio.run(live.run())
    assert live.ask["research"]["status"] == "error" and "smart search down" in live.ask["research"]["error"]
    assert "Research notes" not in calls[0][1][1]["content"]
    assert live.ask["status"] == "done"


def test_no_research_unless_asked():
    setup = _setup(rounds=1)
    assert setup["research"] is False
    assert _ask(setup)["research"] is None


def test_retry_runs_one_turn_then_concludes_again():
    setup = _setup(rounds=1)
    live, events, calls, saved = _live(setup, {"b": [["B 重试成功"]], "a": [["## 结论\n新"]]})
    _done(live.ask, 1, "s1", "A1")
    live.ask["turns"].append({"id": "r1-s2", "round": 1, "seat": "s2", "status": "error", "content": "", "error": "429"})
    live.ask["conclusion"] = {"status": "done", "content": "## 结论\n旧", "model": "a", "name": "a"}
    live.retry_turn = "r1-s2"
    asyncio.run(live.run())
    assert [model for model, _ in calls] == ["b", "a"]
    turn = live.ask["turns"][1]
    assert (turn["status"], turn["content"], turn.get("error")) == ("done", "B 重试成功", None)
    assert live.ask["conclusion"]["content"] == "## 结论\n新"
    assert live.ask["previousConclusions"][0]["content"] == "## 结论\n旧"
    assert live.ask["status"] == "done"


# --- self-repair ---------------------------------------------------------------------------------


RATE_LIMIT = "Your requests to gpt-6-astra for gpt-6-astra in eastus2 have exceeded token rate limit."


def test_passing_failures_are_told_apart_from_lasting_ones():
    assert room.transient_reason(ValueError(RATE_LIMIT)) == "限流"
    assert room.transient_reason(room.UpstreamError("slow down", 429)) == "限流"
    assert room.transient_reason(RuntimeError("503 Service Unavailable")) == "上游繁忙"
    assert room.transient_reason(ConnectionResetError("Connection reset by peer")) == "连接中断"
    assert room.transient_reason(ValueError("模型返回了空内容")) == "空回复"
    assert room.transient_reason(RuntimeError("model refused")) is None
    assert room.transient_reason(ValueError("You exceeded your current quota: insufficient_quota")) is None
    assert room.transient_reason(asyncio.TimeoutError()) is None
    assert room.retry_wait(ValueError("Please retry after 30 seconds."), 8) == 31
    assert room.retry_wait(ValueError("Please retry after 600 seconds."), 8) == room.RETRY_MAX_WAIT
    assert room.retry_wait(ValueError(RATE_LIMIT), 20) == 20


def test_a_rate_limited_turn_waits_and_tries_again():
    setup = _setup(rounds=1, moderator="c")
    live, events, calls, saved = _live(
        setup, {"a": [ValueError(RATE_LIMIT), ["A1"]], "b": [["B1"]], "c": [["## 结论\n好"]]}
    )
    asyncio.run(live.run())
    turn = live.ask["turns"][0]
    assert (turn["status"], turn["content"], turn.get("retry")) == ("done", "A1", None)
    assert [model for model, _ in calls].count("a") == 2
    waits = [e["data"]["turn"]["retry"] for e in events if e["data"]["kind"] == "turn" and e["data"]["turn"].get("retry")]
    assert waits and waits[0]["reason"] == "限流" and waits[0]["n"] == 1 and waits[0]["of"] == 3
    assert live.ask["status"] == "done"


def test_a_turn_gives_up_after_its_retries():
    setup = _setup(rounds=1, moderator="c")
    live, events, calls, saved = _live(
        setup, {"a": [ValueError(RATE_LIMIT)] * 4, "b": [["B1"]], "c": [["## 结论\n好"]]}
    )
    asyncio.run(live.run())
    turn = live.ask["turns"][0]
    assert turn["status"] == "error" and "rate limit" in turn["error"] and turn.get("retry") is None
    assert [model for model, _ in calls].count("a") == 4
    assert live.ask["status"] == "done"  # the rest of the table still reaches a conclusion


def test_a_moderator_that_stays_rate_limited_hands_the_conclusion_to_a_seat():
    setup = _setup(rounds=1, moderator="c")
    live, events, calls, saved = _live(
        setup,
        {"a": [["A1"], ["## 结论\n由 a 代写"]], "b": [["B1"]], "c": [ValueError(RATE_LIMIT)] * 4},
    )
    asyncio.run(live.run())
    conclusion = live.ask["conclusion"]
    assert live.ask["status"] == "done"
    assert conclusion["content"] == "## 结论\n由 a 代写"
    assert (conclusion["model"], conclusion["name"]) == ("a", "a")
    assert conclusion["standIn"]["for"] == "c" and conclusion["standIn"]["reason"] == "限流"
    assert [model for model, _ in calls][-5:] == ["c", "c", "c", "c", "a"]
    # the stand-in writes the moderator's conclusion, with the whole transcript
    assert calls[-1][1][0]["content"].startswith("You moderated")


def test_the_conclusion_errors_only_when_every_writer_fails():
    setup = _setup(rounds=1, moderator="c")
    live, events, calls, saved = _live(
        setup,
        {"a": [["A1"], RuntimeError("a refused")], "b": [["B1"], RuntimeError("b refused")], "c": [RuntimeError("c refused")]},
    )
    asyncio.run(live.run())
    assert live.ask["status"] == "error" and live.ask["error"] == "c refused"
    assert live.ask["conclusion"]["status"] == "error"


def test_resume_reruns_the_unfinished_round_then_the_rest():
    setup = _setup(rounds=2, moderator="c")
    live, events, calls, saved = _live(
        setup, {"a": [["A1 again"], ["A2"]], "b": [["B2"]], "c": [["## 结论\n续上了"]]}
    )
    live.ask["turns"] = [
        {"id": "r1-s1", "round": 1, "seat": "s1", "status": "error", "content": "", "error": "rate limit"},
        {"id": "r1-s2", "round": 1, "seat": "s2", "status": "done", "content": "B1"},
    ]
    live.ask["status"] = "running"
    live.resume = True
    asyncio.run(live.run())
    assert [(t["id"], t["status"], t["content"]) for t in live.ask["turns"]] == [
        ("r1-s1", "done", "A1 again"), ("r1-s2", "done", "B1"), ("r2-s1", "done", "A2"), ("r2-s2", "done", "B2"),
    ]
    assert [model for model, _ in calls] == ["a", "a", "b", "c"]
    assert live.ask["status"] == "done" and live.ask["conclusion"]["content"] == "## 结论\n续上了"


def test_resume_after_a_failed_conclusion_only_writes_the_conclusion():
    setup = _setup(rounds=1, moderator="c")
    live, events, calls, saved = _live(setup, {"c": [["## 结论\n补上"]]})
    _done(live.ask, 1, "s1", "A1")
    _done(live.ask, 1, "s2", "B1")
    live.ask["conclusion"] = {"status": "error", "content": "", "model": "c", "name": "c", "error": RATE_LIMIT}
    live.resume = True
    asyncio.run(live.run())
    assert [model for model, _ in calls] == ["c"]
    assert live.ask["status"] == "done"


# --- attachments --------------------------------------------------------------------------------


def test_seats_know_whether_their_model_reads_images():
    models = {
        "a": {"id": "a", "name": "a"},
        "blind": {"id": "blind", "name": "blind", "info": {"meta": {"capabilities": {"vision": False}}}},
    }
    setup = room.normalize_setup({"seats": ["a", "blind"], "moderator": "blind"}, models, set(), _user(), _no_exclusion)
    assert [seat["vision"] for seat in setup["seats"]] == [True, False]
    assert setup["moderator"]["vision"] is False


def test_images_go_to_seeing_seats_in_round_one_and_documents_to_everyone():
    models = {
        "a": {"id": "a", "name": "a"},
        "blind": {"id": "blind", "name": "blind", "info": {"meta": {"capabilities": {"vision": False}}}},
    }
    setup = room.normalize_setup({"seats": ["a", "blind"], "rounds": 2, "moderator": "a"}, models, set(), _user(), _no_exclusion)
    ask = room.new_ask(
        question="哪张图的配色好？",
        setup=setup,
        user_message_id="u",
        message_id="m",
        files=[
            {"id": "f1", "name": "a.png", "type": "image"},
            {"id": "f2", "name": "方案.docx", "type": "file", "text": "预算 10 万"},
        ],
    )
    images = ["data:image/png;base64,AAA"]
    seeing = room.build_turn_messages(setup=setup, ask=ask, seat=setup["seats"][0], round_index=1, history=[], images=images)
    content = seeing[1]["content"]
    assert isinstance(content, list) and content[1] == {"type": "image_url", "image_url": {"url": images[0]}}
    assert "Attached file «方案.docx»:\n预算 10 万" in content[0]["text"]
    assert "included with this message" in content[0]["text"]
    blind = room.build_turn_messages(setup=setup, ask=ask, seat=setup["seats"][1], round_index=1, history=[], images=images)
    assert isinstance(blind[1]["content"], str) and "cannot see" in blind[1]["content"]
    later = room.build_turn_messages(setup=setup, ask=ask, seat=setup["seats"][0], round_index=2, history=[], images=images)
    assert isinstance(later[1]["content"], str) and "shown to everyone in round 1" in later[1]["content"]
    conclusion = room.build_conclusion_messages(setup=setup, ask=ask, history=[], images=images)
    assert isinstance(conclusion[1]["content"], list)


def test_a_seat_that_rejects_images_speaks_again_without_them():
    setup = room.normalize_setup({"seats": ["a", "b"], "rounds": 1, "moderator": "a"}, _models("a", "b"), set(), _user(), _no_exclusion)
    events, calls = [], []

    async def emit(event):
        events.append(event)

    async def call_model(model, messages):
        calls.append((model, messages))
        if isinstance(messages[1]["content"], list) and model == "b":
            raise RuntimeError("Unsupported content type: image_url")
        reply = "## 结论\n好" if messages[0]["content"].startswith("You moderated") else f"{model} 看了"
        return {"choices": [{"message": {"content": reply}}]}

    live = room.LiveDiscussion(
        chat_id="c-img", user_id="u1", setup=setup,
        ask=room.new_ask(question="图里是什么？", setup=setup, user_message_id="u", message_id="m", files=[{"id": "f", "name": "x.png", "type": "image"}]),
        history=[], emit=emit, call_model=call_model, persist=lambda ask: None, images=["data:image/png;base64,AA"],
    )
    asyncio.run(live.run())
    turns = {t["seat"]: t for t in live.ask["turns"]}
    assert turns["s1"]["status"] == "done" and not turns["s1"].get("imagesDropped")
    assert turns["s2"]["status"] == "done" and turns["s2"]["imagesDropped"] is True
    b_calls = [m for model, m in calls if model == "b"]
    assert isinstance(b_calls[0][1]["content"], list) and isinstance(b_calls[1][1]["content"], str)
    assert "cannot see" in b_calls[1][1]["content"]
    assert live.ask["status"] == "done"


def test_compare_is_one_independent_round_and_the_moderator_compares():
    setup = _setup(mode="compare", rounds=3)
    assert setup["rounds"] == 1
    ask = room.new_ask(question="Q", setup=setup, user_message_id="u", message_id="m")
    assert ask["rounds"] == 1
    turn = room.build_turn_messages(setup=setup, ask=ask, seat=setup["seats"][0], round_index=1, history=[])
    assert "will not see them" in turn[1]["content"]
    conclusion = room.build_conclusion_messages(setup=setup, ask=ask, history=[])
    assert "how the answers differ" in conclusion[0]["content"]


def test_a_discussion_started_from_a_chat_carries_it_as_background():
    assert room.clean_context(None) is None
    assert room.clean_context({"text": "   "}) is None
    context = room.clean_context({"text": "用户：去哪玩？\n助手：杭州", "title": "旅行", "chat_id": "../etc"})
    assert context == {"text": "用户：去哪玩？\n助手：杭州", "title": "旅行", "chatId": None}
    assert room.clean_context({"text": "x" * 20000, "chat_id": "c-1"})["chatId"] == "c-1"
    assert len(room.clean_context({"text": "x" * 20000})["text"]) == room.CONTEXT_MAX_CHARS

    setup = _setup()
    ask = room.new_ask(question="预算够吗？", setup=setup, user_message_id="u", message_id="m", context=context)
    turn = room.build_turn_messages(setup=setup, ask=ask, seat=setup["seats"][0], round_index=1, history=[])[1]["content"]
    assert "earlier conversation «旅行»" in turn and "助手：杭州" in turn
    assert turn.index("Background") < turn.index("User question")
    conclusion = room.build_conclusion_messages(setup=setup, ask=ask, history=[])[1]["content"]
    assert "助手：杭州" in conclusion
    # without one, nothing is added
    plain = room.new_ask(question="预算够吗？", setup=setup, user_message_id="u", message_id="m")
    assert "Background" not in room.build_turn_messages(setup=setup, ask=plain, seat=setup["seats"][0], round_index=1, history=[])[1]["content"]
