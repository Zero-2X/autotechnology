import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from infra.foundation.storage import (
    FakeStorage, StorageSettings, StorageAccessError, StorageConfigurationError,
    MAX_STORAGE_KEY_BYTES,
)


@pytest.mark.parametrize("key", [
    "a\u0000b", "a\nb", "a\tb", "a\u007fb", "a\u0085b", "a\u202eb", "a\u200bb", chr(0xD800),
    "cafe\u0301.txt", "a%2fb", "a?x", "a#x", " a", "a ", "a/ b", "a /b",
    "/a", "a/", "a//b", "a/../b", "./a", "a\\b", "", None, 123,
])
def test_invalid_keys_never_write_or_alias(key):
    storage = FakeStorage()
    with pytest.raises(StorageAccessError):
        storage.put("org-a", key, b"synthetic", idempotency_key="same-key")
    assert storage.list("org-a") == ()
    valid = storage.put("org-a", "valid.txt", b"other", idempotency_key="same-key")
    assert storage.get("org-a", valid.storage_object_ref) == b"other"


@pytest.mark.parametrize("tenant", ["org\u0000a", "org\u202ea", " org-a", "org a", "org/a", "org%2fa", "..", "e\u0301", "a" * 129, "中" * 43, None])
def test_invalid_tenant_namespace_is_rejected(tenant):
    storage = FakeStorage()
    with pytest.raises(StorageAccessError):
        storage.put(tenant, "valid.txt", b"synthetic")


@pytest.mark.parametrize("namespace", ["tenant\u0000", "tenant\u202e", "tenant/child", "tenant ", "e\u0301", "中" * 43, ".."])
def test_invalid_config_namespace_is_rejected(namespace):
    with pytest.raises(StorageConfigurationError):
        StorageSettings(None, None, namespace_prefix=namespace)
    with pytest.raises(StorageConfigurationError):
        StorageSettings.from_env({"STORAGE_NAMESPACE_PREFIX": namespace})


def test_total_byte_budget_includes_namespace_and_tenant():
    storage = FakeStorage()
    remaining = MAX_STORAGE_KEY_BYTES - len("tenant/org-a/".encode("utf-8"))
    key = "x" * remaining
    record = storage.put("org-a", key, b"edge")
    assert storage.get("org-a", record.storage_object_ref) == b"edge"
    for invalid in (key + "x", "中" * (remaining // 3 + 1)):
        with pytest.raises(StorageAccessError, match="byte limit"):
            storage.put("org-a", invalid, b"too long")
        with pytest.raises(StorageAccessError, match="byte limit"):
            storage.get("org-a", "private://foundation-fixture/tenant/org-a/" + invalid)
    assert len(storage.list("org-a")) == 1


def test_unicode_and_interior_space_round_trip_without_normalization():
    storage = FakeStorage()
    record = storage.put("租户", "资料/café 😀.txt", b"synthetic")
    assert record.object_key == "资料/café 😀.txt"
    assert storage.head("租户", record.storage_object_ref) == record
    assert storage.get("租户", record.storage_object_ref) == b"synthetic"
    with pytest.raises(StorageAccessError):
        storage.delete("租户", record.storage_object_ref.replace("café", "cafe\u0301"))
    assert storage.get("租户", record.storage_object_ref) == b"synthetic"
    storage.delete("租户", record.storage_object_ref)
    assert storage.list("租户") == ()


@pytest.mark.parametrize("method", ["get", "head", "delete"])
@pytest.mark.parametrize("suffix", [" ", "\n", "\u202e", "%20", "/../valid.txt"])
def test_invalid_references_cannot_alias_or_delete_valid_objects(method, suffix):
    storage = FakeStorage()
    record = storage.put("org-a", "valid.txt", b"synthetic")
    with pytest.raises(StorageAccessError):
        getattr(storage, method)("org-a", record.storage_object_ref + suffix)
    assert storage.get("org-a", record.storage_object_ref) == b"synthetic"


@pytest.mark.parametrize("key", ["a\n", "/a", "a/", "a//b", "a/../b", "a/./b", "a\\b", "a?b", "a%2fb", " a", "a /b", "a/ b", "x" * 1025])
def test_metadata_schema_rejects_structurally_invalid_keys(key):
    schema = json.loads((Path(__file__).resolve().parents[2] / "packages/contracts/jsonschema/storage-object.schema.json").read_text(encoding="utf-8"))
    record = FakeStorage().put("org-a", "valid.txt", b"synthetic").as_contract()
    validator = Draft202012Validator(schema)
    assert validator.is_valid(record)
    assert not validator.is_valid({**record, "object_key": key})
