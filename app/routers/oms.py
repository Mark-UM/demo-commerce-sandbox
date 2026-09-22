from fastapi import APIRouter, Request

from app.errors import require, store
from app.schemas import Order, Parcel

router = APIRouter(prefix="/api/oms", tags=["OMS"])


@router.get("/orders/{order_id}", response_model=Order)
def order(order_id: str, request: Request):
    return require(request, "orders", order_id, "ORDER_NOT_FOUND")


@router.get("/orders/{order_id}/parcels", response_model=list[Parcel])
def parcels(order_id: str, request: Request):
    require(request, "orders", order_id, "ORDER_NOT_FOUND")
    return store(request).get("parcels", order_id)
