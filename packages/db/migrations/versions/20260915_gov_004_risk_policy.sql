-- Revision: 20260915_gov_004_risk_policy
-- GOV-004: versioned R0-R4 risk classification and escalation policy storage.
CREATE TABLE IF NOT EXISTS risk_policies (
    policy_key TEXT NOT NULL,
    policy_version INTEGER NOT NULL CHECK (policy_version >= 1),
    status TEXT NOT NULL CHECK (status IN ('active', 'superseded')),
    scale JSON NOT NULL,
    dimensions JSON NOT NULL,
    cross_policy_refs JSON NOT NULL,
    mandatory_rules JSON NOT NULL,
    levels JSON NOT NULL,
    effective_at TEXT NOT NULL,
    locked_by TEXT NOT NULL,
    PRIMARY KEY (policy_key, policy_version)
);
