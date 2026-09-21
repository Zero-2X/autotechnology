"""Tenant-scoped checkpoint ports and SQLite/PostgreSQL implementations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sqlite3
from threading import RLock
from typing import Any, Mapping, Protocol

from .state import StateViolation, validate_state


@dataclass(frozen=True)
class Checkpoint:
    run_id: str
    org_id: str
    sequence: int
    state: dict[str, Any]
    node: str | None
    created_at: str

    def as_contract(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "org_id": self.org_id, "sequence": self.sequence,
                "state": dict(self.state), "node": self.node, "created_at": self.created_at}


class Checkpointer(Protocol):
    def save(self, checkpoint: Checkpoint) -> Checkpoint: ...
    def latest(self, *, org_id: str, run_id: str) -> Checkpoint | None: ...
    def list(self, *, org_id: str, run_id: str) -> tuple[Checkpoint, ...]: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class InMemoryCheckpointer:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], list[Checkpoint]] = {}
        self._lock = RLock()

    def save(self, checkpoint: Checkpoint) -> Checkpoint:
        state = validate_state(checkpoint.state)
        with self._lock:
            key = (str(checkpoint.org_id), str(checkpoint.run_id))
            rows = self._rows.setdefault(key, [])
            expected = len(rows) + 1
            if checkpoint.sequence != expected:
                raise StateViolation("checkpoint sequence must be append-only")
            saved = Checkpoint(str(checkpoint.run_id), str(checkpoint.org_id), checkpoint.sequence,
                               state, checkpoint.node, checkpoint.created_at or _now())
            rows.append(saved)
            return saved

    def latest(self, *, org_id: str, run_id: str) -> Checkpoint | None:
        rows = self._rows.get((str(org_id), str(run_id)), [])
        return rows[-1] if rows else None

    def list(self, *, org_id: str, run_id: str) -> tuple[Checkpoint, ...]:
        return tuple(self._rows.get((str(org_id), str(run_id)), ()))


class SQLiteCheckpointer:
    """SQLite dev checkpointer; business facts remain outside this table."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS graph_checkpoints (
                org_id TEXT NOT NULL, run_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                state_json TEXT NOT NULL, node TEXT, created_at TEXT NOT NULL,
                PRIMARY KEY (org_id, run_id, sequence)
            )
        """)
        self.connection.commit()

    def save(self, checkpoint: Checkpoint) -> Checkpoint:
        state = validate_state(checkpoint.state)
        latest = self.latest(org_id=checkpoint.org_id, run_id=checkpoint.run_id)
        expected = 1 if latest is None else latest.sequence + 1
        if checkpoint.sequence != expected:
            raise StateViolation("checkpoint sequence must be append-only")
        saved = Checkpoint(str(checkpoint.run_id), str(checkpoint.org_id), checkpoint.sequence, state,
                           checkpoint.node, checkpoint.created_at or _now())
        self.connection.execute(
            "INSERT INTO graph_checkpoints(org_id,run_id,sequence,state_json,node,created_at) VALUES(?,?,?,?,?,?)",
            (saved.org_id, saved.run_id, saved.sequence, json.dumps(state, ensure_ascii=False, sort_keys=True), saved.node, saved.created_at),
        )
        self.connection.commit()
        return saved

    def latest(self, *, org_id: str, run_id: str) -> Checkpoint | None:
        row = self.connection.execute(
            "SELECT sequence,state_json,node,created_at FROM graph_checkpoints WHERE org_id=? AND run_id=? ORDER BY sequence DESC LIMIT 1",
            (str(org_id), str(run_id)),
        ).fetchone()
        if row is None:
            return None
        return Checkpoint(str(run_id), str(org_id), int(row[0]), validate_state(json.loads(row[1])), row[2], row[3])

    def list(self, *, org_id: str, run_id: str) -> tuple[Checkpoint, ...]:
        rows = self.connection.execute(
            "SELECT sequence,state_json,node,created_at FROM graph_checkpoints WHERE org_id=? AND run_id=? ORDER BY sequence",
            (str(org_id), str(run_id)),
        ).fetchall()
        return tuple(Checkpoint(str(run_id), str(org_id), int(row[0]), validate_state(json.loads(row[1])), row[2], row[3]) for row in rows)


class PostgresCheckpointer:
    """PostgreSQL production checkpointer using a DB-API connection.

    The implementation deliberately accepts a connection instead of importing a
    PostgreSQL driver.  Applications choose psycopg/psycopg2 through their
    composition root, while orchestration depends only on this port.  Each write
    is tenant-scoped, append-only, and committed as one transaction.
    """

    def __init__(self, connection: Any, *, initialize: bool = True) -> None:
        if connection is None or not callable(getattr(connection, "cursor", None)):
            raise TypeError("a DB-API PostgreSQL connection is required")
        self.connection = connection
        if initialize:
            self._initialize()

    def _initialize(self) -> None:
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS graph_checkpoints (
                    org_id UUID NOT NULL,
                    run_id UUID NOT NULL,
                    sequence INTEGER NOT NULL,
                    state_json JSONB NOT NULL,
                    node TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (org_id, run_id, sequence)
                )
                """
            )
            self.connection.commit()
        finally:
            close = getattr(cursor, "close", None)
            if callable(close):
                close()

    @staticmethod
    def _row(row: Any) -> tuple[Any, Any, Any, Any]:
        """Read tuple and mapping rows returned by common DB-API drivers."""
        if isinstance(row, Mapping):
            return row["sequence"], row["state_json"], row.get("node"), row["created_at"]
        return row[0], row[1], row[2], row[3]

    @staticmethod
    def _decode_state(value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            value = json.loads(value)
        return validate_state(value)

    def save(self, checkpoint: Checkpoint) -> Checkpoint:
        state = validate_state(checkpoint.state)
        cursor = self.connection.cursor()
        saved = Checkpoint(
            str(checkpoint.run_id), str(checkpoint.org_id), int(checkpoint.sequence), state,
            checkpoint.node, checkpoint.created_at or _now(),
        )
        try:
            # Lock the run's existing rows so two workers cannot select the same
            # next sequence.  A run with no rows is still protected by the
            # primary key; callers should retry a serialization conflict.
            cursor.execute(
                "SELECT sequence FROM graph_checkpoints WHERE org_id = %s AND run_id = %s "
                "ORDER BY sequence DESC LIMIT 1 FOR UPDATE",
                (saved.org_id, saved.run_id),
            )
            row = cursor.fetchone()
            latest = None if row is None else int(row[0] if not isinstance(row, Mapping) else row["sequence"])
            expected = 1 if latest is None else latest + 1
            if saved.sequence != expected:
                self.connection.rollback()
                raise StateViolation("checkpoint sequence must be append-only")
            cursor.execute(
                "INSERT INTO graph_checkpoints "
                "(org_id, run_id, sequence, state_json, node, created_at) "
                "VALUES (%s, %s, %s, %s::jsonb, %s, %s)",
                (saved.org_id, saved.run_id, saved.sequence,
                 json.dumps(state, ensure_ascii=False, sort_keys=True), saved.node, saved.created_at),
            )
            self.connection.commit()
            return saved
        except StateViolation:
            raise
        except Exception:
            self.connection.rollback()
            raise
        finally:
            close = getattr(cursor, "close", None)
            if callable(close):
                close()

    def latest(self, *, org_id: str, run_id: str) -> Checkpoint | None:
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "SELECT sequence, state_json, node, created_at FROM graph_checkpoints "
                "WHERE org_id = %s AND run_id = %s ORDER BY sequence DESC LIMIT 1",
                (str(org_id), str(run_id)),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            sequence, state_json, node, created_at = self._row(row)
            return Checkpoint(str(run_id), str(org_id), int(sequence), self._decode_state(state_json), node, str(created_at))
        finally:
            close = getattr(cursor, "close", None)
            if callable(close):
                close()

    def list(self, *, org_id: str, run_id: str) -> tuple[Checkpoint, ...]:
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "SELECT sequence, state_json, node, created_at FROM graph_checkpoints "
                "WHERE org_id = %s AND run_id = %s ORDER BY sequence",
                (str(org_id), str(run_id)),
            )
            rows = []
            for row in cursor.fetchall():
                sequence, state_json, node, created_at = self._row(row)
                rows.append(Checkpoint(str(run_id), str(org_id), int(sequence), self._decode_state(state_json), node, str(created_at)))
            return tuple(rows)
        finally:
            close = getattr(cursor, "close", None)
            if callable(close):
                close()


__all__ = ["Checkpoint", "Checkpointer", "InMemoryCheckpointer", "PostgresCheckpointer", "SQLiteCheckpointer"]
