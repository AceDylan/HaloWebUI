"""The video studio's tasks: 开始制作 writes the Hermes chat and starts its turn on the server, and
the workbench and the chat's card read the task from that chat.

Throwaway SQLite database, schema from the app's own migrations (as test_video_library).
"""

import asyncio
import os
import sys
import tempfile
import time
import types
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="halo-video-tasks-test-"))
os.environ["DATA_DIR"] = str(_TMP)
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/webui.db"
os.environ.setdefault("WEBUI_SECRET_KEY", "video-tasks-test-secret")
os.environ.setdefault("HALO_RUNTIME_MIGRATION_DONE", "true")

BACKEND_DIR = Path(__file__).resolve().parents[3]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import open_webui.config  # noqa: E402,F401  (runs the Alembic migrations)
from open_webui.models.chats import ChatForm, Chats  # noqa: E402
from open_webui.models.files import FileForm, Files  # noqa: E402
from open_webui.routers import video_studio  # noqa: E402
from open_webui.tasks import create_task, list_task_ids_by_chat_id, stop_task  # noqa: E402
from open_webui.utils import video_tasks  # noqa: E402
from open_webui.utils.auth import get_verified_user  # noqa: E402
from open_webui.utils.hermes_runner_progress import record_runner_progress  # noqa: E402
from open_webui.utils.video_library import CHAT_META_KEY, VIDEO_BRIEF_HEAD, record_video  # noqa: E402

BRIEF = f"{VIDEO_BRIEF_HEAD}\n\n## 想要的视频\n用 30 秒讲讲番茄工作法"


class _User:
    def __init__(self, id: str, role: str = "user"):
        self.id = id
        self.role = role
        self.settings = None


