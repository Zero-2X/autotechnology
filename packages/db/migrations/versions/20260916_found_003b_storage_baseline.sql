-- Revision: 20260916_found_003b_storage_baseline
-- FOUND-003B: non-secret S3-compatible storage and private-object metadata baseline.
CREATE TABLE IF NOT EXISTS storage_object_baselines (
    baseline_key TEXT NOT NULL CHECK (baseline_key = 's3-compatible-storage'),
    baseline_version INTEGER NOT NULL CHECK (baseline_version >= 1),
    status TEXT NOT NULL CHECK (status IN ('active', 'superseded')),
    provider TEXT NOT NULL CHECK (provider = 's3-compatible'),
    bucket_name TEXT NOT NULL,
    namespace_prefix TEXT NOT NULL,
    default_access_policy TEXT NOT NULL CHECK (default_access_policy = 'private'),
    object_hash_algorithm TEXT NOT NULL CHECK (object_hash_algorithm = 'sha256'),
    deletion_propagation TEXT NOT NULL CHECK (deletion_propagation = 'port_delete_then_metadata_delete'),
    config_hash TEXT NOT NULL CHECK (config_hash LIKE 'sha256:%'),
    effective_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    PRIMARY KEY (baseline_key, baseline_version)
);

CREATE TABLE IF NOT EXISTS storage_object_metadata (
    org_id TEXT NOT NULL,
    object_key TEXT NOT NULL,
    storage_object_ref TEXT NOT NULL CHECK (storage_object_ref LIKE 'private://%'),
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    content_type TEXT NOT NULL,
    access_policy TEXT NOT NULL CHECK (access_policy = 'private'),
    status TEXT NOT NULL CHECK (status IN ('active', 'deleted')),
    created_at TEXT NOT NULL,
    deleted_at TEXT,
    PRIMARY KEY (org_id, storage_object_ref),
    UNIQUE (org_id, object_key)
);
