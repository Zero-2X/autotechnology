-- Revision: 20260915_gov_002_release_levels
-- GOV-002: versioned release-level policy storage.
CREATE TABLE IF NOT EXISTS release_level_policies (
    policy_key TEXT NOT NULL,
    policy_version INTEGER NOT NULL CHECK (policy_version >= 1),
    status TEXT NOT NULL CHECK (status IN ('active', 'superseded')),
    levels JSON NOT NULL,
    effective_at TEXT NOT NULL,
    locked_by TEXT NOT NULL,
    PRIMARY KEY (policy_key, policy_version)
);
