"""Manual source updates for test drivers; each endpoint writes one subsystem."""

from fastapi import APIRouter, Request

from app.errors import store
from app.schemas import (
    Event,
    Note,
    Order,
    OrderState,
    Parcel,
    ParcelAssignment,
    Shipment,
    ShipmentState,
)

router = APIRouter(prefix="/api/admin", tags=["Source simulation"])


@router.post("/oms/orders", response_model=Order, status_code=201)
def create_order(command: Order, request: Request):
    return store(request).source_write("create_order", command)


@router.patch("/oms/orders/{order_id}", response_model=Order)
def update_order(order_id: str, command: OrderState, request: Request):
    return store(request).source_write("update_order", command, order_id)


@router.post("/oms/orders/{order_id}/parcels", response_model=Parcel, status_code=201)
def create_parcel(order_id: str, command: Parcel, request: Request):
    return store(request).source_write("create_parcel", command, order_id)


@router.patch("/oms/parcels/{parcel_id}", response_model=Parcel)
def assign_parcel(parcel_id: str, command: ParcelAssignment, request: Request):
    return store(request).source_write("assign_parcel", command, parcel_id)


@router.post("/logistics/shipments", response_model=Shipment, status_code=201)
def create_shipment(command: Shipment, request: Request):
    return store(request).source_write("create_shipment", command)


@router.patch("/logistics/shipments/{tracking_number}", response_model=Shipment)
def update_shipment(tracking_number: str, command: ShipmentState, request: Request):
    return store(request).source_write("update_shipment", command, tracking_number)


@router.post(
    "/logistics/shipments/{tracking_number}/events",
    response_model=Event,
    status_code=201,
)
def append_event(tracking_number: str, command: Event, request: Request):
    return store(request).source_write("append_event", command, tracking_number)


@router.post("/warehouse/orders/{order_id}/notes", response_model=Note, status_code=201)
def append_note(order_id: str, command: Note, request: Request):
    return store(request).source_write("append_note", command, order_id)
