from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from urllib.parse import urljoin
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
import pytest
import sqlalchemy as sa

from infra.foundation.control_plane import ControlPlaneError, ControlPlaneStore, SideEffectRejected
from infra.foundation.observability import TenantContext
from scripts.bootstrap_foundation_db import bootstrap


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 18, tzinfo=timezone.utc)


def fixture(tmp_path):
    path = tmp_path / "found008.db"
    engine = sa.create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as connection:
        bootstrap(connection)
    engine.dispose()
    connection = sqlite3.connect(path)
    org_id, actor_id = str(uuid4()), str(uuid4())
    context = TenantContext(trace_id="trace-found-008", request_id="request-found-008", org_id=org_id, actor_id=actor_id)
    return connection, ControlPlaneStore(connection, global_authorizer=lambda candidate: candidate.actor_id == actor_id), context


def digest(char="a"):
    return char * 64


def test_flags_are_versioned_idempotent_and_tenant_scoped(tmp_path):
    connection, store, context = fixture(tmp_path)
    changed = store.set_feature_flag(context=context, flag_key="delivery_mode.authorized_api", enabled=True,
                                     reason="synthetic enable", expected_version=0, idempotency_key="flag-1", now=NOW)
    assert changed.version == 1 and changed.enabled is True
    assert store.set_feature_flag(context=context, flag_key="delivery_mode.authorized_api", enabled=True,
                                  reason="synthetic enable", expected_version=0, idempotency_key="flag-1", now=NOW) == changed
    with pytest.raises(ControlPlaneError, match="different command") as reused:
        store.set_feature_flag(context=context, flag_key="delivery_mode.authorized_api", enabled=False,
                               reason="different", expected_version=1, idempotency_key="flag-1", now=NOW)
    assert reused.value.code == "IDEMPOTENCY_KEY_REUSED"
    with pytest.raises(ControlPlaneError) as stale:
        store.set_feature_flag(context=context, flag_key="delivery_mode.authorized_api", enabled=False,
                               reason="stale", expected_version=0, idempotency_key="flag-2", now=NOW)
    assert stale.value.code == "CONTROL_VERSION_CONFLICT"
    other = TenantContext(trace_id="trace-other", request_id="request-other", org_id=str(uuid4()), actor_id=context.actor_id)
    assert store.get_feature_flag(other.org_id, "delivery_mode.authorized_api") is None
    assert connection.execute("SELECT decision FROM foundation_control_audit").fetchall() == [("changed",)]


def test_default_modes_and_feature_rejection_are_audited(tmp_path):
    connection, store, context = fixture(tmp_path)
    allowed = store.guard_new_task(context=context, delivery_mode="simulation", requires_side_effect=False,
                                   task_kind="simulation", payload_hash=digest(), idempotency_key="gate-allow", now=NOW)
    assert allowed.allowed and allowed.feature_enabled
    replayed = store.guard_new_task(context=context, delivery_mode="simulation", requires_side_effect=False,
                                    task_kind="simulation", payload_hash=digest(), idempotency_key="gate-allow", now=NOW)
    assert replayed.allowed and replayed.replayed
    with pytest.raises(SideEffectRejected) as rejected:
        store.guard_new_task(context=context, delivery_mode="authorized_api", requires_side_effect=True,
                             task_kind="publication", payload_hash=digest("b"), idempotency_key="gate-reject", now=NOW)
    assert rejected.value.code == "FEATURE_FLAG_DISABLED"
    assert set(connection.execute("SELECT decision, reason FROM foundation_control_audit").fetchall()) == {
        ("allow", "ALLOWED"), ("reject", "FEATURE_FLAG_DISABLED")
    }
    with pytest.raises(SideEffectRejected) as replay:
        store.guard_new_task(context=context, delivery_mode="authorized_api", requires_side_effect=True,
                             task_kind="publication", payload_hash=digest("b"), idempotency_key="gate-reject", now=NOW)
    assert replay.value.code == "FEATURE_FLAG_DISABLED"
    assert connection.execute("SELECT COUNT(*) FROM foundation_control_audit").fetchone()[0] == 2
    with pytest.raises(ControlPlaneError) as changed:
        store.guard_new_task(context=context, delivery_mode="authorized_api", requires_side_effect=True,
                             task_kind="publication", payload_hash=digest("c"), idempotency_key="gate-reject", now=NOW)
    assert changed.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_pause_rejects_new_side_effects_and_writes_audit_and_outbox_atomically(tmp_path):
    connection, store, context = fixture(tmp_path)
    paused = store.set_global_kill_switch(context=context, paused=True, reason="synthetic incident",
                                          expected_version=0, idempotency_key="pause-1", now=NOW)
    assert paused.status == "paused" and paused.version == 1
    assert store.set_global_kill_switch(context=context, paused=True, reason="synthetic incident",
                                        expected_version=0, idempotency_key="pause-1", now=NOW) == paused
    row = connection.execute("SELECT event_type, aggregate_version, payload FROM outbox_events").fetchone()
    assert row[:2] == ("kill_switch.paused", 1)
    payload = json.loads(row[2])
    assert payload["from_state"] == "active" and payload["to_state"] == "paused"
    with pytest.raises(SideEffectRejected) as rejected:
        store.guard_new_task(context=context, delivery_mode="simulation", requires_side_effect=True,
                             task_kind="side-effect", payload_hash=digest(), idempotency_key="blocked", now=NOW)
    assert rejected.value.code == "GLOBAL_KILL_SWITCH_PAUSED"
    safe = store.guard_new_task(context=context, delivery_mode="manual_export", requires_side_effect=False,
                                task_kind="manual-export", payload_hash=digest("b"), idempotency_key="safe", now=NOW)
    assert safe.allowed and safe.kill_switch_status == "paused"
    resumed = store.set_global_kill_switch(context=context, paused=False, reason="synthetic recovery",
                                           expected_version=1, idempotency_key="resume-1", now=NOW)
    assert resumed.status == "active" and resumed.version == 2
    assert connection.execute("SELECT event_type FROM outbox_events ORDER BY aggregate_version").fetchall() == [
        ("kill_switch.paused",), ("kill_switch.resumed",)
    ]


