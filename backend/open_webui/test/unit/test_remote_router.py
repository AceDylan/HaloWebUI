"""/api/v1/remote: 精答 / 讨论 / 自动分流 started from Telegram or QQ through Hermes, and read back."""

import pathlib
import sys
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from open_webui.routers import answers, auto, discussions, remote  # noqa: E402
from open_webui.routers import teams as teams_router  # noqa: E402
from open_webui.utils import agent_teams as teams_utils  # noqa: E402
from open_webui.utils import mode_dispatch  # noqa: E402
from open_webui.utils import mode_illustrate  # noqa: E402

H = {"X-Hermes-Key": "k", "X-Halo-Owner": "u1"}


@pytest.fixture
def client(monkeypatch):
    async def target(request, user):
        return teams_utils.HermesTarget("http://hermes", {"Authorization": "Bearer k"}, str(user.id))

    monkeypatch.setattr(teams_router, "hermes_target", target)
    monkeypatch.setattr(teams_router.Users, "get_user_by_id", lambda uid: SimpleNamespace(id=uid) if uid == "u1" else None)
    teams_router._hermes_auth_cache.clear()
    remote._keys.clear()
    app = FastAPI()
    app.include_router(remote.router, prefix="/api/v1/remote")
    return TestClient(app)


def test_only_the_users_own_hermes_key_is_accepted(client):
    body = {"question": "q", "key": "k1"}
    assert client.post("/api/v1/remote/answer", json=body).status_code == 401
    assert client.post("/api/v1/remote/answer", json=body, headers={**H, "X-Hermes-Key": "wrong"}).status_code == 401
    assert client.post("/api/v1/remote/answer", json=body, headers={**H, "X-Halo-Owner": "u2"}).status_code == 401
    assert client.get("/api/v1/remote/answer/c1").status_code == 401
    assert client.post("/api/v1/remote/team", json=body, headers=H).status_code == 422


def test_start_each_kind_once_per_key(client, monkeypatch):
    started = []

    async def open_answer(request, user, *, question, context, origin, files=None):
        started.append(("answer", question, context, origin))
        return "chat-a"

    async def open_discussion(request, user, *, question, context, origin, files=None):
        started.append(("discuss", question, context, origin))
        return "chat-d"

    async def start_auto(request, user, form, origin=None):
        started.append(("auto", form.question, form.client_key, origin))
        return {"id": "route-1"}

    monkeypatch.setattr(answers, "open_for_chat", open_answer)
    monkeypatch.setattr(discussions, "open_for_chat", open_discussion)
    monkeypatch.setattr(auto, "start", start_auto)
    first = client.post("/api/v1/remote/answer", json={"question": " 天为什么是蓝的 ", "key": "tg:1:7"}, headers=H)
    assert first.json() == {"kind": "answer", "id": "chat-a"}
    again = client.post("/api/v1/remote/answer", json={"question": "天为什么是蓝的", "key": "tg:1:7"}, headers=H)
    assert again.json() == {"kind": "answer", "id": "chat-a", "deduplicated": True}
    assert client.post("/api/v1/remote/discuss", json={"question": "要不要换工作", "key": "qq:2:8"},
                       headers=H).json()["id"] == "chat-d"
    assert client.post("/api/v1/remote/auto", json={"question": "比较方案", "key": "qq:2:9"},
                       headers=H).json()["id"] == "route-1"
    # standalone runs: no chat of origin to report back into (the result goes to the Telegram / QQ chat)
    assert started == [("answer", "天为什么是蓝的", None, None), ("discuss", "要不要换工作", None, None),
                       ("auto", "比较方案", "remote:qq:2:9", None)]
    assert client.post("/api/v1/remote/answer", json={"question": "   ", "key": "x"}, headers=H).status_code == 400
    # a QQ key (openid + message id) is longer than a 分流's client_key may be
    qq = "qqbot:" + "A" * 32 + ":ROBOT1.0_" + "b" * 100
    assert client.post("/api/v1/remote/auto", json={"question": "长 key", "key": qq}, headers=H).status_code == 200
    key = started[-1][2]
    assert key.startswith("remote:sha256:") and len(key) <= 128
    assert auto.CreateForm(question="q", client_key=key).client_key == key


def _run(status="done", ended=None, **extra):
    return {"id": "m1", "question": "天为什么是蓝的", "status": status,
            "endedAt": (ended if ended is not None else time.time() - 60) * 1000,
            "answer": {"content": "因为瑞利散射。"}, "assistant": {"emoji": "🔭", "name": "物理老师"}, **extra}


