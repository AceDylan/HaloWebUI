"""Obsidian 笔记 for the composer (utils/vault_notes.py). Admin only: the vault is the
owner's private notes.

GET /api/v1/vault/notes?q= — notes matching the words (the newest ones without any)
GET /api/v1/vault/note?path= — one note's text, to attach to a message
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from open_webui.utils.auth import get_admin_user
from open_webui.utils.vault_notes import VaultError, read_note, search_notes, vault_dir

router = APIRouter()


@router.get("/notes")
async def list_vault_notes(
    q: str = Query("", max_length=200),
    limit: int = Query(12, ge=1, le=50),
    user=Depends(get_admin_user),
):
    if vault_dir() is None:
        return {"enabled": False, "notes": []}
    return {"enabled": True, "notes": await asyncio.to_thread(search_notes, q, limit)}


@router.get("/note")
async def get_vault_note(path: str = Query(..., max_length=1024), user=Depends(get_admin_user)):
    try:
        return await asyncio.to_thread(read_note, path)
    except VaultError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
