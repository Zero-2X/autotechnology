from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "docs/governance/raci-v1.yaml"
SCHEMA = ROOT / "packages/contracts/jsonschema/raci-policy.schema.json"
MIGRATION = ROOT / "packages/db/migrations/versions/20260915_gov_003_raci_policy.sql"


def test_raci_policy_has_roles_matrix_and_incident_coverage() -> None:
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
    assert set(schema["required"]) <= set(policy)
    roles = {item["role_key"] for item in policy["roles"]}
    assert {"governance_owner", "product_owner", "auditor", "security_incident_lead", "on_call_engineer"} <= roles
    assert len(policy["raci_matrix"]) >= 10
    assert len(policy["incident_contacts"]) == 5
    assert {item["severity"] for item in policy["incident_contacts"]} == {"R0", "R1", "R2", "R3", "R4"}
    assert policy["audit_responsibilities"]["audit_owner_role"] == "auditor"
    assert policy["audit_responsibilities"]["evidence_retention_days"] == 730
    assert policy["audit_responsibilities"]["review_cadence"] == "monthly"
    assert all(item["accountable"] for item in policy["raci_matrix"])
    for item in policy["raci_matrix"]:
        assigned = set(item["responsible"] + item["accountable"] + item["consulted"] + item["informed"])
        assert assigned <= roles
        assert len(item["accountable"]) == 1
    for contact in policy["incident_contacts"]:
        assert contact["primary_role"] in roles
        assert set(contact["backup_roles"]) <= roles
        assert contact["primary_role"] not in contact["backup_roles"]
    datetime.fromisoformat(policy["effective_at"])
    text = POLICY.read_text(encoding="utf-8")
    for forbidden in ("@", "+86", "access_token", "client_secret", "BEGIN PRIVATE KEY"):
        assert forbidden not in text


def test_raci_migration_is_idempotent_and_versioned() -> None:
    connection = sqlite3.connect(":memory:")
    sql = MIGRATION.read_text(encoding="utf-8")
    connection.executescript(sql)
    connection.executescript(sql)
    connection.execute(
        "INSERT INTO raci_policies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("raci-role-map", 1, "active", "[]", "[]", "{}", "[]", "2026-09-15T00:00:00+08:00", "team/governance"),
    )
    assert connection.execute("SELECT COUNT(*) FROM raci_policies").fetchone()[0] == 1
