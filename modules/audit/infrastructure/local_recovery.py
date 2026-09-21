"""Disposable SQLite and private-object recovery drill with verified snapshots."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Protocol
from uuid import UUID

from modules.audit.recovery import BackupSnapshot, RecoveryError, RecoveryService, RestoreRun


class ObjectStore(Protocol):
    def list(self, org_id: str) -> tuple[object, ...]: ...
    def get(self, org_id: str, storage_object_ref: str) -> bytes: ...
    def put(self, org_id: str, object_key: str, content: bytes, *, content_type: str,
            metadata: dict[str, str]) -> object: ...


@dataclass(frozen=True)
class LocalRestore:
    run: RestoreRun
    connection: sqlite3.Connection
    object_store: ObjectStore


class LocalRecoveryDrill:
    """Recover a synthetic source into an isolated DB and empty object store."""

    def __init__(self, root: Path, service: RecoveryService) -> None:
        self.root = root.resolve()
        self.service = service
        self._restores: dict[UUID, LocalRestore] = {}

    def backup(self, *, org_id: UUID, database: sqlite3.Connection, object_store: ObjectStore,
               latest_event_at: datetime, captured_at: datetime, idempotency_key: str,
               trace_id: str) -> BackupSnapshot:
        tenant = UUID(str(org_id))
        image = database.serialize()
        objects = []
        for item in object_store.list(str(tenant)):
            content = object_store.get(str(tenant), item.storage_object_ref)
            objects.append({"object_key": item.object_key, "content_type": item.content_type,
                            "metadata": dict(item.metadata), "content_hash": sha256(content).hexdigest(),
                            "content_base64": base64.b64encode(content).decode("ascii")})
        objects.sort(key=lambda item: item["object_key"])
        database_hash = sha256(image).hexdigest()
        snapshot = self.service.create_backup(org_id=tenant, database_payload={"sha256": database_hash},
            object_payload=[{k: v for k, v in item.items() if k != "content_base64"} for item in objects],
            latest_event_at=latest_event_at, captured_at=captured_at,
            idempotency_key=idempotency_key, trace_id=trace_id)
        destination = self._directory(tenant, snapshot.id)
        if destination.exists():
            self._verify_files(destination)
            return snapshot
        destination.mkdir(parents=True)
        (destination / "database.sqlite").write_bytes(image)
        (destination / "objects.json").write_text(json.dumps(objects, sort_keys=True), encoding="utf-8")
        (destination / "snapshot.json").write_text(json.dumps(snapshot.as_contract(), sort_keys=True), encoding="utf-8")
        return snapshot

    def restore(self, *, org_id: UUID, snapshot_id: UUID, object_store: ObjectStore,
                failure_started_at: datetime, restored_at: datetime, idempotency_key: str,
                trace_id: str, queue_names: tuple[str, ...] = ("default",)) -> LocalRestore:
        tenant = UUID(str(org_id))
        snapshot_id = UUID(str(snapshot_id))
        prior = self.service._commands.get((tenant, idempotency_key))
        if prior is not None and isinstance(prior[1], RestoreRun):
            return self._restores[prior[1].id]
        if object_store.list(str(tenant)):
            raise RecoveryError("RESTORE_TARGET_NOT_EMPTY", "restore object store must be empty")
        directory = self._directory(tenant, snapshot_id)
        snapshot, image, objects = self._verify_files(directory)
        if snapshot.org_id != tenant:
            raise RecoveryError("TENANT_SCOPE_VIOLATION", "snapshot belongs to another organization")
        self.service.snapshots.setdefault(snapshot.id, snapshot)
        connection = sqlite3.connect(":memory:")
        connection.deserialize(image)
        try:
            for item in objects:
                object_store.put(str(tenant), item["object_key"], base64.b64decode(item["content_base64"]),
                    content_type=item["content_type"], metadata=item["metadata"])
            connection.execute("CREATE TABLE IF NOT EXISTS audit_recovery_queue_pauses ("
                "org_id TEXT NOT NULL, queue_name TEXT NOT NULL, restore_id TEXT NOT NULL, "
                "paused INTEGER NOT NULL, version INTEGER NOT NULL, PRIMARY KEY (org_id, queue_name))")
            run = self.service.restore(org_id=tenant, snapshot_id=snapshot.id,
                failure_started_at=failure_started_at, restored_at=restored_at,
                latest_recovered_event_at=snapshot.latest_event_at,
                idempotency_key=idempotency_key, trace_id=trace_id, queue_names=queue_names)
            for queue_name in queue_names:
                row = connection.execute("SELECT version FROM audit_recovery_queue_pauses "
                    "WHERE org_id = ? AND queue_name = ?", (str(tenant), queue_name)).fetchone()
                version = int(row[0]) + 1 if row else 1
                connection.execute("INSERT OR REPLACE INTO audit_recovery_queue_pauses VALUES (?, ?, ?, 1, ?)",
                    (str(tenant), queue_name, str(run.id), version))
            connection.commit()
            result = LocalRestore(run, connection, object_store)
            self._restores[run.id] = result
            return result
        except Exception:
            connection.close()
            raise

    def release(self, *, org_id: UUID, restore_id: UUID, expected_version: int,
                idempotency_key: str, trace_id: str) -> RestoreRun:
        tenant = UUID(str(org_id))
        result = self._restores.get(UUID(str(restore_id)))
        if result is None or result.run.org_id != tenant:
            raise RecoveryError("TENANT_SCOPE_VIOLATION", "restore does not belong to organization")
        run = self.service.release_queues(org_id=tenant, restore_id=restore_id,
            expected_version=expected_version, idempotency_key=idempotency_key, trace_id=trace_id)
        result.connection.execute("UPDATE audit_recovery_queue_pauses SET paused = 0, version = version + 1 "
            "WHERE org_id = ? AND restore_id = ?", (str(tenant), str(restore_id)))
        result.connection.commit()
        self._restores[run.id] = LocalRestore(run, result.connection, result.object_store)
        return run

    def _directory(self, tenant: UUID, snapshot: UUID) -> Path:
        return self.root / str(tenant) / str(snapshot)

    def _verify_files(self, directory: Path) -> tuple[BackupSnapshot, bytes, list[dict]]:
        try:
            metadata = json.loads((directory / "snapshot.json").read_text(encoding="utf-8"))
            image = (directory / "database.sqlite").read_bytes()
            objects = json.loads((directory / "objects.json").read_text(encoding="utf-8"))
            snapshot = BackupSnapshot(UUID(metadata["id"]), UUID(metadata["org_id"]),
                metadata["database_snapshot_ref"], metadata["object_snapshot_ref"],
                metadata["captured_at"], metadata["latest_event_at"], metadata["payload_hash"],
                metadata["status"], metadata["version"])
            summary = [{k: v for k, v in item.items() if k != "content_base64"} for item in objects]
            digest = _payload_hash({"sha256": sha256(image).hexdigest()}, summary)
            if digest != snapshot.payload_hash:
                raise ValueError("snapshot content hash differs")
            for item in objects:
                content = base64.b64decode(item["content_base64"], validate=True)
                if sha256(content).hexdigest() != item["content_hash"]:
                    raise ValueError("object content hash differs")
            return snapshot, image, objects
        except (OSError, KeyError, ValueError, TypeError) as exc:
            raise RecoveryError("BACKUP_VERIFICATION_FAILED", "synthetic backup is missing or corrupt") from exc


def _payload_hash(database_summary: dict, object_summary: list[dict]) -> str:
    value = json.dumps({"database": database_summary, "objects": object_summary},
        sort_keys=True, separators=(",", ":"))
    return sha256(value.encode()).hexdigest()
