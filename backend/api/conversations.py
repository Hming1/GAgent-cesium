"""HTTP API for persisted chat conversations."""

from __future__ import annotations

from typing import Optional
from uuid import UUID as UUIDType

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import decode_access_token
from db.session import get_session
from services.conversation.store import ConversationStore

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _optional_user_id(request: Request) -> Optional[UUIDType]:
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        return UUIDType(user_id) if user_id else None
    except (JWTError, ValueError, TypeError):
        return None


@router.get("")
async def list_conversations(
    request: Request,
    db: AsyncSession = Depends(get_session),
    session_id: Optional[str] = Query(default=None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List recent conversations for the current user (or session fallback)."""
    user_id = _optional_user_id(request)
    if not user_id and not session_id:
        raise HTTPException(
            status_code=400,
            detail="登录用户或提供 session_id 后才能列出会话",
        )
    store = ConversationStore(db)
    items = await store.list_conversations(
        user_id=user_id,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )
    return {"conversations": items, "count": len(items)}


@router.get("/{conversation_id}")
async def get_conversation_messages(
    conversation_id: str,
    request: Request,
    db: AsyncSession = Depends(get_session),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    include_tool_messages: bool = Query(True),
):
    """Fetch ordered messages for a conversation (for history restore / eval)."""
    store = ConversationStore(db)
    payload = await store.get_messages(
        conversation_id,
        limit=limit,
        offset=offset,
        include_tool_messages=include_tool_messages,
    )
    if payload.get("conversation") is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    conversation = payload["conversation"]
    user_id = _optional_user_id(request)
    # Soft ownership check: if conversation has a user, require matching login.
    if conversation.get("user_id") and user_id and str(user_id) != conversation["user_id"]:
        raise HTTPException(status_code=403, detail="无权访问该会话")

    return payload
