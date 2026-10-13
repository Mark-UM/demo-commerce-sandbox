# Complete Sandbox implementation status

The broader environment scope is implemented while preserving the revised
S01-S12 golden IDs and `/api` contracts. The original plan under
`docs/reference/` is historical input; `docs/api-contract.md` is the current
HTTP authority.

| Capability | Implementation |
|---|---|
| Independent service | One FastAPI application, SQLite, health and Swagger |
| Deterministic seed | 120 orders, 60 customer references, 20 SKUs, 143 parcels, 141 shipments, 539 events, 120 notes, 60 inquiries |
| Golden scenarios | S01-S12 unchanged; S12 deliberately has no order |
| OMS | Order/items, parcel discovery, customer order pagination |
| Logistics | Shipment and events; independent per-parcel failures |
| Warehouse | Original free text, restock/plans/conflicts, instruction-like test text |
| Support | New inquiries/follow-ups, message history, pending discovery, bound replies and persistent idempotency |
| Continuous progression | Admin creation/update of OMS, parcels, shipments, events and warehouse notes |
| Policy | Two static source facts; no retrieval/interpretation engine |
| Fault controls | NORMAL, TIMEOUT_ONCE, ALWAYS_TIMEOUT, HTTP_500, HTTP_429, SLOW_RESPONSE, STALE_DATA, EMPTY_RESULT, PARTIAL_FAILURE, CONFLICTING_DATA, MALFORMED_RESPONSE |
| Reset | Atomic HTTP/CLI reset with optional explicit UTC reference |
| Authentication | Configured X-API-Key, 401/403; public health/docs |
| Operations | Record inventory summary, request/correlation/fault logging |
| Persistence | SQLite WAL; restarts retain replies, overrides and consumed budgets |
| Deployment | Non-root Python 3.12 image, locked dependencies, healthcheck, Compose volume |
| Automation | GitHub Actions for unit/lint/HTTP/container/restart checks |
| Sandbox console | Responsive source inspection, customer order lookup, conversations, faults, source writes and confirmed reset through existing HTTP APIs |

## Verification on 2026-10-13

- Python 3.13: 125 tests passed. Two third-party deprecation warnings remain.
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

Functional readiness inspection reproduced and fixed four gaps: delivered
orders predating delivery, S11's note predating pickup (normal progression
rather than conflict), one-item ordinary orders split into two parcels, and
ignored pending-inquiry status filtering. Source OPEN/REPLIED now reflects
accepted reply existence and is queryable without Product processing logic.
Fixtures also expose missing order references, unassigned tracking, and a
known shipment with no event history. The running HTTP verifier checks all
120 orders and every parcel through separate source endpoints.
Real HTTP acceptance passed both before and after restart, covering 34 split
orders and 30 delivered parcels. This supports immediate use for the defined
source-read/reply integration tests. For wall-clock freshness tests, explicitly
reset T0 to the test's current UTC time; the default historical fixture should
not be treated as current data. Continuous ingress and per-source progression
are now implemented and verified: customer follow-ups reopen the queue, old
reply retries do not close new questions, bound stale replies conflict, and
the live HTTP scenario explicitly drives pickup, transit and delivery.
Unknown source updates remain null. No automatic cross-system progression is
introduced; a test driver controls each subsystem independently.

Product HTTP adapters, canonical snapshots, freshness rules, authorization,
AI, validation, human approval and Product end-to-end acceptance belong to the
separate Product repository. Sandbox HTTP checks prove source behavior only.
There is no aggregate order context or cross-system partial envelope. Individual
parcel failures are separate HTTP failures for the Product to interpret.

Ordinary records use deterministic index arithmetic rather than randomness.
Time uses an explicit reference instead of reset's current clock. Customer and
SKU records are source references embedded in orders, without a separate CRM or
catalog service. Authentication is one service key, not a user-permission system.
Random normal latency, real provider integrations and unrelated commerce
operations are outside this environment's purpose.
The user subsequently authorized a lightweight Sandbox control console. It
serves static assets from `/`, keeps the API credential in page memory, and
operates the existing independent HTTP sources. It includes no Product logic.
Browser acceptance covers split parcels, independent 504 responses, NORMAL
recovery, malformed JSON, message reply/follow-up, stale-message 409 with draft
preservation, new unbound inquiries and all eight source write operations.
Confirmed reset restores the baseline inventory; an invalid console API Key
returns a visible 403. Customer lookup and mobile layouts were checked in the
browser; source, conversation and simulation views have no horizontal overflow
at the 390-pixel viewport. No browser script errors were recorded.
The complete follow-up browser audit recorded 169 successful assertions covering
every visible console feature, all 22 system/fault-mode combinations, form error
branches, current/fixed-clock reset and long IDs. It found and fixed stale parcel
retry panels, scenario highlighting, history-loading status and current-thread
refresh. Four dependency-free JavaScript regression tests also pass. See
`docs/console-acceptance.md` for the coverage and reproduction commands.

Existing databases are never silently reseeded; explicit reset upgrades to
`sandbox-v2` and intentionally clears the previous run. Finish previous-run
requests before reset. Basic application APIs and golden identities remain
stable; `/api` now requires a key by default, as documented in README.