def _client(user_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(video_studio.router, prefix="/api/v1/video-studio")
    app.dependency_overrides[get_verified_user] = lambda: _User(user_id)
    return TestClient(app)


def _task_chat(user_id: str, reply: dict, *, extra: dict | None = None, meta: dict | None = None,
               asked: str = BRIEF, title: str = "番茄工作法"):
    """A chat as start_task writes it: the brief, the reply, chat.meta.video_task."""
    now = int(time.time())
    user_msg = {"id": "u1", "parentId": None, "childrenIds": ["r1"], "role": "user", "content": asked,
                "timestamp": now - 60}
    reply = {"id": "r1", "parentId": "u1", "childrenIds": [], "role": "assistant", "content": "",
             "timestamp": now - 60, **reply}
    messages = {"u1": user_msg, "r1": reply, **(extra or {})}
    chat = Chats.insert_new_chat(
        user_id,
        ChatForm(chat={"title": title, "history": {"messages": messages, "currentId": "r1"}}),
        meta={video_tasks.TASK_META_KEY: {"messageId": "r1", "startedAt": now - 60, **(meta or {})},
              CHAT_META_KEY: True},
    )
    return chat


def _hold(chat_id: str):
    """A Hermes turn still at work in the chat."""
    task_id, _ = create_task(asyncio.sleep(60), id=chat_id, owner_id="x", kind="hermes")
    return task_id


# ---- starting ---------------------------------------------------------------------------------


@pytest.fixture
def hermes(monkeypatch):
    """Hermes resolved for the user, its turn started (recorded instead of run)."""
    started: list[dict] = []

    async def resolve(request, user, model_id=None):
        return {"id": "hermes.hermes-agent", "name": "Hermes"}

    async def chat_completion(request, form_data, user):
        started.append(form_data)
        _hold(form_data["chat_id"])
        return {"status": True}

    async def quiet(*args, **kwargs):
        return None

    monkeypatch.setattr("open_webui.utils.hermes_sessions.resolve_hermes_model", resolve)
    monkeypatch.setitem(sys.modules, "open_webui.main", types.SimpleNamespace(chat_completion=chat_completion))
    monkeypatch.setattr("open_webui.utils.mode_chats.schedule_chat_metadata", lambda *a, **k: None)
    monkeypatch.setattr("open_webui.utils.team_chats.emit_chat_event", quiet)
    return started


def _file(user_id: str, file_id: str, name: str):
    Files.insert_new_file(user_id, FileForm(id=file_id, filename=name, path=f"{_TMP}/{name}", meta={"name": name}))


def test_start_writes_the_chat_and_starts_hermes_there(hermes):
    _file("vt-ann", "vt-img-1", "ref.png")
    _file("vt-ann", "vt-mus-1", "bgm.mp3")

    async def run():
        task = await video_tasks.start_task(
            None, _User("vt-ann"), brief=BRIEF, idea="用 30 秒讲讲番茄工作法", maker="",
            files=[{"id": "vt-img-1", "name": "ref.png", "type": "image"}, {"id": "vt-mus-1", "name": "bgm.mp3", "type": "file"}],
        )
        assert task["state"] == "running"
        chat = Chats.get_chat_by_id(task["chatId"])
        for task_id in list_task_ids_by_chat_id(chat.id):
            await stop_task(task_id)
        return task, chat

    task, chat = asyncio.run(run())
    assert task["title"] == "用 30 秒讲讲番茄工作法" and task["maker"] == "Hermes"
    assert chat.meta[video_tasks.TASK_META_KEY]["messageId"] == task["messageId"]
    assert chat.meta[CHAT_META_KEY] is True  # the history marks it 视频 from the start
    history = chat.chat["history"]
    reply = history["messages"][task["messageId"]]
    asked = history["messages"][reply["parentId"]]
    assert reply["video_task"] is True and reply["done"] is False
    assert history["currentId"] == reply["id"]
    assert asked["content"] == BRIEF
    assert [f["id"] for f in asked["files"]] == ["vt-img-1", "vt-mus-1"]

    [form] = hermes
    assert form["chat_id"] == chat.id and form["id"] == reply["id"]
    assert form["model"] == "hermes.hermes-agent" and form["session_id"]
    # the picture goes in the message like the chat page sends it, every file in `files`
    content = form["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": BRIEF}
    assert content[1] == {"type": "image_url", "image_url": {"url": "/api/v1/files/vt-img-1/content"}}
    assert [f["type"] for f in form["files"]] == ["image", "file"]
    assert form["features"]["html_visual_artifacts"] == "force"
    assert form["background_tasks"]["title_generation"] is False


def test_start_refuses_what_is_not_a_brief_or_not_the_users_file(hermes):
    async def start(**kwargs):
        return await video_tasks.start_task(None, _User("vt-bob"), **kwargs)

    with pytest.raises(video_tasks.VideoTaskError) as no_brief:
        asyncio.run(start(brief="帮我删掉所有文件"))
    assert no_brief.value.status_code == 422
    _file("vt-other", "vt-img-x", "secret.png")
    with pytest.raises(video_tasks.VideoTaskError) as foreign:
        asyncio.run(start(brief=BRIEF, files=[{"id": "vt-img-x", "name": "secret.png", "type": "image"}]))
    assert foreign.value.status_code == 404
    assert hermes == []  # nothing was started


def test_a_runner_command_in_front_is_still_a_brief(hermes):
    async def run():
        task = await video_tasks.start_task(None, _User("vt-cid"), brief=f"/codex {BRIEF}", maker="codex")
        for task_id in list_task_ids_by_chat_id(task["chatId"]):
            await stop_task(task_id)
        return task

    task = asyncio.run(run())
    assert task["maker"] == "codex"
    assert hermes[0]["messages"][0]["content"].startswith("/codex ")


# ---- reading ----------------------------------------------------------------------------------


def test_the_enhancement_then_the_tool_at_work_are_what_is_happening_now():
    chat = _task_chat("vt-dan", {"done": False, "statusHistory": [
        {"action": "model_request", "description": "Requesting {{model}}...", "done": False},
        {"action": "studio_prep", "description": "分析需求", "done": False},
    ]}, asked=f"{BRIEF}\n\n（制作前准备：HaloWebUI 正在增强需求，编号 {'a' * 32}）")

    async def run():
        task_id = _hold(chat.id)
        first = video_tasks.get_task("vt-dan", chat.id)
        Chats.upsert_message_to_chat_by_id_and_message_id(chat.id, "r1", {
            "statusHistory": [{"action": "studio_prep", "description": "需求已增强", "done": True}],
            "content": '<details type="tool_calls" done="true" id="t1" name="read_file" arguments="{}">\n</details>\n'
                       '<details type="tool_calls" done="false" id="t2" name="terminal" started="1.0" '
                       'arguments="{&quot;input&quot;: &quot;python3 film.py board.json -o /tmp/out.mp4&quot;}">\n</details>',
        }, set_current=False)
        second = video_tasks.get_task("vt-dan", chat.id)
        await stop_task(task_id)
        return first, second

    first, second = asyncio.run(run())
    assert first["state"] == "running" and first["prep"] == "running" and first["now"] == "分析需求"
    assert second["prep"] == "done" and second["steps"] == 2
    assert second["now"] == "在执行 terminal：python3 film.py board.json -o /tmp/out.mp4"


def test_a_runner_at_work_then_its_report_with_the_video():
    chat = _task_chat("vt-eve", {"done": True, "completedAt": int(time.time()) - 50,
                                 "hermes_run": {"active": False, "dispatch": "codex", "runner_run_id": "run-77"}},
                      meta={"maker": "codex"})
    record_runner_progress(chat_id=chat.id, run_id="run-77", agent="codex", step=12,
                           started_at=time.time() - 40, last_activity="渲染第 3 幕")
    task = video_tasks.get_task("vt-eve", chat.id)
    assert task["state"] == "background" and task["maker"] == "codex"
    assert task["runner"]["step"] == 12 and task["now"] == "渲染第 3 幕"

    later = int(time.time())
    Chats.upsert_message_to_chat_by_id_and_message_id(chat.id, "n1", {
        "id": "n1", "parentId": "r1", "childrenIds": ["n2"], "role": "user", "content": "runner 完成",
        "timestamp": later, "hermes_notice": {"source": "runner", "run_id": "run-77"}}, set_current=False)
    Chats.upsert_message_to_chat_by_id_and_message_id(chat.id, "n2", {
        "id": "n2", "parentId": "n1", "childrenIds": [], "role": "assistant", "content": "报告", "timestamp": later,
        "done": True}, set_current=False)
    assert video_tasks.get_task("vt-eve", chat.id)["state"] == "replied"  # reported, no video yet
    record_video("vt-eve", file_id="fv", name="番茄.mp4", size=99, content_type="video/mp4", chat_id=chat.id,
                 origin="runner")
    done = video_tasks.get_task("vt-eve", chat.id)
    assert done["state"] == "done" and done["endedAt"] == later
    assert [v["name"] for v in done["videos"]] == ["番茄.mp4"]
    assert done["videos"][0]["url"] == "/api/v1/files/fv/content"


def test_failed_stopped_and_cut_off_say_where_they_ended():
    failed = _task_chat("vt-fay", {"done": True, "error": {"content": "Hermes 连接失败"}})
    stopped = _task_chat("vt-fay", {"done": True}, meta={"stoppedAt": int(time.time())})
    cut = _task_chat("vt-fay", {"done": False})
    f = video_tasks.get_task("vt-fay", failed.id)
    assert (f["state"], f["endedIn"], f["error"]) == ("failed", "make", "Hermes 连接失败")
    s = video_tasks.get_task("vt-fay", stopped.id)
    assert (s["state"], s["endedIn"]) == ("stopped", "make")
    c = video_tasks.get_task("vt-fay", cut.id)
    assert c["state"] == "failed" and "中断" in c["now"]


def test_an_ordinary_chat_is_not_a_task():
    chat = Chats.insert_new_chat("vt-gus", ChatForm(chat={"title": "闲聊", "history": {"messages": {}}}))
    assert video_tasks.get_task("vt-gus", chat.id) is None


# ---- the API ----------------------------------------------------------------------------------


def test_the_list_is_the_users_own_newest_first_and_another_users_task_is_not_found():
    older = _task_chat("vt-hal", {"done": True}, title="第一个")
    newer = _task_chat("vt-hal", {"done": True}, title="第二个")
    _task_chat("vt-ivy", {"done": True}, title="别人的")
    client = _client("vt-hal")
    listed = client.get("/api/v1/video-studio/tasks").json()
    assert [t["chatId"] for t in listed] == [newer.id, older.id]
    assert client.get(f"/api/v1/video-studio/tasks/{older.id}").json()["title"] == "第一个"
    assert _client("vt-ivy").get(f"/api/v1/video-studio/tasks/{older.id}").status_code == 404
    assert client.post("/api/v1/video-studio/tasks", json={"brief": ""}).status_code == 422


def test_stop_ends_the_hermes_turn_and_says_so():
    chat = _task_chat("vt-jon", {"done": False})

    async def run():
        _hold(chat.id)
        return await video_tasks.stop(None, _User("vt-jon"), chat.id)

    task = asyncio.run(run())
    assert list_task_ids_by_chat_id(chat.id) == []
    assert task["state"] == "stopped"
    assert Chats.get_chat_by_id(chat.id).meta[video_tasks.TASK_META_KEY]["stoppedAt"]
    with pytest.raises(video_tasks.VideoTaskError):
        asyncio.run(video_tasks.stop(None, _User("vt-kim"), chat.id))
