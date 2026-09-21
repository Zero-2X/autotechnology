from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs/foundation/s3-storage-baseline-v1.yaml"
SCHEMA = ROOT / "packages/contracts/jsonschema/storage-config.schema.json"
MIGRATION = ROOT / "packages/db/migrations/versions/20260916_found_003b_storage_baseline.sql"


def load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_storage_baseline_is_private_by_default_and_schema_aligned() -> None:
    baseline = load_yaml(BASELINE)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert baseline["baseline_key"] == "s3-compatible-storage"
    assert baseline["provider"] == "s3-compatible"
    assert baseline["configuration"]["credentials_in_repository"] is False
    assert baseline["security"] == {
        "default_access_policy": "private",
        "public_urls": False,
        "tenant_namespace": True,
        "content_hash": "sha256",
        "deletion_propagation": "port_delete_then_metadata_delete",
    }
    assert baseline["fixture"] == {
        "kind": "fake_storage",
        "network_access": False,
        "credentials": False,
    }
    assert schema["properties"]["provider"]["const"] == "s3-compatible"


def test_storage_settings_are_non_secret_and_deterministic() -> None:
    from infra.foundation.storage import StorageSettings

    settings = StorageSettings.from_env(
        {
            "STORAGE_ENDPOINT_URL": "https://objects.example.test:9443",
            "STORAGE_BUCKET": "workflow-private",
            "STORAGE_NAMESPACE_PREFIX": "tenant",
            "STORAGE_SIGNED_URL_TTL_SECONDS": "120",
            "STORAGE_DEFAULT_ACCESS_POLICY": "private",
            "STORAGE_REGION": "eu-west-1",
        }
    )
    assert settings.configured is True
    assert settings.redacted_endpoint_url == "https://objects.example.test:9443"
    assert settings.as_contract()["credentials_in_repository"] is False
    assert settings.config_hash.startswith("sha256:")


def test_storage_settings_reject_partial_or_credentialed_configuration() -> None:
    from infra.foundation.storage import StorageConfigurationError, StorageSettings

    assert StorageSettings.from_env({}).configured is False
    with pytest.raises(StorageConfigurationError):
        StorageSettings.from_env({"STORAGE_ENDPOINT_URL": "http://localhost:9000"})
    with pytest.raises(StorageConfigurationError):
        StorageSettings.from_env(
            {
                "STORAGE_ENDPOINT_URL": "http://user:password@localhost:9000",
                "STORAGE_BUCKET": "workflow",
            }
        )
    with pytest.raises(StorageConfigurationError):
        StorageSettings.from_env(
            {
                "STORAGE_ENDPOINT_URL": "http://localhost:9000",
                "STORAGE_BUCKET": "workflow",
                "STORAGE_DEFAULT_ACCESS_POLICY": "public",
            }
        )


def test_storage_health_never_probes_network() -> None:
    from infra.foundation.storage import StorageSettings, storage_health

    not_configured = storage_health(StorageSettings.from_env({}))
    configured = storage_health(StorageSettings.synthetic_fixture())
    assert not_configured["status"] == "not_configured"
    assert configured["status"] == "configured"
    assert configured["probe"] == "not_attempted"
    assert configured["access_policy"] == "private"


def test_fake_storage_hashes_namespaces_and_keeps_objects_private() -> None:
    from infra.foundation.storage import FakeStorage

    storage = FakeStorage()
    record = storage.put(
        "org-a",
        "source/snapshot.txt",
        b"hello",
        content_type="text/plain",
        metadata={"origin": "synthetic"},
    )
    assert record.storage_object_ref.startswith("private://foundation-fixture/tenant/org-a/")
    assert record.content_hash == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert record.size_bytes == 5
    assert record.access_policy == "private"
    assert storage.get("org-a", record.storage_object_ref) == b"hello"
    assert storage.head("org-a", record.storage_object_ref).as_contract() == record.as_contract()
    assert storage.public_url(record.storage_object_ref) is None


def test_fake_storage_rejects_cross_tenant_reads_and_deletes() -> None:
    from infra.foundation.storage import FakeStorage, StorageAccessError

    storage = FakeStorage()
    record = storage.put("org-a", "private.bin", b"payload")
    with pytest.raises(StorageAccessError):
        storage.get("org-b", record.storage_object_ref)
    with pytest.raises(StorageAccessError):
        storage.delete("org-b", record.storage_object_ref)
    assert storage.get("org-a", record.storage_object_ref) == b"payload"


def test_fake_storage_is_idempotent_and_immutable() -> None:
    from infra.foundation.storage import FakeStorage, StorageConflictError

    storage = FakeStorage()
    first = storage.put("org-a", "same.bin", b"one", idempotency_key="key-1")
    replay = storage.put("org-a", "same.bin", b"one", idempotency_key="key-1")
    assert replay.storage_object_ref == first.storage_object_ref
    with pytest.raises(StorageConflictError):
        storage.put("org-a", "same.bin", b"two")
    with pytest.raises(StorageConflictError):
        storage.put("org-a", "another.bin", b"three", idempotency_key="key-1")


def test_fake_storage_delete_removes_private_object() -> None:
    from infra.foundation.storage import FakeStorage, StorageNotFoundError

    storage = FakeStorage()
    record = storage.put("org-a", "delete.bin", b"payload")
    storage.delete("org-a", record.storage_object_ref)
    with pytest.raises(StorageNotFoundError):
        storage.get("org-a", record.storage_object_ref)
    assert storage.list("org-a") == ()


def test_delete_does_not_leave_a_dangling_idempotency_pointer() -> None:
    from infra.foundation.storage import FakeStorage

    storage = FakeStorage()
    first = storage.put("org-a", "replace.bin", b"one", idempotency_key="replace-key")
    storage.delete("org-a", first.storage_object_ref)
    second = storage.put("org-a", "replace.bin", b"two", idempotency_key="replace-key")
    assert second.content_hash != first.content_hash
    assert storage.get("org-a", second.storage_object_ref) == b"two"


def test_storage_baseline_migration_is_idempotent_and_version_locked() -> None:
    connection = sqlite3.connect(":memory:")
    sql = MIGRATION.read_text(encoding="utf-8")
    connection.executescript(sql)
    connection.executescript(sql)
    row = (
        "s3-compatible-storage", 1, "active", "s3-compatible", "foundation-fixture", "tenant",
        "private", "sha256", "port_delete_then_metadata_delete", f"sha256:{'c' * 64}",
        "2026-09-16T00:00:00+00:00", "team/foundation",
    )
    connection.execute(
        "INSERT INTO storage_object_baselines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        row,
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO storage_object_baselines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row,
        )
    assert connection.execute("SELECT COUNT(*) FROM storage_object_baselines").fetchone()[0] == 1
    columns = {row[1] for row in connection.execute("PRAGMA table_info(storage_object_metadata)")}
    assert {"org_id", "storage_object_ref", "content_hash", "access_policy"} <= columns
    connection.execute(
        "INSERT INTO storage_object_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "org-a", "fixture.txt", "private://foundation-fixture/tenant/org-a/fixture.txt",
            "a" * 64, 7, "text/plain", "private", "active",
            "2026-09-16T00:00:00+00:00", None,
        ),
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO storage_object_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "org-a", "fixture.txt", "private://foundation-fixture/tenant/org-a/fixture.txt-2",
                "b" * 64, 8, "text/plain", "private", "active",
                "2026-09-16T00:00:00+00:00", None,
            ),
        )
