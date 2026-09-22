from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Identifier = Annotated[str, Field(min_length=1)]


class SourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Item(SourceModel):
    sku: Identifier
    product_name: Identifier
    quantity: Annotated[int, Field(gt=0)]


class Order(SourceModel):
    order_id: Identifier
    customer_reference: str | None
    status: Identifier
    items: list[Item]
    created_at: datetime
    updated_at: datetime | None


class Parcel(SourceModel):
    parcel_id: Identifier
    order_id: Identifier
    carrier: str | None
    tracking_number: str | None
    updated_at: datetime | None


class Shipment(SourceModel):
    tracking_number: Identifier
    parcel_id: Identifier
    status: str | None
    updated_at: datetime | None


class Event(SourceModel):
    event_id: Identifier
    parcel_id: Identifier
    status: Identifier
    description: str
    occurred_at: datetime
    updated_at: datetime | None


class Note(SourceModel):
    note_id: Identifier
    order_id: Identifier
    text: str
    created_at: datetime
    updated_at: datetime | None


class Inquiry(SourceModel):
    inquiry_id: Identifier
    order_id: str | None
    customer_message: Identifier
    created_at: datetime


class ReplyCommand(SourceModel):
    text: Annotated[str, Field(min_length=1, max_length=10000)]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)]

    @field_validator("text", "idempotency_key")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Must not be blank")
        return value


class Receipt(SourceModel):
    reply_id: Identifier
    status: Literal["SENT"]
    sent_at: datetime


class ErrorDetail(SourceModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(SourceModel):
    error: ErrorDetail
