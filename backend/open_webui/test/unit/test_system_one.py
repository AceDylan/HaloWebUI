import asyncio
import json

import pytest

from open_webui.utils import system_one as s1


def run(coro):
    return asyncio.run(coro)


def test_detects_jev_models_and_systemone_connections():
    assert s1.is_system_one_model("jev-latest")
    assert s1.is_system_one_model("JEV-1.14.0")
    assert s1.is_system_one_model("typesafe/jev-preview")
    assert s1.is_system_one_model("gpt-chat", "https://api.example.com/v1/systemone/")
    assert not s1.is_system_one_model("jevons-7b")
    assert not s1.is_system_one_model("gpt-chat", "https://api.example.com/v1")
    assert s1.is_system_one_model("94dae559.jev-latest")
    assert s1.is_system_one_model("modelref::openai::personal::id:94dae559::jev-latest")


def test_jev_entries_are_kept_out_of_workbenches_and_discussions():
    from open_webui.utils.discussion_room import _default_is_excluded

    jev = {"id": "94dae559.jev-latest", "name": "jev-latest"}
    preset = {"id": "judge", "name": "判断助手", "info": {"base_model_id": "94dae559.jev-latest"}}
    assert s1.is_system_one_entry(jev) and s1.is_system_one_entry(preset)
    assert not s1.is_system_one_entry({"id": "conn.gpt-chat", "info": {"base_model_id": "conn.gpt-chat"}})
    assert "Jev" in (_default_is_excluded(jev) or "") and "Jev" in (_default_is_excluded(preset) or "")
    assert _default_is_excluded({"id": "conn.deepseek-chat", "name": "deepseek-chat"}) is None


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://api.fengshao1227.com/v1/systemone", "https://api.fengshao1227.com/v1/systemone"),
        ("https://api.fengshao1227.com/v1/", "https://api.fengshao1227.com/v1/systemone"),
        ("https://api.example.com/v1/chat/completions", "https://api.example.com/v1/systemone"),
        ("https://api.typesafe.ai", "https://api.typesafe.ai/v1/systemone"),
    ],
)
def test_system_one_url(url, expected):
    assert s1.system_one_url(url) == expected


def test_conversation_splits_last_user_message_from_background():
    ask, background = s1.conversation(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "工单：我被扣了两次款"},
            {"role": "assistant", "content": "**Jev 判断结果**"},
            {"role": "user", "content": [{"type": "text", "text": "再看看急不急"}]},
        ]
    )
    assert ask == "再看看急不急"
    assert background == "用户：工单：我被扣了两次款\n\n助手：**Jev 判断结果**"


def test_direct_request_json_goes_as_is_and_defaults_state_to_the_chat():
    plan = s1.direct_request('{"questions": {"q": {"type": "noul", "instructions": "Is it urgent?"}}}', "前文", "jev-latest")
    assert plan.body == {"model": "jev-latest", "state": "前文", "questions": {"q": {"type": "noul", "instructions": "Is it urgent?"}}}
    assert s1.direct_request("这条工单该给谁", "", "jev-latest") is None
    assert s1.direct_request('{"state": "x"}', "", "jev-latest") is None


PLANNER_REPLY = """```json
{"state": "I was charged twice, refund today.",
 "questions": {
  "Queue!": {"type": "choice", "title": "交给哪个组", "instructions": "Which queue?",
             "criteria": {"billing": "Payments", "account": "Login"}, "labels": {"billing": "账单", "account": "账号"}},
  "urgency": {"type": "score", "title": "多急", "instructions": "How urgent?",
              "criteria": ["Can wait", "This week", "Today"], "labels": ["不急", "本周", "今天"]},
  "refund": {"type": "noul", "title": "要求退款吗", "instructions": "Does the customer ask for a refund?",
             "criteria": "a bare string is not a valid noul criteria"},
  "spam": {"type": "noul", "title": "是广告吗", "instructions": "Is it spam?",
           "criteria": {"true": "Unsolicited promotion", "false": "A real customer message"}},
  "bad": {"type": "choice", "instructions": "One option only", "criteria": {"x": "only"}},
  "worse": {"type": "essay", "instructions": "Write"}
 }}
```"""


def test_plan_keeps_valid_questions_and_strips_display_fields():
    plan = s1.plan_from(PLANNER_REPLY, "jev-latest", "", "ask")
    assert list(plan.body["questions"]) == ["queue", "urgency", "refund", "spam"]
    assert plan.body["questions"]["refund"] == {"type": "noul", "instructions": "Does the customer ask for a refund?"}
    assert plan.body["questions"]["spam"]["criteria"] == {"true": "Unsolicited promotion", "false": "A real customer message"}
    assert plan.body["questions"]["queue"] == {
        "type": "choice",
        "instructions": "Which queue?",
        "criteria": {"billing": "Payments", "account": "Login"},
    }
    assert "labels" not in plan.body["questions"]["urgency"] and "title" not in plan.body["questions"]["refund"]
    assert plan.display["urgency"] == {"title": "多急", "labels": ["不急", "本周", "今天"]}
    assert plan.body["state"] == "I was charged twice, refund today."


