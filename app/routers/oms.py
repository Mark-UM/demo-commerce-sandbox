from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.errors import SourceError, require, store
from app.schemas import Order, Parcel

router = APIRouter(prefix="/api/oms", tags=["OMS"])


@router.get("/customers/{customer_id}/orders", response_model=list[Order])
def customer_orders(
    customer_id: str,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    database = store(request)
    if not database.customer_exists(customer_id):
        raise SourceError(404, "CUSTOMER_NOT_FOUND", "Customer was not found")
    return database.customer_orders(customer_id, limit, offset)


@router.get("/orders/{order_id}", response_model=Order)
def order(order_id: str, request: Request):
    return require(request, "orders", order_id, "ORDER_NOT_FOUND")


@router.get("/orders/{order_id}/parcels", response_model=list[Parcel])
def parcels(order_id: str, request: Request):
    require(request, "orders", order_id, "ORDER_NOT_FOUND")
    return store(request).get("parcels", order_id)
