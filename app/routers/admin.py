from fastapi import APIRouter, Request, Response

from app.errors import require, store
from app.schemas import FaultCommand, FaultState, FaultSystem, ResetCommand, ResetResult
from app.seed import BASE_TIME

router = APIRouter(prefix="/api/admin", tags=["Scenario controls"])


@router.get("/scenarios", response_model=list[FaultState])
def scenarios(request: Request):
    return store(request).list_faults()


@router.put("/scenarios/{system}/{record_id}", response_model=FaultState)
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


@router.delete("/scenarios/{system}/{record_id}", status_code=204)
def clear(system: FaultSystem, record_id: str, request: Request):
    store(request).delete_fault(system, record_id)
    return Response(status_code=204)


@router.post("/reset", response_model=ResetResult)
def reset(command: ResetCommand, request: Request):
    reference = command.base_time or BASE_TIME
    store(request).initialize(reset=True, base_time=reference)
    return ResetResult(status="RESET", seed_version="s0-s1-v1", base_time=reference)
