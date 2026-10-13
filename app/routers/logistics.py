from fastapi import APIRouter, Request

from app.errors import require, store
from app.scenarios import apply_failure, source_payload
from app.schemas import Event, Shipment

router = APIRouter(prefix="/api/logistics", tags=["Logistics"])


@router.get("/shipments/{tracking_number}", response_model=Shipment)
def shipment(tracking_number: str, request: Request):
    mode = apply_failure(store(request), "logistics", tracking_number)
    data = require(request, "shipments", tracking_number, "SHIPMENT_NOT_FOUND")
    return source_payload(mode, data, "logistics")


@router.get("/shipments/{tracking_number}/events", response_model=list[Event])
def events(tracking_number: str, request: Request):
    mode = apply_failure(store(request), "logistics", tracking_number)
    require(request, "shipments", tracking_number, "SHIPMENT_NOT_FOUND")
    return source_payload(
        mode, store(request).get("events", tracking_number), "logistics"
    )
