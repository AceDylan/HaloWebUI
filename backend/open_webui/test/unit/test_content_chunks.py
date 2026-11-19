import asyncio
import json
import pathlib
import sys


_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.routers import gemini as gemini_router
from open_webui.utils import html_visual_prompt
from open_webui.utils.content_chunks import (
    StringifiedChunkDecoder,
    normalize_chat_completion_payload,
    split_stringified_chunks,
)


def _thinking(text: str, closed: bool = True) -> dict:
    chunk = {"type": "thinking", "thinking": [{"type": "text", "text": text}]}
    if closed:
        chunk["closed"] = True
    return chunk


def _dumps(value) -> str:
    # The relay (CPA) serialises without spaces, like this.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# Frames as CPA relayed mistral-large-latest through the gemini-chat route
# (CCHP request 01a1f18c, 2026-11-19), one Gemini text part per SSE event.
_MISTRAL_FRAMES = [
    _dumps([_thinking("用户用中文")]),
    _dumps([_thinking("打", closed=False)]),
    _dumps([_thinking("招呼。")]),
    _dumps([_thinking("。"), {"type": "text", "text": "你好！"}]),
    "有什么我可以",
    "帮你的吗？",
]


def _decode_sse_chunk(chunk: str) -> dict:
    assert chunk.startswith("data: ")
    return json.loads(chunk[len("data: ") :].strip())


def test_decoder_splits_stream_frames_into_thinking_and_answer():
    decoder = StringifiedChunkDecoder()
    reasoning, content = [], []
    for frame in _MISTRAL_FRAMES:
        r, c = decoder.split(frame)
        reasoning.append(r)
        content.append(c)

    assert "".join(reasoning) == "用户用中文打招呼。。"
    assert "".join(content) == "你好！有什么我可以帮你的吗？"


def test_decoder_handles_concatenated_arrays_in_one_text():
    whole = "".join(_MISTRAL_FRAMES)

    reasoning, content = split_stringified_chunks(whole)

    assert reasoning == "用户用中文打招呼。。"
    assert content == "你好！有什么我可以帮你的吗？"


def test_decoder_leaves_ordinary_text_and_json_answers_alone():
    for text in [
        "普通回答",
        "[1, 2, 3]",
        '[{"type":"text","text":"a JSON example the user asked for"}]',
        '[{"type":"thinking","thinking":"x"},{"type":"image_url","url":"y"}]',
        '[{"type":"thinking"',  # truncated: not decodable
        "",
    ]:
        assert split_stringified_chunks(text) == ("", text)


def test_decoder_accepts_text_only_arrays_after_a_thinking_array():
    decoder = StringifiedChunkDecoder()
    decoder.split(_dumps([_thinking("想")]))

    assert decoder.split(_dumps([{"type": "text", "text": "答"}])) == ("", "答")


def test_normalize_openai_chunk_moves_stringified_thinking_to_reasoning():
    decoder = StringifiedChunkDecoder()
    payloads = [
        {"choices": [{"index": 0, "delta": {"content": frame}}]}
        for frame in _MISTRAL_FRAMES
    ]

    for payload in payloads:
        normalize_chat_completion_payload(payload, decoder)

    deltas = [payload["choices"][0]["delta"] for payload in payloads]
    assert "".join(d.get("reasoning_content", "") for d in deltas) == "用户用中文打招呼。。"
    assert "".join(d["content"] for d in deltas) == "你好！有什么我可以帮你的吗？"


def test_normalize_openai_message_with_list_content():
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": [_thinking("先想"), {"type": "text", "text": "结论"}],
                }
            }
        ]
    }

    assert normalize_chat_completion_payload(payload) is True
    message = payload["choices"][0]["message"]
    assert message["content"] == "结论"
    assert message["reasoning_content"] == "先想"


def test_normalize_leaves_regular_openai_chunks_untouched():
    payload = {"choices": [{"delta": {"content": "[链接](https://x)"}}]}

    assert normalize_chat_completion_payload(payload, StringifiedChunkDecoder()) is False
    assert payload["choices"][0]["delta"] == {"content": "[链接](https://x)"}


def test_gemini_stream_chunks_split_stringified_mistral_thinking():
    decoder = StringifiedChunkDecoder()
    reasoning, content = "", ""
    for frame in _MISTRAL_FRAMES:
        chunks, _index, _finished = gemini_router._build_stream_chunks_from_gemini_obj(
            {"candidates": [{"content": {"parts": [{"text": frame}], "role": "model"}}]},
            "stream-1",
            "gemini-chat",
            0,
            chunk_decoder=decoder,
        )
        for chunk in chunks:
            delta = _decode_sse_chunk(chunk)["choices"][0]["delta"]
            reasoning += delta.get("reasoning_content", "")
            content += delta.get("content", "")

    assert reasoning == "用户用中文打招呼。。"
    assert content == "你好！有什么我可以帮你的吗？"


def test_gemini_non_stream_response_splits_stringified_thinking():
    response = gemini_router.convert_gemini_to_openai(
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": "".join(_MISTRAL_FRAMES)}]},
                    "finishReason": "STOP",
                }
            ]
        },
        "gemini-chat",
    )

    message = response["choices"][0]["message"]
    assert message["content"] == "你好！有什么我可以帮你的吗？"
    assert message["reasoning_content"] == "用户用中文打招呼。。"


def test_agy_gateway_drops_stringified_thinking_before_the_card():
    from aiohttp import web

    card = '<div class="hv">你好</div>'

    async def _generate(request):
        return web.json_response(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": _dumps([_thinking("plan the `card`")])
                                    + _dumps([_thinking("."), {"type": "text", "text": "<div"}])
                                    + card[len("<div") :]
                                }
                            ]
                        }
                    }
                ]
            }
        )

    async def _run():
        app = web.Application()
        app.router.add_post("/v1beta/models/{name}", _generate)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            return await html_visual_prompt._request_agy_gateway(
                {
                    "base_url": f"http://127.0.0.1:{port}/",
                    "api_key": "test-key",
                    "model": "gemini-chat",
                },
                "prompt text",
                output_limit=4096,
                timeout_seconds=10,
            )
        finally:
            await runner.cleanup()

    output = asyncio.run(_run())

    assert output.decode("utf-8") == card
    fragment, error = html_visual_prompt._extract_agy_html_fragment(output)
    assert error is None
    assert fragment == card
