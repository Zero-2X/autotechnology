"""SQLite tables for scored opportunities, immutable score versions and audit events."""

from hashlib import sha256
import json


DEFAULT_WEIGHTS = {
    "demand": 0.25, "relevance": 0.25, "evidence_availability": 0.20,
    "differentiation": 0.15, "timeliness": 0.15, "cost": 0.15, "risk": 0.25,
}
DEFAULT_VERSION = "topic-score-v1"


def initialize(connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS topic_scoring_versions ("
        "version TEXT PRIMARY KEY, weights_json TEXT NOT NULL, content_hash TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS topic_opportunities ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, canonical_key TEXT NOT NULL, "
        "status TEXT NOT NULL, expires_at TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL, "
        "UNIQUE(org_id, id))"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_topic_opportunities_active ON "
        "topic_opportunities(org_id, canonical_key, status, expires_at)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS topic_score_snapshots ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, opportunity_id TEXT NOT NULL, "
        "content_hash TEXT NOT NULL, payload TEXT NOT NULL, "
        "FOREIGN KEY(org_id, opportunity_id) REFERENCES topic_opportunities(org_id, id))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS topic_opportunity_commands ("
        "org_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL, "
        "actor_id TEXT NOT NULL, trace_id TEXT NOT NULL, response TEXT NOT NULL, "
        "PRIMARY KEY(org_id, idempotency_key))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS topic_score_snapshot_verifications ("
        "org_id TEXT NOT NULL, snapshot_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, "
        "payload_hash TEXT NOT NULL, payload TEXT NOT NULL, "
        "PRIMARY KEY(org_id, snapshot_id, idempotency_key), "
        "FOREIGN KEY(snapshot_id) REFERENCES topic_score_snapshots(id), "
        "CHECK(length(payload_hash) = 64))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS topic_opportunity_events ("
        "event_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, event_type TEXT NOT NULL, envelope TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS topic_opportunity_state_events ("
        "event_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, opportunity_id TEXT NOT NULL, "
        "event_type TEXT NOT NULL, sequence INTEGER NOT NULL, envelope TEXT NOT NULL, "
        "UNIQUE(org_id, opportunity_id, sequence))"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_topic_opportunity_state_events_org ON "
        "topic_opportunity_state_events(org_id, opportunity_id, sequence)"
    )
    for table in ("topic_scoring_versions", "topic_opportunity_events", "topic_opportunity_state_events"):
        for action in ("UPDATE", "DELETE"):
            connection.execute(
                f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} "
                f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
            )
    for action in ("UPDATE", "DELETE"):
        connection.execute(
            f"CREATE TRIGGER IF NOT EXISTS topic_score_snapshot_verifications_no_{action.lower()} "
            f"BEFORE {action} ON topic_score_snapshot_verifications "
            "BEGIN SELECT RAISE(ABORT, 'topic score snapshot verifications are append-only'); END"
        )
    encoded = json.dumps(DEFAULT_WEIGHTS, sort_keys=True, separators=(",", ":"))
    digest = sha256(encoded.encode()).hexdigest()
    connection.execute(
        "INSERT OR IGNORE INTO topic_scoring_versions (version, weights_json, content_hash) VALUES (?, ?, ?)",
        (DEFAULT_VERSION, encoded, digest),
    )
    stored = connection.execute(
        "SELECT content_hash FROM topic_scoring_versions WHERE version = ?", (DEFAULT_VERSION,)
    ).fetchone()
    if stored[0] != digest:
        raise ValueError("SCORING_CONFIG_DRIFT")
    connection.commit()
