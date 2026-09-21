-- Revision: 20260916_found_002_runtime_entry_baseline
-- FOUND-002: immutable runtime-entry composition and build baseline metadata.
CREATE TABLE IF NOT EXISTS runtime_entry_baselines (
    baseline_key TEXT NOT NULL CHECK (baseline_key = 'runtime-entrypoints'),
    baseline_version INTEGER NOT NULL CHECK (baseline_version >= 1),
    status TEXT NOT NULL CHECK (status IN ('active', 'superseded')),
    entries JSON NOT NULL,
    global_constraints JSON NOT NULL,
    baseline_hash TEXT NOT NULL CHECK (baseline_hash LIKE 'sha256:%'),
    effective_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    PRIMARY KEY (baseline_key, baseline_version)
);
