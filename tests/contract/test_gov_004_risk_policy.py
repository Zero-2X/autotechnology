from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "docs/governance/risk-policy-v1.yaml"
RACI = ROOT / "docs/governance/raci-v1.yaml"
SCHEMA = ROOT / "packages/contracts/jsonschema/risk-policy.schema.json"
MIGRATION = ROOT / "packages/db/migrations/versions/20260915_gov_004_risk_policy.sql"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_risk_policy_defines_increasing_r0_r4_scale_and_all_dimensions() -> None:
    policy = _load(POLICY)
    schema = _load(SCHEMA)
    assert set(schema["required"]) <= set(policy)
    assert policy["scale"]["order"] == ["R0", "R1", "R2", "R3", "R4"]
    assert policy["scale"]["direction"] == "increasing_severity"
    assert policy["scale"]["aggregation_rule"] == "highest_triggered_level_wins"
    assert policy["scale"]["unknown_floor"] == "R2"
    assert policy["dimensions"] == [
        "content",
        "factuality",
        "rights",
        "account",
        "privacy",
        "security",
        "region_compliance",
        "platform",
        "runtime",
    ]
    levels = policy["levels"]
    assert [item["risk_level"] for item in levels] == policy["scale"]["order"]
    triggered_dimensions = {
        trigger["dimension"] for level in levels for trigger in level["triggers"]
    }
    assert triggered_dimensions == set(policy["dimensions"])
    datetime.fromisoformat(policy["effective_at"])


def test_risk_actions_quorum_and_contacts_match_raci() -> None:
    policy = _load(POLICY)
    raci = _load(RACI)
    contacts = {item["severity"]: item for item in raci["incident_contacts"]}
    levels = {item["risk_level"]: item for item in policy["levels"]}
    assert set(contacts) == set(levels) == {"R0", "R1", "R2", "R3", "R4"}
    assert levels["R0"]["kill_switch_requirement"] == "none"
    assert levels["R1"]["human_escalation"] == "conditional"
    assert levels["R2"]["human_escalation"] == "required"
    assert levels["R3"]["minimum_approval_quorum"] == 2
    assert levels["R3"]["kill_switch_requirement"] == "required_scoped"
    assert levels["R4"]["minimum_approval_quorum"] == 2
    assert levels["R4"]["human_escalation"] == "incident_response"
    assert levels["R4"]["kill_switch_requirement"] == "immediate_scoped_or_global"
    assert "禁止自动重发" in next(
        rule["requirement"]
        for rule in policy["mandatory_rules"]
        if rule["rule_id"] == "unknown_requires_human_review"
    )
    for risk_level, level in levels.items():
        contact = contacts[risk_level]
        assert contact["primary_role"] == level["primary_role"]
        assert contact["backup_roles"] == level["backup_roles"]
        assert contact["response_sla_minutes"] == level["response_sla_minutes"]
    assert [contacts[level]["response_sla_minutes"] for level in policy["scale"]["order"]] == [1440, 480, 120, 30, 15]


def test_required_triggers_enforce_manual_review_and_account_boundary() -> None:
    policy = _load(POLICY)
    trigger_levels = {
        trigger["trigger_id"]: level["risk_level"]
        for level in policy["levels"]
        for trigger in level["triggers"]
    }
    assert trigger_levels["conflicting_evidence"] == "R2"
    assert trigger_levels["uncertain_rights"] == "R2"
    assert trigger_levels["suspected_personal_data"] == "R2"
    assert trigger_levels["unknown_external_result"] == "R2"
    assert trigger_levels["denied_rights_distribution_request"] == "R3"
    assert trigger_levels["regional_compliance_conflict"] == "R3"
    assert trigger_levels["malicious_prompt_injection"] == "R3"
    assert trigger_levels["credential_exposure"] == "R4"
    assert trigger_levels["unauthorized_real_publication"] == "R4"
    assert trigger_levels["architecture_mvp_real_side_effect_attempt"] == "R4"
    account_boundary = next(
        rule["requirement"]
        for rule in policy["mandatory_rules"]
        if rule["rule_id"] == "architecture_mvp_account_boundary"
    )
    assert "manual_export" in account_boundary
    assert "simulation" in account_boundary
    assert "真实平台 API" in account_boundary


def test_risk_policy_migration_is_idempotent_and_versioned() -> None:
    connection = sqlite3.connect(":memory:")
    sql = MIGRATION.read_text(encoding="utf-8")
    connection.executescript(sql)
    connection.executescript(sql)
    row = (
        "risk-classification",
        1,
        "active",
        "{}",
        "[]",
        "{}",
        "[]",
        "[]",
        "2026-09-15T00:00:00+08:00",
        "team/governance",
    )
    connection.execute("INSERT INTO risk_policies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("INSERT INTO risk_policies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    assert connection.execute("SELECT COUNT(*) FROM risk_policies").fetchone()[0] == 1
