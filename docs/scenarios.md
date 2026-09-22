# Golden scenarios

Every ID and source record is deterministic. Reference time T0 is
`2026-09-20T06:00:00Z`. Orders are created T0 minus 5 days and updated T0 minus
30 minutes. Notes are created T0 minus 20 minutes. Shipment updates are T0 minus
10 minutes except S07 (minus 72 hours). Event occurrence times are at or before
the corresponding shipment update; event update timestamps are unknown/null.
Parcel update timestamps are null. S05's note update is also null.

For row N, order ID is `ORD-DEMO-NNN`, inquiry ID `INQ-DEMO-NNN`, and note ID
`NOTE-DEMO-NNN` (no note exists for S12). Parcel/tracking IDs are listed below.
Events use `EVT-DEMO-NNN-P-E`, where P is parcel suffix and E is event sequence.
All 12 inquiries exist and ask about their corresponding order. Orders contain
one travel mug; S04 also contains a canvas bag. All data is fictional.

| Scenario | Order ID | Parcel IDs / tracking IDs | Source data and abnormal behavior | Expected API behavior |
|---|---|---|---|---|
| S01 | ORD-DEMO-001 | None | PAID; awaiting packing | Order/notes/inquiry 200; parcels 200 with [] |
| S02 | ORD-DEMO-002 | PAR-DEMO-002-1 / TRK-DEMO-002-1 | SHIPPED; PICKED_UP then IN_TRANSIT | All related reads 200 |
| S03 | ORD-DEMO-003 | PAR-DEMO-003-1 / TRK-DEMO-003-1 | DELIVERED; pickup then delivery event | All related reads 200 |
| S04 | ORD-DEMO-004 | PAR-DEMO-004-1 / TRK-DEMO-004-1; PAR-DEMO-004-2 / TRK-DEMO-004-2 | PARTIALLY_SHIPPED; first parcel IN_TRANSIT, second NOT_COLLECTED with LABEL_CREATED | Parcel list contains exactly two distinct parcels; all reads 200 |
| S05 | ORD-DEMO-005 | None | WAITING_STOCK; note says waiting for restock; unknown note update | Order/notes/inquiry 200; parcels [] |
| S06 | ORD-DEMO-006 | PAR-DEMO-006-1 / TRK-DEMO-006-1 | PACKED; note says expected to ship today subject to carrier collection; shipment NOT_COLLECTED, only LABEL_CREATED | All related reads 200; original tentative note preserved |
| S07 | ORD-DEMO-007 | PAR-DEMO-007-1 / TRK-DEMO-007-1 | IN_TRANSIT with update 2026-09-17T06:00:00Z | 200 with intentionally old source timestamps |
| S08 | ORD-DEMO-008 | PAR-DEMO-008-1 / TRK-DEMO-008-1 | Underlying IN_TRANSIT fixture; logistics upstream failure | Shipment and events 504; OMS, notes, inquiry 200 |
| S09 | ORD-DEMO-009 | PAR-DEMO-009-1 / TRK-DEMO-009-1 | IN_TRANSIT; warehouse unavailable | Warehouse 503; OMS, logistics, inquiry 200 |
| S10 | ORD-DEMO-010 | PAR-DEMO-010-1 / TRK-DEMO-010-1 | PROCESSING; OMS has parcel/reference but logistics has no matching record | OMS/notes/inquiry 200; shipment and events 404 |
| S11 | ORD-DEMO-011 | PAR-DEMO-011-1 / TRK-DEMO-011-1 | Warehouse says not handed to carrier today; logistics says PICKED_UP | All reads 200; conflicting records both preserved |
| S12 | ORD-DEMO-012 (absent) | None | Inquiry references nonexistent order | Order, parcels, warehouse notes 404; inquiry 200 |

Unlisted/missing tracking and inquiry IDs return 404. Reply submission remains
available for each existing inquiry, including S12. Read data and simulated
failures remain unchanged after restart/reset; reset removes accepted replies.
These scenarios specify source behavior only, never what the AI should answer.
