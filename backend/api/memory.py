"""Memory management endpoints."""

from typing import Optional
from uuid import UUID as UUIDType

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from jose import JWTError
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import decode_access_token
from db.session import get_session
from services.memory.long_term_memory import (
    create_memory,
    deactivate_memory,
    list_memories,
    memory_to_dict,
)
from services.memory.short_term_memory import read_short_memory, write_short_memory


router = APIRouter()


class LongTermMemoryCreate(BaseModel):
    content: str = Field(..., min_length=1)
    memory_type: str = Field("fact")
    summary: Optional[str] = None
    importance: int = Field(5, ge=1, le=10)
    source_session_id: Optional[str] = None
    source_message_id: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class ShortTermMemoryUpdate(BaseModel):
    content: str = Field(..., min_length=1)


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


@router.get("/memory/short/{session_id}", tags=["memory"])
async def get_short_memory(session_id: str, request: Request):
    """Return the Markdown short-term memory for a session."""
    user_id = _optional_user_id(request)
    content = read_short_memory(str(user_id) if user_id else None, session_id)
    return {
        "user_id": str(user_id) if user_id else None,
        "session_id": session_id,
        "content": content,
    }


@router.put("/memory/short/{session_id}", tags=["memory"])
async def put_short_memory(session_id: str, payload: ShortTermMemoryUpdate, request: Request):
    """Replace the Markdown short-term memory for a session."""
    user_id = _optional_user_id(request)
    path = write_short_memory(str(user_id) if user_id else None, session_id, payload.content)
    return {
        "status": "updated",
        "user_id": str(user_id) if user_id else None,
        "session_id": session_id,
        "path": str(path),
    }


@router.get("/memory/long", tags=["memory"])
async def get_long_memories(
    request: Request,
    db: AsyncSession = Depends(get_session),
    limit: int = Query(20, ge=1, le=100),
    include_inactive: bool = Query(False),
):
    """List long-term memories for the authenticated user."""
    user_id = _optional_user_id(request)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    memories = await list_memories(
        db, user_id=user_id, limit=limit, include_inactive=include_inactive
    )
    return {"data": [memory_to_dict(memory) for memory in memories]}


@router.post("/memory/long", tags=["memory"], status_code=status.HTTP_201_CREATED)
async def post_long_memory(
    payload: LongTermMemoryCreate,
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """Create a long-term memory for the authenticated user."""
    user_id = _optional_user_id(request)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    memory = await create_memory(
        db,
        user_id=user_id,
        content=payload.content,
        memory_type=payload.memory_type,
        summary=payload.summary,
        importance=payload.importance,
        source_session_id=payload.source_session_id,
        source_message_id=payload.source_message_id,
        tags=payload.tags,
    )
    return memory_to_dict(memory)


@router.delete("/memory/long/{memory_id}", tags=["memory"])
async def delete_long_memory(
    memory_id: UUIDType,
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """Soft-delete a long-term memory for the authenticated user."""
    user_id = _optional_user_id(request)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    deleted = await deactivate_memory(db, user_id=user_id, memory_id=memory_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    return {"status": "deleted", "id": str(memory_id)}
