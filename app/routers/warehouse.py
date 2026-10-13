from fastapi import APIRouter, Request

from app.errors import require, store
from app.scenarios import apply_failure, source_payload
from app.schemas import Note

router = APIRouter(prefix="/api/warehouse", tags=["Warehouse"])


@router.get("/orders/{order_id}/notes", response_model=list[Note])
def notes(order_id: str, request: Request):
    mode = apply_failure(store(request), "warehouse", order_id)
    require(request, "orders", order_id, "ORDER_NOT_FOUND")
    return source_payload(mode, store(request).get("notes", order_id), "warehouse")
