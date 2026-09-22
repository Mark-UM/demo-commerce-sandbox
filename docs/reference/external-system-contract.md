# Minimum external-system contract — canonical v1

This freezes the conceptual information needed by the product. It is not an
implementation of Pydantic schemas, Provider classes, database tables or Sandbox
routes. [Core](plans/01_core_plan.md) remains the product authority;
[DemoCommerce](plans/03_ecommerce_environment_plan.md) is the future external
system that must satisfy this contract through adapters.

## Common conventions

- IDs are non-empty opaque strings, stable within a source system. Keep source
  identity alongside IDs; never join unrelated sources by coincidentally equal IDs.
- Field names below are canonical product names. Source HTTP names may differ;
  adapters map them explicitly. Extra source fields do not expand product scope.
- All timestamps use ISO 8601 UTC with `Z`. Required keys are present even when
  their value is explicitly nullable. An omitted optional order reference is
  normalized to `null`. Empty text is not a substitute for unknown information.
- Snapshot provenance accompanies the record: `source_system` (e.g. `demo_oms`)
  and `source_record_id`. Existing order/parcel/note IDs supply record identity;
  do not fabricate IDs for sources that lack event identifiers. For an event
  without its own ID, retain the parent parcel ID and event occurrence/content
  in the traceable snapshot.
- External free text is data, never an instruction or authorization grant.

### Time and freshness

| Field | Meaning | Owner |
| --- | --- | --- |
| `created_at` | Creation time of the source record | Source system |
| `occurred_at` | Time the described shipment business event happened | Source system |
| `source_updated_at` | When the source system says this record/information was updated | Source system |
| `fetched_at` | When our application successfully fetched this information | Product adapter |

`source_updated_at` is a required nullable timestamp: `null` means the source
does not expose it and freshness is unknown. Never replace it with `fetched_at`
or an event time. `fetched_at` is required and non-null on retrieved snapshots;
it is assigned by the application when receiving source data. A source payload's
own `fetched_at` may be retained as source metadata but is not the application's
fetch time. A cached snapshot retains its original application fetch time.

Future application code will attach `freshness_status = FRESH | STALE | UNKNOWN`
and cache/retrieval outcome metadata. Source flags can supply evidence but cannot
override application freshness rules. This document does not select TTLs or build
a freshness engine. Reading an old source record successfully never proves that
its business state is live.

## OrderSnapshot

| Field | Type | Meaning |
| --- | --- | --- |
| `external_order_id` | string | Stable order lookup and association key |
| `customer_reference` | string or null | Source customer ID, not contact details; missing ID grants no access |
| `status` | string | Source order status; unfamiliar values remain unknown to business rules |
| `items` | array of item objects | Each has `sku: string`, `product_name: string`, `quantity: positive integer` |
| `created_at` | timestamp | Source order creation time |
| `source_updated_at` | timestamp or null | Source order update time |
| `fetched_at` | timestamp | Application fetch time |

`items: []` represents a supplied empty list, not a failed request. The future
resolver must expose missing expected business data. Parcel references, payment
time and address summaries in the environment plan are optional source extensions,
not required by this minimum snapshot. Customer reference is not authorization.

## ParcelSnapshot

| Field | Type | Meaning |
| --- | --- | --- |
| `parcel_id` | string | Stable external parcel identifier |
| `external_order_id` | string | Parent order ID |
| `carrier` | string or null | Unknown or unassigned carrier is null |
| `tracking_number` | string or null | Null before a number is assigned |
| `source_updated_at` | timestamp or null | Source parcel metadata update time |
| `fetched_at` | timestamp | Application fetch time |

An order has zero to many parcels. A tracking number is not a parcel's identity.
Do not invent parcel records for unfulfilled orders. A parcel may exist without
shipment events or a tracking number. Logistics returns all associated parcels;
any partial retrieval must say which known parcels were not retrieved.

## ShipmentSnapshot and ShipmentEvent

One ShipmentSnapshot describes the latest available logistics information for
one parcel; it accompanies that ParcelSnapshot.

| Snapshot field | Type | Meaning |
| --- | --- | --- |
| `parcel_id` | string | Joins exactly one ParcelSnapshot |
| `status` | string or null | Source's current shipment status; null if unavailable |
| `events` | array of ShipmentEvent | All available events for this parcel; empty is valid |
| `source_updated_at` | timestamp or null | Source shipment information update time |
| `fetched_at` | timestamp | Application fetch time |

| Event field | Type | Meaning |
| --- | --- | --- |
| `parcel_id` | string | Parent parcel, inherited from containing shipment if needed |
| `status` | string | Source event status |
| `description` | string | Source event description, not model interpretation |
| `occurred_at` | timestamp | Actual business event occurrence time |
| `source_updated_at` | timestamp or null | Source event record update time if known |
| `fetched_at` | timestamp | Application fetch time, inherited from retrieval |

Known source examples include `IN_TRANSIT`, `PICKED_UP`, `DELIVERED` and
`EXCEPTION`; order examples include `PAID` and `PARTIALLY_SHIPPED`. These are not
a universal closed enum. Adapters retain raw source statuses; future deterministic
normalization handles unknown values without treating them as success or delivery.
Never infer current status from whichever event happens to be first in an array.
No guaranteed shipment or delivery date is introduced by this contract.

## WarehouseNoteSnapshot

| Field | Type | Meaning |
| --- | --- | --- |
| `external_order_id` | string | Parent order association |
| `note_id` | string | Stable source note identifier |
| `note_text` | string | Original note; preserve plans and tentative wording |
| `created_at` | timestamp | Note creation time |
| `source_updated_at` | timestamp or null | Note's last source edit time |
| `fetched_at` | timestamp | Application fetch time |

