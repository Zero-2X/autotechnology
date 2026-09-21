-- Revision: 20260915_gov_005_policy_card
-- GOV-005: versioned policy cards and synthetic/dev Policy snapshots.
CREATE TABLE IF NOT EXISTS policy_versions (
    policy_key TEXT NOT NULL,
    policy_version INTEGER NOT NULL CHECK (policy_version >= 1),
    status TEXT NOT NULL CHECK (status IN ('active', 'superseded')),
    policy_domain TEXT NOT NULL,
    display_name TEXT NOT NULL,
    purpose TEXT NOT NULL,
    owner_role TEXT NOT NULL,
    reviewer_roles JSON NOT NULL,
    evidence_refs JSON NOT NULL,
    rules JSON NOT NULL,
    allowed_release_levels JSON NOT NULL,
    synthetic_only INTEGER NOT NULL CHECK (synthetic_only IN (0, 1)),
    effective_at TEXT NOT NULL,
    review_due_at TEXT NOT NULL,
    locked_by TEXT NOT NULL,
    PRIMARY KEY (policy_key, policy_version)
);

CREATE TABLE IF NOT EXISTS policy_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    policy_key TEXT NOT NULL,
    policy_version INTEGER NOT NULL CHECK (policy_version >= 1),
    org_id TEXT,
    subject_type TEXT NOT NULL,
    subject_ref TEXT NOT NULL,
    policy_version_refs JSON NOT NULL,
    input_hash TEXT NOT NULL,
    rules_hash TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'expired', 'revoked')),
    effective_at TEXT NOT NULL,
    expires_at TEXT,
    review_due_at TEXT,
    UNIQUE (policy_key, policy_version, snapshot_hash)
);
