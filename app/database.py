import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.schemas import FaultCommand, Receipt, ReplyCommand
from app.seed import BASE_TIME, records


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
                for table in ("records", "replies", "metadata", "faults"):
                    db.execute(f"DELETE FROM {table}")
            if needs_seed:
                db.executemany(
                    "INSERT INTO records VALUES (?, ?, ?)",
                    seed_rows,
                )
                db.execute("INSERT INTO metadata VALUES ('s0-s1-v1')")

    def get(self, collection: str, key: str):
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM records WHERE collection=? AND lookup_key=? "
                "ORDER BY rowid",
                (collection, key),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_inquiries(self, limit: int, offset: int, order_id: str | None):
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM records WHERE collection='inquiries' "
                "AND (? IS NULL OR json_extract(payload, '$.order_id')=?) "
                "ORDER BY lookup_key LIMIT ? OFFSET ?",
                (order_id, order_id, limit, offset),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

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
                if row[0] != command.text:
                    raise ValueError("Idempotency key already used with different text")
                return json.loads(row[1])
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
            return receipt

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
