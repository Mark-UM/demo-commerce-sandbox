from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.errors import SourceError, require, store
from app.schemas import (
    AcceptedReply,
    CustomerMessageCreate,
    Inquiry,
    InquiryCreate,
    InquiryStatus,
    Receipt,
    ReplyCommand,
    SupportMessage,
)

router = APIRouter(prefix="/api/support", tags=["Support"])

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.post("/inquiries", response_model=Inquiry, status_code=201)
def receive_inquiry(command: InquiryCreate, request: Request):
    return store(request).receive_customer(command)


@router.get("/inquiries/{inquiry_id}/messages", response_model=list[SupportMessage])
def messages(inquiry_id: str, request: Request, limit: Limit = 50, offset: Offset = 0):
    require(request, "inquiries", inquiry_id, "INQUIRY_NOT_FOUND")
    return store(request).messages(inquiry_id, limit, offset)


@router.post(
    "/inquiries/{inquiry_id}/messages", response_model=SupportMessage, status_code=201
)
def customer_message(inquiry_id: str, command: CustomerMessageCreate, request: Request):
    return store(request).receive_customer(command, inquiry_id)


@router.get("/inquiries", response_model=list[Inquiry])
def inquiries(
    request: Request,
    limit: Limit = 50,
    offset: Offset = 0,
    order_id: Annotated[str | None, Query(min_length=1)] = None,
    status: InquiryStatus | None = None,
):
    return store(request).list_inquiries(limit, offset, order_id, status)


@router.get("/inquiries/{inquiry_id}", response_model=Inquiry)
def inquiry(inquiry_id: str, request: Request):
    return require(request, "inquiries", inquiry_id, "INQUIRY_NOT_FOUND")


@router.get("/inquiries/{inquiry_id}/replies", response_model=list[AcceptedReply])
def replies(inquiry_id: str, request: Request, limit: Limit = 50, offset: Offset = 0):
    require(request, "inquiries", inquiry_id, "INQUIRY_NOT_FOUND")
    return store(request).list_replies(inquiry_id, limit, offset)


@router.post("/inquiries/{inquiry_id}/replies", response_model=Receipt)
def reply(inquiry_id: str, command: ReplyCommand, request: Request):
    require(request, "inquiries", inquiry_id, "INQUIRY_NOT_FOUND")
    try:
        return store(request).reply(inquiry_id, command)
    except ValueError as error:
        raise SourceError(409, "IDEMPOTENCY_CONFLICT", str(error)) from error
