from fastapi import APIRouter, HTTPException

from app.schemas.trace import TraceDetail
from app.services.trace_store import get_trace_store


router = APIRouter()


@router.get("/traces/{trace_id}", response_model=TraceDetail)
def get_trace(trace_id: str) -> TraceDetail:
    trace = get_trace_store().get_trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace
