-- Revision: 20260916_found_003a_database_baseline
-- FOUND-003A: non-secret PostgreSQL configuration and fixture baseline metadata.
CREATE TABLE IF NOT EXISTS database_connection_baselines (
    baseline_key TEXT NOT NULL CHECK (baseline_key = 'postgresql-foundation'),
    baseline_version INTEGER NOT NULL CHECK (baseline_version >= 1),
    status TEXT NOT NULL CHECK (status IN ('active', 'superseded')),
    engine TEXT NOT NULL CHECK (engine = 'postgresql'),
    host TEXT NOT NULL,
    port INTEGER NOT NULL CHECK (port BETWEEN 1 AND 65535),
    database_name TEXT NOT NULL,
    ssl_mode TEXT NOT NULL,
    fixture_kind TEXT NOT NULL CHECK (fixture_kind IN ('synthetic', 'none')),
    config_hash TEXT NOT NULL CHECK (config_hash LIKE 'sha256:%'),
    effective_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    PRIMARY KEY (baseline_key, baseline_version)
);