def test_plan_ignores_what_follows_the_json():
    plan = s1.plan_from('{"state": "x", "questions": {"q": {"type": "noul", "instructions": "Is it?"}}}\n\n```html\n<div>{card}</div>\n```', "jev-latest", "", "")
    assert list(plan.body["questions"]) == ["q"]


def test_plan_without_questions_says_why_for_the_retry():
    plan = s1.plan_from('{"questions": {"bad": {"type": "choice", "instructions": "x", "criteria": {"a": "only"}}}}', "jev-latest", "", "你好")
    assert plan.body["questions"] == {} and plan.body["state"] == "你好"
    assert plan.problems == ("bad：choice 至少要 2 个选项",)
    assert s1.plan_from("not json", "jev-latest", "", "x").problems == ("回复里没有 JSON 对象",)
    assert s1.plan_from('{"questions": {}}', "jev-latest", "", "x").problems == ("questions 是空的",)


def test_plan_state_question_is_the_users_own_words():
    reply = '{"state": {"question": "对话前文：（无） 这次的消息：1+1是2吗", "material": "x"}, "questions": {"q": {"type": "noul", "instructions": "Is it?"}}}'
    assert s1.plan_from(reply, "jev-latest", "", "1+1是2吗").body["state"] == {"question": "1+1是2吗", "material": "x"}


def test_fallback_plan_is_one_yes_no_question_on_the_message():
    plan = s1.fallback_plan("1+1 是 2 吗", "用户：前文", "jev-latest")
    assert plan.body["state"] == {"question": "1+1 是 2 吗", "context": "用户：前文"}
    assert list(plan.body["questions"]) == ["answer"] and plan.body["questions"]["answer"]["type"] == "noul"
    assert plan.display["answer"]["title"] == "1+1 是 2 吗"


JEV_RESPONSE = {
    "model": "jev-1.14.0",
    "answers": {
        "queue": {"type": "choice", "choice": "billing", "confidence": 1.0, "probabilities": {"billing": 1.0, "account": 0.0}},
        "urgency": {"type": "score", "score": 1.7, "confidence": 0.55, "probabilities": {"0": 0.1, "1": 0.1, "2": 0.8}},
        "refund": {"type": "noul", "noul": 0.98},
    },
    "usage": {"input_tokens": 357, "output_tokens": 55},
}


def test_render_shows_only_the_conclusions():
    plan = s1.plan_from(PLANNER_REPLY, "jev-latest", "", "ask")
    text = s1.render(plan, JEV_RESPONSE)
    assert text.startswith("### Jev 的判断\n")
    assert "| 交给哪个组 | 账单 · 把握 100% |" in text
    assert "| 多急 | 今天 · 把握 55% |" in text
    assert "| 要求退款吗 | 是（98%） |" in text
    # split votes only where Jev is split; a lone 100% says nothing the table doesn't
    assert "- 多急：今天 80% · 不急 10% · 本周 10%" in text and "- 交给哪个组" not in text
    assert "把握不到 60%" in text
    assert "```" not in text and "`" not in text and '"instructions"' not in text and "tokens" not in text
    assert "<details>" not in text and "<sub>" not in text


def test_render_is_structured_markdown_so_no_escaped_fallback_card():
    from open_webui.utils.html_visual_prompt import append_html_visual_fallback, is_structured_markdown_reply

    text = s1.render(s1.plan_from(PLANNER_REPLY, "jev-latest", "", "ask"), JEV_RESPONSE)
    assert is_structured_markdown_reply(text) and is_structured_markdown_reply(s1.HELP)
    meta = {"server_surface": "halowebui-web"}
    assert "HALOWEBUI_HTML_VISUAL_SAFE_FALLBACK" not in append_html_visual_fallback(text, meta)


def test_render_strips_backticks_and_names_noul_sides():
    plan = s1.Plan(body={"questions": {"q": {"type": "noul", "instructions": "Is `ticket.text` spam?"}}}, display={})
    text = s1.render(plan, {"answers": {"q": {"type": "noul", "noul": 0.1}}})
    assert "| Is ticket.text spam? | 否（90%） |" in text and "`" not in text
    assert "拿不准（是的概率 50%）" in s1.render(plan, {"answers": {"q": {"type": "noul", "noul": 0.5}}})


def test_judge_plans_then_posts_and_reports_status():
    seen = {}
    statuses = []

    async def planner(messages):
        seen["planner"] = messages
        return PLANNER_REPLY

    async def post(body):
        seen["body"] = body
        return JEV_RESPONSE

    async def status(text, done):
        statuses.append((text, done))

    content, usage = run(
        s1.judge(
            [{"role": "user", "content": "工单：我被扣了两次款，今天要退款。交给哪个组？急不急？"}],
            "jev-latest",
            ask_planner=planner,
            post=post,
            status=status,
            planner_name="gpt-chat",
        )
    )
    assert "工单：我被扣了两次款" in seen["planner"][1]["content"]
    assert seen["body"]["model"] == "jev-latest" and len(seen["body"]["questions"]) == 4
    assert usage == {"input_tokens": 357, "output_tokens": 55}
    assert statuses[0] == ("gpt-chat 正在把消息拆成判断题", False)
    assert statuses[-1] == ("Jev 已判断 3 道题", True)
    assert "| 交给哪个组 |" in content


