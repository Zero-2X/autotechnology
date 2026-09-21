-- Revision: 20260915_gov_003_raci_policy
-- GOV-003: versioned RACI, role and incident responsibility policy storage.
CREATE TABLE IF NOT EXISTS raci_policies (
    policy_key TEXT NOT NULL,
    policy_version INTEGER NOT NULL CHECK (policy_version >= 1),
    status TEXT NOT NULL CHECK (status IN ('active', 'superseded')),
    roles JSON NOT NULL,
    raci_matrix JSON NOT NULL,
    audit_responsibilities JSON NOT NULL,
    incident_contacts JSON NOT NULL,
    effective_at TEXT NOT NULL,
    locked_by TEXT NOT NULL,
    PRIMARY KEY (policy_key, policy_version)
);
