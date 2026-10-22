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


def test_plan_without_questions_falls_back_to_the_message_as_state():
    plan = s1.plan_from('{"questions": {}, "note": "请给出要判断的内容"}', "jev-latest", "", "你好")
    assert plan.body["questions"] == {} and plan.note == "请给出要判断的内容" and plan.body["state"] == "你好"
    assert s1.plan_from("not json", "jev-latest", "", "x").body["questions"] == {}


JEV_RESPONSE = {
    "model": "jev-1.14.0",
    "answers": {
        "queue": {"type": "choice", "choice": "billing", "confidence": 1.0, "probabilities": {"billing": 1.0, "account": 0.0}},
        "urgency": {"type": "score", "score": 1.7, "confidence": 0.55, "probabilities": {"0": 0.1, "1": 0.1, "2": 0.8}},
        "refund": {"type": "noul", "noul": 0.98},
    },
    "usage": {"input_tokens": 357, "output_tokens": 55},
}


def test_render_answers_as_a_table_with_chinese_names():
    plan = s1.plan_from(PLANNER_REPLY, "jev-latest", "", "ask")
    text = s1.render(plan, JEV_RESPONSE)
    assert "**Jev 判断结果**（jev-1.14.0）" in text
    assert "| 交给哪个组 | 账单（billing） · 把握 100% |" in text
    assert "| 多急 | 今天（1.70 / 2） · 把握 55% |" in text
    assert "| 要求退款吗 | 是（是的概率 98%） |" in text
    assert "- 多急：今天 80% · 不急 10% · 本周 10%" in text
    assert '"instructions": "Which queue?"' in text and "labels" not in text.split("```json")[1]
    assert "<details>" not in text and "<sub>" not in text
    assert "注：输入 357 tokens；" in text and "*输入" not in text


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


def test_judge_without_judgeable_content_explains_instead_of_calling_jev():
    async def planner(messages):
        return '{"questions": {}, "note": "没有看到要判断的内容。"}'

    async def post(body):
        raise AssertionError("Jev must not be called")

    async def status(text, done):
        pass

    content, usage = run(s1.judge([{"role": "user", "content": "你好"}], "jev-latest", ask_planner=planner, post=post, status=status, planner_name="gpt-chat"))
    assert content.startswith("没有看到要判断的内容。") and "Jev 是判断模型" in content and usage == {}


def test_judge_skips_the_planner_for_a_request_json():
    async def planner(messages):
        raise AssertionError("no planning for a request JSON")

    async def post(body):
        return {"model": "jev-1.14.0", "answers": {"q": {"type": "noul", "noul": 0.1}}}

    async def status(text, done):
        pass

    msg = '{"state": "hi", "questions": {"q": {"type": "noul", "instructions": "Is this spam?"}}}'
    content, _ = run(s1.judge([{"role": "user", "content": msg}], "jev-latest", ask_planner=planner, post=post, status=status, planner_name="gpt-chat"))
    assert "| Is this spam? | 否（是的概率 10%） |" in content


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
