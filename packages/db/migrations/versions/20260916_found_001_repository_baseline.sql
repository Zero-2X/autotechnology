-- Revision: 20260916_found_001_repository_baseline
-- FOUND-001: immutable repository layout and branch-protection baseline metadata.
CREATE TABLE IF NOT EXISTS repository_branch_protection_baselines (
    baseline_key TEXT NOT NULL CHECK (baseline_key = 'repository-branch-protection'),
    baseline_version INTEGER NOT NULL CHECK (baseline_version >= 1),
    repository_state TEXT NOT NULL CHECK (repository_state IN ('not_a_git_worktree', 'git_worktree')),
    enforcement_status TEXT NOT NULL CHECK (enforcement_status IN ('documented_not_enforced', 'enforced')),
    baseline_hash TEXT NOT NULL CHECK (baseline_hash LIKE 'sha256:%'),
    layout_hash TEXT NOT NULL CHECK (layout_hash LIKE 'sha256:%'),
    effective_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    PRIMARY KEY (baseline_key, baseline_version)
);
