-- Revision: 20260916_found_000_repository_inventory
-- FOUND-000: immutable metadata for verified repository inventory reports.
CREATE TABLE IF NOT EXISTS repository_inventory_snapshots (
    task_id TEXT NOT NULL CHECK (task_id = 'FOUND-000'),
    inventory_version TEXT NOT NULL,
    source_fingerprint TEXT NOT NULL CHECK (source_fingerprint LIKE 'sha256:%'),
    report_path TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    repository_classification TEXT NOT NULL CHECK (
        repository_classification IN ('planning-and-contract-baseline', 'runtime-implementation-detected')
    ),
    secret_contents_read INTEGER NOT NULL CHECK (secret_contents_read = 0),
    created_by TEXT NOT NULL,
    PRIMARY KEY (task_id, source_fingerprint)
);
