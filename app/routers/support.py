from fastapi import APIRouter, Request

from app.errors import SourceError, require, store
from app.schemas import Inquiry, Receipt, ReplyCommand

router = APIRouter(prefix="/api/support", tags=["Support"])


@router.get("/inquiries/{inquiry_id}", response_model=Inquiry)
def inquiry(inquiry_id: str, request: Request):
    return require(request, "inquiries", inquiry_id, "INQUIRY_NOT_FOUND")


@router.post("/inquiries/{inquiry_id}/replies", response_model=Receipt)
def reply(inquiry_id: str, command: ReplyCommand, request: Request):
    require(request, "inquiries", inquiry_id, "INQUIRY_NOT_FOUND")
    try:
        return store(request).reply(inquiry_id, command)
    except ValueError as error:
        raise SourceError(409, "IDEMPOTENCY_CONFLICT", str(error)) from error