def test_state_waits_for_the_picture_then_gives_the_result(client, monkeypatch):
    chat = SimpleNamespace(title="天空为什么是蓝色")
    run = _run(illustration={"status": "ready", "url": "/api/v1/files/abcdef12-3456/content"},
               research={"sources": [{"n": 1, "title": "维基", "url": "https://w.example"}]})
    monkeypatch.setattr(remote, "_chat_run", lambda kind, chat_id, user: (chat, run))
    monkeypatch.setitem(mode_illustrate.DRAWING, "c1", {})
    assert client.get("/api/v1/remote/answer/c1", headers=H).json()["status"] == "running"
    mode_illustrate.DRAWING.pop("c1")
    got = client.get("/api/v1/remote/answer/c1", headers=H).json()
    assert got["status"] == "done" and got["title"] == "天空为什么是蓝色" and got["by"] == "🔭物理老师"
    assert got["url"] == "/answer/c1" and got["picture"] is True
    assert "瑞利散射" in got["text"] and "资料来源" in got["text"] and "/api/v1/files/" not in got["text"]


def test_state_of_running_failed_and_gone_runs(client, monkeypatch):
    chat = SimpleNamespace(title="New Chat")
    runs = {"c1": _run("answering"), "c2": _run("error", error="模型超时"), "c3": _run("done", ended=time.time()),
            "c4": _run("stopped")}
    monkeypatch.setattr(remote, "_chat_run", lambda kind, chat_id, user: (chat, runs[chat_id]) if chat_id in runs
                        else (None, None))
    assert client.get("/api/v1/remote/answer/c1", headers=H).json()["status"] == "running"
    failed = client.get("/api/v1/remote/answer/c2", headers=H).json()
    assert failed["status"] == "failed" and failed["error"] == "模型超时" and failed["title"] == "天为什么是蓝的"
    # just finished: its picture's slot is taken right after, so not done yet
    assert client.get("/api/v1/remote/answer/c3", headers=H).json()["status"] == "running"
    assert client.get("/api/v1/remote/discuss/c4", headers=H).json()["status"] == "stopped"
    assert client.get("/api/v1/remote/discuss/nope", headers=H).json()["status"] == "gone"


def test_state_of_an_auto_route(client, monkeypatch):
    rows = {"r1": {"status": "dispatched", "mode": "discuss", "target_id": "d7", "reason": "多角度", "href": "/discuss/d7",
                   "title": "比较方案", "read_only": False, "degraded": None},
            "r2": {"status": "routing", "title": "t"},
            "r3": {"status": "error", "error": "需要真实文件检查", "title": "t"}}

    def own(route_id, user):
        if route_id not in rows:
            raise auto.HTTPException(404, "这条分流记录不存在")
        return route_id

    monkeypatch.setattr(auto, "_own", own)
    monkeypatch.setattr(auto, "public", lambda row, user: rows[row])
    got = client.get("/api/v1/remote/auto/r1", headers=H).json()
    assert got["status"] == "dispatched" and got["mode"] == "discuss" and got["target_id"] == "d7"
    assert got["url"] == "/discuss/d7" and got["reason"] == "多角度"
    assert client.get("/api/v1/remote/auto/r2", headers=H).json()["status"] == "running"
    assert client.get("/api/v1/remote/auto/r3", headers=H).json()["error"] == "需要真实文件检查"
    assert client.get("/api/v1/remote/auto/none", headers=H).json()["status"] == "gone"


def test_picture_only_of_the_users_own_ready_picture(client, monkeypatch, tmp_path):
    from open_webui.models.files import Files
    from open_webui.storage.provider import Storage

    image = tmp_path / "pic.png"
    image.write_bytes(b"\x89PNG data")
    run = _run(illustration={"status": "ready", "url": "/api/v1/files/abcdef12-3456/content"})
    monkeypatch.setattr(remote, "_chat_run", lambda kind, chat_id, user: (SimpleNamespace(title="t"), run))
    files = {"abcdef12-3456": SimpleNamespace(user_id="u1", path="p", meta={"content_type": "image/png"})}
    monkeypatch.setattr(Files, "get_file_by_id", lambda file_id: files.get(file_id))
    monkeypatch.setattr(Storage, "get_file", lambda path: str(image))
    got = client.get("/api/v1/remote/answer/c1/picture", headers=H)
    assert got.status_code == 200 and got.content == b"\x89PNG data" and got.headers["content-type"] == "image/png"
    files["abcdef12-3456"].user_id = "u2"
    assert client.get("/api/v1/remote/answer/c1/picture", headers=H).status_code == 404
    run["illustration"] = {"status": "generating"}
    assert client.get("/api/v1/remote/discuss/c1/picture", headers=H).status_code == 404


def test_result_content_with_and_without_the_picture():
    run = _run(illustration={"status": "ready", "url": "/api/v1/files/abcdef12-3456/content"},
               card={"status": "ready", "html": "<div>card</div>"})
    with_picture = mode_dispatch.result_content("answer", run)
    assert "/api/v1/files/abcdef12-3456/content" in with_picture and "card" not in with_picture
    assert "/api/v1/files/" not in mode_dispatch.result_content("answer", run, picture=False)
