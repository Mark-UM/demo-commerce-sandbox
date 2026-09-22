# S0-S1 source HTTP contract

The Pydantic models in `app/schemas.py` and generated `/openapi.json` define the
concrete schema. These are raw source payloads, not canonical Product snapshots.
All object fields listed by the schema are required, including nullable fields.
Collections return bare arrays. Unknown records return 404; a known unfulfilled
order's parcel array can be empty. Shipment status is explicit and never inferred
from event ordering. Status strings remain open rather than a universal enum.

| Source response | Fields |
|---|---|
| Order | order_id, customer_reference (nullable), status, items, created_at, updated_at (nullable) |
| Item | sku, product_name, quantity (positive integer) |
| Parcel | parcel_id, order_id, carrier (nullable), tracking_number (nullable), updated_at (nullable) |
| Shipment | tracking_number, parcel_id, status (nullable), updated_at (nullable) |
| Event | event_id, parcel_id, status, description, occurred_at, updated_at (nullable) |
| Note | note_id, order_id, text, created_at, updated_at (nullable) |
| Inquiry | inquiry_id, order_id (nullable), customer_message, created_at |
| Reply receipt | reply_id, status (SENT), sent_at |

Source identity comes from the subsystem URL: demo_oms, demo_logistics,
demo_warehouse, or demo_support. IDs identify records within those sources.
Product adapters map `order_id` to `external_order_id`, `updated_at` to
`source_updated_at`, and warehouse `text` to `note_text`. They assign their own
`fetched_at`. The Sandbox never supplies freshness or canonical snapshots.
Source timestamps use UTC ISO 8601 with Z; unknown timestamps are null.
Seed data never changes with wall-clock time. See README for the reference clock.

POST reply takes `text` and `idempotency_key` in JSON, with inquiry ID in the path.
Blank values and unknown fields produce 422. Text is preserved exactly, including
surrounding whitespace. Limits are 10,000 text characters and 200 key characters.
Deduplication scope is `(inquiry_id, idempotency_key)` and survives restarts.
Same pair/text returns the original HTTP 200 receipt. Different text produces
409. A different key or inquiry creates a new simulated reply. SQLite serializes
the check and insertion atomically. Reset deletes this history.

Errors use `{"error":{"code":"...","message":"...","request_id":"..."}}`.
An optional `X-Request-Id` is echoed in the response header and error object;
otherwise the service generates one. Missing records are 404, validation is 422,
S08 logistics is 504, and S09 warehouse is 503. Failure injection is centralized
in `app/scenarios.py`; future delay, transient failures, rate limits, or malformed
responses can extend that boundary. They are not implemented now. S08 is an
immediate simulated upstream 504, not an intentional client-side socket timeout.

## Resolved differences from reference documents

- This phase uses the requested `/api/...` paths, not the older `/.../v1` paths.
- OMS lists parcels, then the Product retrieves each shipment and event list.
  There is no aggregate order context, HTTP 207, or cross-system partial envelope.
- The current 12 scenario definitions replace the plan's older scenario mapping.
- S12 has an inquiry but deliberately no order; only 11 order records exist.
- Fixed timestamps replace reset-time timestamps for exact reproducibility.
- No fetched_at is fabricated; null updates remain unknown.
- No API key, policy API, admin API, random records, or additional fault modes
  are introduced in S0-S1. Reset is a local CLI operation with the service stopped.
