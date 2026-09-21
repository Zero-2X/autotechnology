-- Revision: 20260915_gov_006_tech_stack_baseline
-- GOV-006: immutable modular-monolith and deployment technology baseline.
CREATE TABLE IF NOT EXISTS architecture_baselines (
    baseline_key TEXT NOT NULL,
    baseline_version INTEGER NOT NULL CHECK (baseline_version >= 1),
    status TEXT NOT NULL CHECK (status IN ('active', 'superseded')),
    components JSON NOT NULL,
    excluded_initially JSON NOT NULL,
    architecture_constraints JSON NOT NULL,
    upgrade_policy JSON NOT NULL,
    effective_at TEXT NOT NULL,
    locked_by TEXT NOT NULL,
    PRIMARY KEY (baseline_key, baseline_version)
);