def test_kill_switch_event_matches_registered_contract(tmp_path):
    connection, store, context = fixture(tmp_path)
    store.set_global_kill_switch(context=context, paused=True, reason="contract test",
                                 expected_version=0, idempotency_key="contract", now=NOW)
    columns = [item[1] for item in connection.execute("PRAGMA table_info(outbox_events)")]
    row = connection.execute("SELECT * FROM outbox_events").fetchone()
    event = dict(zip(columns, row))
    event["payload"] = json.loads(event["payload"])
    schema = json.loads((ROOT / "packages/contracts/events/kill_switch-paused.schema.json").read_text(encoding="utf-8"))
    envelope = json.loads((ROOT / "packages/contracts/events/event-envelope.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resource(urljoin(schema["$id"], "./event-envelope.schema.json"), Resource.from_contents(envelope))
    contract_fields = set(envelope["properties"])
    Draft202012Validator(schema, registry=registry, format_checker=FormatChecker()).validate({key: event[key] for key in contract_fields})
    kill_schema = json.loads((ROOT / "packages/contracts/jsonschema/kill-switch.schema.json").read_text(encoding="utf-8"))
    mode_schema = json.loads((ROOT / "packages/contracts/jsonschema/delivery-mode.schema.json").read_text(encoding="utf-8"))
    kill_registry = Registry().with_resource(mode_schema["$id"], Resource.from_contents(mode_schema))
    Draft202012Validator(kill_schema, registry=kill_registry, format_checker=FormatChecker()).validate(store.get_kill_switch().as_contract())


def test_outbox_failure_rolls_back_switch_and_audit(tmp_path):
    connection, store, context = fixture(tmp_path)
    connection.execute("""CREATE TRIGGER reject_kill_event BEFORE INSERT ON outbox_events
        WHEN NEW.event_type = 'kill_switch.paused' BEGIN SELECT RAISE(ABORT, 'synthetic outbox failure'); END""")
    connection.commit()
    with pytest.raises(sqlite3.IntegrityError, match="synthetic outbox failure"):
        store.set_global_kill_switch(context=context, paused=True, reason="must rollback",
                                     expected_version=0, idempotency_key="rollback", now=NOW)
    assert connection.execute("SELECT COUNT(*) FROM foundation_kill_switch").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM foundation_control_audit").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM foundation_control_commands").fetchone()[0] == 0


@pytest.mark.parametrize("field", ["org", "actor"])
def test_missing_or_invalid_identity_has_no_writes(tmp_path, field):
    connection, store, context = fixture(tmp_path)
    broken = TenantContext(trace_id=context.trace_id, request_id=context.request_id,
                           org_id=None if field == "org" else context.org_id,
                           actor_id="not-a-uuid" if field == "actor" else context.actor_id)
    with pytest.raises(ControlPlaneError):
        store.set_global_kill_switch(context=broken, paused=True, reason="invalid identity",
                                     expected_version=0, idempotency_key="identity", now=NOW)
    assert connection.execute("SELECT COUNT(*) FROM foundation_control_audit").fetchone()[0] == 0


def test_invalid_mode_hash_and_naive_time_are_deterministic(tmp_path):
    connection, store, context = fixture(tmp_path)
    for kwargs in (
        {"delivery_mode": "unknown", "payload_hash": digest(), "now": NOW},
        {"delivery_mode": "simulation", "payload_hash": "bad", "now": NOW},
        {"delivery_mode": "simulation", "payload_hash": digest(), "now": datetime(2026, 9, 18)},
    ):
        with pytest.raises(ControlPlaneError):
            store.guard_new_task(context=context, requires_side_effect=True, task_kind="invalid",
                                 idempotency_key=str(uuid4()), **kwargs)
    assert connection.execute("SELECT COUNT(*) FROM foundation_control_audit").fetchone()[0] == 0


def test_global_control_requires_explicit_authorizer(tmp_path):
    connection, _, context = fixture(tmp_path)
    store = ControlPlaneStore(connection)
    with pytest.raises(ControlPlaneError) as forbidden:
        store.set_global_kill_switch(context=context, paused=True, reason="unauthorized",
                                     expected_version=0, idempotency_key="forbidden", now=NOW)
    assert forbidden.value.code == "GLOBAL_CONTROL_FORBIDDEN"
    assert connection.execute("SELECT COUNT(*) FROM foundation_kill_switch").fetchone()[0] == 0


def test_gate_replay_rejects_changed_metadata_even_with_same_payload_hash(tmp_path):
    connection, store, context = fixture(tmp_path)
    store.guard_new_task(context=context, delivery_mode="simulation", requires_side_effect=False,
                         task_kind="simulation", payload_hash=digest(), idempotency_key="metadata", now=NOW)
    for changes in (
        {"delivery_mode": "manual_export", "requires_side_effect": False, "task_kind": "simulation"},
        {"delivery_mode": "simulation", "requires_side_effect": True, "task_kind": "simulation"},
        {"delivery_mode": "simulation", "requires_side_effect": False, "task_kind": "other"},
    ):
        with pytest.raises(ControlPlaneError) as reused:
            store.guard_new_task(context=context, payload_hash=digest(), idempotency_key="metadata", now=NOW, **changes)
        assert reused.value.code == "IDEMPOTENCY_KEY_REUSED"
