"""Offline FOUND-011 smoke: architecture, API liveness, shared-store tenancy."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from apps.api.main import create_app
from infra.foundation.storage import FakeStorage, StorageAccessError
from scripts.check_architecture import check_architecture


def main() -> int:
    errors = check_architecture()
    if errors:
        for error in errors:
            print(error)
        return 1
    with TestClient(create_app()) as client:
        if client.get("/health/live").status_code != 200:
            print("api_liveness_failed")
            return 1
    store = FakeStorage()
    first = store.put("org-a", "smoke.txt", b"synthetic")
    store.put("org-b", "smoke.txt", b"other")
    if len(store.list("org-a")) != 1 or len(store.list("org-b")) != 1:
        print("tenant_list_isolation_failed")
        return 1
    for operation in (store.get, store.delete):
        try:
            operation("org-b", first.storage_object_ref)
        except StorageAccessError:
            pass
        else:
            print("cross_tenant_access_allowed")
            return 1
    if store.get("org-a", first.storage_object_ref) != b"synthetic":
        print("tenant_data_changed")
        return 1
    print("smoke_ok architecture api_liveness tenant_isolation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
