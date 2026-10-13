from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


InquiryStatus = Literal["OPEN", "REPLIED"]


class Inquiry(SourceModel):
    inquiry_id: Identifier
    order_id: str | None
    customer_message: Identifier
    created_at: datetime
    status: InquiryStatus = "OPEN"


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


class AcceptedReply(Receipt):
    inquiry_id: Identifier
    text: str
    idempotency_key: Identifier


class ResetCommand(SourceModel):
    base_time: datetime | None = None

    @field_validator("base_time", mode="before")
    @classmethod
    def timestamp_string(cls, value):
        if value is not None and not isinstance(value, str):
            raise ValueError("Use an ISO 8601 UTC timestamp string")
        return value

    @field_validator("base_time")
    @classmethod
    def utc_reference(cls, value):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError("Seed reference time must be timezone-aware UTC")
            try:
                value - timedelta(days=5)
            except OverflowError as error:
                raise ValueError("Seed reference time is out of range") from error
        return value


class ResetResult(SourceModel):
    status: Literal["RESET"]
    seed_version: str
    base_time: datetime


class PolicyFact(SourceModel):
    code: Identifier
    content: Identifier
    updated_at: datetime | None


class PolicyFacts(SourceModel):
    facts: list[PolicyFact]


class Summary(SourceModel):
    seed_version: str
    base_time: datetime
    scenarios: int
    customers: int
    products: int
    orders: int
    parcels: int
    shipments: int
    shipment_events: int
    warehouse_notes: int
    inquiries: int
    replies: int
    fault_overrides: int


class ErrorDetail(SourceModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(SourceModel):
    error: ErrorDetail


FaultSystem = Literal["logistics", "warehouse"]
FaultMode = Literal[
    "NORMAL",
    "TIMEOUT_ONCE",
    "ALWAYS_TIMEOUT",
    "HTTP_500",
    "HTTP_429",
    "SLOW_RESPONSE",
    "STALE_DATA",
    "EMPTY_RESULT",
    "PARTIAL_FAILURE",
    "CONFLICTING_DATA",
    "MALFORMED_RESPONSE",
]


class FaultCommand(SourceModel):
    mode: FaultMode
    delay_ms: Annotated[int, Field(strict=True, ge=0, le=10000)] = 0

    @model_validator(mode="after")
    def validate_delay(self):
        if (self.mode == "SLOW_RESPONSE") != (self.delay_ms > 0):
            raise ValueError("Positive delay_ms is required only for SLOW_RESPONSE")
        return self


class FaultState(FaultCommand):
    system: FaultSystem
    record_id: Identifier
    remaining_failures: int | None
