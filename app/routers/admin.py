from fastapi import APIRouter, Request, Response

from app.errors import require, store
from app.schemas import FaultCommand, FaultState, FaultSystem

router = APIRouter(prefix="/api/admin/scenarios", tags=["Scenario controls"])


@router.get("", response_model=list[FaultState])
def scenarios(request: Request):
    return store(request).list_faults()


@router.put("/{system}/{record_id}", response_model=FaultState)
def configure(
    system: FaultSystem, record_id: str, command: FaultCommand, request: Request
):
    collection, code = (
        ("shipments", "SHIPMENT_NOT_FOUND")
        if system == "logistics"
        else ("orders", "ORDER_NOT_FOUND")
    )
    require(request, collection, record_id, code)
    return store(request).set_fault(system, record_id, command)


@router.delete("/{system}/{record_id}", status_code=204)
def clear(system: FaultSystem, record_id: str, request: Request):
    store(request).delete_fault(system, record_id)
    return Response(status_code=204)
