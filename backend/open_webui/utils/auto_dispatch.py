"""Chat adapter for the same automatic workbench used by /auto."""
import time

from fastapi import HTTPException


async def run_auto_dispatch(request, form_data, user, metadata, model_id):
    from open_webui.models.chats import Chats
    from open_webui.routers.auto import CreateForm, start
    from open_webui.socket.main import get_event_emitter
    from open_webui.tasks import create_task
    from open_webui.utils.dispatch_files import conversation_file_ids
    from open_webui.utils.hermes_agent import is_temporary_chat_id
    from open_webui.utils.mode_dispatch import conversation_of

    chat_id, message_id = metadata["chat_id"], metadata["message_id"]
    emitter = get_event_emitter(metadata)
    ask, background = conversation_of(form_data.get("messages"))

    async def handler():
        fields = {"done": True, "completedAt": int(time.time()), "model": model_id}
        try:
            if is_temporary_chat_id(chat_id):
                raise HTTPException(400, "临时对话不能自动派发，请先保存对话")
            if not ask:
                raise HTTPException(400, "请写下问题或任务")
            files = conversation_file_ids(metadata, form_data.get("messages"))
            if len(files) > 4:
                raise HTTPException(400, "自动分流最多携带 4 个附件，请减少附件后重试")
            row = await start(request, user, CreateForm(question=ask, context=background,
                files=files, client_key=f"chat:{chat_id}:{message_id}"),
                origin={"chatId": chat_id, "messageId": message_id})
            Chats.set_chat_meta_value_by_id(chat_id, "auto_route", {"id": row["id"], "mode": row.get("mode")})
            from open_webui.utils.mode_chats import schedule_chat_metadata
            from open_webui.utils.team_chats import emit_chat_event
            await emit_chat_event(user.id, chat_id, "chat:title", Chats.get_chat_title_by_id(chat_id))
            asks = [m for m in (form_data.get("messages") or []) if isinstance(m, dict) and m.get("role") == "user"]
            schedule_chat_metadata(request, user, chat_id, model_id=model_id,
                messages=[{"role": "user", "content": ask}], message_id=message_id,
                user_message_count=max(1, len(asks)))
            fields.update(content="已交给自动分流工作台：正在选择处理方式，结果会发回这个对话。",
                          auto_route={"id": row["id"]})
        except Exception as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else "请稍后再试"
            fields.update(content=f"未能自动分流：{detail}", error={"content": str(detail)})
        Chats.upsert_message_to_chat_by_id_and_message_id(chat_id, message_id, fields)
        await emitter({"type": "chat:completion", "data": fields})

    task_id, _ = create_task(handler(), id=chat_id, owner_id=user.id)
    return {"status": True, "task_id": task_id}
