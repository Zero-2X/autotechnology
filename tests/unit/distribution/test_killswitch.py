from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
import json
from pathlib import Path
from uuid import uuid4

from modules.distribution import DistributionKillSwitchService, DistributionService, KillSwitchError


ROOT = Path(__file__).resolve().parents[3]
ORG = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000009"
ACTOR = "00000000-0000-4000-8000-000000000002"
PLATFORM = "00000000-0000-4000-8000-000000000003"
ACCOUNT = "00000000-0000-4000-8000-000000000004"
TARGET = "00000000-0000-4000-8000-000000000005"
STAMP = "2026-09-19T00:00:00Z"


def test_global_platform_account_and_target_scopes_are_contract_valid() -> None:
    service = DistributionKillSwitchService()
    global_switch = service.set_kill_switch(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="global",
                                            scope="global", paused=True, reason="incident", expected_version=0,
                                            changed_at=STAMP)
    assert service.set_kill_switch(org_id=ORG, actor_id=ACTOR, trace_id="different", idempotency_key="global",
                                   scope="global", paused=True, reason="incident", expected_version=0,
                                   changed_at=STAMP) == global_switch
    platform_switch = service.set_kill_switch(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="platform",
                                              scope="platform", scope_id=PLATFORM, paused=True, reason="platform issue",
                                              expected_version=0, blocked_delivery_modes=["authorized_api"], changed_at=STAMP)
    account_switch = service.set_kill_switch(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="account",
                                             scope="account", scope_id=ACCOUNT, paused=True, reason="account issue",
                                             expected_version=0, blocked_delivery_modes=["draft_only"], changed_at=STAMP)
    target_switch = service.set_kill_switch(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="target",
                                            scope="target", scope_id=TARGET, paused=True, reason="target issue",
                                            expected_version=0, blocked_delivery_modes=["simulation"], changed_at=STAMP)
    schema = json.loads((ROOT / "packages/contracts/jsonschema/kill-switch.schema.json").read_text(encoding="utf-8"))
    mode_schema = json.loads((ROOT / "packages/contracts/jsonschema/delivery-mode.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resource(mode_schema["$id"], Resource.from_contents(mode_schema))
    for value in (global_switch, platform_switch, account_switch, target_switch):
        Draft202012Validator(schema, registry=registry, format_checker=FormatChecker()).validate(value)
    assert global_switch["scope"] == "global" and global_switch["org_id"] is None
    assert service.events[-1]["event_type"] == "kill_switch.paused"


def test_scope_guard_blocks_only_matching_side_effect_and_is_idempotent() -> None:
    service = DistributionKillSwitchService()
    service.set_kill_switch(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="platform",
                            scope="platform", scope_id=PLATFORM, paused=True, reason="maintenance", expected_version=0,
                            blocked_delivery_modes=["authorized_api"], changed_at=STAMP)
    with pytest.raises(KillSwitchError, match="blocked"):
        service.guard(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="gate",
                      delivery_mode="authorized_api", requires_side_effect=True, platform_id=PLATFORM)
    allowed = service.guard(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="safe",
                            delivery_mode="manual_export", requires_side_effect=False, platform_id=PLATFORM)
    assert allowed["allowed"] is True
    replay = service.guard(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="safe",
                           delivery_mode="manual_export", requires_side_effect=False, platform_id=PLATFORM)
    assert replay == allowed
    with pytest.raises(KillSwitchError, match="version"):
        service.set_kill_switch(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="platform-2",
                                scope="platform", scope_id=PLATFORM, paused=False, reason="bad version", expected_version=0,
                                changed_at=STAMP)


def test_cross_tenant_scope_isolated() -> None:
    service = DistributionKillSwitchService()
    service.set_kill_switch(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="account",
                            scope="account", scope_id=ACCOUNT, paused=True, reason="blocked", expected_version=0,
                            blocked_delivery_modes=["draft_only"], changed_at=STAMP)
    allowed = service.guard(org_id=OTHER, actor_id=ACTOR, trace_id="trace", idempotency_key="other",
                            delivery_mode="draft_only", requires_side_effect=True, account_connection_id=ACCOUNT)
    assert allowed["allowed"] is True


def test_distribution_execute_honors_target_kill_switch_before_attempt() -> None:
    service = DistributionService()
    target = service.create_target(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="target",
                                   platform_id=PLATFORM, market="US", locale="en-US", channel="article", environment="dev",
                                   created_at=STAMP)
    version = service.create_target_version(
        org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="version",
        distribution_target_id=target["id"], platform_id=PLATFORM, market="US", locale="en-US", channel="article",
        environment="dev", region_profile_version_id=str(uuid4()), synthetic_target_id="fake", policy_snapshot_id=str(uuid4()),
        eligible_delivery_modes=["simulation"], created_at=STAMP,
    )
    intent = service.create_publication_intent(
        org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="intent",
        variant_version_id=str(uuid4()), asset_version_ids=[], target_version_id=version["id"], delivery_mode="simulation",
        region_profile_version_id=version["region_profile_version_id"], payload_snapshot={"title": "x", "body": {}, "tags": [], "disclosure": None},
        capability_snapshot_hash="a" * 64, intent_key="intent-key", policy_snapshot_id=version["policy_snapshot_id"], created_at=STAMP,
    )
    service.set_kill_switch(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="target-switch",
                            scope="target", scope_id=target["id"], paused=True, reason="pause target", expected_version=0,
                            blocked_delivery_modes=["simulation"], changed_at=STAMP)
    with pytest.raises(KillSwitchError, match="blocked"):
        service.execute(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="execute",
                        intent_id=intent["id"], policy_decision={"id": str(uuid4()), "org_id": ORG, "final_decision": "allow"}, executed_at=STAMP)
    assert service.attempts == {}
