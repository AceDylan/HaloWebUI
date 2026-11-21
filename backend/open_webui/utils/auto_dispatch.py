"""Chat adapter for the same automatic workbench used by /auto.

The reply waits for the choice (its card shows it being made): handed to 精答 / 讨论 / 协作台 it
ends as the note on where it went, with that mode's card; handed to Hermes it goes on as Hermes'
own answer to the message, as if it had been sent with 「直接」.
"""
import asyncio
import time

from fastapi import HTTPException

# What the reply says while the mode is being chosen.
CHOOSING = "🔀 自动分流：正在判断交给 Hermes、精答、讨论还是协作台，选择依据在下面的卡片里。"


async def run_auto_dispatch(request, form_data, user, metadata, model_id, model=None, events=None):
    from open_webui.models.auto_routes import AutoRoutes
    from open_webui.models.chats import Chats
    from open_webui.routers.auto import CreateForm, routed, start
    from open_webui.socket.main import get_event_emitter
    from open_webui.tasks import create_task
    from open_webui.utils.dispatch_files import conversation_file_ids
    from open_webui.utils.hermes_agent import is_temporary_chat_id
    from open_webui.utils.hermes_route import run_turn
    from open_webui.utils.mode_dispatch import conversation_of

    chat_id, message_id = metadata["chat_id"], metadata["message_id"]
    if is_temporary_chat_id(chat_id):
        # nothing can be sent back into an unsaved chat: Hermes, the one that answers here, takes it
        return await run_turn(request, form_data, user, metadata, model or {"id": model_id}, events)
    emitter = get_event_emitter(metadata)
    ask, background = conversation_of(form_data.get("messages"))

    async def handler():
        fields = {"done": True, "completedAt": int(time.time()), "model": model_id}
        route_id = None
        try:
            if not ask:
                raise HTTPException(400, "请写下问题或任务")
            files = conversation_file_ids(metadata, form_data.get("messages"))
            if len(files) > 4:
                raise HTTPException(400, "自动分流最多携带 4 个附件，请减少附件后重试")
            row = await start(request, user, CreateForm(question=ask, context=background,
                files=files, client_key=f"chat:{chat_id}:{message_id}"),
                origin={"chatId": chat_id, "messageId": message_id}, chat_turn=True)
            route_id = row["id"]
            Chats.set_chat_meta_value_by_id(chat_id, "auto_route", {"id": route_id, "mode": row.get("mode")})
            from open_webui.utils.mode_chats import schedule_chat_metadata
            from open_webui.utils.team_chats import emit_chat_event
            await emit_chat_event(user.id, chat_id, "chat:title", Chats.get_chat_title_by_id(chat_id))
            asks = [m for m in (form_data.get("messages") or []) if isinstance(m, dict) and m.get("role") == "user"]
            schedule_chat_metadata(request, user, chat_id, model_id=model_id,
                messages=[{"role": "user", "content": ask}], message_id=message_id,
                user_message_count=max(1, len(asks)))
            choosing = {"content": CHOOSING, "auto_route": {"id": route_id}}
            Chats.upsert_message_to_chat_by_id_and_message_id(chat_id, message_id, choosing)
            await emitter({"type": "chat:completion", "data": choosing})
            row = await routed(route_id, user)
            if row["status"] == "dispatched" and row.get("mode") == "hermes":
                handed = {"content": "", "auto_route": {"id": route_id, "mode": "hermes"}}
                Chats.upsert_message_to_chat_by_id_and_message_id(chat_id, message_id, handed)
                await emitter({"type": "chat:completion", "data": handed})
                result = await run_turn(request, form_data, user, metadata, model or {"id": model_id}, events,
                                        wait=True)
                if result:
                    return  # Hermes' run finished the reply
                raise HTTPException(503, "Hermes 现在连不上，请稍后重试或改选精答")
            # where it went (utils/auto.py rewrote the reply), or the reason it went nowhere
            content = (Chats.get_message_by_id_and_message_id(chat_id, message_id) or {}).get("content") or CHOOSING
            if content == CHOOSING and row["status"] in ("error", "interrupted", "cancelled"):
                why = (row["data"].get("error") or "已取消").rstrip("。")
                content = f"🔀 自动分流没有派发：{why}。可以在下面的卡片里重新分流，或直接交给 Hermes、精答、讨论或协作台。"
            fields.update(content=content, auto_route={"id": route_id})
        except asyncio.CancelledError:
            if route_id:  # stopped while choosing: nothing is dispatched after all
                AutoRoutes.update(route_id, user.id, expect=("routing",), status="cancelled")
            raise
        except Exception as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else "请稍后再试"
            fields.update(content=f"未能自动分流：{detail}", error={"content": str(detail)})
            if route_id:
                fields["auto_route"] = {"id": route_id}
        Chats.upsert_message_to_chat_by_id_and_message_id(chat_id, message_id, fields)
        await emitter({"type": "chat:completion", "data": fields})

    task_id, _ = create_task(handler(), id=chat_id, owner_id=user.id, kind="dispatch")
    return {"status": True, "task_id": task_id}
