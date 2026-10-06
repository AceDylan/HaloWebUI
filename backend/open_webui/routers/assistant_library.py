"""助手库 API: /api/v1/assistant-library (see utils/assistant_library.py).

The assistants the workbenches and the chat's assistant picker can use (hidden ones included),
an assistant's versions (restore one, undo what a run changed), archiving, and the version a chat
keeps of an assistant. Creating and editing by hand stays with /api/v1/models.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from open_webui.models.chats import Chats
from open_webui.models.models import Models
from open_webui.utils import assistant_library as lib
from open_webui.utils.access_control import can_read_resource, can_write_resource, has_permission
from open_webui.utils.auth import get_verified_user

router = APIRouter()


def _may_write(request: Request, user) -> bool:
    if getattr(user, "role", None) == "admin":
        return True
    return has_permission(user.id, "workspace.models", request.app.state.config.USER_PERMISSIONS)


def _fail(exc: lib.LibraryError):
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


async def _models_map(request: Request, user) -> dict:
    from open_webui.utils.models import get_all_models

    if not getattr(request.state, "MODELS", None):
        await get_all_models(request, user=user)
    return getattr(request.state, "MODELS", None) or {}


def _readable(model_id: str, user):
    row = Models.get_model_by_id(model_id)
    if row is None or not row.base_model_id:
        raise HTTPException(status_code=404, detail="这个助手不存在")
    if not can_read_resource(user, row):
        raise HTTPException(status_code=403, detail="没有查看这个助手的权限")
    return row


@router.get("/")
async def list_library(request: Request, user=Depends(get_verified_user)):
    """The assistants a workbench or the chat may use, with their settings."""
    assistants, bases = lib.library(await _models_map(request, user), user)
    return {
        "assistants": [{**a, "baseName": lib.base_name(bases, a["base"])} for a in assistants],
        "may_write": _may_write(request, user),
        "favorites": lib.favorites_of(user),
    }


@router.get("/templates")
async def templates(q: str = "", refs: str = "", limit: int = 20, user=Depends(get_verified_user)):
    """Built-in templates: the ones named in ``refs`` (comma-separated ``builtin:<id>``), else the
    best matches for ``q`` (without their prompts; the page does not need them to pick one)."""
    keys = ("ref", "id", "name", "emoji", "description", "groups")
    if refs:
        found = [lib.builtin_by_ref(ref) for ref in refs.split(",")[:50]]
        return [{k: t[k] for k in keys} for t in found if t]
    limit = max(1, min(int(limit or 20), 50))
    if not q.strip():
        return [{k: t[k] for k in keys} for t in lib.builtin_templates()[:limit]]
    _, found = lib.shortlist(q, [], user_limit=0, builtin_limit=limit)
    return [{k: t[k] for k in keys} for t in found]


@router.get("/versions")
async def versions(id: str, user=Depends(get_verified_user)):
    row = _readable(id, user)
    info = lib.lib_meta(row.meta)
    return {
        "id": row.id,
        "name": row.name,
        "editable": can_write_resource(user, row),
        "source": info["source"],
        "domain": info["domain"],
        "createdFor": info.get("createdFor"),
        "current": {
            "version": info["version"],
            "name": row.name,
            "system": str(row.params.model_dump().get("system") or ""),
            "description": row.meta.description or "",
            "at": int((row.updated_at or 0) * 1000),
        },
        "revisions": list(reversed(info["revisions"])),
    }


class RestoreForm(BaseModel):
    version: int


@router.post("/restore")
async def restore(id: str, form: RestoreForm, user=Depends(get_verified_user)):
    try:
        lib.restore_version(user, id, form.version)
    except lib.LibraryError as exc:
        _fail(exc)
    return await versions(id, user)


class ArchiveForm(BaseModel):
    archived: bool


@router.post("/archive")
async def archive(id: str, form: ArchiveForm, user=Depends(get_verified_user)):
    try:
        row = lib.set_archived(user, id, form.archived)
    except lib.LibraryError as exc:
        _fail(exc)
    return {"id": row.id, "archived": form.archived, "is_active": row.is_active}


class UndoForm(BaseModel):
    id: str
    run_ref: str
    after_system: Optional[str] = None


@router.post("/undo")
async def undo(form: UndoForm, user=Depends(get_verified_user)):
    """Undo the upgrade one run made (``answer:<chat>``, ``discuss:<chat>:<ask>``, ``team:<id>``)."""
    try:
        row = lib.undo_run(user, form.id, form.run_ref, after_system=form.after_system)
    except lib.LibraryError as exc:
        _fail(exc)
    return {"id": row.id, "version": lib.lib_meta(row.meta)["version"]}


def _own_chat(chat_id: str, user):
    chat = Chats.get_chat_by_id_and_user_id(chat_id, user.id)
    if chat is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return chat


@router.get("/pins/{chat_id}")
async def pins(chat_id: str, user=Depends(get_verified_user)):
    """The assistants this chat keeps at an older version than their current one."""
    chat = _own_chat(chat_id, user)
    out = []
    for model_id, pin in ((chat.meta or {}).get(lib.PIN_META_KEY) or {}).items():
        row = Models.get_model_by_id(model_id)
        if row is None or not isinstance(pin, dict):
            continue
        current = lib.lib_meta(row.meta)["version"]
        if pin.get("version") != current:
            out.append({"id": model_id, "name": row.name, "pinned": pin.get("version"), "current": current})
    return out


class RefreshForm(BaseModel):
    id: str


@router.post("/pins/{chat_id}/refresh")
async def refresh_pin(chat_id: str, form: RefreshForm, user=Depends(get_verified_user)):
    """Switch this chat to the assistant's current version."""
    _own_chat(chat_id, user)
    row = _readable(form.id, user)
    lib.pin_chat(
        chat_id,
        row.id,
        {"version": lib.lib_meta(row.meta)["version"], "system": row.params.model_dump().get("system") or "", "name": row.name, "base": row.base_model_id},
    )
    return {"ok": True}
