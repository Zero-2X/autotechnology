from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker
import yaml

from modules.media import MediaScriptService


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def _fixture() -> tuple[str, str, dict, dict]:
    org, actor = str(uuid4()), str(uuid4())
    canonical, variant, claim = str(uuid4()), str(uuid4()), str(uuid4())
    value = {
        "id": variant, "org_id": org, "content_variant_id": str(uuid4()),
        "canonical_content_version_id": canonical, "version_no": 1, "locale": "en-US", "market": "US",
        "audience": "engineers", "tone": "neutral", "region_profile_version_id": str(uuid4()),
        "source_variant_version_id": None,
        "body": {"blocks": [{"block_id": "intro", "localized_text": "A verified fact is available.", "term_refs": [], "disclosure": None}]},
        "term_memory_version": "terms-v1", "disclosure": None, "policy_snapshot_id": str(uuid4()),
        "status": "approved", "snapshot_hash": "a" * 64, "created_by": actor, "created_at": "2026-01-01T00:00:00Z",
    }
    fact = {
        "id": claim, "org_id": org, "entity_ids": [], "statement": "A verified fact is available.",
        "fact_type": "product.fact", "applicable_versions": [canonical], "applicable_regions": [],
        "applicable_locales": ["en-US"], "valid_from": None, "valid_to": None, "review_due_at": None,
        "supersedes_claim_id": None, "freshness_status": "fresh", "status": "verified", "version": 1,
        "content_hash": "b" * 64, "created_by": actor, "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    return org, actor, value, fact


def test_media_001_schemas_are_closed_and_registered() -> None:
    for name in ("media-script.schema.json", "media-script-version.schema.json"):
        schema = json.loads((ROOT / "packages/contracts/jsonschema" / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False
        assert schema["x-source"] == "MEDIA-001"
    registry = yaml.safe_load((ROOT / "docs/task-registry.yaml").read_text(encoding="utf-8"))
    task = next(item for item in registry["tasks"] if item["id"] == "MEDIA-001")
    assert task["status"] == "done"
    assert task["migration_refs"] == ["packages/db/migrations/versions/20260920_media_001.py"]
    assert set(task["contract_refs"]) >= {
        "packages/contracts/jsonschema/asset-version.schema.json",
        "packages/contracts/jsonschema/media-script.schema.json",
        "packages/contracts/jsonschema/media-script-version.schema.json",
    }


def test_service_output_validates_and_hash_excludes_actor_trace_and_clock() -> None:
    org, actor, variant, claim = _fixture()
    kwargs = {
        "variant_version": variant, "duration_seconds": 30,
        "source_map": [{"block_id": "intro", "claim_id": claim["id"]}], "claims": [claim],
        "org_id": org, "idempotency_key": "contract-1", "created_at": NOW,
    }
    first = MediaScriptService(clock=lambda: NOW).create_script(**kwargs, actor_id=actor, trace_id="one")
    second_kwargs = {
        **kwargs, "idempotency_key": "contract-2",
        "created_at": datetime(2027, 1, 1, tzinfo=timezone.utc),
    }
    second = MediaScriptService(clock=lambda: datetime(2027, 1, 1, tzinfo=timezone.utc)).create_script(
        **second_kwargs, actor_id=str(uuid4()), trace_id="two",
    )
    schema = json.loads((ROOT / "packages/contracts/jsonschema/media-script-version.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(first["version"])
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(second["version"])
    assert first["version"]["snapshot_hash"] == second["version"]["snapshot_hash"]
    assert "model" not in json.dumps(first.as_contract()).lower()


def test_media_001_migration_is_chained_and_keeps_raw_provider_fields_out() -> None:
    source = (ROOT / "packages/db/migrations/versions/20260920_media_001.py").read_text(encoding="utf-8")
    for marker in (
        'revision = "20260920_media_001"', 'down_revision = "20260920_site_004"',
        "media_scripts", "media_script_versions", "media_script_claim_refs", "media_script_commands",
        "append-only", "variant_versions", "claims", "def upgrade()", "def downgrade()",
    ):
        assert marker in source
    for forbidden in ('sa.Column("token"', 'sa.Column("secret"', 'sa.Column("provider"', 'sa.Column("payload"'):
        assert forbidden not in source
