from fastapi import APIRouter, Request

from app.errors import require, store
from app.scenarios import apply_failure
from app.schemas import Note

router = APIRouter(prefix="/api/warehouse", tags=["Warehouse"])


@router.get("/orders/{order_id}/notes", response_model=list[Note])
def notes(order_id: str, request: Request):
    apply_failure("warehouse", order_id)
    require(request, "orders", order_id, "ORDER_NOT_FOUND")
    return store(request).get("notes", order_id)
