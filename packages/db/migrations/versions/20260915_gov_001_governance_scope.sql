-- Revision: 20260915_gov_001_governance_scope
-- GOV-001: versioned governance scope storage.
-- This migration contains no credentials and no external platform side effects.
CREATE TABLE IF NOT EXISTS governance_scopes (
    scope_key TEXT NOT NULL,
    scope_version INTEGER NOT NULL CHECK (scope_version >= 1),
    status TEXT NOT NULL CHECK (status IN ('locked', 'superseded')),
    vertical_name TEXT NOT NULL,
    vertical_definition TEXT NOT NULL,
    primary_topics JSON NOT NULL,
    product_capabilities JSON NOT NULL,
    languages JSON NOT NULL,
    content_types JSON NOT NULL,
    knowledge_site TEXT NOT NULL CHECK (knowledge_site = 'first_party'),
    distribution_modes JSON NOT NULL,
    account_strategy TEXT NOT NULL CHECK (account_strategy = 'deferred_to_M2'),
    initial_in_scope JSON NOT NULL,
    initial_out_of_scope JSON NOT NULL,
    locked_at TEXT NOT NULL,
    locked_by TEXT NOT NULL,
    PRIMARY KEY (scope_key, scope_version)
);