def _quiet(*_):
    async def status(text, done):
        pass

    return status


def test_judge_replans_with_the_reason_then_falls_back_to_a_yes_no_question():
    calls = []

    async def planner(messages):
        calls.append(messages)
        return '{"questions": {}}'

    async def post(body):
        calls.append(body)
        return {"model": "jev-1.14.0", "answers": {"answer": {"type": "noul", "noul": 0.97}}}

    content, _ = run(s1.judge([{"role": "user", "content": "1+1是2吗"}], "jev-latest", ask_planner=planner, post=post, status=_quiet(), planner_name="gpt-chat"))
    assert len(calls) == 3  # two plans, then the fallback goes to Jev
    assert calls[1][-1]["role"] == "user" and "questions 是空的" in calls[1][-1]["content"] and calls[1][-2]["role"] == "assistant"
    assert calls[2]["state"]["question"] == "1+1是2吗"
    assert "| 1+1是2吗 | 是（97%） |" in content


def test_judge_replans_when_jev_rejects_the_request():
    plans = []
    posts = []

    async def planner(messages):
        plans.append(messages)
        return '{"state": {"m": "x"}, "questions": {"q": {"type": "noul", "title": "是吗", "instructions": "Is it?"}}}'

    async def post(body):
        posts.append(body)
        if len(posts) == 1:
            raise s1.SystemOneError("Jev 返回 HTTP 422：criteria invalid", 422)
        return {"answers": {"q": {"type": "noul", "noul": 0.9}}}

    content, _ = run(s1.judge([{"role": "user", "content": "x"}], "jev-latest", ask_planner=planner, post=post, status=_quiet(), planner_name="gpt-chat"))
    assert len(plans) == 2 and "Jev 拒绝了上一版请求：Jev 返回 HTTP 422" in plans[1][-1]["content"]
    assert "| 是吗 | 是（90%） |" in content


def test_judge_does_not_replan_on_an_auth_error():
    async def planner(messages):
        return '{"questions": {"q": {"type": "noul", "instructions": "Is it?"}}}'

    async def post(body):
        raise s1.SystemOneError("Jev 返回 HTTP 401：bad key", 401)

    with pytest.raises(s1.SystemOneError):
        run(s1.judge([{"role": "user", "content": "x"}], "jev-latest", ask_planner=planner, post=post, status=_quiet(), planner_name="gpt-chat"))


def test_judge_without_a_message_explains_jev():
    async def never(_):
        raise AssertionError("nothing to plan or judge")

    content, usage = run(s1.judge([{"role": "user", "content": " "}], "jev-latest", ask_planner=never, post=never, status=_quiet(), planner_name="gpt-chat"))
    assert content == s1.HELP and usage == {} and "`" not in s1.HELP


def test_judge_skips_the_planner_for_a_request_json():
    async def planner(messages):
        raise AssertionError("no planning for a request JSON")

    async def post(body):
        return {"model": "jev-1.14.0", "answers": {"q": {"type": "noul", "noul": 0.1}}}

    async def status(text, done):
        pass

    msg = '{"state": "hi", "questions": {"q": {"type": "noul", "instructions": "Is this spam?"}}}'
    content, _ = run(s1.judge([{"role": "user", "content": msg}], "jev-latest", ask_planner=planner, post=post, status=status, planner_name="gpt-chat"))
    assert "| Is this spam? | 否（90%） |" in content


def _events(chunks):
    return [json.loads(c[len("data: ") :]) for c in chunks if c.startswith("data: {")]


async def _collect(gen):
    return [c async for c in gen]


def test_stream_body_sends_content_usage_and_done():
    async def ok():
        return "表格", {"input_tokens": 10, "output_tokens": 2}

    chunks = run(_collect(s1.stream_body("jev-latest", ok)))
    events = _events(chunks)
    assert events[0]["choices"][0]["delta"]["content"] == "表格"
    assert events[-1]["usage"] == {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
    assert chunks[-1] == "data: [DONE]\n\n"


def test_stream_body_turns_a_failure_into_an_error_event():
    async def fail():
        raise s1.SystemOneError("Jev 返回 HTTP 401：bad key", 401)

    events = _events(run(_collect(s1.stream_body("jev-latest", fail))))
    assert events == [{"error": {"message": "Jev 返回 HTTP 401：bad key", "type": "api_error", "code": "http_401"}}]


def test_completion_body_maps_usage():
    body = s1.completion_body("jev-latest", "x", {"input_tokens": 3, "output_tokens": 1})
    assert body["choices"][0]["message"]["content"] == "x"
    assert body["usage"]["total_tokens"] == 4
