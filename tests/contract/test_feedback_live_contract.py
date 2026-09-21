from datetime import datetime, timedelta, timezone
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker
from pathlib import Path
import json

from modules.feedback.live import LiveFeedbackService
from modules.analytics import ObservationService


ROOT = Path(__file__).resolve().parents[2]


def test_live_observations_validate_against_observation_contract():
    service = LiveFeedbackService(observation_service=ObservationService(), clock=lambda: datetime(2026, 9, 21, tzinfo=timezone.utc))
    org_id, connection_id = uuid4(), uuid4()
    result = service.ingest_platform_window(
        org_id=org_id, actor_id=uuid4(), trace_id="trace", idempotency_key="contract-live",
        account_connection_id=connection_id, platform_id=uuid4(), external_account_id="account",
        publication_id=uuid4(), window_start=datetime(2026, 9, 21, tzinfo=timezone.utc),
        window_end=datetime(2026, 9, 21, 1, tzinfo=timezone.utc),
        attribution={"external_object_id": "object"}, interactions={"views": 1}, platform_cost=0,
        lead_quality={"qualified": False}, source_snapshot_ref="private://live/snapshot",
        account_evidence={"org_id": str(org_id), "connection_id": str(connection_id), "status": "verified"},
    )
    schema = json.loads((ROOT / "packages/contracts/jsonschema/observation.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for observation in result["observations"]:
        validator.validate(observation)
