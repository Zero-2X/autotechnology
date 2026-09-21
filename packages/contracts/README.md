# Contract source layout

`packages/contracts/jsonschema/` contains machine-validated object schemas.
`packages/contracts/events/` contains machine-validated event schemas.
`packages/contracts/openapi/` contains the HTTP contract.
`docs/contracts/` contains human-facing indexes and change notes.

The reproducible baseline is generated with:

```text
python scripts/generate_json_schemas.py
python scripts/generate_event_registry.py
python scripts/generate_state_registry.py
python scripts/generate_contract_manifest.py
python scripts/generate_migration_manifest.py
```

`docs/contracts/contract-manifest.yaml` records which contract files exist for
each task. `docs/contracts/migration-manifest.yaml` is an index and gate record,
never executable SQL. Its lifecycle is fixed:

- `planned`: `migration_refs` may point to an absent path under
  `packages/db/migrations/planned/`; this records intended table scope only.
- `in_progress`: the task must replace that reference with a real Alembic
  revision. The revision must exist and pass lint plus disposable database
  execution before the task can proceed.
- `done`: the real revision has been executed and verified; the manifest must
  retain the revision path and verification evidence. A planned path or empty
  placeholder never satisfies this state.

`blocked` keeps the current reference but must record the missing dependency,
owner, fallback and next review time. The manifest's `path_kind`, `exists` and
`verification_status` fields make these distinctions machine-readable.
