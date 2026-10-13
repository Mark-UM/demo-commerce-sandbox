# Complete Sandbox implementation status

The broader environment scope is implemented while preserving the revised
S01-S12 golden IDs and `/api` contracts. The original plan under
`docs/reference/` is historical input; `docs/api-contract.md` is the current
HTTP authority.

| Capability | Implementation |
|---|---|
| Independent service | One FastAPI application, SQLite, health and Swagger |
| Deterministic seed | 120 orders, 60 customer references, 20 SKUs, 142 parcels, 141 shipments, 543 events, 120 notes, 60 inquiries |
| Golden scenarios | S01-S12 unchanged; S12 deliberately has no order |
| OMS | Order/items, parcel discovery, customer order pagination |
| Logistics | Shipment and events; independent per-parcel failures |
| Warehouse | Original free text, restock/plans/conflicts, instruction-like test text |
| Support | Inquiry discovery, exact accepted replies, atomic persistent idempotency |
| Policy | Two static source facts; no retrieval/interpretation engine |
| Fault controls | NORMAL, TIMEOUT_ONCE, ALWAYS_TIMEOUT, HTTP_500, HTTP_429, SLOW_RESPONSE, STALE_DATA, EMPTY_RESULT, PARTIAL_FAILURE, CONFLICTING_DATA, MALFORMED_RESPONSE |
| Reset | Atomic HTTP/CLI reset with optional explicit UTC reference |
| Authentication | Configured X-API-Key, 401/403; public health/docs |
| Operations | Record inventory summary, request/correlation/fault logging |
| Persistence | SQLite WAL; restarts retain replies, overrides and consumed budgets |
| Deployment | Non-root Python 3.12 image, locked dependencies, healthcheck, Compose volume |
| Automation | GitHub Actions for unit/lint/HTTP/container/restart checks |

## Verification on 2026-10-13

- Python 3.13: 104 tests passed. Two third-party deprecation warnings remain.
- Ruff lint and format checks passed; diff whitespace check passed.
- Real Uvicorn HTTP smoke passed, including normal/golden failures, authentication,
  Policy, complete inventory, source reads, reply deduplication, actual client
  timeout, reset and a second test run.
- The process was stopped and started with the same temporary SQLite file;
  the running-service verifier confirmed the original receipt and consumed
  one-shot fault budget survived restart.
- Docker Compose configuration validation passed.
- Docker Engine started, but image pulls from GHCR and Docker Hub encountered
  TLS handshake timeouts. Image build and container execution could not be
  confirmed on this host. CI is configured, not yet executed remotely.

## Deliberate boundaries

Product HTTP adapters, canonical snapshots, freshness rules, authorization,
AI, validation, human approval and Product end-to-end acceptance belong to the
separate Product repository. Sandbox HTTP checks prove source behavior only.
There is no aggregate order context or cross-system partial envelope. Individual
parcel failures are separate HTTP failures for the Product to interpret.

Ordinary records use deterministic index arithmetic rather than randomness.
Time uses an explicit reference instead of reset's current clock. Customer and
SKU records are source references embedded in orders, without a separate CRM or
catalog service. Authentication is one service key, not a user-permission system.
Random normal latency, a UI, real provider integrations and unrelated commerce
operations are outside this environment's purpose.

Existing databases are never silently reseeded; explicit reset upgrades to
`sandbox-v2` and intentionally clears the previous run. Finish previous-run
requests before reset. Basic application APIs and golden identities remain
stable; `/api` now requires a key by default, as documented in README.