A warehouse plan is not a shipment fact. Conflicting notes and logistics records
are both retained for future validation/review. Instruction-like text in a note
cannot alter permissions or prove that an action happened.

## SupportInquiryInput

| Field | Type | Meaning |
| --- | --- | --- |
| `inquiry_id` | string | Stable external inquiry ID, distinct from future internal IDs |
| `customer_message` | string | Original non-empty customer message |
| `external_order_id` | string or null | Order reference when available; not proof of permission |
| `created_at` | timestamp | Source inquiry creation time |

An inquiry without an order reference requires later authorized order resolution.
The product must not silently guess an order or expose unrelated customer orders.

## SupportReplyCommand

| Field | Type | Meaning |
| --- | --- | --- |
| `inquiry_id` | string | External target inquiry |
| `reply_text` | string | Exact non-empty human-reviewed final text |
| `idempotency_key` | string | Stable non-empty key reused for retries of this approved reply |

The future backend checks authorization, validation and approval before dispatch.
The receiver must atomically deduplicate `(inquiry_id, idempotency_key)`. Retrying
the same text with the same pair returns the original result and creates no second
reply. Reusing the pair with different text is a conflict (HTTP 409), not a new send.
The minimal success receipt has `reply_id`, `status` and `sent_at`; Sandbox's
`status: SENT` means a simulated reply was recorded, not delivered to a real customer.
The Sandbox retains deduplication results until reset. A Sandbox reset starts a new
test run; previous-run retries must not be replayed afterward.

## Future DemoCommerce HTTP mapping

| Product concept | Planned source endpoint | Field mapping |
| --- | --- | --- |
| OrderSnapshot | `GET /oms/v1/orders/{external_order_id}` | `customer.external_customer_id` → `customer_reference`; `source` → provenance |
| ParcelSnapshot + ShipmentSnapshot[] | `GET /logistics/v1/orders/{order_id}/shipments` | Envelope `order_id` → `external_order_id`; `shipments[].parcel_id` supplies parcel identity |
| ShipmentEvent | Events nested in each shipment | `message` → `description`; `event_time` → `occurred_at`; inherit `parcel_id`; absent event update time → null |
| WarehouseNoteSnapshot[] | `GET /warehouse/v1/orders/{order_id}/notes` | Envelope `order_id` → `external_order_id`; `id` → `note_id`; `text` → `note_text`; `updated_at` → `source_updated_at` |
| SupportInquiryInput | `GET /support/v1/inquiries` and `GET /support/v1/inquiries/{id}` | `external_inquiry_id` → `inquiry_id`; `order_id` → `external_order_id` |
| SupportReplyCommand | `POST /support/v1/inquiries/{inquiry_id}/replies` | ID in path; `reply_text` → body `text`; `idempotency_key` unchanged |

Shipment source timestamps must not be assigned to an individual event as if they
were event-specific updates. Similarly, missing parcel metadata update times remain
null. Application `fetched_at` is added on each successful source retrieval.

Future Sandbox service authentication uses `X-API-Key`, with secrets in environment
configuration. An optional `X-Request-Id` correlates requests. Service credentials
never replace product user authorization. Policy/admin APIs in the environment
plan are separate Sandbox concerns, not extra product Providers in this phase.

## Result and failure semantics

- Success with `[]` means the source successfully reports no records. For an
  existing unfulfilled order, shipments can be empty (`reason: NOT_FULFILLED`).
- A missing requested order/inquiry is 404; missing/wrong Sandbox credentials are
  401/403. They must not be normalized to an empty success.
- Timeout, rate limit (429), and upstream 5xx are retrieval failures. They do not
  establish a parcel's business state. No automatic retry policy is implemented here.
- Use the environment plan's unified error object:
  `{"error":{"code":"LOGISTICS_TEMPORARILY_UNAVAILABLE","message":"...","request_id":"..."}}`.
  Its earlier scalar error example is illustrative; use the structured envelope.
- Partial success must explicitly include `partial: true`, available shipments and
  `failed_parcel_ids` plus per-parcel error codes. A whole-list discovery failure
  is an unavailable result, never a silently incomplete “complete” list. Freeze
  the concrete HTTP partial-result envelope in the Sandbox's schema phase.
- Cached fallback retains source provenance and original timestamps and is marked
  stale by the product; no cache miss may be fabricated into business data.

## Worked canonical example (documentation only)

```json
{
  "parcel": {
    "parcel_id": "PAR-DEMO-031",
    "external_order_id": "ORD-DEMO-003",
    "carrier": "DemoExpress",
    "tracking_number": "TRK000031",
    "source_updated_at": null,
    "fetched_at": "2026-09-20T06:12:10Z"
  },
  "shipment": {
    "parcel_id": "PAR-DEMO-031",
    "status": "IN_TRANSIT",
    "source_updated_at": "2026-09-20T06:10:00Z",
    "fetched_at": "2026-09-20T06:12:10Z",
    "events": [{
      "parcel_id": "PAR-DEMO-031",
      "status": "IN_TRANSIT",
      "description": "Departed sorting facility",
      "occurred_at": "2026-09-20T06:10:00Z",
      "source_updated_at": null,
      "fetched_at": "2026-09-20T06:12:10Z"
    }]
  },
  "provenance": {
    "source_system": "demo_logistics",
    "source_record_id": "PAR-DEMO-031"
  }
}
```

## Before Sandbox implementation

The minimum information and semantics above are frozen. Confirm the Sandbox's
repository/directory location and concrete HTTP schemas, especially the partial
result envelope, before building it. Use the mappings above for the existing plan's
field names. Source timestamp absence and idempotency conflicts need contract tests.
Freshness thresholds and retry budgets are product decisions for later phases;
they do not block basic Sandbox data APIs. No implementation begins here.
