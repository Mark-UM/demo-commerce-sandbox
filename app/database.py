import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.errors import SourceError
from app.schemas import (
    CustomerMessageCreate,
    FaultCommand,
    Inquiry,
    InquiryCreate,
    Receipt,
    ReplyCommand,
    SupportMessage,
)
from app.seed import BASE_TIME, SCENARIOS, SEED_VERSION, records


class Store:
    def __init__(self, path: str):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self, reset: bool = False, base_time: datetime = BASE_TIME):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS metadata (version TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS records (
                collection TEXT NOT NULL, lookup_key TEXT NOT NULL,
                payload TEXT NOT NULL)""")
            db.execute("""CREATE INDEX IF NOT EXISTS record_lookup
                ON records(collection, lookup_key)""")
            db.execute("""CREATE TABLE IF NOT EXISTS replies (
                inquiry_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                text TEXT NOT NULL, receipt TEXT NOT NULL,
                PRIMARY KEY (inquiry_id, idempotency_key))""")
            db.execute("""CREATE TABLE IF NOT EXISTS faults (
                system TEXT NOT NULL, record_id TEXT NOT NULL, mode TEXT NOT NULL,
                delay_ms INTEGER NOT NULL, remaining_failures INTEGER,
                PRIMARY KEY (system, record_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS support_messages (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                inquiry_id TEXT NOT NULL, message_id TEXT NOT NULL UNIQUE,
                sender_type TEXT NOT NULL, payload TEXT NOT NULL)""")
            db.execute("""CREATE INDEX IF NOT EXISTS message_lookup
                ON support_messages(inquiry_id, sequence)""")
            db.execute("""CREATE TABLE IF NOT EXISTS inbound_requests (
                scope TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                payload TEXT NOT NULL, result TEXT NOT NULL,
                PRIMARY KEY(scope, idempotency_key))""")
            needs_seed = (
                reset or not db.execute("SELECT version FROM metadata").fetchone()
            )
            if needs_seed:
                # Validate and serialize before deleting any existing data.
                seed_rows = [
                    (kind, key, value.model_dump_json())
                    for kind, key, value in records(base_time)
                ]
            if reset:
                for table in (
                    "records",
                    "replies",
                    "metadata",
                    "faults",
                    "support_messages",
                    "inbound_requests",
                ):
                    db.execute(f"DELETE FROM {table}")
            if needs_seed:
                db.executemany(
                    "INSERT INTO records VALUES (?, ?, ?)",
                    seed_rows,
                )
                db.execute("INSERT INTO metadata VALUES (?)", (SEED_VERSION,))
            # Seed histories, or expose already stored inquiries/replies on first use.
            for inquiry_id, payload in db.execute(
                "SELECT lookup_key, payload FROM records WHERE collection='inquiries' "
                "AND NOT EXISTS(SELECT 1 FROM support_messages "
                "WHERE inquiry_id=records.lookup_key) ORDER BY rowid"
            ).fetchall():
                inquiry = json.loads(payload)
                self._message(
                    db,
                    SupportMessage(
                        message_id=f"MSG-{inquiry_id}",
                        inquiry_id=inquiry_id,
                        sender_type="CUSTOMER",
                        text=inquiry["customer_message"],
                        created_at=inquiry["created_at"],
                    ),
                )
            for inquiry_id, text, receipt_json in db.execute(
                "SELECT inquiry_id, text, receipt FROM replies WHERE NOT EXISTS "
                "(SELECT 1 FROM support_messages "
                "WHERE message_id=json_extract(replies.receipt, '$.reply_id')) "
                "ORDER BY rowid"
            ).fetchall():
                receipt = json.loads(receipt_json)
                self._message(
                    db,
                    SupportMessage(
                        message_id=receipt["reply_id"],
                        inquiry_id=inquiry_id,
                        sender_type="SUPPORT",
                        text=text,
                        created_at=receipt["sent_at"],
                    ),
                )

    def customer_exists(self, customer_id: str):
        with self.connect() as db:
            return (
                db.execute(
                    "SELECT 1 FROM records WHERE collection='orders' "
                    "AND json_extract(payload, '$.customer_reference')=? LIMIT 1",
                    (customer_id,),
                ).fetchone()
                is not None
            )

    def customer_orders(self, customer_id: str, limit: int, offset: int):
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM records WHERE collection='orders' "
                "AND json_extract(payload, '$.customer_reference')=? "
                "ORDER BY lookup_key LIMIT ? OFFSET ?",
                (customer_id, limit, offset),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def summary(self):
        with self.connect() as db:
            db.execute("BEGIN")  # One consistent snapshot during concurrent writes.
            counts = dict(
                db.execute(
                    "SELECT collection, count(*) FROM records GROUP BY collection"
                ).fetchall()
            )
            customers = db.execute(
                "SELECT count(DISTINCT json_extract(payload, '$.customer_reference')) "
                "FROM records WHERE collection='orders'"
            ).fetchone()[0]
            products = db.execute(
                "SELECT count(DISTINCT json_extract(item.value, '$.sku')) "
                "FROM records, json_each(records.payload, '$.items') AS item "
                "WHERE records.collection='orders'"
            ).fetchone()[0]
            reference = json.loads(
                db.execute(
                    "SELECT payload FROM records WHERE collection='inquiries' "
                    "AND lookup_key='INQ-DEMO-001'"
                ).fetchone()[0]
            )["created_at"]
            return {
                "seed_version": db.execute("SELECT version FROM metadata").fetchone()[
                    0
                ],
                "base_time": reference,
                "scenarios": len(SCENARIOS),
                "customers": customers,
                "products": products,
                "orders": counts.get("orders", 0),
                "parcels": counts.get("parcels", 0),
                "shipments": counts.get("shipments", 0),
                "shipment_events": counts.get("events", 0),
                "warehouse_notes": counts.get("notes", 0),
                "inquiries": counts.get("inquiries", 0),
                "replies": db.execute("SELECT count(*) FROM replies").fetchone()[0],
                "fault_overrides": db.execute("SELECT count(*) FROM faults").fetchone()[
                    0
                ],
            }

    def get(self, collection: str, key: str):
        with self.connect() as db:
            db.execute("BEGIN")
            rows = db.execute(
                "SELECT payload FROM records WHERE collection=? AND lookup_key=? "
                "ORDER BY rowid",
                (collection, key),
            ).fetchall()
            result = [json.loads(row[0]) for row in rows]
            if collection == "inquiries":
                for row in result:
                    row.update(self._inquiry_activity(db, key))
        return result

    def list_inquiries(
        self, limit: int, offset: int, order_id: str | None, status: str | None = None
    ):
        with self.connect() as db:
            db.execute("BEGIN")
            rows = db.execute(
                "SELECT lookup_key, payload "
                "FROM records WHERE collection='inquiries' "
                "AND (? IS NULL OR json_extract(payload, '$.order_id')=?) "
                "AND (? IS NULL OR COALESCE((SELECT sender_type FROM support_messages "
                "WHERE inquiry_id=records.lookup_key ORDER BY sequence DESC LIMIT 1), "
                "'CUSTOMER') = CASE WHEN ?='REPLIED' "
                "THEN 'SUPPORT' ELSE 'CUSTOMER' END) "
                "ORDER BY lookup_key LIMIT ? OFFSET ?",
                (order_id, order_id, status, status, limit, offset),
            ).fetchall()
            return [
                {**json.loads(payload), **self._inquiry_activity(db, key)}
                for key, payload in rows
            ]

    def list_replies(self, inquiry_id: str, limit: int, offset: int):
        with self.connect() as db:
            rows = db.execute(
                "SELECT text, idempotency_key, receipt FROM replies WHERE inquiry_id=? "
                "ORDER BY rowid LIMIT ? OFFSET ?",
                (inquiry_id, limit, offset),
            ).fetchall()
        return [
            {
                **json.loads(receipt),
                "inquiry_id": inquiry_id,
                "text": text,
                "idempotency_key": key,
            }
            for text, key, receipt in rows
        ]

    def reply(self, inquiry_id: str, command: ReplyCommand):
        # Serialize the lookup and insert across threads/processes, not just requests.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT text, receipt FROM replies "
                "WHERE inquiry_id=? AND idempotency_key=?",
                (inquiry_id, command.idempotency_key),
            ).fetchone()
            if row:
                stored = json.loads(row[1])
                binding = db.execute(
                    "SELECT payload FROM support_messages WHERE message_id=?",
                    (stored["reply_id"],),
                ).fetchone()
                requested = (
                    json.loads(binding[0]).get("in_reply_to_message_id")
                    if binding
                    else None
                )
                if (
                    row[0] != command.text
                    or requested != command.in_reply_to_message_id
                ):
                    raise ValueError(
                        "Idempotency key already used with different payload"
                    )
                return stored
            activity = self._inquiry_activity(db, inquiry_id)
            if (
                command.in_reply_to_message_id is not None
                and command.in_reply_to_message_id
                != activity["latest_customer_message_id"]
            ):
                raise SourceError(
                    409,
                    "CUSTOMER_MESSAGE_CHANGED",
                    "Reply target is not the latest customer message",
                )
            receipt = Receipt(
                reply_id=f"REP-{uuid4()}", status="SENT", sent_at=datetime.now(UTC)
            )
            db.execute(
                "INSERT INTO replies VALUES (?, ?, ?, ?)",
                (
                    inquiry_id,
                    command.idempotency_key,
                    command.text,
                    receipt.model_dump_json(),
                ),
            )
            self._message(
                db,
                SupportMessage(
                    message_id=receipt.reply_id,
                    inquiry_id=inquiry_id,
                    sender_type="SUPPORT",
                    text=command.text,
                    created_at=receipt.sent_at,
                    in_reply_to_message_id=command.in_reply_to_message_id,
                ),
            )
            db.execute(
                "UPDATE records SET payload=json_set(payload, '$.updated_at', ?) "
                "WHERE collection='inquiries' AND lookup_key=?",
                (receipt.sent_at.isoformat().replace("+00:00", "Z"), inquiry_id),
            )
            return receipt

    @staticmethod
    def _message(db, message: SupportMessage):
        db.execute(
            "INSERT INTO support_messages(inquiry_id, message_id, sender_type, payload)"
            "VALUES (?, ?, ?, ?)",
            (
                message.inquiry_id,
                message.message_id,
                message.sender_type,
                message.model_dump_json(),
            ),
        )

    @staticmethod
    def _inquiry_activity(db, inquiry_id):
        last = db.execute(
            "SELECT sender_type FROM support_messages WHERE inquiry_id=? "
            "ORDER BY sequence DESC LIMIT 1",
            (inquiry_id,),
        ).fetchone()
        customer = db.execute(
            "SELECT message_id FROM support_messages WHERE inquiry_id=? "
            "AND sender_type='CUSTOMER' ORDER BY sequence DESC LIMIT 1",
            (inquiry_id,),
        ).fetchone()
        return {
            "status": "REPLIED" if last and last[0] == "SUPPORT" else "OPEN",
            "latest_customer_message_id": customer[0] if customer else None,
        }

    def messages(self, inquiry_id: str, limit: int, offset: int):
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM support_messages WHERE inquiry_id=? "
                "ORDER BY sequence LIMIT ? OFFSET ?",
                (inquiry_id, limit, offset),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def receive_customer(
        self,
        command: InquiryCreate | CustomerMessageCreate,
        inquiry_id: str | None = None,
    ):
        scope = f"inquiry:{inquiry_id}" if inquiry_id else "new-inquiry"
        fingerprint = command.model_dump_json(
            exclude={"idempotency_key"}, exclude_unset=inquiry_id is not None
        )
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT payload, result FROM inbound_requests "
                "WHERE scope=? AND idempotency_key=?",
                (scope, command.idempotency_key),
            ).fetchone()
            if prior:
                if prior[0] != fingerprint:
                    raise SourceError(
                        409,
                        "IDEMPOTENCY_CONFLICT",
                        "Inbound key already used for another payload",
                    )
                return json.loads(prior[1])
            now = datetime.now(UTC)
            message_id = f"MSG-{uuid4()}"
            if inquiry_id is None:
                inquiry_id = f"INQ-{uuid4()}"
                inquiry = Inquiry(
                    inquiry_id=inquiry_id,
                    order_id=command.order_id,
                    customer_message=command.customer_message,
                    created_at=now,
                    updated_at=now,
                    latest_customer_message_id=message_id,
                )
                db.execute(
                    "INSERT INTO records VALUES ('inquiries', ?, ?)",
                    (inquiry_id, inquiry.model_dump_json()),
                )
                text = command.customer_message
                result = inquiry.model_dump(mode="json")
            else:
                row = db.execute(
                    "SELECT rowid, payload FROM records WHERE collection='inquiries' "
                    "AND lookup_key=?",
                    (inquiry_id,),
                ).fetchone()
                if row is None:
                    raise SourceError(404, "INQUIRY_NOT_FOUND", "Inquiry was not found")
                payload = json.loads(row[1])
                payload.update(
                    customer_message=command.text,
                    updated_at=now.isoformat().replace("+00:00", "Z"),
                )
                if "order_id" in command.model_fields_set:
                    payload["order_id"] = command.order_id
                db.execute(
                    "UPDATE records SET payload=? WHERE rowid=?",
                    (json.dumps(payload), row[0]),
                )
                text = command.text
                result = None
            message = SupportMessage(
                message_id=message_id,
                inquiry_id=inquiry_id,
                sender_type="CUSTOMER",
                text=text,
                created_at=now,
            )
            self._message(db, message)
            result = result or message.model_dump(mode="json")
            db.execute(
                "INSERT INTO inbound_requests VALUES (?, ?, ?, ?)",
                (scope, command.idempotency_key, fingerprint, json.dumps(result)),
            )
            return result

    @staticmethod
    def _record(db, collection: str, key: str, code: str):
        row = db.execute(
            "SELECT rowid, payload FROM records WHERE collection=? AND lookup_key=?",
            (collection, key),
        ).fetchone()
        if row is None:
            raise SourceError(404, code, f"Record {key} was not found")
        return row[0], json.loads(row[1])

    @staticmethod
    def _identified(db, collection: str, field: str, key: str):
        row = db.execute(
            "SELECT rowid, payload FROM records WHERE collection=? "
            "AND json_extract(payload, ?)=?",
            (collection, f"$.{field}", key),
        ).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    @staticmethod
    def _unique_tracking(db, tracking: str | None, parcel_id: str):
        if tracking is None:
            return
        row = db.execute(
            "SELECT payload FROM records WHERE collection='parcels' "
            "AND json_extract(payload, '$.tracking_number')=? "
            "AND json_extract(payload, '$.parcel_id')<>?",
            (tracking, parcel_id),
        ).fetchone()
        if row:
            raise SourceError(
                409,
                "TRACKING_ALREADY_ASSIGNED",
                "Tracking number belongs to another parcel",
            )

    def source_write(self, operation: str, command, target: str | None = None):
        payload = command.model_dump(mode="json")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row_id = None
            if operation == "create_order":
                collection, key = "orders", command.order_id
                if db.execute(
                    "SELECT 1 FROM records WHERE collection=? AND lookup_key=?",
                    (collection, key),
                ).fetchone():
                    raise SourceError(
                        409, "ORDER_ALREADY_EXISTS", "Order ID already exists"
                    )
            elif operation == "update_order":
                row_id, existing = self._record(db, "orders", target, "ORDER_NOT_FOUND")
                payload = {**existing, **payload}
            elif operation in ("create_parcel", "assign_parcel"):
                if operation == "create_parcel":
                    self._record(db, "orders", target, "ORDER_NOT_FOUND")
                    if command.order_id != target:
                        raise SourceError(
                            409, "ORDER_MISMATCH", "Parcel order does not match path"
                        )
                    if self._identified(db, "parcels", "parcel_id", command.parcel_id):
                        raise SourceError(
                            409, "PARCEL_ALREADY_EXISTS", "Parcel ID already exists"
                        )
                    collection, key, parcel_id = "parcels", target, command.parcel_id
                else:
                    found = self._identified(db, "parcels", "parcel_id", target)
                    if found is None:
                        raise SourceError(
                            404, "PARCEL_NOT_FOUND", "Parcel was not found"
                        )
                    row_id, existing = found
                    if command.tracking_number != existing[
                        "tracking_number"
                    ] and self._identified(db, "shipments", "parcel_id", target):
                        raise SourceError(
                            409,
                            "TRACKING_IMMUTABLE",
                            "Registered shipment tracking cannot be reassigned",
                        )
                    payload = {**existing, **payload}
                    parcel_id = target
                self._unique_tracking(db, command.tracking_number, parcel_id)
            elif operation == "create_shipment":
                parcel = self._identified(db, "parcels", "parcel_id", command.parcel_id)
                if parcel is None:
                    raise SourceError(404, "PARCEL_NOT_FOUND", "Parcel was not found")
                if parcel[1]["tracking_number"] != command.tracking_number:
                    raise SourceError(
                        409, "TRACKING_MISMATCH", "Tracking does not match OMS parcel"
                    )
                collection, key = "shipments", command.tracking_number
                if self._identified(db, collection, "tracking_number", key):
                    raise SourceError(
                        409, "SHIPMENT_ALREADY_EXISTS", "Shipment already exists"
                    )
            elif operation == "update_shipment":
                row_id, existing = self._record(
                    db, "shipments", target, "SHIPMENT_NOT_FOUND"
                )
                payload = {**existing, **payload}
            elif operation == "append_event":
                _, shipment = self._record(
                    db, "shipments", target, "SHIPMENT_NOT_FOUND"
                )
                if command.parcel_id != shipment["parcel_id"]:
                    raise SourceError(
                        409, "PARCEL_MISMATCH", "Event belongs to another parcel"
                    )
                collection, key = "events", target
                if self._identified(db, collection, "event_id", command.event_id):
                    raise SourceError(
                        409, "EVENT_ALREADY_EXISTS", "Event ID already exists"
                    )
            elif operation == "append_note":
                self._record(db, "orders", target, "ORDER_NOT_FOUND")
                if command.order_id != target:
                    raise SourceError(
                        409, "ORDER_MISMATCH", "Note order does not match path"
                    )
                collection, key = "notes", target
                if self._identified(db, collection, "note_id", command.note_id):
                    raise SourceError(
                        409, "NOTE_ALREADY_EXISTS", "Note ID already exists"
                    )
            else:
                raise ValueError("Unsupported source write")
            if row_id is not None:
                db.execute(
                    "UPDATE records SET payload=? WHERE rowid=?",
                    (json.dumps(payload), row_id),
                )
            else:
                db.execute(
                    "INSERT INTO records VALUES (?, ?, ?)",
                    (collection, key, json.dumps(payload)),
                )
            return payload

    def set_fault(self, system: str, record_id: str, command: FaultCommand):
        remaining = 1 if command.mode == "TIMEOUT_ONCE" else None
        with self.connect() as db:
            db.execute(
                "INSERT INTO faults VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(system, record_id) DO UPDATE SET "
                "mode=excluded.mode, delay_ms=excluded.delay_ms, "
                "remaining_failures=excluded.remaining_failures",
                (system, record_id, command.mode, command.delay_ms, remaining),
            )
        return {
            "system": system,
            "record_id": record_id,
            **command.model_dump(),
            "remaining_failures": remaining,
        }

    def list_faults(self):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in db.execute("SELECT * FROM faults ORDER BY system, record_id")
            ]

    def delete_fault(self, system: str, record_id: str):
        with self.connect() as db:
            db.execute(
                "DELETE FROM faults WHERE system=? AND record_id=?", (system, record_id)
            )

    def take_fault(self, system: str, record_id: str):
        # Consume a one-shot failure atomically even across concurrent workers.
        # Commit before any HTTP error/delay, so locks never span response delays.
        with self.connect() as db:
            row = db.execute(
                "SELECT mode, delay_ms, remaining_failures FROM faults "
                "WHERE system=? AND record_id=?",
                (system, record_id),
            ).fetchone()
            if row is None:
                return None
            if row[0] == "TIMEOUT_ONCE":
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT mode, delay_ms, remaining_failures FROM faults "
                    "WHERE system=? AND record_id=?",
                    (system, record_id),
                ).fetchone()
                if row is None:
                    return None
            mode, delay, remaining = row
            if mode == "TIMEOUT_ONCE":
                if remaining == 0:
                    return "NORMAL", 0
                db.execute(
                    "UPDATE faults SET remaining_failures=0 "
                    "WHERE system=? AND record_id=?",
                    (system, record_id),
                )
            return mode, delay
