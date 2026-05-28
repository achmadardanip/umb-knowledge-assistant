from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException

from app.chat.memory_service import delete_memory, get_active_memories, refresh_session_memory, toggle_memory
from app.db.database import get_db


router = APIRouter(tags=["memory"])


class MemoryToggleRequest(BaseModel):
    memory_enabled: bool


def serialize_memory(memory) -> dict:
    return {
        "id": memory.id,
        "memory_type": memory.memory_type,
        "content": memory.content,
        "importance_score": memory.importance_score,
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
        "expires_at": memory.expires_at.isoformat() if memory.expires_at else None,
        "is_active": memory.is_active,
    }


@router.get("/sessions/{session_id}/memory")
def get_memory(session_id: str, db: Session = Depends(get_db)) -> dict:
    return {"memories": [serialize_memory(memory) for memory in get_active_memories(db, session_id)]}


@router.patch("/sessions/{session_id}/memory-toggle")
def patch_memory_toggle(session_id: str, payload: MemoryToggleRequest, db: Session = Depends(get_db)) -> dict:
    session = toggle_memory(db, session_id, payload.memory_enabled)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session.id, "memory_enabled": session.memory_enabled}


@router.delete("/memories/{memory_id}")
def remove_memory(memory_id: str, db: Session = Depends(get_db)) -> dict:
    if not delete_memory(db, memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"ok": True}


@router.post("/sessions/{session_id}/memory/refresh")
def refresh_memory(session_id: str, db: Session = Depends(get_db)) -> dict:
    memory = refresh_session_memory(db, session_id)
    if not memory:
        return {"memory": None, "status": "skipped"}
    db.commit()
    db.refresh(memory)
    return {"memory": serialize_memory(memory), "status": "updated"}

