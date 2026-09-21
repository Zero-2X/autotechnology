from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import create_app
from modules.canonical_content import CanonicalContentService
from modules.provenance import SourceService


class _LockedBriefs:
    def __init__(self, org_id: str, brief_id: str, snapshot_hash: str) -> None:
        self.org_id = org_id
        self.brief_id = brief_id
        self.snapshot_hash = snapshot_hash

    def get(self, *, org_id: str, brief_id: str) -> dict[str, str]:
        if org_id != self.org_id or brief_id != self.brief_id:
            raise ValueError("missing brief")
        return {"id": brief_id, "org_id": org_id, "status": "locked", "input_snapshot_hash": self.snapshot_hash}


def test_canonical_content_api_create_version_and_submit_review() -> None:
    org_id, actor_id, brief_id = str(uuid4()), str(uuid4()), str(uuid4())
    snapshot_hash = "c" * 64
    source = SourceService()
    briefs = _LockedBriefs(org_id, brief_id, snapshot_hash)
    canonical = CanonicalContentService(connection=source._connection, topic_brief_service=briefs)
    client = TestClient(create_app(provenance_service=source, canonical_content_service=canonical))
    headers = {"X-Org-Id": org_id, "X-Actor-Id": actor_id, "Idempotency-Key": "canonical-root"}
    root_response = client.post("/internal/canonical-contents", headers=headers, json={
        "topic_brief_id": brief_id, "stable_key": "api-guide",
    })
    assert root_response.status_code == 201, root_response.text
    content_id = root_response.json()["data"]["content"]["id"]
    version_response = client.post(
        f"/internal/canonical-contents/{content_id}/versions",
        headers={**headers, "Idempotency-Key": "canonical-version"},
        json={"title": "API guide", "abstract": "Abstract", "input_snapshot_hash": snapshot_hash},
    )
    assert version_response.status_code == 201, version_response.text
    review = client.post(
        f"/internal/canonical-contents/{content_id}:submit-review",
        headers={**headers, "Idempotency-Key": "canonical-review", "If-Match": "1"},
        json={},
    )
    assert review.status_code == 200, review.text
    assert review.json()["data"]["content"]["status"] == "in_review"
    history = client.get(
        f"/internal/canonical-contents/{content_id}/versions?from_version_no=1&to_version_no=1",
        headers={"X-Org-Id": org_id},
    )
    assert history.status_code == 200, history.text
    assert history.json()["data"]["diff"]["empty"] is True
