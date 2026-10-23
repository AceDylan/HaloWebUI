"""辅助决策模型 API: /api/v1/decision-model — the user's own setting (utils/decision_model.py)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from open_webui.utils import decision_model as dm
from open_webui.utils.auth import get_verified_user

router = APIRouter()


class SetForm(BaseModel):
    # a selection id from the candidates; "" / null = 沿用现有逻辑
    model: Optional[str] = Field(default=None, max_length=500)


async def _state(request: Request, user) -> dict:
    from open_webui.utils.models import get_all_models

    await get_all_models(request, user=user)
    models_map = getattr(request.state, "MODELS", None) or {}
    options = dm.candidates(models_map, user)
    model = dm.configured(user)
    current = next((c for c in options if c["id"] == model), None)
    return {
        "model": model or None,
        "name": current["name"] if current else None,
        "kind": current["kind"] if current else None,
        # set, but the model is gone or no longer allowed: decisions fall back until it is changed
        "available": bool(current) if model else None,
        "candidates": options,
    }


@router.get("/")
async def get_decision_model(request: Request, user=Depends(get_verified_user)):
    return await _state(request, user)


@router.post("/")
async def set_decision_model(request: Request, form: SetForm, user=Depends(get_verified_user)):
    from open_webui.models.users import Users

    model = (form.model or "").strip()
    if model:
        from open_webui.utils.models import get_all_models

        await get_all_models(request, user=user)
        if not any(c["id"] == model for c in dm.candidates(getattr(request.state, "MODELS", None) or {}, user)):
            raise HTTPException(status_code=400, detail="这个模型不能用作辅助决策模型（不存在、没有权限或不是文字/判断模型）")
    dm.save(user.id, model)
    return await _state(request, Users.get_user_by_id(user.id) or user)
