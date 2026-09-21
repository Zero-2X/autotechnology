from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest

from modules.distribution.account import AccountError, InMemoryAccountService


NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def _service():
    service = InMemoryAccountService()
    org_id = uuid4()
    profile = service.create_profile(org_id=org_id, platform_id=uuid4(), profile_kind="real", display_name="Real sandbox")
    connection = service.create_connection(
        org_id=org_id,
        account_profile_id=profile.id,
        platform_id=profile.platform_id,
        external_account_id="sandbox-account-1",
        environment="sandbox",
        scope_snapshot={"provider": "fake", "scopes": ["profile", "content.draft"]},
        actor_id=uuid4(), trace_id="trace", idempotency_key="connection-1", now=NOW,
    )
    return service, org_id, profile, connection


def test_connection_is_pending_until_complete_evidence_and_passport_is_secret_free():
    service, org_id, profile, connection = _service()
    assert connection.connection_status == "pending"
    with pytest.raises(AccountError) as error:
        service.create_connected_target_version(
            org_id=org_id, target_id=uuid4(), connection_id=connection.id, market="US", locale="en-US",
            region_profile_version_id=uuid4(), created_by=uuid4(), policy_snapshot_id=None,
            capability_snapshot={"actions": ["draft"]},
        )
    assert error.value.code == "TENANT_SCOPE_VIOLATION"

    service.attach_authorization_evidence(
        org_id=org_id, connection_id=connection.id, evidence_type="oauth_consent",
        external_reference="oauth-evidence-1", scope_snapshot={"provider": "fake", "scopes": ["profile"]},
        actor_id=uuid4(), trace_id="trace", idempotency_key="evidence-1", now=NOW,
    )
    service.attach_authorization_evidence(
        org_id=org_id, connection_id=connection.id, evidence_type="sandbox_membership",
        external_reference="sandbox-evidence-1", scope_snapshot={"provider": "fake", "scopes": ["profile"]},
        actor_id=uuid4(), trace_id="trace", idempotency_key="evidence-2", now=NOW,
    )
    passport = service.account_passport(org_id=org_id, connection_id=connection.id)
    assert passport["evidence_completeness_percent"] == 100.0
    assert passport["ready_for_side_effects"] is True
    assert "access-secret" not in json.dumps(passport).lower()

    target = service.create_target(org_id=org_id, account_profile_id=profile.id, channel="article")
    version = service.create_connected_target_version(
        org_id=org_id, target_id=target.id, connection_id=connection.id, market="US", locale="en-US",
        region_profile_version_id=uuid4(), created_by=uuid4(), policy_snapshot_id=None,
        capability_snapshot={"actions": ["draft"]}, now=NOW,
    )
    assert version["account_connection_id"] == str(connection.id)
    assert version["status"] == "draft"
    assert version["account_connection_snapshot"]["token_version"] == 0


def test_duplicate_and_cross_tenant_connections_are_blocked():
    service, org_id, profile, connection = _service()
    with pytest.raises(AccountError) as duplicate:
        service.create_connection(
            org_id=org_id, account_profile_id=profile.id, platform_id=profile.platform_id,
            external_account_id="sandbox-account-1", environment="sandbox",
            scope_snapshot={}, now=NOW,
        )
    assert duplicate.value.code == "DUPLICATE_CONNECTION"
    with pytest.raises(AccountError) as cross_tenant:
        service.account_passport(org_id=uuid4(), connection_id=connection.id)
    assert cross_tenant.value.code == "CONNECTION_NOT_FOUND"


def test_connection_and_evidence_commands_replay_same_immutable_result():
    service = InMemoryAccountService()
    org_id = uuid4()
    profile = service.create_profile(org_id=org_id, platform_id=uuid4(), profile_kind="real", display_name="Replay")
    kwargs = dict(
        org_id=org_id, account_profile_id=profile.id, platform_id=profile.platform_id,
        external_account_id="replay-account", environment="sandbox", scope_snapshot={},
        idempotency_key="same-connection", now=NOW,
    )
    first = service.create_connection(**kwargs)
    replay = service.create_connection(**kwargs)
    assert replay == first
    evidence_kwargs = dict(
        org_id=org_id, connection_id=first.id, evidence_type="oauth_consent",
        external_reference="oauth", scope_snapshot={}, idempotency_key="same-evidence", now=NOW,
    )
    evidence = service.attach_authorization_evidence(**evidence_kwargs)
    assert service.attach_authorization_evidence(**evidence_kwargs) == evidence


def test_health_check_restricts_expired_or_policy_disallowed_connections():
    service, org_id, _, connection = _service()
    service.attach_authorization_evidence(
        org_id=org_id, connection_id=connection.id, evidence_type="oauth_consent",
        external_reference="oauth", scope_snapshot={"provider": "fake", "scopes": ["profile"]}, now=NOW,
    )
    service.attach_authorization_evidence(
        org_id=org_id, connection_id=connection.id, evidence_type="sandbox_membership",
        external_reference="sandbox", scope_snapshot={"provider": "fake", "scopes": ["profile"]}, now=NOW,
    )
    restricted = service.check_health(
        org_id=org_id, connection_id=connection.id, policy_allowed=False,
        token_expires_at=NOW + timedelta(hours=1), now=NOW,
    )
    assert restricted.connection_status == "restricted"
    assert restricted.health_status == "restricted"
    assert restricted.last_refresh_error == "POLICY_CHANGED"


def test_scope_escalation_is_rejected():
    service, org_id, _, connection = _service()
    with pytest.raises(AccountError) as error:
        service.attach_authorization_evidence(
            org_id=org_id, connection_id=connection.id, evidence_type="oauth_consent",
            external_reference="oauth", scope_snapshot={"provider": "fake", "scopes": ["content.publish"]},
            now=NOW,
        )
    assert error.value.code == "SCOPE_ESCALATION"


def test_delivery_guard_rechecks_each_phase_and_blocks_restricted_accounts():
    from modules.distribution.killswitch import DistributionKillSwitchService, KillSwitchError

    service, org_id, _, connection = _service()
    service.attach_authorization_evidence(
        org_id=org_id, connection_id=connection.id, evidence_type="oauth_consent",
        external_reference="oauth", scope_snapshot={"provider": "fake", "scopes": ["profile"]}, now=NOW,
    )
    service.attach_authorization_evidence(
        org_id=org_id, connection_id=connection.id, evidence_type="sandbox_membership",
        external_reference="sandbox", scope_snapshot={"provider": "fake", "scopes": ["profile"]}, now=NOW,
    )
    switches = DistributionKillSwitchService()
    allowed = service.guard_delivery_phase(
        kill_switch=switches, org_id=org_id, connection_id=connection.id, actor_id=uuid4(),
        trace_id="trace", idempotency_key="guard", phase="queue_claim", delivery_mode="draft_only",
    )
    assert allowed["side_effect_triggered"] is False
    switches.set_kill_switch(
        org_id=org_id, actor_id=uuid4(), trace_id="trace", idempotency_key="pause",
        scope="account", scope_id=connection.id, paused=True, reason="incident", expected_version=0,
    )
    with pytest.raises(KillSwitchError) as error:
        service.guard_delivery_phase(
            kill_switch=switches, org_id=org_id, connection_id=connection.id, actor_id=uuid4(),
            trace_id="trace", idempotency_key="guard-2", phase="platform_call", delivery_mode="draft_only",
        )
    assert error.value.code == "KILL_SWITCH_PAUSED"
