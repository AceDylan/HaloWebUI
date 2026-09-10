"""Opt-in LOCAL integration check, using an existing frontend build.

No real model, credentials, production DB, or notification endpoint is used.
Uses the production notification handler, chat model, Socket.IO emitter, and
compiled frontend. The upstream model and unrelated app APIs are fixtures.
Requires Python test dependencies, Playwright, and a Chromium installation.
"""

import argparse
import ast
import asyncio
from contextlib import contextmanager
import importlib.util
import json
import logging
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace


REPO = Path(__file__).resolve().parents[1]


def load_functions(path, names, namespace):
    tree = ast.parse(path.read_text())
    body = []
    for node in tree.body:
        if getattr(node, "name", None) in names:
            node.decorator_list = []
            body.append(node)
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])),
            str(path),
            "exec",
        ),
        namespace,
    )


async def verify(build, workspace):
    os.environ["DATA_DIR"] = str(workspace)
    os.environ["DATABASE_URL"] = f"sqlite:///{workspace / 'imports.db'}"
    os.environ["HF_HUB_OFFLINE"] = "1"
    sys.path.insert(0, str(REPO / "backend"))
    from fastapi import FastAPI, Request, HTTPException, Depends, status
    from fastapi.responses import FileResponse, JSONResponse
    from pydantic import BaseModel, Field
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from typing import Optional
    import socketio
    import uvicorn
    from playwright.async_api import async_playwright
    from open_webui.models import chats as model

    engine = create_engine(f"sqlite:///{workspace / 'chats.db'}")
    model.Chat.__table__.create(engine)
    model.ChatMessage.__table__.create(engine)
    sessions = sessionmaker(bind=engine)

    @contextmanager
    def get_db():
        with sessions() as session:
            yield session

    model.get_db = get_db
    user = SimpleNamespace(id="fixture-user", role="admin")
    for chat_id in ["fixture-chat", "other-chat"]:
        with get_db() as db:
            db.add(
                model.Chat(
                    id=chat_id,
                    user_id=user.id,
                    title="Local notification fixture",
                    created_at=1,
                    updated_at=1,
                    chat={
                        "title": "Local notification fixture",
                        "models": ["hermes-fixture"],
                        "params": {},
                        "history": {
                            "currentId": "answer",
                            "messages": {
                                "question": {
                                    "id": "question",
                                    "role": "user",
                                    "content": "fixture question",
                                    "parentId": None,
                                    "childrenIds": ["answer"],
                                    "timestamp": 1,
                                },
                                "answer": {
                                    "id": "answer",
                                    "role": "assistant",
                                    "content": "WAITING_FOR_CODEX",
                                    "model": "hermes-fixture",
                                    "modelName": "Fixture",
                                    "parentId": "question",
                                    "childrenIds": [],
                                    "done": True,
                                    "completedAt": 1,
                                    "timestamp": 1,
                                },
                            },
                        },
                    },
                )
            )
            db.commit()

    sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=[])
    pool = {user.id: []}
    trace = []

    @sio.event
    async def connect(sid, environ, auth):
        if (auth or {}).get("token") != "local-test-only":
            return False
        pool[user.id].append(sid)

    @sio.event
    async def disconnect(sid):
        pool[user.id] = [value for value in pool[user.id] if value != sid]

    import uuid

    emitter_ns = {
        "uuid": uuid,
        "json": json,
        "USER_POOL": pool,
        "Chats": model.Chats,
        "sio": sio,
    }
    load_functions(
        REPO / "backend/open_webui/socket/main.py",
        {"get_event_emitter", "_merge_message_files"},
        emitter_ns,
    )
    get_event_emitter = emitter_ns["get_event_emitter"]

    # Load the whole real follow-up module, replacing only service imports.
    path = REPO / "backend/open_webui/utils/hermes_notify.py"
    tree = ast.parse(path.read_text())
    tree.body = [
        node
        for node in tree.body
        if not (
            isinstance(node, ast.ImportFrom)
            and (node.module or "").startswith("open_webui")
        )
    ]
    notify_ns = {
        "SRC_LOG_LEVELS": {},
        "Chats": model.Chats,
        "Users": SimpleNamespace(get_user_by_id=lambda _: user),
        "get_event_emitter": get_event_emitter,
        "list_task_ids_by_chat_id": lambda _: [],
    }
    exec(compile(tree, str(path), "exec"), notify_ns)
    notify_ns["RELOAD_SETTLE_SECONDS"] = 0.05
    pending = set()
    reply_number = 0

    # This is the only replacement for the upstream Hermes/LLM execution.
    async def chat_completion(request, form_data, owner):
        nonlocal reply_number
        reply_number += 1
        number = reply_number
        cid, mid = form_data["chat_id"], form_data["id"]
        assert (
            model.Chats.get_chat_by_id(cid).chat["history"]["messages"][mid]["done"]
            is False
        )
        trace.append("follow_up_started")

        async def finish():
            await asyncio.sleep(0.15)
            payload = {
                "content": f"LOCAL_CODEX_RESULT_{number}",
                "done": True,
                "completedAt": int(time.time()),
            }
            model.Chats.upsert_message_to_chat_by_id_and_message_id(cid, mid, payload)
            trace.append("result_persisted")
            await get_event_emitter(
                {"chat_id": cid, "message_id": mid, "user_id": owner.id}
            )({"type": "chat:completion", "data": payload})
            trace.append("completion_broadcast")

        task = asyncio.create_task(finish())
        pending.add(task)
        task.add_done_callback(pending.discard)
        return {"status": True, "task_id": f"fixture-task-{number}"}

    fake_main = ModuleType("open_webui.main")
    fake_main.chat_completion = chat_completion
    sys.modules["open_webui.main"] = fake_main
    route_ns = {
        "BaseModel": BaseModel,
        "Field": Field,
        "Optional": Optional,
        "Request": Request,
        "HTTPException": HTTPException,
        "NOTIFICATION_PROMPT_MAX_CHARS": 8000,
        "notify_token_configured": lambda: True,
        "verify_notify_token": lambda value: value == "Bearer local-notify-only",
        "start_follow_up_turn": notify_ns["start_follow_up_turn"],
        "HermesNotifyError": notify_ns["HermesNotifyError"],
        "log": logging.getLogger("local-fixture"),
    }
    load_functions(
        REPO / "backend/open_webui/routers/hermes.py",
        {"HermesNotificationForm", "receive_hermes_notification"},
        route_ns,
    )
    app = FastAPI()
    app.add_api_route(
        "/api/v1/hermes/notifications",
        route_ns["receive_hermes_notification"],
        methods=["POST"],
    )
    completed_posts = []
    requests = []

    @app.api_route("/api/{path:path}", methods=["GET", "POST"])
    async def api(path: str, request: Request):
        requests.append((request.method, path))
        clean = path.rstrip("/")
        if clean == "config":
            return {
                "name": "HaloWebUI",
                "version": "0.0.1",
                "default_locale": "en-US",
                "default_prompt_suggestions": [],
                "features": {"auth": True, "enable_websocket": True},
            }
        if clean == "version":
            return {"version": "0.0.1"}
        if clean == "v1/auths":
            return {
                "id": user.id,
                "role": "admin",
                "name": "Local fixture",
                "email": "fixture@example.invalid",
                "token": "local-test-only",
                "profile_image_url": "/static/favicon.png",
            }
        if clean == "models" or clean == "models/base":
            return {
                "data": [
                    {
                        "id": "hermes-fixture",
                        "name": "Fixture",
                        "owned_by": "openai",
                        "info": {"meta": {"capabilities": {}}},
                    }
                ]
            }
        if clean == "v1/users/user/settings":
            return {"ui": {"responseAutoPlayback": False}, "revision": 1}
        if clean == "v1/hermes/runs":
            return {"runs": [], "unread": []}
        if clean == "chat/completed":
            completed_posts.append(await request.json())
            return {"messages": []}
        if clean.startswith("v1/chats"):
            parts = clean.split("/")
            cid = parts[2] if len(parts) > 2 else None
            chat = (
                model.Chats.get_chat_by_id(cid)
                if cid in {"fixture-chat", "other-chat"}
                else None
            )
            if chat:
                if clean.endswith("/context"):
                    return {"tags": [], "task_ids": []}
                if request.method == "POST":
                    body = await request.json()
                    if clean.endswith("/composer-state"):
                        chat = model.Chats.update_chat_composer_state_by_id(
                            cid, body.get("composer_state", {})
                        )
                    else:
                        chat = model.Chats.update_chat_by_id(
                            cid,
                            {**chat.chat, **body.get("chat", {})},
                            base_chat=body.get("base_chat"),
                            update_title=False,
                        )
                return chat.model_dump()
            if clean == "v1/chats":
                return [
                    {
                        "id": cid,
                        "title": "Local notification fixture",
                        "updated_at": 1,
                        "created_at": 1,
                    }
                    for cid in ["fixture-chat", "other-chat"]
                ]
        return [] if request.method == "GET" else {"status": True}

    @app.get("/{path:path}")
    async def static(path: str):
        target = (build / path).resolve()
        if target.is_relative_to(build) and target.is_file():
            return FileResponse(target)
        if path.startswith("c/") or not path:
            return FileResponse(build / "index.html")
        return JSONResponse({}, status_code=404)

    bound = socket.socket()
    bound.bind(("127.0.0.1", 0))
    port = bound.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            socketio.ASGIApp(sio, app, socketio_path="ws/socket.io"),
            host="127.0.0.1",
            port=port,
            log_level="error",
            lifespan="off",
        )
    )
    server_task = asyncio.create_task(server.serve(sockets=[bound]))
    while not server.started:
        await asyncio.sleep(0.01)
    base = f"http://127.0.0.1:{port}"

    spec = importlib.util.spec_from_file_location(
        "runner_notify", REPO / "integrations/hermes-runner/reclaude-notify.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    state = workspace / "state.db"
    command = "codex-run.sh run --task 'fixture only, never executed'"
    with sqlite3.connect(state) as db:
        db.executescript(
            "create table sessions(id text,source text); create table messages(session_id text,role text,timestamp real,tool_calls text,tool_call_id text,tool_name text,content text);"
        )
        db.execute("insert into sessions values ('fixture-chat','api_server')")
        db.execute(
            "insert into messages values (?,?,?,?,?,?,?)",
            (
                "fixture-chat",
                "assistant",
                time.time(),
                json.dumps(
                    [
                        {
                            "id": "launch",
                            "function": {
                                "name": "terminal",
                                "arguments": json.dumps({"command": command}),
                            },
                        }
                    ]
                ),
                None,
                None,
                "",
            ),
        )
        db.execute(
            "insert into messages values (?,?,?,?,?,?,?)",
            (
                "fixture-chat",
                "tool",
                time.time(),
                None,
                "launch",
                "terminal",
                '{"session_id":"proc-local"}',
            ),
        )
        db.execute(
            "insert into messages values (?,?,?,?,?,?,?)",
            (
                "fixture-chat",
                "tool",
                time.time(),
                None,
                "poll",
                "process",
                json.dumps(
                    {
                        "session_id": "proc-local",
                        "output_preview": "==== codex run local-run started now ====",
                    }
                ),
            ),
        )

    async def deliver():
        origin = runner.find_origin("local-run", "", "", "codex-run.sh", str(state))
        assert origin == ("fixture-chat", "api_server")
        status_code, _ = await asyncio.to_thread(
            runner.post_notification,
            base + "/api/v1/hermes/notifications",
            "local-notify-only",
            {
                "chat_id": origin[0],
                "run_id": "local-run",
                "source": "codex-runner",
                "prompt": "[后台任务完成通知] LOCAL FIXTURE ONLY",
            },
        )
        assert status_code == 200

    errors = []
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE"),
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            contexts = [
                await browser.new_context(service_workers="block") for _ in range(2)
            ]
            pages = []
            for context in contexts:
                await context.route(
                    "**/*",
                    lambda route: (
                        route.continue_()
                        if route.request.url.startswith(base)
                        or route.request.url.startswith("data:")
                        else route.abort()
                    ),
                )
                await context.add_init_script(
                    "localStorage.token='local-test-only'; localStorage.locale='en-US';"
                )
                page = await context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto(base + "/c/fixture-chat")
                await page.get_by_text("WAITING_FOR_CODEX", exact=True).wait_for(
                    timeout=30000
                )
                pages.append(page)
            await deliver()
            for page in pages:
                await page.get_by_text("LOCAL_CODEX_RESULT_1", exact=True).wait_for(
                    timeout=15000
                )
                assert page.url == base + "/c/fixture-chat"
            await contexts[1].set_offline(True)
            await deliver()
            await pages[0].get_by_text("LOCAL_CODEX_RESULT_2", exact=True).wait_for(
                timeout=15000
            )
            await contexts[1].set_offline(False)
            await pages[1].get_by_text("LOCAL_CODEX_RESULT_2", exact=True).wait_for(
                timeout=15000
            )
            await pages[1].reload()
            await pages[1].get_by_text("LOCAL_CODEX_RESULT_2", exact=True).wait_for(
                timeout=15000
            )
            await pages[1].goto(base + "/c/other-chat")
            await pages[1].get_by_text("WAITING_FOR_CODEX", exact=True).wait_for(
                timeout=15000
            )
            await deliver()
            await pages[0].get_by_text("LOCAL_CODEX_RESULT_3", exact=True).wait_for(
                timeout=15000
            )
            assert pages[1].url == base + "/c/other-chat"
            assert (
                not completed_posts
            ), "observer pages must not duplicate completion writes"
            history = model.Chats.get_chat_by_id("fixture-chat").chat["history"]
            assert len(history["messages"]) == 8
            print(
                json.dumps(
                    {
                        "result": "passed",
                        "scenarios": [
                            "origin lookup",
                            "notification HTTP",
                            "follow-up persistence",
                            "socket broadcast",
                            "two visible browsers",
                            "offline recovery",
                            "reload recovery",
                            "no route hijack",
                            "no observer completion writes",
                        ],
                        "message_count": len(history["messages"]),
                        "browser_errors": errors,
                        "trace": trace,
                    }
                )
            )
            await browser.close()
    except Exception:
        print(
            json.dumps(
                {"browser_errors": errors, "requests": requests[-30:], "trace": trace}
            )
        )
        raise
    finally:
        server.should_exit = True
        await server_task
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend-build", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="halo-notify-fixture-") as directory:
        asyncio.run(verify(args.frontend_build.resolve(), Path(directory)))
