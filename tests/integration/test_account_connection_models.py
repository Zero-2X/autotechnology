import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from modules.distribution.account import InMemoryAccountService


ROOT = Path(__file__).resolve().parents[2]


def _registry():
    registry = Registry()
    for path in (ROOT / "packages/contracts/jsonschema").glob("*.schema.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(document["$id"], Resource.from_contents(document))
    return registry


def test_connection_evidence_and_target_version_contracts_validate():
    from uuid import uuid4
    from datetime import datetime, timezone

    service = InMemoryAccountService()
    org_id = uuid4()
    profile = service.create_profile(org_id=org_id, platform_id=uuid4(), profile_kind="real", display_name="Contract")
    connection = service.create_connection(
        org_id=org_id, account_profile_id=profile.id, platform_id=profile.platform_id,
        external_account_id="contract-account", environment="sandbox",
        scope_snapshot={"provider": "fake", "scopes": ["profile"]}, now=datetime.now(timezone.utc),
    )
    evidence = service.attach_authorization_evidence(
        org_id=org_id, connection_id=connection.id, evidence_type="oauth_consent",
        external_reference="oauth-ref", scope_snapshot={"provider": "fake", "scopes": ["profile"]},
    )
    service.attach_authorization_evidence(
        org_id=org_id, connection_id=connection.id, evidence_type="sandbox_membership",
        external_reference="sandbox-ref", scope_snapshot={"provider": "fake", "scopes": ["profile"]},
    )
    target = service.create_target(org_id=org_id, account_profile_id=profile.id, channel="short_post")
    version = service.create_connected_target_version(
        org_id=org_id, target_id=target.id, connection_id=connection.id, market="US", locale="en-US",
        region_profile_version_id=uuid4(), created_by=uuid4(), policy_snapshot_id=None,
        capability_snapshot={"actions": ["draft"]},
    )
    directory = ROOT / "packages/contracts/jsonschema"
    registry = _registry()
    for name, value in [
        ("account-connection.schema.json", service.connections[(org_id, connection.id)].as_contract()),
        ("authorization-evidence.schema.json", evidence.as_contract()),
        ("distribution-target-version.schema.json", version),
    ]:
        schema = json.loads((directory / name).read_text(encoding="utf-8"))
        Draft202012Validator(schema, registry=registry, format_checker=FormatChecker()).validate(value)
