# Repository inventory

This report contains repository structure and metadata only. Sensitive filename hits are never opened.

## Scan metadata

- Inventory version: `found-000-v1`
- Generated at (UTC): `2026-09-23T14:18:50+00:00`
- Source fingerprint: `sha256:0df6db76680fe029c06c5c2ea0409bf65c619ae89a480b12094243d6454a8bfd`
- Repository root: `D:/akagent`
- Scanned files: `1646`
- Secret contents read: `false`
- Freshness limit: `24 hours`

## Git status and branch

- Availability: `git worktree`
- Branch: `master`
- HEAD: `a2d72f4a52aaff0be7aad5b2a40289d31112eb8d`

## Top-level directories

| Directory | Scanned files |
|---|---:|
| `.ci-artifacts/` | 3 |
| `.github/` | 1 |
| `.openai/` | 0 |
| `adapters/` | 10 |
| `apps/` | 31 |
| `ci/` | 1 |
| `deploy/` | 8 |
| `docs/` | 403 |
| `infra/` | 31 |
| `integrations/` | 9 |
| `modules/` | 248 |
| `orchestration/` | 23 |
| `packages/` | 522 |
| `scripts/` | 36 |
| `tests/` | 307 |

## Existing applications and modules

| Path | Files | Runtime source files |
|---|---:|---:|
| `adapters/contract` | 1 | 0 |
| `adapters/fake` | 3 | 2 |
| `adapters/manual` | 1 | 0 |
| `adapters/xiaohongshu` | 5 | 5 |
| `apps/__init__.py` | 1 | 1 |
| `apps/api` | 4 | 3 |
| `apps/knowledge-site` | 9 | 4 |
| `apps/scheduler` | 5 | 4 |
| `apps/web-console` | 7 | 0 |
| `apps/worker` | 5 | 4 |
| `infra/__init__.py` | 1 | 1 |
| `infra/compose` | 3 | 0 |
| `infra/foundation` | 21 | 20 |
| `infra/policies` | 5 | 4 |
| `infra/scripts` | 1 | 0 |
| `modules/agent` | 10 | 10 |
| `modules/analytics` | 12 | 6 |
| `modules/approval` | 2 | 2 |
| `modules/audit` | 13 | 7 |
| `modules/canonical_content` | 10 | 4 |
| `modules/distribution` | 25 | 19 |
| `modules/feedback` | 18 | 12 |
| `modules/geo_content` | 11 | 5 |
| `modules/geo_region` | 9 | 3 |
| `modules/governance` | 6 | 0 |
| `modules/iam` | 11 | 5 |
| `modules/knowledge` | 10 | 4 |
| `modules/media` | 18 | 12 |
| `modules/model_gateway` | 11 | 5 |
| `modules/platforms` | 2 | 2 |
| `modules/policy` | 9 | 3 |
| `modules/production` | 13 | 7 |
| `modules/provenance` | 13 | 7 |
| `modules/qa` | 10 | 4 |
| `modules/support` | 9 | 3 |
| `modules/topic` | 17 | 11 |
| `modules/workflow` | 9 | 3 |
| `packages/contracts` | 373 | 0 |
| `packages/db` | 141 | 127 |
| `packages/observability` | 3 | 2 |
| `packages/prompt_registry` | 3 | 2 |
| `packages/testkit` | 2 | 1 |

## Dependency manifests

- `apps/knowledge-site/package.json`
- `apps/knowledge-site/pnpm-lock.yaml`
- `apps/web-console/package.json`
- `apps/web-console/pnpm-lock.yaml`
- `docs/external-dependencies.yaml`
- `pyproject.toml`
- `requirements-browser.txt`
- `requirements.txt`

## Migrations

- `alembic.ini`
- `packages/db/migrations/__init__.py`
- `packages/db/migrations/env.py`
- `packages/db/migrations/planned/README.md`
- `packages/db/migrations/script.py.mako`
- `packages/db/migrations/versions/20260915_gov_001_governance_scope.sql`
- `packages/db/migrations/versions/20260915_gov_002_release_levels.sql`
- `packages/db/migrations/versions/20260915_gov_003_raci_policy.sql`
- `packages/db/migrations/versions/20260915_gov_004_risk_policy.sql`
- `packages/db/migrations/versions/20260915_gov_005_policy_card.sql`
- `packages/db/migrations/versions/20260915_gov_006_tech_stack_baseline.sql`
- `packages/db/migrations/versions/20260916_found_000_repository_inventory.sql`
- `packages/db/migrations/versions/20260916_found_001_repository_baseline.sql`
- `packages/db/migrations/versions/20260916_found_002_runtime_entry_baseline.sql`
- `packages/db/migrations/versions/20260916_found_003a_database_baseline.sql`
- `packages/db/migrations/versions/20260916_found_003b_storage_baseline.sql`
- `packages/db/migrations/versions/20260916_found_003d_task_jobs.sql`
- `packages/db/migrations/versions/20260916_found_004a_migration_baseline.py`
- `packages/db/migrations/versions/20260916_found_004b_outbox.py`
- `packages/db/migrations/versions/20260916_found_004c_task_leases.py`
- `packages/db/migrations/versions/20260916_found_004d_failure_retry.py`
- `packages/db/migrations/versions/20260916_found_004e_replay.py`
- `packages/db/migrations/versions/20260916_found_004f_api_observability.py`
- `packages/db/migrations/versions/20260916_found_006a_health_metrics.py`
- `packages/db/migrations/versions/20260916_found_006b_tracing_cost.py`
- `packages/db/migrations/versions/20260916_found_007a_openapi.py`
- `packages/db/migrations/versions/20260916_found_007b_events.py`
- `packages/db/migrations/versions/20260916_found_007c_agent_output.py`
- `packages/db/migrations/versions/20260916_found_007d_core_contracts.py`
- `packages/db/migrations/versions/20260918_account_core_001.py`
- `packages/db/migrations/versions/20260918_agent_core_001.py`
- `packages/db/migrations/versions/20260918_agent_core_002.py`
- `packages/db/migrations/versions/20260918_agent_core_003.py`
- `packages/db/migrations/versions/20260918_agent_core_004.py`
- `packages/db/migrations/versions/20260918_canon_001.py`
- `packages/db/migrations/versions/20260918_canon_002.py`
- `packages/db/migrations/versions/20260918_canon_003.py`
- `packages/db/migrations/versions/20260918_canon_004.py`
- `packages/db/migrations/versions/20260918_canon_005.py`
- `packages/db/migrations/versions/20260918_feedback_core_001.py`
- `packages/db/migrations/versions/20260918_found_003c_redis.py`
- `packages/db/migrations/versions/20260918_found_008_control_plane.py`
- `packages/db/migrations/versions/20260918_found_009_testkit.py`
- `packages/db/migrations/versions/20260918_found_010_platform_contracts.py`
- `packages/db/migrations/versions/20260918_found_011_architecture_guard.py`
- `packages/db/migrations/versions/20260918_found_012a_ci.py`
- `packages/db/migrations/versions/20260918_found_012b_supply_chain.py`
- `packages/db/migrations/versions/20260918_found_013_registry.py`
- `packages/db/migrations/versions/20260918_geo_region_core_001.py`
- `packages/db/migrations/versions/20260918_gov_007_data_processing_policy.py`
- `packages/db/migrations/versions/20260918_gov_008_operational_targets.py`
- `packages/db/migrations/versions/20260918_gov_009_account_dependency.py`
- `packages/db/migrations/versions/20260918_gov_010_vendor_inventory.py`
- `packages/db/migrations/versions/20260918_iam_core_001.py`
- `packages/db/migrations/versions/20260918_know_001.py`
- `packages/db/migrations/versions/20260918_know_002.py`
- `packages/db/migrations/versions/20260918_model_core_001.py`
- `packages/db/migrations/versions/20260918_model_core_002.py`
- `packages/db/migrations/versions/20260918_obs_core_001.py`
- `packages/db/migrations/versions/20260918_obs_core_002.py`
- `packages/db/migrations/versions/20260918_obs_core_003.py`
- `packages/db/migrations/versions/20260918_prov_001.py`
- `packages/db/migrations/versions/20260918_prov_002.py`
- `packages/db/migrations/versions/20260918_prov_003.py`
- `packages/db/migrations/versions/20260918_sched_001.py`
- `packages/db/migrations/versions/20260918_topic_001.py`
- `packages/db/migrations/versions/20260918_topic_002.py`
- `packages/db/migrations/versions/20260918_topic_003.py`
- `packages/db/migrations/versions/20260918_topic_004.py`
- `packages/db/migrations/versions/20260918_topic_005.py`
- `packages/db/migrations/versions/20260918_topic_006.py`
- `packages/db/migrations/versions/20260918_topic_007.py`
- `packages/db/migrations/versions/20260918_topic_008.py`
- `packages/db/migrations/versions/20260918_workflow_core_001.py`
- `packages/db/migrations/versions/20260918_workflow_core_002.py`
- `packages/db/migrations/versions/20260918_workflow_core_003.py`
- `packages/db/migrations/versions/20260919_agent_core_005a.py`
- `packages/db/migrations/versions/20260919_agent_core_005b.py`
- `packages/db/migrations/versions/20260919_agent_core_005c.py`
- `packages/db/migrations/versions/20260919_agent_core_005d.py`
- `packages/db/migrations/versions/20260919_agent_core_005e.py`
- `packages/db/migrations/versions/20260919_approval_001.py`
- `packages/db/migrations/versions/20260919_approval_002.py`
- `packages/db/migrations/versions/20260919_canon_006.py`
- `packages/db/migrations/versions/20260919_dist_001.py`
- `packages/db/migrations/versions/20260919_dist_002.py`
- `packages/db/migrations/versions/20260919_dist_003a.py`
- `packages/db/migrations/versions/20260919_dist_003b.py`
- `packages/db/migrations/versions/20260919_dist_004.py`
- `packages/db/migrations/versions/20260919_dist_005a.py`
- `packages/db/migrations/versions/20260919_dist_005b.py`
- `packages/db/migrations/versions/20260919_dist_006a.py`
- `packages/db/migrations/versions/20260919_dist_006b.py`
- `packages/db/migrations/versions/20260919_dist_006c.py`
- `packages/db/migrations/versions/20260919_dist_007.py`
- `packages/db/migrations/versions/20260919_dist_008a.py`
- `packages/db/migrations/versions/20260919_dist_008b.py`
- `packages/db/migrations/versions/20260919_dist_009.py`
- `packages/db/migrations/versions/20260919_dist_010.py`
- `packages/db/migrations/versions/20260919_dist_011.py`
- `packages/db/migrations/versions/20260919_eval_001.py`
- `packages/db/migrations/versions/20260919_feedback_core_002.py`
- `packages/db/migrations/versions/20260919_geo_content_001.py`
- `packages/db/migrations/versions/20260919_geo_content_002.py`
- `packages/db/migrations/versions/20260919_model_001.py`
- `packages/db/migrations/versions/20260919_model_003.py`
- `packages/db/migrations/versions/20260919_policy_001.py`
- `packages/db/migrations/versions/20260919_policy_002.py`
- `packages/db/migrations/versions/20260919_prod_001.py`
- `packages/db/migrations/versions/20260919_prod_002.py`
- `packages/db/migrations/versions/20260919_prod_003.py`
- `packages/db/migrations/versions/20260919_prod_004.py`
- `packages/db/migrations/versions/20260919_qa_001.py`
- `packages/db/migrations/versions/20260919_qa_002.py`
- `packages/db/migrations/versions/20260919_qa_003.py`
- `packages/db/migrations/versions/20260919_site_001.py`
- `packages/db/migrations/versions/20260919_site_002.py`
- `packages/db/migrations/versions/20260919_site_003.py`
- `packages/db/migrations/versions/20260920_analytics_001.py`
- `packages/db/migrations/versions/20260920_analytics_002.py`
- `packages/db/migrations/versions/20260920_analytics_003.py`
- `packages/db/migrations/versions/20260920_geo_content_003.py`
- `packages/db/migrations/versions/20260920_geo_region_001.py`
- `packages/db/migrations/versions/20260920_geo_region_002.py`
- `packages/db/migrations/versions/20260920_media_001.py`
- `packages/db/migrations/versions/20260920_media_002.py`
- `packages/db/migrations/versions/20260920_media_003a.py`
- `packages/db/migrations/versions/20260920_media_003b.py`
- `packages/db/migrations/versions/20260920_media_003c.py`
- `packages/db/migrations/versions/20260920_media_004a.py`
- `packages/db/migrations/versions/20260920_media_004b.py`
- `packages/db/migrations/versions/20260920_media_005a.py`
- `packages/db/migrations/versions/20260920_media_005b.py`
- `packages/db/migrations/versions/20260920_media_006.py`
- `packages/db/migrations/versions/20260920_site_004.py`
- `packages/db/migrations/versions/20260921_analytics_004.py`
- `packages/db/migrations/versions/20260921_feedback_core_003.py`
- `packages/db/migrations/versions/20260921_feedback_core_004.py`
- `packages/db/migrations/versions/20260921_feedback_core_005.py`
- `packages/db/migrations/versions/20260921_feedback_exp_001.py`
- `packages/db/migrations/versions/20260921_sup_001.py`
- `packages/db/migrations/versions/20260921_sup_002.py`

## Environment variable names

| Name | Referenced by |
|---|---|
| `API_PORT` | `apps/api/__main__.py`, `apps/api/main.py` |
| `DATABASE_URL` | `packages/db/migrations/env.py` |
| `DEMO_API_KEY` | `tests/contract/test_found_000_inventory.py` |
| `FORCE_JSON_SCHEMA_REGEN` | `scripts/generate_json_schemas.py` |
| `MINIO_ROOT_PASSWORD` | `infra/compose/storage.dev.yaml` |
| `MINIO_ROOT_USER` | `infra/compose/storage.dev.yaml` |
| `MODEL_BASE_URL` | `integrations/langchain/responses.py`, `modules/model_gateway/console_provider.py` |
| `MODEL_CONTENT_ID` | `modules/model_gateway/console_provider.py` |
| `MODEL_ID` | `modules/model_gateway/console_provider.py` |
| `MODEL_PROVIDER` | `integrations/langchain/responses.py`, `modules/model_gateway/console_provider.py` |
| `MODEL_TIMEOUT_SECONDS` | `modules/model_gateway/console_provider.py` |
| `OPENAI_API_KEY` | `integrations/langchain/responses.py`, `modules/model_gateway/console_provider.py` |
| `OPENAI_MODEL` | `modules/model_gateway/console_provider.py` |

## Sensitive filename hits

| Path | Redacted type | Size |
|---|---|---:|
| `packages/contracts/jsonschema/token-lease.schema.json` | `credential-name-marker` | 1148 |
| `scripts/check_secrets.py` | `credential-name-marker` | 1894 |

## Deployment scripts

- `.github/workflows/ci.yml`
- `deploy/environments/dev/README.md`
- `deploy/environments/dev/database.env.example`
- `deploy/environments/dev/storage.env.example`
- `deploy/environments/dev/task-queue.env.example`
- `deploy/environments/staging/README.md`
- `deploy/environments/staging/database.env.example`
- `deploy/environments/staging/storage.env.example`
- `deploy/environments/staging/task-queue.env.example`
- `scripts/bootstrap_foundation_db.py`
- `scripts/restart-web-console.ps1`
- `scripts/start-web-console.ps1`
- `scripts/start-workflow.ps1`
- `scripts/start-xhs-login.ps1`
- `scripts/start-xhs-login.py`

## Test entrypoints

Recommended repository gate: `python -m pytest tests --maxfail=1 -q`

- `scripts/check_architecture.py`
- `scripts/check_ci_configuration.py`
- `scripts/check_event_compatibility.py`
- `scripts/check_foundation_contracts.py`
- `scripts/check_json_schemas.py`
- `scripts/check_langgraph_task_registry.py`
- `scripts/check_lockfiles.py`
- `scripts/check_migrations.py`
- `scripts/check_openapi_compatibility.py`
- `scripts/check_openapi_contract.py`
- `scripts/check_plan_consistency.py`
- `scripts/check_secrets.py`
- `scripts/check_supply_chain.py`
- `scripts/check_task_card_precision.py`
- `scripts/check_task_card_registry_refs.py`
- `scripts/check_v3_completion_evidence.py`
- `tests/accessibility/test_site_004.py`
- `tests/contract/test_analytics_001_contract.py`
- `tests/contract/test_analytics_002_contract.py`
- `tests/contract/test_analytics_003_contract.py`
- `tests/contract/test_analytics_004_contract.py`
- `tests/contract/test_completed_task_evidence.py`
- `tests/contract/test_feedback_core_003_contract.py`
- `tests/contract/test_feedback_core_004_contract.py`
- `tests/contract/test_feedback_core_005_contract.py`
- `tests/contract/test_feedback_exp_001_contract.py`
- `tests/contract/test_feedback_live_contract.py`
- `tests/contract/test_found_000_inventory.py`
- `tests/contract/test_found_001_repository_baseline.py`
- `tests/contract/test_found_002_runtime_entries.py`
- `tests/contract/test_found_003a_database.py`
- `tests/contract/test_found_003b_key_policy.py`
- `tests/contract/test_found_003b_storage.py`
- `tests/contract/test_found_003c_redis.py`
- `tests/contract/test_found_003d_task_jobs.py`
- `tests/contract/test_found_004a_migrations.py`
- `tests/contract/test_found_004b_outbox.py`
- `tests/contract/test_found_004c_task_claim.py`
- `tests/contract/test_found_004d_failure_retry.py`
- `tests/contract/test_found_004e_replay.py`
- `tests/contract/test_found_005_observability.py`
- `tests/contract/test_found_006a_metrics.py`
- `tests/contract/test_found_006b_tracing_cost.py`
- `tests/contract/test_found_007a_constraint_regressions.py`
- `tests/contract/test_found_007a_openapi.py`
- `tests/contract/test_found_007b_envelope_regressions.py`
- `tests/contract/test_found_007b_events.py`
- `tests/contract/test_found_007b_versioned_consumers.py`
- `tests/contract/test_found_007c_agent_output.py`
- `tests/contract/test_found_007d_approval_schema.py`
- `tests/contract/test_found_007d_core_schemas.py`
- `tests/contract/test_found_007d_cross_fields.py`
- `tests/contract/test_found_007d_gate.py`
- `tests/contract/test_found_007d_observation_binding.py`
- `tests/contract/test_found_008_control_plane.py`
- `tests/contract/test_found_009_testkit_contract.py`
- `tests/contract/test_found_010_platform_contracts.py`
- `tests/contract/test_found_011_architecture_guard.py`
- `tests/contract/test_found_012a_ci.py`
- `tests/contract/test_found_012b_supply_chain.py`
- `tests/contract/test_found_013_registry.py`
- `tests/contract/test_geo_content_002_contract.py`
- `tests/contract/test_geo_content_003_contract.py`
- `tests/contract/test_geo_region_001_contract.py`
- `tests/contract/test_geo_region_002_contract.py`
- `tests/contract/test_geo_region_002_migration_contract.py`
- `tests/contract/test_gov_001_migration.py`
- `tests/contract/test_gov_001_scope.py`
- `tests/contract/test_gov_002_release_levels.py`
- `tests/contract/test_gov_003_raci.py`
- `tests/contract/test_gov_004_risk_policy.py`
- `tests/contract/test_gov_005_policy_card.py`
- `tests/contract/test_gov_006_tech_stack.py`
- `tests/contract/test_gov_007_data_processing.py`
- `tests/contract/test_gov_008_operational_targets.py`
- `tests/contract/test_gov_009_account_dependency.py`
- `tests/contract/test_gov_010_vendor_inventory.py`
- `tests/contract/test_media_001_contract.py`
- `tests/contract/test_media_002_contract.py`
- `tests/contract/test_media_003a_contract.py`
- `tests/contract/test_media_003b_contract.py`
- `tests/contract/test_media_003c_contract.py`
- `tests/contract/test_media_003c_postgres_sql.py`
- `tests/contract/test_media_004a_contract.py`
- `tests/contract/test_media_004a_postgres_sql.py`
- `tests/contract/test_media_004b_contract.py`
- `tests/contract/test_media_005a_contract.py`
- `tests/contract/test_media_005b_contract.py`
- `tests/contract/test_media_006_contract.py`
- `tests/contract/test_oauth_contracts.py`
- `tests/contract/test_site_004_contract.py`
- `tests/contract/test_support_contracts.py`
- `tests/contract/test_v3_completion_evidence.py`
- `tests/contract/test_v3_task_precision.py`
- `tests/integration/conftest.py`
- `tests/integration/test_account_connection_models.py`
- `tests/integration/test_agent_core_005b_research.py`
- `tests/integration/test_agent_core_005c_rights_provenance.py`
- `tests/integration/test_agent_core_005d_transform.py`
- `tests/integration/test_agent_core_005e_qa.py`
- `tests/integration/test_analytics_001_migration.py`
- `tests/integration/test_analytics_002_migration.py`
- `tests/integration/test_analytics_003_migration.py`
- `tests/integration/test_analytics_004_migration.py`
- `tests/integration/test_audit_persistence.py`
- `tests/integration/test_canonical_content_api.py`
- `tests/integration/test_console_startup.py`
- `tests/integration/test_deletion_persistence.py`
- `tests/integration/test_dist_010_fake_workflow.py`
- `tests/integration/test_dist_011_webhook_ingress.py`
- `tests/integration/test_eval_001_offline_gateway.py`
- `tests/integration/test_feedback_core_002_recommendation.py`
- `tests/integration/test_feedback_core_003_migration.py`
- `tests/integration/test_feedback_core_004_migration.py`
- `tests/integration/test_feedback_core_005_migration.py`
- `tests/integration/test_feedback_exp_001_migration.py`
- `tests/integration/test_found_003a_connection_fixture.py`
- `tests/integration/test_found_003b_fake_storage.py`
- `tests/integration/test_found_003d_polling_config.py`
- `tests/integration/test_found_004b_outbox_integration.py`
- `tests/integration/test_found_004c_task_claim_integration.py`
- `tests/integration/test_found_004d_failure_retry_integration.py`
- `tests/integration/test_found_004e_replay_integration.py`
- `tests/integration/test_found_005_observability_integration.py`
- `tests/integration/test_found_006a_metrics_integration.py`
- `tests/integration/test_found_006b_tracing_cost_integration.py`
- `tests/integration/test_found_007a_openapi_integration.py`
- `tests/integration/test_found_007b_events_integration.py`
- `tests/integration/test_found_008_control_plane_integration.py`
- `tests/integration/test_found_009_fixture_storage.py`
- `tests/integration/test_foundation_bootstrap.py`
- `tests/integration/test_foundation_failure_facade.py`
- `tests/integration/test_foundation_worker_runtime.py`
- `tests/integration/test_geo_content_001.py`
- `tests/integration/test_geo_content_002.py`
- `tests/integration/test_geo_content_003.py`
- `tests/integration/test_geo_region_001.py`
- `tests/integration/test_geo_region_002_migration.py`
- `tests/integration/test_geo_region_002_site_render.py`
- `tests/integration/test_iam_core_001_api.py`
- `tests/integration/test_knowledge_api.py`
- `tests/integration/test_knowledge_core_api.py`
- `tests/integration/test_local_draft_api.py`
- `tests/integration/test_local_recovery_drill.py`
- `tests/integration/test_media_001.py`
- `tests/integration/test_media_001_migration.py`
- `tests/integration/test_media_002.py`
- `tests/integration/test_media_002_migration.py`
- `tests/integration/test_media_003a.py`
- `tests/integration/test_media_003a_migration.py`
- `tests/integration/test_media_003b.py`
- `tests/integration/test_media_003b_migration.py`
- `tests/integration/test_media_003c.py`
- `tests/integration/test_media_003c_migration.py`
- `tests/integration/test_media_004a.py`
- `tests/integration/test_media_004a_migration.py`
- `tests/integration/test_media_004b.py`
- `tests/integration/test_media_004b_migration.py`
- `tests/integration/test_media_005a_migration.py`
- `tests/integration/test_media_005b_migration.py`
- `tests/integration/test_media_006_migration.py`
- `tests/integration/test_model_001_optional_provider.py`
- `tests/integration/test_provenance.py`
- `tests/integration/test_rights_api.py`
- `tests/integration/test_rights_guard_api.py`
- `tests/integration/test_site_001.py`
- `tests/integration/test_site_002.py`
- `tests/integration/test_site_003.py`
- `tests/integration/test_site_004_migration.py`
- `tests/integration/test_site_004_quality.py`
- `tests/integration/test_sup_001_migration.py`
- `tests/integration/test_sup_002_migration.py`
- `tests/integration/test_topic_brief.py`
- `tests/integration/test_topic_calendar.py`
- `tests/integration/test_topic_opportunity.py`
- `tests/integration/test_topic_signal_import.py`
- `tests/integration/test_topic_state_machine.py`
- `tests/integration/test_topic_taxonomy_persistence.py`
- `tests/integration/test_variant_draft.py`
- `tests/integration/test_variant_store.py`
- `tests/integration/test_workflow_core_002_api.py`
- `tests/integration/test_xhs_browser_preparation.py`
- `tests/integration/test_xhs_inbox_navigation.py`
- `tests/integration/test_xhs_inbox_operator.py`
- `tests/integration/test_xhs_launch_status.py`
- `tests/integration/test_zpproxy_responses.py`
- `tests/unit/agent/test_ledger.py`
- `tests/unit/agent/test_planner.py`
- `tests/unit/agent/test_qa.py`
- `tests/unit/agent/test_registry.py`
- `tests/unit/agent/test_research.py`
- `tests/unit/agent/test_rights_provenance.py`
- `tests/unit/agent/test_runner.py`
- `tests/unit/agent/test_tools.py`
- `tests/unit/agent/test_transform.py`
- `tests/unit/analytics/test_geo_quality_service.py`
- `tests/unit/analytics/test_kpi_service.py`
- `tests/unit/analytics/test_metric_definition_service.py`
- `tests/unit/analytics/test_observation_service.py`
- `tests/unit/approval/test_service.py`
- `tests/unit/audit/test_deletion.py`
- `tests/unit/audit/test_recovery.py`
- `tests/unit/audit/test_service.py`
- `tests/unit/canonical_content/test_lineage.py`
- `tests/unit/canonical_content/test_service.py`
- `tests/unit/distribution/test_deadletter.py`
- `tests/unit/distribution/test_fake.py`
- `tests/unit/distribution/test_idempotency.py`
- `tests/unit/distribution/test_killswitch.py`
- `tests/unit/distribution/test_manual.py`
- `tests/unit/distribution/test_matrix.py`
- `tests/unit/distribution/test_package_storage.py`
- `tests/unit/distribution/test_ports.py`
- `tests/unit/distribution/test_reconcile.py`
- `tests/unit/distribution/test_retry.py`
- `tests/unit/distribution/test_service.py`
- `tests/unit/distribution/test_target_immutability.py`
- `tests/unit/distribution/test_vertical_slice.py`
- `tests/unit/distribution/test_webhook.py`
- `tests/unit/distribution_account/test_connections.py`
- `tests/unit/distribution_account/test_service.py`
- `tests/unit/distribution_oauth/test_service.py`
- `tests/unit/evaluation/test_service.py`
- `tests/unit/feedback/test_contracts.py`
- `tests/unit/feedback/test_experiment_service.py`
- `tests/unit/feedback/test_feedback_action.py`
- `tests/unit/feedback/test_feedback_item_service.py`
- `tests/unit/feedback/test_feedback_recommendation.py`
- `tests/unit/feedback/test_live_feedback_service.py`
- `tests/unit/feedback/test_recommendation_service.py`
- `tests/unit/geo_content/test_fixture_service.py`
- `tests/unit/geo_content/test_geo_run_service.py`
- `tests/unit/geo_content/test_rules_adversarial.py`
- `tests/unit/geo_content/test_service.py`
- `tests/unit/geo_region/test_policy.py`
- `tests/unit/geo_region/test_region_service.py`
- `tests/unit/geo_region/test_service.py`
- `tests/unit/iam/test_security.py`
- `tests/unit/iam/test_service.py`
- `tests/unit/knowledge/test_core_service.py`
- `tests/unit/knowledge/test_service.py`
- `tests/unit/knowledge_site/test_site_page.py`
- `tests/unit/knowledge_site/test_site_quality.py`
- `tests/unit/knowledge_site/test_site_render.py`
- `tests/unit/knowledge_site/test_site_structured_data.py`
- `tests/unit/langchain/test_compatibility.py`
- `tests/unit/langchain/test_ports.py`
- `tests/unit/media/test_media_asset_lineage_service.py`
- `tests/unit/media/test_media_content_qa_service.py`
- `tests/unit/media/test_media_output_spec_service.py`
- `tests/unit/media/test_media_qa_service.py`
- `tests/unit/media/test_media_render_retry_service.py`
- `tests/unit/media/test_media_render_service.py`
- `tests/unit/media/test_media_script_service.py`
- `tests/unit/media/test_media_storyboard_service.py`
- `tests/unit/media/test_media_subtitle_service.py`
- `tests/unit/media/test_media_visual_asset_service.py`
- `tests/unit/model_gateway/test_approved_provider.py`
- `tests/unit/model_gateway/test_budget.py`
- `tests/unit/model_gateway/test_gateway.py`
- `tests/unit/model_gateway/test_service.py`
- `tests/unit/orchestration/test_content_graph.py`
- `tests/unit/orchestration/test_langgraph_adapter.py`
- `tests/unit/orchestration/test_ports_and_replay.py`
- `tests/unit/orchestration/test_production_boundaries.py`
- `tests/unit/orchestration/test_runtime.py`
- `tests/unit/orchestration/test_state_lint.py`
- `tests/unit/orchestration/test_task_feedback_topology.py`
- `tests/unit/platform_adapter/test_fake_official_server.py`
- `tests/unit/policy/test_expiry.py`
- `tests/unit/policy/test_gate.py`
- `tests/unit/production/test_region_rules.py`
- `tests/unit/production/test_terminology.py`
- `tests/unit/production/test_variant_draft.py`
- `tests/unit/provenance/test_rights.py`
- `tests/unit/provenance/test_rights_guard.py`
- `tests/unit/provenance/test_source.py`
- `tests/unit/qa/test_advanced.py`
- `tests/unit/qa/test_sandbox.py`
- `tests/unit/qa/test_service.py`
- `tests/unit/scheduler/test_service.py`
- `tests/unit/support/test_inbox_service.py`
- `tests/unit/test_console_provider.py`
- `tests/unit/test_found_009_testkit.py`
- `tests/unit/test_found_010_platform_registry.py`
- `tests/unit/test_local_demo_generator.py`
- `tests/unit/test_local_reply_generator.py`
- `tests/unit/test_platform_routing.py`
- `tests/unit/topic/test_brief.py`
- `tests/unit/topic/test_calendar.py`
- `tests/unit/topic/test_opportunity.py`
- `tests/unit/topic/test_service.py`
- `tests/unit/topic/test_signal_import.py`
- `tests/unit/topic/test_state_machine.py`
- `tests/unit/workflow/test_dispatcher.py`
- `tests/unit/workflow/test_service.py`

## Uncommitted changes

- ` M docs/repo-inventory.md`

## Repository classification

Classification: `runtime-implementation-detected`.

Formal runtime source was detected under apps/modules/services/src:
- `apps/__init__.py`
- `apps/api/__init__.py`
- `apps/api/__main__.py`
- `apps/api/main.py`
- `apps/knowledge-site/scripts/site_page.py`
- `apps/knowledge-site/scripts/site_quality.py`
- `apps/knowledge-site/scripts/site_render.py`
- `apps/knowledge-site/scripts/site_structured_data.py`
- `apps/scheduler/__init__.py`
- `apps/scheduler/__main__.py`
- `apps/scheduler/main.py`
- `apps/scheduler/service.py`
- `apps/worker/__init__.py`
- `apps/worker/__main__.py`
- `apps/worker/main.py`
- `apps/worker/runtime.py`
- `modules/agent/__init__.py`
- `modules/agent/ledger.py`
- `modules/agent/planner.py`
- `modules/agent/qa.py`
- `modules/agent/registry.py`
- `modules/agent/research.py`
- `modules/agent/rights_provenance.py`
- `modules/agent/runner.py`
- `modules/agent/tools.py`
- `modules/agent/transform.py`
- `modules/analytics/__init__.py`
- `modules/analytics/catalog.py`
- `modules/analytics/geo_quality.py`
- `modules/analytics/kpi.py`
- `modules/analytics/observation.py`
- `modules/analytics/service.py`
- `modules/approval/__init__.py`
- `modules/approval/service.py`
- `modules/audit/__init__.py`
- `modules/audit/deletion.py`
- `modules/audit/infrastructure/audit_schema.py`
- `modules/audit/infrastructure/deletion_schema.py`
- `modules/audit/infrastructure/local_recovery.py`
- `modules/audit/recovery.py`
- `modules/audit/service.py`
- `modules/canonical_content/__init__.py`
- `modules/canonical_content/infrastructure/canonical_schema.py`
- `modules/canonical_content/lineage.py`
- `modules/canonical_content/service.py`
- `modules/distribution/__init__.py`
- `modules/distribution/account/__init__.py`
- `modules/distribution/account/service.py`
- `modules/distribution/deadletter.py`
- `modules/distribution/fake.py`
- `modules/distribution/fake_workflow.py`
- `modules/distribution/idempotency.py`
- `modules/distribution/killswitch.py`
- `modules/distribution/manual.py`
- `modules/distribution/matrix.py`
- `modules/distribution/oauth/__init__.py`
- `modules/distribution/oauth/service.py`
- `modules/distribution/package_storage.py`
- `modules/distribution/ports.py`
- `modules/distribution/reconcile.py`
- `modules/distribution/retry.py`
- `modules/distribution/service.py`
- `modules/distribution/vertical.py`
- `modules/distribution/webhook.py`
- `modules/feedback/__init__.py`
- `modules/feedback/core/__init__.py`
- `modules/feedback/core/contracts.py`
- `modules/feedback/core/feedback_action.py`
- `modules/feedback/core/feedback_item.py`
- `modules/feedback/core/feedback_recommendation.py`
- `modules/feedback/core/service.py`
- `modules/feedback/exp/__init__.py`
- `modules/feedback/exp/service.py`
- `modules/feedback/live/__init__.py`
- `modules/feedback/live/ports.py`
- `modules/feedback/live/service.py`
- `modules/geo_content/__init__.py`
- `modules/geo_content/fixtures.py`
- `modules/geo_content/runs.py`
- `modules/geo_content/sampling.py`
- `modules/geo_content/service.py`
- `modules/geo_region/__init__.py`
- `modules/geo_region/policy.py`
- `modules/geo_region/service.py`
- `modules/iam/__init__.py`
- `modules/iam/application/__init__.py`
- `modules/iam/application/service.py`
- `modules/iam/domain/__init__.py`
- `modules/iam/domain/models.py`
- `modules/knowledge/__init__.py`
- `modules/knowledge/core_service.py`
- `modules/knowledge/infrastructure/knowledge_schema.py`
- `modules/knowledge/service.py`
- `modules/media/__init__.py`
- `modules/media/local_demo_generator.py`
- `modules/media/media_asset_lineage_service.py`
- `modules/media/media_content_qa_service.py`
- `modules/media/media_qa_service.py`
- `modules/media/output_spec_service.py`
- `modules/media/render_retry_service.py`
- `modules/media/render_service.py`
- `modules/media/script_service.py`
- `modules/media/storyboard_service.py`
- `modules/media/subtitle_service.py`
- `modules/media/visual_asset_service.py`
- `modules/model_gateway/__init__.py`
- `modules/model_gateway/approved_provider.py`
- `modules/model_gateway/budget.py`
- `modules/model_gateway/console_provider.py`
- `modules/model_gateway/service.py`
- `modules/platforms/__init__.py`
- `modules/platforms/routing.py`
- `modules/policy/__init__.py`
- `modules/policy/expiry.py`
- `modules/policy/gate.py`
- `modules/production/__init__.py`
- `modules/production/infrastructure/__init__.py`
- `modules/production/infrastructure/variant_schema.py`
- `modules/production/region_rules.py`
- `modules/production/service.py`
- `modules/production/terminology.py`
- `modules/production/variant_store.py`
- `modules/provenance/__init__.py`
- `modules/provenance/guard.py`
- `modules/provenance/infrastructure/rights_guard_schema.py`
- `modules/provenance/infrastructure/rights_schema.py`
- `modules/provenance/infrastructure/source_schema.py`
- `modules/provenance/rights.py`
- `modules/provenance/source.py`
- `modules/qa/__init__.py`
- `modules/qa/advanced.py`
- `modules/qa/sandbox.py`
- `modules/qa/service.py`
- `modules/support/__init__.py`
- `modules/support/local_reply_generator.py`
- `modules/support/service.py`
- `modules/topic/__init__.py`
- `modules/topic/brief.py`
- `modules/topic/calendar.py`
- `modules/topic/infrastructure/brief_schema.py`
- `modules/topic/infrastructure/calendar_schema.py`
- `modules/topic/infrastructure/opportunity_schema.py`
- `modules/topic/infrastructure/signal_schema.py`
- `modules/topic/infrastructure/taxonomy_schema.py`
- `modules/topic/opportunity.py`
- `modules/topic/service.py`
- `modules/topic/signal.py`
- `modules/workflow/__init__.py`
- `modules/workflow/dispatcher.py`
- `modules/workflow/service.py`

## Compatibility strategy

- Continue from the frozen modular-monolith and LangGraph/LangChain boundaries in ADR-001.
- Extend existing contracts and migrations with new versions; do not replace or rewrite accepted baselines.
- Preserve current checks, tests, task IDs, synthetic-only policy, and account-free delivery constraints.
- Treat any later runtime implementation as existing user work and integrate through declared ports and module boundaries.

## Do-not-overwrite paths

- `AI跨境技术内容自动化工作流开发清单*.md` — human plan and task ordering.
- `docs/adr/`, `docs/governance/`, `docs/task-registry.yaml`, `docs/tasks/` — accepted decisions and task state.
- `packages/contracts/` — machine-readable contracts; changes require compatible versions and tests.
- `packages/db/migrations/versions/` — append-only versioned migrations; never rewrite accepted revisions.
- `adapters/platforms/`, `deploy/environments/prod/`, `secrets/`, `**/*.pem`, `**/*secret*.json`, `**/*token*.json` — forbidden for FOUND-000.

## Scanned files

| Path | Size | Content evidence |
|---|---:|---|
| `.ci-artifacts/artifact-attestation.json` | 260 | `sha256:40606eeb38033564e4ed3a3c7db3ea569b438ab5dda1f61d1291d87a24329afd` |
| `.ci-artifacts/sbom.cdx.json` | 2978 | `sha256:efd8dbb0be0a3b93a15918a28a4f201c2ef7eb1876f6b5e9b44cf7f6ef39ac5e` |
| `.ci-artifacts/scan-report.json` | 139 | `sha256:d373626b817f57596ce45f22812a5eadcf0eaed18c038757e65b52c9ea1dbe58` |
| `.github/workflows/ci.yml` | 3260 | `sha256:e6ce38893058a70b9c57f96f42ac63ab8ec3de3f0fad709bf93647d858f0e707` |
| `.gitignore` | 115 | `sha256:1cb21f51d97101ec35fa1a6fda33ba21da12a336ed6e3967ba894d683a1d1726` |
| `AI跨境技术内容自动化工作流开发清单_LangGraph_V3.md` | 16550 | `sha256:69b0456e3ddb232b6a4ce4f33cf8505b791b390c9a9fbffc1a9516c632d0e59c` |
| `AI跨境技术内容自动化工作流开发清单_审计与优化版.md` | 178643 | `sha256:779643afe11e18fc62beae09576f2df517675349a02b78129ec42aecfdf7ed87` |
| `CODEOWNERS` | 514 | `sha256:152da1963e31d07517b9c4cafaa9b8b497111d7c9df309345a96f9c63e7c0052` |
| `CONTRIBUTING.md` | 2036 | `sha256:0621ce2d1d50a30c19d34d3ebf62b763ca80abe0dcaf4d348998b98d8a265469` |
| `README.md` | 4447 | `sha256:365d045ac7eb520ffd43ffba70aaa2f235ec7fc495a10e74fc988badf64520b6` |
| `adapters/contract/README.md` | 275 | `sha256:4ff153566dfec036aa7e80ee022c5c4ac7e0581b30cb93bffadf877940a3d27c` |
| `adapters/fake/README.md` | 283 | `sha256:ba31e050c12680d184143138f37e6095db03bef747afb09483d946f3e39c5ab3` |
| `adapters/fake/__init__.py` | 181 | `sha256:700998fe8f70d81fee803803aac25cd0b3b325b390f237056325331fd826364c` |
| `adapters/fake/official_server.py` | 13806 | `sha256:c5441c384b29dc36bf5b5893b24232007b45b382e183f9accb044e95d724ca91` |
| `adapters/manual/README.md` | 273 | `sha256:d59bef0fc5f4a9cc268df05437b9ce4ee8f4242ecca67fee326bb5e4e7b87195` |
| `adapters/xiaohongshu/__init__.py` | 75 | `sha256:bf99d42faa7c125384db75b10d0f90c78a4f212c45b18eb9df7d94f0aee7f39c` |
| `adapters/xiaohongshu/browser.py` | 6263 | `sha256:be18963a5eb9ebfa7ac18d07763743f676cbe69e2c21d5cfa809816b075ca959` |
| `adapters/xiaohongshu/inbox.py` | 4852 | `sha256:5b02f9726903f6cdcf3dc87ce294924d1f456394dafb1c1acf4ac8419fa0c1ef` |
| `adapters/xiaohongshu/operator.py` | 9420 | `sha256:7c5c60ad52bdf0ab8b7a92f811d1e12055ecdc9fa4fb8175e767cf0ea35dd242` |
| `adapters/xiaohongshu/session.py` | 4744 | `sha256:843613cc75419c400c78b9c0c749afb4ba66a19e58c9e85c8235098951ed7a93` |
| `alembic.ini` | 576 | `sha256:43cb71b556fae313d03aea59033aab50e46b03d00c5e6857bfd90a920b508247` |
| `apps/__init__.py` | 62 | `sha256:1cdc47f24c4d8980cd92e816bb63a156ef30cad06aa12d1af84d407bb740c579` |
| `apps/api/README.md` | 446 | `sha256:00ee4c3fb0d3bdf46ad5086e7ebd73e9b2da477d860283c09b90cbfb92c0ba51` |
| `apps/api/__init__.py` | 32 | `sha256:28c766504a198d3c17832b792c4924608f4a4fda643c7c3a22f440390f761ba5` |
| `apps/api/__main__.py` | 161 | `sha256:bae5b4c98263891c73bb5a0ac56635e07eab1321074660c1b1b94dcfffb55ffc` |
| `apps/api/main.py` | 111619 | `sha256:e1b4a33f2671652d683882b1a0ea3700e6ae6954a464bac18f5e18489a48b1aa` |
| `apps/knowledge-site/README.md` | 2283 | `sha256:4b2c9d85f876a568737f6a8348461f7ced28bf747c9797aec7aa30c44d8b6a60` |
| `apps/knowledge-site/package.json` | 170 | `sha256:32d859006b73671808cad8fd910f1db1532d65e8b5a9fd6e1f13f07d0f960238` |
| `apps/knowledge-site/pnpm-lock.yaml` | 114 | `sha256:17c814b167307942d3609c7b9d916ceddb85839573ab39baa114e30edb132a1a` |
| `apps/knowledge-site/scripts/build.mjs` | 860 | `sha256:735c2a8c08f435a9cb4f16ef081542c0977a3d2e09549a1ee3c557ba22ccd65a` |
| `apps/knowledge-site/scripts/site_page.py` | 31190 | `sha256:54ea3bf84fc6d6c9bcf7b12e3f93ed44ddfd44827e0f60f12aa77a2d9cc41ca6` |
| `apps/knowledge-site/scripts/site_quality.py` | 50486 | `sha256:c3aeec17e3a0c2b357f943a5fa0a11a8b6d3736098ed8fd5d6b2996a54b5bb78` |
| `apps/knowledge-site/scripts/site_render.py` | 48064 | `sha256:fd8f65b7c510b1ef16dc22519fdfa66699d7f60f122bbae18bb7c72b949c223b` |
| `apps/knowledge-site/scripts/site_structured_data.py` | 32831 | `sha256:edc2874ece017df2be2a4d2505c0bde7975be9597e55ee0fbb6ba0e7108311a4` |
| `apps/knowledge-site/src/index.html` | 412 | `sha256:75b0e83fe627a49371d8050db18bcadeb76c67d93b963be5ac39d91fc06639f0` |
| `apps/scheduler/README.md` | 337 | `sha256:35a8a2eabef86bbeedf774dc76938e140a81457fd28fce3ec40534441ca7ebe7` |
| `apps/scheduler/__init__.py` | 215 | `sha256:255f64be0f69b8e38854eb1927317e0acbcd4a3c7bfc378f710b99352d34714b` |
| `apps/scheduler/__main__.py` | 81 | `sha256:954eaddc192523ee47f44769ae571e58baf451c0e67d752edd3874b6393600d0` |
| `apps/scheduler/main.py` | 1397 | `sha256:6698cebfe15b06e90e8fb9143eb61c82783f2bb75c3b532fb82d78a0e9fe0235` |
| `apps/scheduler/service.py` | 13686 | `sha256:695f51c7d8571bcfd708a23679f747c01b64d25041bd174b5787beafeee3d8c3` |
| `apps/web-console/.gitignore` | 32 | `sha256:825137c1d763dfd1e1dd53a262dc3f598788391360823d14be0e5d3fde87871c` |
| `apps/web-console/.openai/hosting.json` | 106 | `sha256:4c4a860d7dfe034e7b89c01cde829b5b2f4f430ce991963e03682aed3c255839` |
| `apps/web-console/README.md` | 379 | `sha256:a34c9005c8272c85ffa90e5f0100ca754d18f5ef19eea0c72337a4642a609e04` |
| `apps/web-console/package.json` | 167 | `sha256:9b5d3d2153ac4164c691902f80b75a3911a4be54f82b3579b9f6f39e078f3066` |
| `apps/web-console/pnpm-lock.yaml` | 114 | `sha256:17c814b167307942d3609c7b9d916ceddb85839573ab39baa114e30edb132a1a` |
| `apps/web-console/scripts/build.mjs` | 851 | `sha256:eae2a2b621e5162dde56ffc02b716fc21c71146456cb69cf7bfdd23727030609` |
| `apps/web-console/src/index.html` | 93612 | `sha256:f8d71f7d466dd0fa69c9bc76a4d8cd90884a5d3d0c63b4b8fabbe8b3b94f83f7` |
| `apps/worker/README.md` | 843 | `sha256:585eb3815e3271923e72d2c66325ce36be5af3c66135774cb734008315742021` |
| `apps/worker/__init__.py` | 31 | `sha256:53da4abf7d557e2589aa76efd85c921469f44127a4035ec9f6c2f6361484ee76` |
| `apps/worker/__main__.py` | 81 | `sha256:954eaddc192523ee47f44769ae571e58baf451c0e67d752edd3874b6393600d0` |
| `apps/worker/main.py` | 2775 | `sha256:f596466c5db912331cca5fd1da0311c8ee2b51723df3b1e4dbd84903e927db40` |
| `apps/worker/runtime.py` | 12822 | `sha256:45c00ca8c7932ae64c88f3d6e2b67638ebc9995a85af15ff8eb77644d9a99fa5` |
| `ci/tooling.lock` | 146 | `sha256:da351a667e980b99e2db75222fba85219e1586b5eead3632c157654b57118a4c` |
| `deploy/environments/dev/README.md` | 426 | `sha256:ddc7937f7e1ebac0e109e5dd7baabe0eb7434e7a705e8804e4c6c18320ba6d09` |
| `deploy/environments/dev/database.env.example` | 231 | `sha256:d33e702880ebb9eec8d8dabd0d3bfd982be989f6744cc1816cbb5481e6bcdf9b` |
| `deploy/environments/dev/storage.env.example` | 288 | `sha256:34db95442e0cf520c8f3db39943bb254c33d5d83d86af7c878977b67e40d38bf` |
| `deploy/environments/dev/task-queue.env.example` | 163 | `sha256:72d9e4fe9d75e3e89b49327bbb643cec7432953b40d98d2e48238a83839ad950` |
| `deploy/environments/staging/README.md` | 407 | `sha256:2bbfffc6e5652c93d44e5f2da45e30b12eabd110aeefc609b311b55e2678a66c` |
| `deploy/environments/staging/database.env.example` | 254 | `sha256:6b4c64bc1d209175fb50724152a54aae0df637fb5b0ad1eb43f737e2a1a91397` |
| `deploy/environments/staging/storage.env.example` | 188 | `sha256:04de4558880ba2234b3f050627b84cc6ac991e4066dd63b64caf441bb1e5051c` |
| `deploy/environments/staging/task-queue.env.example` | 175 | `sha256:933642584aca496a0581c1ea5ad68dc97c9de1f773b3aede6854ecf3d01840ce` |
| `docs/BUILD_MANIFEST.md` | 4236 | `sha256:9a414fe37ef954d23a740d76a0f94847d74d8349b865e29bcce3fba6ee0ad9a0` |
| `docs/CODEX_EXECUTION_PROTOCOL.md` | 6435 | `sha256:8d474673d198f1184dcd43685eebbeb6525da8d08539f753b4fbc36506935c88` |
| `docs/CODEX_START_PROMPT.md` | 3364 | `sha256:d16774413884baab4c632f3403290e2c94a18100bcb9a8e61e539f1873ef749f` |
| `docs/START_HERE.md` | 4326 | `sha256:4c58840d7d30b71869b76b028f89928e6a676315a242ccd72d5c7e4693149feb` |
| `docs/adr/ADR-001-langchain-langgraph-architecture.md` | 7117 | `sha256:6bcf17ea46d7d2cd484daaa18dca95b40f4801fca984b32171e49fb0fc8212bb` |
| `docs/adr/ADR-002-live-feedback-observation-port.md` | 1619 | `sha256:e69703200f1c96d80389f30ce1860904c3e60dd44a11457a55cbba130facb035` |
| `docs/audits/contract-gap-audit.md` | 5408 | `sha256:459bdaccc9b30e1bc261071c2339dea55cc1e184496fc31b9fac35d535e923ed` |
| `docs/audits/foundation-overall-audit-2026-09-16.md` | 4673 | `sha256:56c57a8e8b88a822bd92caa160ae25a9218cb830eea78fe43012f5531f50648c` |
| `docs/audits/v2.4-readiness-audit.md` | 8467 | `sha256:b6b55062aeb76aec161e953aee93a3895f3de7a093667de704ffdad05459eb3c` |
| `docs/contracts/analytics-event-catalog-v1.yaml` | 3824 | `sha256:b2d88dd46cca297df1c20e379da4a6796ba338463fbd3d607e4ba9140d480775` |
| `docs/contracts/contract-manifest.yaml` | 95060 | `sha256:06c25bd4de27b1e99d6f551d9a7e31cca576b00abe4de3f7512f80fa279f50bd` |
| `docs/contracts/event-registry.yaml` | 74324 | `sha256:6b41c5bc25869e6e24504c78a4cb684d65eac649993714b55a11e6e02456bb20` |
| `docs/contracts/migration-manifest.yaml` | 75595 | `sha256:27024feee1e689b54a000b21a0679d06cb2e76b66805fc267260e09a3d8703c3` |
| `docs/contracts/state-registry.yaml` | 36536 | `sha256:23ed22eeec5acaf98306fdaba94a868f1fbe4296799034152fc80785b7a2cbb2` |
| `docs/external-dependencies.yaml` | 1594 | `sha256:6b5093923f164dee704973cf991c855d284e76c708d4f744e66fa6e139052c00` |
| `docs/foundation/ACCOUNT-CORE-001-EVIDENCE.yaml` | 656 | `sha256:1e92b84f60f17260811f788203d46644272d27d8b7b3bc9233a5191291ffc8c3` |
| `docs/foundation/ACCOUNT-OAUTH-IMPLEMENTATION-READINESS.yaml` | 3284 | `sha256:7b1f6bb72028c83ff52ea86b61f791c95a40361d1d410452558812d0ec4665ce` |
| `docs/foundation/AGENT-CORE-001-EVIDENCE.yaml` | 597 | `sha256:e2c26237ac23c0a2e8ea0d2c8e5b54661acbed39e0ffa9a47e95cf143d460980` |
| `docs/foundation/AGENT-CORE-002-EVIDENCE.yaml` | 642 | `sha256:4cd39e0ba220302ed52388bab68841473ef0bad893a89f1ea850be9d668ea0b2` |
| `docs/foundation/AGENT-CORE-003-EVIDENCE.yaml` | 597 | `sha256:2057466d860364c8742857c008819b902d7591b15a24690eb444b779d8129034` |
| `docs/foundation/AGENT-CORE-004-EVIDENCE.yaml` | 573 | `sha256:c032595684608e04c23339d4b97af685b816e8eb01b825a73a399885e3ff7390` |
| `docs/foundation/AGENT-CORE-005A-EVIDENCE.yaml` | 1570 | `sha256:201689f64174eee1cc4b49e80731656f0b11552571ca88f12fb0ab9ecb460b16` |
| `docs/foundation/AGENT-CORE-005B-EVIDENCE.yaml` | 1647 | `sha256:29a82229156d7af0047d2cd39778669300a04bcdc52ce050713e08c381498752` |
| `docs/foundation/AGENT-CORE-005C-EVIDENCE.yaml` | 1814 | `sha256:718d617f2978824ee3e1ac8e6956924694d7885ec9c8f531140761e7e96ac34d` |
| `docs/foundation/AGENT-CORE-005D-EVIDENCE.yaml` | 1790 | `sha256:2afa9676be0e273221b913b672576ef9bb359c63cc80724603b3cdb99e57e060` |
| `docs/foundation/AGENT-CORE-005E-EVIDENCE.yaml` | 1714 | `sha256:a898b9af1b678d272c7cea9e55ad462689fa13c1c7b0bbe47f2d567547f2154d` |
| `docs/foundation/ANALYTICS-001-EVIDENCE.yaml` | 2518 | `sha256:c86bea4c9aaa7fc0a104b4db9d2f5984f7279449d71396f6067b895cf4de7654` |
| `docs/foundation/ANALYTICS-002-EVIDENCE.yaml` | 2417 | `sha256:deb1e1a62e68c2809ac2bf434034274b5d25fc8c09541dbd61708b1d024a24f7` |
| `docs/foundation/ANALYTICS-003-EVIDENCE.yaml` | 1953 | `sha256:7416ec55c5269a23ee87e97f67135a65386b37fd101c724c39803305d3a3e623` |
| `docs/foundation/ANALYTICS-004-EVIDENCE.yaml` | 1769 | `sha256:af3b84679653864c1f45ce1412f25411b30bc5ab8b6957a8d64105345cbf5ea6` |
| `docs/foundation/APPROVAL-001-EVIDENCE.yaml` | 1478 | `sha256:c1ebec0690fb91e8b780eb611fe438528f076d1f26061e0cfd29ef4cea7430e4` |
| `docs/foundation/APPROVAL-002-EVIDENCE.yaml` | 1415 | `sha256:7e5bf11d1de7a5433f90a2ca062449a27afa71d7d9d9159d07708ba4c953bad3` |
| `docs/foundation/CANON-001-EVIDENCE.yaml` | 1488 | `sha256:d96649684d19a32e594d6c321dc20f9d78646fd6bbbfe6a836432a153a2dee58` |
| `docs/foundation/CANON-002-EVIDENCE.yaml` | 1223 | `sha256:8aa938757c0da4af7584dcb47dbbbf302564ae5a5a253be21a368a6684468cdd` |
| `docs/foundation/CANON-003-EVIDENCE.yaml` | 1003 | `sha256:998f33f039177af7e5ef4fe886bb31a36287dd970329a3f93d96e12536dea449` |
| `docs/foundation/CANON-004-EVIDENCE.yaml` | 1665 | `sha256:8c7bf3e6f1f44dcc054e65c5cb89f90037ab3089695729e08ff48fb3f56a6b0f` |
| `docs/foundation/CANON-005-EVIDENCE.yaml` | 1623 | `sha256:09e48c51685cbe597ce473b8823d0237604cee0c1ad118df1606c4a56536553e` |
| `docs/foundation/CANON-006-EVIDENCE.yaml` | 1557 | `sha256:d60ac1305419d3ac6a97df3bdc1a1c33c73c41ecd8acf8993c47c622858fe6be` |
| `docs/foundation/DIST-001-EVIDENCE.yaml` | 1806 | `sha256:51b75ca52634fdbc96f6f2433505e31d786fec98d69c86bfa55496d6c50f8011` |
| `docs/foundation/DIST-002-EVIDENCE.yaml` | 1393 | `sha256:757bbcc7fb30b16d881081ea041db2fe06592a2165132deec0e27cc0ea91cbd2` |
| `docs/foundation/DIST-003A-EVIDENCE.yaml` | 1419 | `sha256:444fde7b2d738b0f2f308264804b1587a3d1903b1439380c6f9c50a59c672268` |
| `docs/foundation/DIST-003B-EVIDENCE.yaml` | 1465 | `sha256:85211deaace0c3d512f42bb95d7d0d014b6bbaeb822aeb89addb7e6a80262967` |
| `docs/foundation/DIST-004-EVIDENCE.yaml` | 1510 | `sha256:06791562bf51ad4c7b9065425e90047649d9026760933f7c1f7434e73ed2c802` |
| `docs/foundation/DIST-005A-EVIDENCE.yaml` | 1400 | `sha256:999b9525ddcc11bc2ea898bc20e4495fe7ba98cccb55863247f2b398b0d29d7f` |
| `docs/foundation/DIST-005B-EVIDENCE.yaml` | 1341 | `sha256:ec03565351de8564ea9b313d2378686434d4ee6966fd5b22008c6007a4e25592` |
| `docs/foundation/DIST-006A-EVIDENCE.yaml` | 1436 | `sha256:ba0a556614c534a3f004ec1ba328adb7aabfc4b1c8a45d38bf998fce378e87f9` |
| `docs/foundation/DIST-006B-EVIDENCE.yaml` | 1438 | `sha256:35f88a3c77781fb10ac1943e0f540221a735e93653b6b6e55a74115de769d008` |
| `docs/foundation/DIST-006C-EVIDENCE.yaml` | 1606 | `sha256:1d7bdf6f83dd208d686a4e8cedc2ee9f0a48caa5b0976bdef07ff03106c19316` |
| `docs/foundation/DIST-007-EVIDENCE.yaml` | 1570 | `sha256:8375663ee749ca4a65b2c5d15b9c73f5981f9bb1f16f05d794e33e8d263f3ad2` |
| `docs/foundation/DIST-008A-EVIDENCE.yaml` | 1394 | `sha256:8ec2d3a084d365481c369b3579ee2d95ef20ecda856e663b3c4bf353e675f861` |
| `docs/foundation/DIST-008B-EVIDENCE.yaml` | 1585 | `sha256:067ce05048fbc189ba7ca0258a9b94e31a1d5569119a2fbcf4e4600fb227308b` |
| `docs/foundation/DIST-009-EVIDENCE.yaml` | 1460 | `sha256:7a9578078ebe64593d75ac8ecb7dd8ec2e5a6fb78445393ff72a22f087e95570` |
| `docs/foundation/DIST-010-EVIDENCE.yaml` | 1726 | `sha256:6a3da7a08b3d49bcc75ab4c562dd16cc6b78fe05d5b0e72a5462a25c43663e70` |
| `docs/foundation/DIST-011-EVIDENCE.yaml` | 1754 | `sha256:7328d2c54da5116cb19094aed23652af64c5b718f6e0f665cd6ef16b792c86e5` |
| `docs/foundation/EVAL-001-EVIDENCE.yaml` | 1838 | `sha256:76a850368f9a66956c297f61b9da5198c1f1f170f31c34d9cd4d4f85d545ee1f` |
| `docs/foundation/FEEDBACK-CORE-001-EVIDENCE.yaml` | 636 | `sha256:5feb4039338a85917685299c8c225be15c7dc2f42360aef12b807c90ae32d1fe` |
| `docs/foundation/FEEDBACK-CORE-002-EVIDENCE.yaml` | 1874 | `sha256:d1648d7998ea54ed2e7b0ec6172390c21499b4121493c4ee8c770cf4c41d430c` |
| `docs/foundation/FEEDBACK-CORE-003-EVIDENCE.yaml` | 1108 | `sha256:aa8d131513ed9e249f54a89810931e44c28c24ada394d4fd25fb533dadce4dbe` |
| `docs/foundation/FEEDBACK-CORE-004-EVIDENCE.yaml` | 949 | `sha256:5587be75b3feefac154e511e7d1c501f8e04101e2787ab7f2ac6c56be9d16ee9` |
| `docs/foundation/FEEDBACK-CORE-005-EVIDENCE.yaml` | 1015 | `sha256:1e1135fb229a67086b674b6945145bedf225cd67018cca5ab9c14e09ac0fd391` |
| `docs/foundation/FEEDBACK-EXP-001-EVIDENCE.yaml` | 935 | `sha256:b1cb45f7245debd2a3da41a4ef7c66815f65fa49504ed0bcca05dd58c4a38da4` |
| `docs/foundation/FOUND-000-EVIDENCE.yaml` | 1849 | `sha256:80729f59f9ef60904bedd8041be9e8f158f9b6751285435f2c33172fcd54bc83` |
| `docs/foundation/FOUND-001-EVIDENCE.yaml` | 1678 | `sha256:70435cd3ce3cba5294de5aac10acc6907f32872bed3480d9292e765cbf23f6fa` |
| `docs/foundation/FOUND-002-EVIDENCE.yaml` | 2003 | `sha256:22ef5c1fd98294e82b90652769db08bbe65defaadd14fda1dee282acb5089c0b` |
| `docs/foundation/FOUND-003A-EVIDENCE.yaml` | 2407 | `sha256:a7927a37f7367428a39fb29532efdafdfaf70b0f727105df8511e79f30582d86` |
| `docs/foundation/FOUND-003B-EVIDENCE.yaml` | 3463 | `sha256:5b7ed15e053d44e7c45a53262b7b6e63cc75860ecb832e0ecfc5ce482d570a54` |
| `docs/foundation/FOUND-003C-EVIDENCE.yaml` | 721 | `sha256:e5f05595b1643b8d038660200ff6dcd34f94e694f5680497f0ad914f823c88d6` |
| `docs/foundation/FOUND-003D-EVIDENCE.yaml` | 2411 | `sha256:4cf767d165243245e862331cd3ee352a17bc95483151b356b13955967950f47c` |
| `docs/foundation/FOUND-004A-EVIDENCE.yaml` | 2444 | `sha256:58542ce8707698f986b9677783067da3432eb77658167df7b3eea357b2ab6855` |
| `docs/foundation/FOUND-004B-EVIDENCE.yaml` | 2826 | `sha256:c53fd5fbb07e142ae5d8fe6bd2a4a57689b26720907eef9e768a551e9846a0e1` |
| `docs/foundation/FOUND-004C-EVIDENCE.yaml` | 3270 | `sha256:caaed825de5d22719c14a18f8244dc60cd6fa9df61d06641eaa9947ba5bdbc72` |
| `docs/foundation/FOUND-004D-EVIDENCE.yaml` | 3893 | `sha256:2079dbd44be3b580d0c7533534bf1a477be5df57a6e1a585308b09907218bdc3` |
| `docs/foundation/FOUND-004E-EVIDENCE.yaml` | 3094 | `sha256:52af8dccf3b78d34c561701cb6c3c22c6fdf59240f99925808f525348fd041fd` |
| `docs/foundation/FOUND-005-EVIDENCE.yaml` | 3511 | `sha256:53e92ccdd067e1be6f28c4e1713f657798234342041777331f57df804eb64626` |
| `docs/foundation/FOUND-006A-EVIDENCE.yaml` | 3355 | `sha256:61836e704a01393562c4314653113836cf24d5e381269193780efe2b58ae4489` |
| `docs/foundation/FOUND-006B-EVIDENCE.yaml` | 3455 | `sha256:cfd93dfdec9d23bbd2dfa104bd7b3df9cb7c11af2774d3bf3901f41ad0ee0231` |
| `docs/foundation/FOUND-007A-EVIDENCE.yaml` | 3197 | `sha256:07b5dbf52537bf1daef94d06cf13203262ee67cbd1dfeba067e027d38902f31f` |
| `docs/foundation/FOUND-007B-EVIDENCE.yaml` | 6008 | `sha256:0a75818b40217e191da09a99be066f9c96d24449498532f6c641dcb6bd8841b2` |
| `docs/foundation/FOUND-007C-EVIDENCE.yaml` | 1245 | `sha256:7b3b1131dcc5055c8158cdf3690943c845962e1e551a47debe52b5ed710711f6` |
| `docs/foundation/FOUND-007D-EVIDENCE.yaml` | 1094 | `sha256:06eac41bf3f63004126ac665fe4f9fa309a345fbd7fc4514e572972c9032728e` |
| `docs/foundation/FOUND-007D-PROGRESS.yaml` | 1009 | `sha256:6fd680a1cbffbc87e78e41c2c0d7134f59958089bb051a1996b364c6642d31eb` |
| `docs/foundation/FOUND-008-EVIDENCE.yaml` | 2640 | `sha256:837e32080915eb910d2792d8b2b307e010bed3071929bf8b75796643a9452f81` |
| `docs/foundation/FOUND-009-EVIDENCE.yaml` | 2278 | `sha256:997ccd9bbb4ebe581bfaf35937281a72d22bc4acc2d83379dd12b7c3253452c7` |
| `docs/foundation/FOUND-010-EVIDENCE.yaml` | 1322 | `sha256:23ac2d66d02bd8570ff81b1576e5ce5202fa67de9c84fc90c7213768f3f4f209` |
| `docs/foundation/FOUND-011-EVIDENCE.yaml` | 1152 | `sha256:99603b0968fc64fde79ded98f5fa89bb8441af5809eeff4b55017360ef900063` |
| `docs/foundation/FOUND-012A-EVIDENCE.yaml` | 1117 | `sha256:36a95be72f11e0993b523e5a8aded90a5f227e0aeaef4dd9a69b3cb12894eca7` |
| `docs/foundation/FOUND-012B-EVIDENCE.yaml` | 947 | `sha256:232ad1498fdbcdf83ca38e76e7bbff0ed3c50e69229734e1dc476c3b43ddd3c6` |
| `docs/foundation/FOUND-013-EVIDENCE.yaml` | 830 | `sha256:a2e65fe16d00ac240ced29597f7845aaedb7f1e375d4377058ea181ce3b28103` |
| `docs/foundation/FOUNDATION-RECHECK-2026-09-16.yaml` | 660 | `sha256:a542eeb27ce8163c8bd051d65cf05efbf8149836517bfdf9c486df0260e52c18` |
| `docs/foundation/GEO_CONTENT-001-EVIDENCE.yaml` | 2632 | `sha256:5cd4948a294f18e48399c09500c295fe614e91440713966a82728721bcd97249` |
| `docs/foundation/GEO_CONTENT-002-EVIDENCE.yaml` | 2630 | `sha256:5727b68d55cc97d06513707bbb97dec1d1c36b26bb17d554d57d23a152617b00` |
| `docs/foundation/GEO_CONTENT-003-EVIDENCE.yaml` | 3131 | `sha256:d576bc12daf891d1abfaf77c19d9e50600b48455b2913338aaf5e4dd5a7395fb` |
| `docs/foundation/GEO_REGION-001-EVIDENCE.yaml` | 3484 | `sha256:cee94785228c144a40962f3b7895b85e195201f5232fce6bfb99ff669f7a479f` |
| `docs/foundation/GEO_REGION-002-EVIDENCE.yaml` | 3566 | `sha256:b6eed210aec759cfb2eb2dfc31694afca1ef5a3120dfd54b33f3cdbdc8959c6b` |
| `docs/foundation/GEO_REGION-CORE-001-EVIDENCE.yaml` | 642 | `sha256:ff119ac5d6b22a001c00467d7075a4af3dde142ea94e639d9b9504dd61047d59` |
| `docs/foundation/IAM-CORE-001-EVIDENCE.yaml` | 666 | `sha256:6b39437597443803555694bad122cafa0648ba9bdabe11a95e7d1215bbf97bfc` |
| `docs/foundation/KNOW-001-EVIDENCE.yaml` | 1736 | `sha256:e98b0da2f54f0a99cda808cf66da12f8f558a703494b0dc037927bd79e17203c` |
| `docs/foundation/KNOW-002-EVIDENCE.yaml` | 1584 | `sha256:f2b874f467090073d6e9b71201264ddccfd727fb03c62231fde1aa5099d509c4` |
| `docs/foundation/MEDIA-001-EVIDENCE.yaml` | 2540 | `sha256:69b9126d0453b66f56f72e7095e1fc172d9cc6846060bb14224fe4af42579238` |
| `docs/foundation/MEDIA-002-EVIDENCE.yaml` | 2621 | `sha256:7e019a2aa0dfd8ccb80fdf9fdb439a224ea11a7e03797ef939c04e8d63b5a3c6` |
| `docs/foundation/MEDIA-003A-EVIDENCE.yaml` | 2432 | `sha256:13b43c7871845a6153327172b3814ec35cd66431af2ae7899734470167304195` |
| `docs/foundation/MEDIA-003B-EVIDENCE.yaml` | 2737 | `sha256:3c767beeb5ad2343f50780c7e9acbe010b2fb22fdcbe14bfe8dd56bb4ef7ecac` |
| `docs/foundation/MEDIA-003C-EVIDENCE.yaml` | 1478 | `sha256:05e36298803735bdedf3b182c31ee066571b308867f92198c125a8a89ab7f85e` |
| `docs/foundation/MEDIA-004A-EVIDENCE.yaml` | 2447 | `sha256:0ff035bdd6352455141e7dd2f4803e3361221bfb668f4d36a19010aa7d8a2e32` |
| `docs/foundation/MEDIA-004B-EVIDENCE.yaml` | 2447 | `sha256:55c393538e730ed0ed955fbd6e2897b0f22e61a2c4059573e7d6b94fafaf4837` |
| `docs/foundation/MEDIA-005A-EVIDENCE.yaml` | 2054 | `sha256:6c17758575d86b77c8e019ef5a696cc4785443f747924778977c97698af29345` |
| `docs/foundation/MEDIA-005B-EVIDENCE.yaml` | 1937 | `sha256:68c11ae3d3e616a6358e119f79970526ae9d3b7cb1a58789e8f36a7877fcdefd` |
| `docs/foundation/MEDIA-006-EVIDENCE.yaml` | 2014 | `sha256:97b54ee8b379518e9c24387bc5efff76a793bfb58d46a0b3f607db271d1c5113` |
| `docs/foundation/MODEL-001-EVIDENCE.yaml` | 1864 | `sha256:9b7660f3ef20a4cce86a73157b262b3c632899eea7b7454ce4dfb6bced901ca8` |
| `docs/foundation/MODEL-003-EVIDENCE.yaml` | 1789 | `sha256:723b3702317f800650a024b77715b731e4ca9ee84114b4379b52672e78b88a5a` |
| `docs/foundation/MODEL-CORE-001-EVIDENCE.yaml` | 703 | `sha256:4bca941549554862b595ea063ee8731aef25ae1ea4a6337399df732e9327a0b9` |
| `docs/foundation/MODEL-CORE-002-EVIDENCE.yaml` | 709 | `sha256:35d0e11a44b8a3fff8ed22ae9ad966960932870792a2f4e9b955f3b6bd39e495` |
| `docs/foundation/OBS-CORE-001-EVIDENCE.yaml` | 955 | `sha256:ec9ae04a2e155c3e415f4994206ac8f2fd990bbfa78ac4446841940460262374` |
| `docs/foundation/OBS-CORE-002-EVIDENCE.yaml` | 804 | `sha256:d36be30b9b925a9a8217359df3e8886a38276df8212bc547faa64ade1e1de1de` |
| `docs/foundation/OBS-CORE-003-EVIDENCE.yaml` | 833 | `sha256:13a7f0b28e2177f875c924c5b75d562a07e40f4b95c4117a37b88eabab675b9c` |
| `docs/foundation/POLICY-001-EVIDENCE.yaml` | 1537 | `sha256:ec3ccce33a507c8113e52e863e01d34312f06ab0e74ed564aa2d55795d169d5d` |
| `docs/foundation/POLICY-002-EVIDENCE.yaml` | 1525 | `sha256:41c5d0fcb5fdbf7a555132989fc6a096ed21eaf963791f1e753970d1f12e6f95` |
| `docs/foundation/PROD-001-EVIDENCE.yaml` | 1250 | `sha256:4007039c7f5d2936b3e4bfd99a3ee9c1d35a66d93306bf2d877c3a389b670b20` |
| `docs/foundation/PROD-002-EVIDENCE.yaml` | 1462 | `sha256:59c201684b1a1a34f7c7c5da0744b557e1476f90c4697a9ecdcaaaeaadb36eaa` |
| `docs/foundation/PROD-003-EVIDENCE.yaml` | 1391 | `sha256:a6d14a625c3f480a4fffb47d3cc5b25886a4b10853d94bfa1e57c3f454e9e0f8` |
| `docs/foundation/PROD-004-EVIDENCE.yaml` | 1689 | `sha256:3d1e47231518079074c6c89b66a0c6ff1d117ec0b190ebe1bd7766ddab3b3ebc` |
| `docs/foundation/PROV-001-EVIDENCE.yaml` | 1361 | `sha256:b313a2106fa331d1873bdebea7edbb066addb6f47c48566cdf09332c6a2c9c46` |
| `docs/foundation/PROV-002-EVIDENCE.yaml` | 1368 | `sha256:46564b4680412158b98e07dbe7978bd2d29b4e2d5462679a524c01da0315613b` |
| `docs/foundation/PROV-003-EVIDENCE.yaml` | 1357 | `sha256:2da35925d8cefc93f5998e1db1321f92cdb12a289302239e11c1412253a6a9fe` |
| `docs/foundation/QA-001-EVIDENCE.yaml` | 1541 | `sha256:78714f10d0cf763f7e7eb2c7242b5d4b83116362f9e70a48a7080e783d8e2153` |
| `docs/foundation/QA-002-EVIDENCE.yaml` | 1545 | `sha256:8a1cbb19afc26f4b324c3285ae8b623f1922e3668d2d77ea3e85e756f352d083` |
| `docs/foundation/QA-003-EVIDENCE.yaml` | 1420 | `sha256:e82a06b6e2cb3ec4ebd750340cabe4dbe49c9d2df718bbd4965ef072b3ee054f` |
| `docs/foundation/SCHED-001-EVIDENCE.yaml` | 635 | `sha256:6222f7691622628a14819f4100b62b3bb4a690d085ae94ad72b43f32c83b1cad` |
| `docs/foundation/SITE-001-EVIDENCE.yaml` | 1719 | `sha256:e86101b67a5fffbc8e959cd34cc34aa63667da3446a5d347060368c93f6b8e22` |
| `docs/foundation/SITE-002-EVIDENCE.yaml` | 2106 | `sha256:2ddc8340fdb63a3373864d65c86244c90ebb16ad9c76361903019512daeb13f8` |
| `docs/foundation/SITE-003-EVIDENCE.yaml` | 2150 | `sha256:6470ba013d17d57e67fa4cec33ce56735c1e6806dff9cd7fcdd2afa2d91a9c48` |
| `docs/foundation/SITE-004-EVIDENCE.yaml` | 2913 | `sha256:e07decaffc15223e5ac6f8f743b25a15b5fd71089e816821aea09d8f2d8dcbbf` |
| `docs/foundation/SUP-001-EVIDENCE.yaml` | 873 | `sha256:782a5a15405414e30d38b81f74f44df9f799172c0dd45a5eb06ea924efe2801a` |
| `docs/foundation/SUP-002-EVIDENCE.yaml` | 865 | `sha256:99550fe8bf5fbdd0e2ba589e7e3bcd9d12030f54fb094b32d4448df321415b04` |
| `docs/foundation/TOPIC-001-EVIDENCE.yaml` | 765 | `sha256:886ccb7a7304519d23dc4cd4935302ebb25144f877ca7965fa57da6635498623` |
| `docs/foundation/TOPIC-002-EVIDENCE.yaml` | 1179 | `sha256:86a9087b3c7112338a99427bbacec139bd509d518f43cb77ee78fbc722038555` |
| `docs/foundation/TOPIC-003-EVIDENCE.yaml` | 1141 | `sha256:bae9cf8cbd7aef4a4b7d3bec73d7bb185be37bd2fc4edbd2d358fa764e340bfb` |
| `docs/foundation/TOPIC-004-EVIDENCE.yaml` | 995 | `sha256:8ec97f61c7bd7c27e94052823633a0bd6ea5369598a313fc7cdbb75ce3f5f308` |
| `docs/foundation/TOPIC-005-EVIDENCE.yaml` | 914 | `sha256:a36bc07c979b71838b50e43c346519fae7662eed2225323a1dc85ca4f2999bd5` |
| `docs/foundation/TOPIC-006-EVIDENCE.yaml` | 961 | `sha256:67bbf2e9d7e23f35f4f2b8264fd9f498f7b5508cc4efe8f541b6753b588a7ada` |
| `docs/foundation/TOPIC-007-EVIDENCE.yaml` | 977 | `sha256:dc6ab1f21aa160b7d7a5b821b867c8bc6ba499bd3a2fd041642966fca73c1b61` |
| `docs/foundation/TOPIC-008-EVIDENCE.yaml` | 1091 | `sha256:e05c94245589c720572d86cf0a5002eb1d76289206334e491be9cb2e5ed10734` |
| `docs/foundation/V3-ORCHESTRATION-EVIDENCE.yaml` | 5669 | `sha256:ed34cfe52b79f27e6ede309988679ad52b6a1e0641c03c6dd076a3648c2ba81b` |
| `docs/foundation/V3-ORCHESTRATION-READINESS.yaml` | 2859 | `sha256:ebb48c75a03066c711c070461efec497b6393ecbe8b2a2f8f9d6f337b7223cf0` |
| `docs/foundation/WORKER-COMPOSITION-AUDIT-2026-09-18.yaml` | 1886 | `sha256:7918a2e5735bd53d2210cdedb4d2b4d05c648e947f3dc9d04c658df7cc23fe40` |
| `docs/foundation/WORKFLOW-CORE-001-EVIDENCE.yaml` | 654 | `sha256:d7972abcaaed67d1ccb8e5f2dd1b192db0eb797d4e09860138c4630c52665dc9` |
| `docs/foundation/WORKFLOW-CORE-002-EVIDENCE.yaml` | 917 | `sha256:8bdc21cfac1e51074b24a1b904e4264ddc1a900edc5d048ef56499bc625628a0` |
| `docs/foundation/WORKFLOW-CORE-003-EVIDENCE.yaml` | 759 | `sha256:7cb8b851e1e8dc15b349d1afe026a3095db852ba701b12a83a8d71d4a74fc95c` |
| `docs/foundation/architecture-guard-v1.yaml` | 4834 | `sha256:e063c807b1f60871fbab96b22e50c7efa390e9da34647daf61221fb741615f60` |
| `docs/foundation/development-progress-2026-09-17.md` | 2794 | `sha256:11b8dbc2e735a2b53ca73de857ac8c14be55aac498e7f8230eb1b151ad9a9ffd` |
| `docs/foundation/development-progress-2026-09-18.md` | 9469 | `sha256:0d818f9213503ffb995c61d41e8da6aec986ca00ddd06fe94475322e06b9b6bc` |
| `docs/foundation/development-progress-2026-09-19.md` | 19750 | `sha256:de6c02321c95b00bd39aee2b0b60574141837f7ba1c9f2920c2a5bb739a9fbea` |
| `docs/foundation/development-progress-2026-09-20.md` | 17678 | `sha256:d31f5212c7df6d3033ce2dd6db909af5739c3563f40f4ad721ece11b7b82d117` |
| `docs/foundation/development-progress-2026-09-21.md` | 5272 | `sha256:c7f45e9a79e636856de53b418a6967894f82f9718111fb34b5847a4895b49cff` |
| `docs/foundation/error-code-catalog-v1.yaml` | 4094 | `sha256:c0ddfb5cf3ad060f6c9a02b488ea17f1e7f46472313d7c13b53211edf0209c77` |
| `docs/foundation/event-compatibility-baseline-v1.yaml` | 153902 | `sha256:c630c44ef169a6ac63ea4f9f21ca56e02514b0df364e4ce8850d0e013d58e311` |
| `docs/foundation/event-envelope-baseline-v1.schema.json` | 1884 | `sha256:b59f4bfe6a7683b28ff68eecff89751c8659974e81cbbdb34e9f392a7fe059a1` |
| `docs/foundation/metrics-health-baseline-v1.yaml` | 862 | `sha256:2383e0716f190932e5272b027abb89a7b1017f51587b9cd39c25c157e2fa670a` |
| `docs/foundation/migration-framework-baseline-v1.yaml` | 605 | `sha256:f5a72c2cc2f94fe1ca75fbbe3cea3ecd488499bb80c5c87537008c3294709a75` |
| `docs/foundation/openapi-compatibility-baseline-v1.yaml` | 9280 | `sha256:e31877a464f077c6c1d103a4028e73af23a56687733497a78e581ece9d16a197` |
| `docs/foundation/postgresql-foundation-baseline-v1.yaml` | 554 | `sha256:967969f145b63ff37a22c35511a91619b4d3a5d9680b160470318ca2c59df262` |
| `docs/foundation/redis-baseline-v1.yaml` | 863 | `sha256:1fa4c330d7adcbfb734a0407b12dbd53d4a20dbd99a4e98692aa956d17491975` |
| `docs/foundation/runtime-entry-baseline-v1.yaml` | 1799 | `sha256:944ee45965c4bad2bb2dfdb490d075e1c0dfce70cbce0c0af75ae49fd07ec2df` |
| `docs/foundation/s3-storage-baseline-v1.yaml` | 626 | `sha256:1852cd3c9ab4c2480aa2074c4e793a8ddc6b2e03aa61527818e15f3687959e72` |
| `docs/foundation/storage-key-policy-v1.md` | 1670 | `sha256:982cb27911fcd2ca5357c6f2e6b791b2b8c6b95df262d3f55dfa8a1d76a11dd2` |
| `docs/foundation/supply-chain-baseline-v1.yaml` | 409 | `sha256:747869879baf6ae2b5eb008e9e34e454ce81a8667d078c120eaa92dde45e9ae6` |
| `docs/foundation/task-job-polling-baseline-v1.yaml` | 730 | `sha256:ff2b61307d58360ec6b028359d0dd2c0ffc5a17cec038c4118622214058e25ea` |
| `docs/foundation/tracing-cost-baseline-v1.yaml` | 904 | `sha256:b208c59daf4d7872abdb9357324facb24358872b2bf4a61e8adf768be69f0222` |
| `docs/foundation/v2-directory-baseline-v1.yaml` | 1472 | `sha256:1686e460a8b9947230eb21090a01192ce58f2afa8acd2e4cb80b6492cefa0018` |
| `docs/governance/GOV-001-DECISION.md` | 3088 | `sha256:8f606f2257e485ee8f560a5671c2c734db7edcc69c6ed91af7e86ea983107b99` |
| `docs/governance/GOV-001-EVIDENCE.yaml` | 1254 | `sha256:0170a508c49d218e4a50f57e52eb0943ac975c5b7c69c329df1359a11f3fa414` |
| `docs/governance/GOV-002-EVIDENCE.yaml` | 703 | `sha256:4a28858d3164aef8409105ded3c19f69fa84fcd5258b0514781b7fe1f6e34643` |
| `docs/governance/GOV-003-EVIDENCE.yaml` | 734 | `sha256:464f109a2a55f2aa304a3c271f538c0745eee0f6ae70dec6a9b39cc4b1e138c8` |
| `docs/governance/GOV-004-EVIDENCE.yaml` | 1148 | `sha256:67c7f1eb874c022f7cfdbbbcde872fe64bdc0957d923c1e967b6f0ec7a9fee66` |
| `docs/governance/GOV-005-EVIDENCE.yaml` | 973 | `sha256:a69c6445fb9e32ad40caf59f8e534f685b65905a4dd044eb52e433f126e442d7` |
| `docs/governance/GOV-006-EVIDENCE.yaml` | 1075 | `sha256:50238a0c6dfa929660fc38fdf039810ad754b951422f916b9f204750287cd50c` |
| `docs/governance/GOV-007-EVIDENCE.yaml` | 1434 | `sha256:c511407c263def418cfb71a5cfd3d0a4eda81c1867248bd394658015e1a475cd` |
| `docs/governance/GOV-008-EVIDENCE.yaml` | 1106 | `sha256:e4eea57b8ec9f5dd355d49b8d2731f0e228c58a83cf60ae24f61972dc6457c06` |
| `docs/governance/GOV-009-EVIDENCE.yaml` | 1002 | `sha256:6856e3752c1bb84ca87150bd8a788ba7f3c90fde2c4a7efddb80b00b7f23cbbf` |
| `docs/governance/GOV-010-EVIDENCE.yaml` | 916 | `sha256:68d8ad9f80c743df6fcbc4c398832339feff1e626bee9548f73e5606793056aa` |
| `docs/governance/README.md` | 534 | `sha256:a0e6fd5884190083e92b7a4e4d41d49341203ad48b06fe51796bd57494d517f9` |
| `docs/governance/branch-protection-baseline-v1.yaml` | 672 | `sha256:b8c8b8947b18a8cc9993af9d61697cc850feb5dd95154574f42c3a053deff1ab` |
| `docs/governance/data-processing-policy-v1.yaml` | 2028 | `sha256:868621b08e2a97abeaa0f0f997698467e6a12579489c2910f5328f6dc90e7fe7` |
| `docs/governance/operational-targets-v1.yaml` | 2124 | `sha256:399e82dc1b7621197b6594055a7d0b86a231666a965a733877ea7b0d27191fd6` |
| `docs/governance/policy-card-baseline-v1.yaml` | 1876 | `sha256:5fae6f989b75902bc64e6df64d14a26c1ba34c5e2d6f47a9f5b06566131933b2` |
| `docs/governance/policy-snapshot-synthetic-v1.yaml` | 1035 | `sha256:fb11edebada68dc798dfcfe6977ae9702b5a246df97569ce43ed4d251e0d413b` |
| `docs/governance/raci-v1.yaml` | 7473 | `sha256:a063705f9e20fd227db2bd8eb31c881e5e4e6edfff822c29766e5adc8693fc79` |
| `docs/governance/real-account-dependency-v1.yaml` | 1294 | `sha256:9146da2c92044a544a48602500795de3521cb3a3c336749df4ded27edbcedc11` |
| `docs/governance/release-levels-v1.yaml` | 4129 | `sha256:01d5f73a4440f4f22c57c09056377d2137847ab101f8d2033cbb53f9055631e2` |
| `docs/governance/risk-policy-v1.yaml` | 10732 | `sha256:67a67eb01cf9fad8eee4fedd95221be7fb8489ba6de8f2e50586fc2f87df65c5` |
| `docs/governance/tech-stack-baseline-v1.yaml` | 4993 | `sha256:4b774bc96c42d7a63006df5bac115e9a50d552f14ae59924153eef9650958ba3` |
| `docs/governance/vendor-inventory-v1.yaml` | 1855 | `sha256:af084327509876d3b332b22162a79122702b240117ead564e8bd147bc9db327c` |
| `docs/governance/vertical-scope.yaml` | 1959 | `sha256:4a663d60207bb542f14d290b6a1235c046a5fa193df9f9421fa56be5d2f3ce52` |
| `docs/graphs/README.md` | 869 | `sha256:56407a8905d45c0244ff59f123edf536a876746d6a6356e2652354492a6ad1da` |
| `docs/graphs/v3-version-policy.yaml` | 607 | `sha256:ae33d260981bc4ee4af1943cd4521f4b002066f51bf73b113c74b8d55099deb8` |
| `docs/modules/README.md` | 219 | `sha256:948a873bda430e8923104be9e535ce44b2776f0602dee7a2fcb0ea6d067d2fb1` |
| `docs/runbooks/README.md` | 235 | `sha256:994005e3130cc7a3962801027699a693274b744b35934f262de13aad1cf7350a` |
| `docs/runbooks/foundation-bootstrap.md` | 1406 | `sha256:ff430ab066c9ae954c0702004de927507890b45b4db0f2ad78a3997196234f47` |
| `docs/runbooks/v3-orchestration-local.md` | 991 | `sha256:649efcfcb139cf680ed3d752c6c5a476db428b315d45b9bba8a7f586bab31dae` |
| `docs/runbooks/v3-upgrade-window.md` | 631 | `sha256:fce7e9df76e29576e5df50194b4680fa8d85b2802da89c38a0df58579d7be3a0` |
| `docs/task-registry-langgraph-v3.yaml` | 46389 | `sha256:91022f2844e0d72ffaf91985361277273ade824f2c75917689abf7dd5df2bad0` |
| `docs/task-registry.yaml` | 312265 | `sha256:1a4f2eb02e0ef02da3ad635fee48d85bf3c3e4385cb9dfa7056dcee2ee4c17bf` |
| `docs/tasks/ACCOUNT-001A.md` | 2866 | `sha256:f3cc7bdd40beaecaa73887bb4c5f1330c31abaad56f007ed9139cb8a4cf7d274` |
| `docs/tasks/ACCOUNT-001B.md` | 2771 | `sha256:76323898769d079af025973cee38ebb9c1f608a2468104dec0e6bda4a244c748` |
| `docs/tasks/ACCOUNT-001C.md` | 2879 | `sha256:141b354a33888d3022e678210d968ca961fe1b26fe924c97debb2be08961b654` |
| `docs/tasks/ACCOUNT-002.md` | 2744 | `sha256:0b40b7650f38ad00e2bf7d8bf7aad6b065aac943aea60e658c02f6b2bcc3e3e7` |
| `docs/tasks/ACCOUNT-003.md` | 2759 | `sha256:eb534ebfc13db65075da2d6e21a242d750c1685c79ca9afa1d85bd3c00805f1d` |
| `docs/tasks/ACCOUNT-CORE-001.md` | 5620 | `sha256:973891cd1d9b191330afa75d91e296d09373f6b561bfb958fb4e9f74cc231ea4` |
| `docs/tasks/AGENT-CORE-001.md` | 3634 | `sha256:0c0c2196243b31ad9d3b5561309810eb9b90cc5a5e1d10caf8fa63039fc97df4` |
| `docs/tasks/AGENT-CORE-002.md` | 3600 | `sha256:083fbd4452f6e3d9e4a62c6ac09884ca9b4a66bbb48a6bc7735495c113525906` |
| `docs/tasks/AGENT-CORE-003.md` | 3491 | `sha256:615027c8e813174cf61d3f4a382f19ae9a7aebd267847e6ed01e94fbc1a8b97c` |
| `docs/tasks/AGENT-CORE-004.md` | 3590 | `sha256:c4bdf51ee9ee32843ec273170f0a1491576292ba1036753744be2ce1d93e0f89` |
| `docs/tasks/AGENT-CORE-005A.md` | 4850 | `sha256:8011d1ff5947f266d4f3ed888f7beaeea82c8e44a222fab21d8309172fb858a2` |
| `docs/tasks/AGENT-CORE-005B.md` | 5037 | `sha256:91769299a8b9a65df4eee44043e90c952551f010f48749166ab84438ee3ee2f2` |
| `docs/tasks/AGENT-CORE-005C.md` | 5251 | `sha256:873a95aa4c0feed17c93db868ae4a6c747ddc8410a2617a85a172af4a618480f` |
| `docs/tasks/AGENT-CORE-005D.md` | 5084 | `sha256:f30956364c2ed2c7fc738f10ff1413e4bfbed5c17427441722b3f3956ef25b19` |
| `docs/tasks/AGENT-CORE-005E.md` | 4868 | `sha256:0b5a9b793eca928b49d30db01a3a622ffedfe21d03eadbfcd9f00cff6418732b` |
| `docs/tasks/ANALYTICS-001.md` | 5599 | `sha256:60a77f1b755056234518e6025d2153e7f96d44c874d74118ebb1a55f98fdec8c` |
| `docs/tasks/ANALYTICS-002.md` | 5545 | `sha256:e7912018443f90a91b1afec301b381ffbf66bebbfd172a8cef65dc7f5dd3118b` |
| `docs/tasks/ANALYTICS-003.md` | 6404 | `sha256:b3208ddaca30aa034da50af15c3ec8ded31b47d24a850327096e03d3dd491432` |
| `docs/tasks/ANALYTICS-004.md` | 4192 | `sha256:d3edc6485c8c1ef733b401d7510277780bb65c0b2781fb37f1c56d26792d7bf3` |
| `docs/tasks/APPROVAL-001.md` | 4678 | `sha256:4fa1207e92955b61890997830eca589d138cd3c2689a62b50620852a93df984c` |
| `docs/tasks/APPROVAL-002.md` | 4752 | `sha256:c4e112c4f381b2aa1266275a4d7785cd0b9e235794a06a757c3414fe3e78fb26` |
| `docs/tasks/CANON-001.md` | 5098 | `sha256:f540c1bb7e7bbcc3d0b59792c45ef1f7fbf14aa73a5d38c84ba1ced3f7cf743d` |
| `docs/tasks/CANON-002.md` | 4156 | `sha256:d9c45abc226e4ddc76e0e31169d36eb9c8d4dd3d704f435084bb997c6a02ccd5` |
| `docs/tasks/CANON-003.md` | 3756 | `sha256:eeef0989e51f9f1b4008448ef1cebff2a596a665348278051e3707de2a156bb4` |
| `docs/tasks/CANON-004.md` | 3902 | `sha256:5bd215c758cd2ee79fab8b64c727823f4ae57863cf95463b59d12486e53deac5` |
| `docs/tasks/CANON-005.md` | 5554 | `sha256:e14f682da5f5e16839364cddd71b865cb9d81388e56cb0f47e56afcf60be2961` |
| `docs/tasks/CANON-006.md` | 5794 | `sha256:2ee98ca643f2efab02f3cdf34d01a176f63b1163bec07f063d3b947b6eefd3f6` |
| `docs/tasks/DIST-001.md` | 5790 | `sha256:954096f67b59fec9a2f31460ce7393e5f20990c57adbc9e898d21cbb33e0fa47` |
| `docs/tasks/DIST-002.md` | 3635 | `sha256:31a445ccddb25453857d3a179737b484e5b7d599568062f021779f9ad732a84b` |
| `docs/tasks/DIST-003A.md` | 3742 | `sha256:512a70d7e3a5f5806e33f85e392dc2a0389630cfb47d8a7ca991b14affbe425b` |
| `docs/tasks/DIST-003B.md` | 3765 | `sha256:8d2a13e30968b4537d22c209edd3234a51d727f22f5c1e52d6ba35a6efb2c475` |
| `docs/tasks/DIST-004.md` | 3799 | `sha256:470454961988b40b4611adf6beadfead977acf7434cdef01a2a887438e3580d9` |
| `docs/tasks/DIST-005A.md` | 3570 | `sha256:50412d5676f3e396f63a12e1cdc378a67eefeae7f6a75d0b026facdf58d95782` |
| `docs/tasks/DIST-005B.md` | 3460 | `sha256:6ec8c9823d3be0569c7db2878187d51c3ab1244555dfbc2b7fa3b9195c61498e` |
| `docs/tasks/DIST-006A.md` | 3605 | `sha256:18cde9881acc6cab4b53da3ac8923dd18c4726ebc576069949c8e512096aab8f` |
| `docs/tasks/DIST-006B.md` | 3464 | `sha256:118a695e94a913b370a654baddea98164f96e867a221f8b0ba0dd3bdf4ec242c` |
| `docs/tasks/DIST-006C.md` | 5079 | `sha256:67053d741bf242b7579714ecae85c9234b4a643f7fc7c0c9f71a03cf3c6c7157` |
| `docs/tasks/DIST-007.md` | 5141 | `sha256:3d4436a8c1f56c066f454c994f395221ebf19a82151b3dd7217ab2cf843e4f3a` |
| `docs/tasks/DIST-008A.md` | 4843 | `sha256:ea6ab42dd4ad7d16427e4d761095d9720841961b9e8b3c3e909ebb2833904c2d` |
| `docs/tasks/DIST-008B.md` | 4840 | `sha256:b1a5c8bfb3068a64b3e97ebcbda4ae07254f8f0e2f5b5032a2198ca64df6c907` |
| `docs/tasks/DIST-009.md` | 4997 | `sha256:4cbaa412627fec707201ed94973aa5eb02f4f2a5c3e44cfb67090336c3b2dd2c` |
| `docs/tasks/DIST-010.md` | 4879 | `sha256:ec12dff6314635281ce6cf0c9084bdb4577959b3b4e334faa0d803f698f2f4a7` |
| `docs/tasks/DIST-011.md` | 4980 | `sha256:8f56bd46c053267c96edf8098cd6e717a053814e2d16f03c9192da5d728e8145` |
| `docs/tasks/EVAL-001.md` | 6070 | `sha256:fb8b239295312689a011f4b77baf25d79242f8a58096205eb0e59e0ec0e21794` |
| `docs/tasks/FEEDBACK-CORE-001.md` | 4076 | `sha256:d2d6d0e510b697968a988bb06249133e4624e92450425081d2e049c8c1659dac` |
| `docs/tasks/FEEDBACK-CORE-002.md` | 4945 | `sha256:d9661116c5bc7d33982fe57c8f697388b7b9d19df9a59d6f8aed0c483948f485` |
| `docs/tasks/FEEDBACK-CORE-003.md` | 3784 | `sha256:31bb265996d5db316125eea5da1e064150c1ed81259323444a562b5402f9ad01` |
| `docs/tasks/FEEDBACK-CORE-004.md` | 3576 | `sha256:f4a9918ad8844bd5757a545ec553a87b06af562f6642adbdc3e133d72e50129f` |
| `docs/tasks/FEEDBACK-CORE-005.md` | 3795 | `sha256:4b3eaee274e199e7decd5d24dcc128efde00a8fa046393f031ef0d6a7096c94c` |
| `docs/tasks/FEEDBACK-EXP-001.md` | 3432 | `sha256:560db4b9917f8ddfc61c2fccf1101970d0257eae95f364bbc5852cd1e5556cd9` |
| `docs/tasks/FEEDBACK-LIVE-001.md` | 3069 | `sha256:7ba6a08a53424fc18e469ab17a6c6f7c823f031ebfc3db902fa6d7c356c2e2e1` |
| `docs/tasks/FOUND-000.md` | 6647 | `sha256:05fd7cbe786cef40c47a63fbfdb39dd7d943dd33eb8bf9ccbf4c0fadf1eea0d1` |
| `docs/tasks/FOUND-001.md` | 8058 | `sha256:63b947c1dac0443c7e520247c175d7ed633da4b35236a341d11a6ccd4c03388a` |
| `docs/tasks/FOUND-002.md` | 6740 | `sha256:8f778d6d3fe20e110e6d61ef0ffc37bef33d4e07ee2640a00bbe63a291147ed7` |
| `docs/tasks/FOUND-003A.md` | 6548 | `sha256:30a53463ce3c340a92b02c63a55af1a78cdadde81a53afb70da9c27016a4e535` |
| `docs/tasks/FOUND-003B.md` | 7068 | `sha256:9605229bc964826c55cb7cc7857641b7152ec4bb870dfc166072f3d5f2b11e6e` |
| `docs/tasks/FOUND-003C.md` | 4500 | `sha256:44dbac57f7b6b8d37a45a844e106d38f4b7f3afdde2f08103d526fa77a255d00` |
| `docs/tasks/FOUND-003D.md` | 7511 | `sha256:97ceb7f226e1b604d82a9fd0591e64569995605398592546091013421f77bdc8` |
| `docs/tasks/FOUND-004A.md` | 5649 | `sha256:d071cf4bd0ac8d3d711dfc0f7edb2c255ad22a74f8e43d5c8d90c2ab4a7f346e` |
| `docs/tasks/FOUND-004B.md` | 6918 | `sha256:d0c7d570ba275003a1c752af3bcc656e4c72f5b1036cf1507d1a617911d46cde` |
| `docs/tasks/FOUND-004C.md` | 6518 | `sha256:fb00ec9776456a75d8b6b802bb7b047930c0f84921ef28d83aee2a71b274267e` |
| `docs/tasks/FOUND-004D.md` | 6560 | `sha256:a3231b8ea8d55e73df902dd8e41998109323ae8dfa2ce595173068b14611cc39` |
| `docs/tasks/FOUND-004E.md` | 5053 | `sha256:8c27b503b780d90a515b1a628e6b0c510072960adc9ec7c3a77e9cdb4b05affc` |
| `docs/tasks/FOUND-005.md` | 8343 | `sha256:18842c47953b999ae15fff3880518db1a252756efed83c98c382ce0bf7c87a83` |
| `docs/tasks/FOUND-006A.md` | 7466 | `sha256:1ca94c370e7f9d4fff62c59946ca2679b47eeb89e84699bd68e9675ec7b8f894` |
| `docs/tasks/FOUND-006B.md` | 7487 | `sha256:3332fe8a783524c8cfe7df5db137012fb1780b1f30ff5c61bda0888d466cdac8` |
| `docs/tasks/FOUND-007A.md` | 6119 | `sha256:47b7651b2b8aec69f3bfb7503554aca552c0c80b4a0a9edf0b6f34aef5157429` |
| `docs/tasks/FOUND-007B.md` | 7170 | `sha256:4d4d2b95f660ff4587a5645dd90f1d28cc334050d3e93dce45487630a94baa92` |
| `docs/tasks/FOUND-007C.md` | 4640 | `sha256:deee0c1b1538856a1a78b4cb9ce231605b2e2ee6062bb769c4943370c3ff8b4c` |
| `docs/tasks/FOUND-007D.md` | 9745 | `sha256:ac0a4eb9ddfe5cc43de6a60f961942e4c2048f4498ada056826934ab4297ed5a` |
| `docs/tasks/FOUND-008.md` | 7020 | `sha256:f2b80ed24af4ef8b53166e25c2edcf9134bb4e8b41881e0366f3fa4c388511e8` |
| `docs/tasks/FOUND-009.md` | 6171 | `sha256:6da3f400f6cf93e0b18d64f59173fd1064bd9cd34d653564375c134f8ac30321` |
| `docs/tasks/FOUND-010.md` | 5416 | `sha256:a5c6ec97710d63c07f367e443c7a3d760939b32f029aebf249f9f288db75af19` |
| `docs/tasks/FOUND-011.md` | 4372 | `sha256:f03b621bcac0e74be58d571017ff18d6cc7b0625ef064b58cf4cc201ee7bdef6` |
| `docs/tasks/FOUND-012A.md` | 4867 | `sha256:6d2ce1e6f32ee5896dd0f1cc913adccc79b53d07f15c5fd9304de1edd6f5c9cb` |
| `docs/tasks/FOUND-012B.md` | 3672 | `sha256:96127e5cd3a3b999a403318146f8a2d8a1cae6cb29057cb690f6169ca56f03b3` |
| `docs/tasks/FOUND-013.md` | 5264 | `sha256:37253377f5b033b6e87076d6e0e35c7794c758b4c06e9c254f6497ee939cd647` |
| `docs/tasks/GEO_CONTENT-001.md` | 9618 | `sha256:e6b1cfc76cbf6b11c2351359dd7440a5712f23cbaae0c326c79067a99a85cabd` |
| `docs/tasks/GEO_CONTENT-002.md` | 8014 | `sha256:05cc93063688d9f7bfca0c6426b08173f82c2d2f79400749b49f650fb9403a83` |
| `docs/tasks/GEO_CONTENT-003.md` | 7649 | `sha256:da269d39640bf0ea113cc7a1a6d5cfa307c67072a65274625e672ac3f94724bf` |
| `docs/tasks/GEO_REGION-001.md` | 7402 | `sha256:64a611f864af66628645bf2683774fc27ff15af0b92249afd1a04108d2f89092` |
| `docs/tasks/GEO_REGION-002.md` | 8347 | `sha256:8837a5ef6deb19b05b818e0e944ffdc428f97417f01efb587b0ef1bda5fdbdf9` |
| `docs/tasks/GEO_REGION-CORE-001.md` | 4901 | `sha256:ae151d95d2e7ec4c206ff81d1e02befeb8dd5f96425daf7629846610525e4469` |
| `docs/tasks/GOV-001.md` | 5313 | `sha256:203df76c098949794baacdc0d7c290c23f61984980af90d570d3237a0241f283` |
| `docs/tasks/GOV-002.md` | 4994 | `sha256:9457b37c56e1a9a83b1940269566b1a235ab7a6363922871b82728e51bc3fe8f` |
| `docs/tasks/GOV-003.md` | 4282 | `sha256:219a038867b3c58190d5bfb4f3e566077a2a18db4af14b225edd005eb75d0790` |
| `docs/tasks/GOV-004.md` | 7346 | `sha256:ee226889a7bca108c019487ec8c14d198d787b9d4397693c2f0ebb3606d62b51` |
| `docs/tasks/GOV-005.md` | 5454 | `sha256:18ef94be311d1eba3e5c7b7d02233d63bd9e1810fdf16cfc7aea637275ba86a2` |
| `docs/tasks/GOV-006.md` | 5311 | `sha256:95dfc97932cd8b25bfd69a943b128609c5594741c3d4e840903455e6e2268589` |
| `docs/tasks/GOV-007.md` | 4599 | `sha256:eb739ed812cfb6c69fce44574b1a0b2107fcdc003636d4a9c5fc535353c6fb2b` |
| `docs/tasks/GOV-008.md` | 4484 | `sha256:1e63e9c81f756c193bc3843986e2c2ef487e7c5b95026fe0490a33a79d4efa21` |
| `docs/tasks/GOV-009.md` | 4353 | `sha256:651d196638c5673012c187a4a6acacce7509ccf9343dabdd78484a696caf7d07` |
| `docs/tasks/GOV-010.md` | 4354 | `sha256:0fb5cb38a63614ccd6221aa12a458be717b658d83e289cdd976ba6c3070bb9bc` |
| `docs/tasks/GRAPH-CORE-001.md` | 3643 | `sha256:4f2ac40df9aeb12ebbd8ae1695c5c914d84aabd9489930bebdfdc9ffeb6b7f03` |
| `docs/tasks/GRAPH-CORE-002.md` | 3709 | `sha256:fc8cd6d8e60ae152387ce5706966bbcfb4b2393243852f55900a71c0ae5a237f` |
| `docs/tasks/GRAPH-CORE-003.md` | 3671 | `sha256:4d4e3645c5ddab05a13d163216473f93fb647754d3d485462d83cfb2f7055f36` |
| `docs/tasks/GRAPH-CORE-004.md` | 3633 | `sha256:51f3292623b2aa178af31c56d87f2bfe4126b49bf3f39a18fbab6bf1f42566d1` |
| `docs/tasks/GRAPH-CORE-005.md` | 3647 | `sha256:5d7ece37a4cbadef186dd6f7808db40d18acfb2e577741bc29f5ae773ab82d00` |
| `docs/tasks/GRAPH-CORE-006.md` | 3667 | `sha256:8542deb866e17aa324fb6a138db5c6ae0d14240ff9f252dba9e8b2e1ee45b1e7` |
| `docs/tasks/GRAPH-DIST-001.md` | 3685 | `sha256:e487fa27b9759b6b0dbf71da8700c0b7e3ddfc9c47e80028cf082388f88bc8ff` |
| `docs/tasks/GRAPH-DIST-002.md` | 3623 | `sha256:7f44967349eed9421a796fda13e64b928af1c7cdeffacf08917626144903a8a6` |
| `docs/tasks/GRAPH-DIST-003.md` | 3627 | `sha256:d383c208dcde0f087d6bf6d17c65619bf35a54094cf60ef542435c0b8f21185e` |
| `docs/tasks/GRAPH-DIST-004.md` | 3649 | `sha256:a103824e575264cceb1496427a9f7a8a362a4f1bbcf75eddd509b16f174786f1` |
| `docs/tasks/GRAPH-EVAL-001.md` | 3666 | `sha256:649baf6c56843219f8c625bd1d2eaba67fee9336f3d2f810c1b83346a65ecdcf` |
| `docs/tasks/GRAPH-EVAL-002.md` | 3630 | `sha256:4b141daafb4b521dd897f7a30e0d0922f762e4f01f2bb121f1aa6780bd521ba4` |
| `docs/tasks/GRAPH-FEEDBACK-001.md` | 3668 | `sha256:a2a97a1a42825dc786312b1a8f3cabd4514f03376ad60da07e203e2772334812` |
| `docs/tasks/GRAPH-GOV-001.md` | 3610 | `sha256:79b8c34a483d754df1d6001530767674d5cdaa01a81a4bb61c8dc86ccfc4aae8` |
| `docs/tasks/GRAPH-GOV-002.md` | 3660 | `sha256:0153584fa753fad295b669d5a340a9c86520f3471062ea1258da32f36f574527` |
| `docs/tasks/GRAPH-GOV-003.md` | 3702 | `sha256:b8baabbff60c1d52a8f6302edb4e7e90b7e3367754d8f7c2ad87e2ce2f47c272` |
| `docs/tasks/GRAPH-GOV-004.md` | 3652 | `sha256:473bfd8d364bf60e8af6abdf75166f2876506be7db784e4dcab4549b777e889e` |
| `docs/tasks/GRAPH-GOV-005.md` | 3664 | `sha256:ef1afb110bb07f1cdcfc0c71f1bcfeb2c913231324f4f05ebe61436bf281c7fe` |
| `docs/tasks/GRAPH-HUMAN-001.md` | 3672 | `sha256:73c9e4a335729862087f0685a35e8493b56cd1fa6ce7a5dfe4103f7ad9a8b0c8` |
| `docs/tasks/GRAPH-NODE-001.md` | 3665 | `sha256:cc96bff77fdb737a9cf5a16923dda37081b92af3723318b004811f9121a74ba3` |
| `docs/tasks/GRAPH-NODE-002.md` | 3649 | `sha256:9f596f7a6baa3054652c95546f53d4b5ec302b6e591c31d4284788a9af37eaf7` |
| `docs/tasks/GRAPH-NODE-003.md` | 3661 | `sha256:dc97cb15b967cf9008d64b2afd56eb288b0f3caec3e11db9cf67f4bb6c431503` |
| `docs/tasks/GRAPH-NODE-004.md` | 3659 | `sha256:7b5b1a29bd2771d31d0b3d6ac7df763a10eed3b4cc581ef1cc9fa0821592e76c` |
| `docs/tasks/GRAPH-OBS-001.md` | 3665 | `sha256:3008e480b47a20211d680b06c34cd8a0fd005fb73808567cbf4f2b2f3971638b` |
| `docs/tasks/GRAPH-OBS-002.md` | 3633 | `sha256:848723e8d9902b353ddcdc729abb1b5d494e711c6257fc64bf49332171ffe993` |
| `docs/tasks/GRAPH-REPLAY-001.md` | 3691 | `sha256:1e7e758e24958e646a808bf537f6a7c83dc88051299747125938f916decef54f` |
| `docs/tasks/GRAPH-ROUTER-001.md` | 3669 | `sha256:0db28804e502159b098c5b2af24f20f064990df6627f0f97b2dd35a9b520332b` |
| `docs/tasks/GRAPH-STATE-001.md` | 3650 | `sha256:645a53c4635d2c0f96c3519e3ffb11656245e91e709b110f013190224cc62e5c` |
| `docs/tasks/GRAPH-STATE-002.md` | 3682 | `sha256:41f61e4827e9af96880d8580132ef07e0c225abf5ca302465d31872c8831c075` |
| `docs/tasks/GRAPH-STATE-003.md` | 3638 | `sha256:46db47cc31ec144bfff177494964fa277cef34266a422bc00588f6092379af5f` |
| `docs/tasks/GRAPH-STATE-004.md` | 3634 | `sha256:3b411651e3eee19ed51f7749222f0e907e3d31f0f45c17874b4a23cc5d2e4841` |
| `docs/tasks/GRAPH-STATE-005.md` | 3632 | `sha256:cc6319091a900fa473c50ef4a444cea017f2356cc82551ca284a546393c3568c` |
| `docs/tasks/IAM-CORE-001.md` | 4876 | `sha256:40f2e797a6a39209efaac7f84f0605a1ce1d72b6cb8a0c27dbf9fdfdffb6f4bd` |
| `docs/tasks/IAM-CORE-002.md` | 2691 | `sha256:cddb894899ef104174548de60ccc08e9d8b2c10f2f2e47b4859c81be539ca829` |
| `docs/tasks/KNOW-001.md` | 6313 | `sha256:6a496ccf494fbe2438dc4b18d7a1ea16c364532c1b9b44d11bf953fba6c898e5` |
| `docs/tasks/KNOW-002.md` | 5221 | `sha256:167478e3a5c2335fe04ec3f225077381a426f87df217db8db16f14fc07c614d4` |
| `docs/tasks/LC-MODEL-001.md` | 3637 | `sha256:b253131a65480f17f510afe88bd44f2c68f7afd28025ea3814ddbabb71a9fb64` |
| `docs/tasks/LC-MODEL-002.md` | 3613 | `sha256:05005664f0b5ff3085b252802d82d4d0ad11964acedbea6f037376d57bfc4b6c` |
| `docs/tasks/LC-PARSER-001.md` | 3642 | `sha256:e5ef05a07a169c1d585b3a1a36106d0dee3156f9a0848d65f7121b36c4ec5c76` |
| `docs/tasks/LC-PROMPT-001.md` | 3628 | `sha256:3d6be07a16e4da27491109e25e0b593ed8de35d280bfe0ae2bc02a1fe6f2e47a` |
| `docs/tasks/LC-RETRIEVER-001.md` | 3651 | `sha256:463e2e2f1908e4f5717a7b8a8216e51d0f49d6df1787971e0f2f760b7084e061` |
| `docs/tasks/LC-TOOL-001.md` | 3648 | `sha256:8a6b253c97143b7b9adf2dcc1a288e7dbb42dcc440adc8c6ea6e5342d80036f8` |
| `docs/tasks/MEDIA-001.md` | 7324 | `sha256:7c8c6444fee98cf93a4db49d66d73e67ccf66293cfd58c1c30b5a3252e972c76` |
| `docs/tasks/MEDIA-002.md` | 7130 | `sha256:9146df6dabfc8a45295cf5b7d0b417757245a46c673d05ca5b9aeeeb6e8c803d` |
| `docs/tasks/MEDIA-003A.md` | 6671 | `sha256:bfe7d14f2b969d00d0dea6566412257073b436ba1feb746783d1b296b6138a28` |
| `docs/tasks/MEDIA-003B.md` | 6697 | `sha256:03ea4ba5e1a936c938e9d2d9b2615e6afc635fe30f8366496b7dc1a96fb7accc` |
| `docs/tasks/MEDIA-003C.md` | 8721 | `sha256:85a78af74ea3db2f2af39f6c88ef4c418eef887a88757b29e5dd07384dcb9456` |
| `docs/tasks/MEDIA-004A.md` | 6495 | `sha256:3406777068e257b56ce3a609b274965ba3e57e4cb1a4ccbe0c8189359c214499` |
| `docs/tasks/MEDIA-004B.md` | 8277 | `sha256:0b78ceabfc651f624b9cef37da542e4526ba6bc349eb0be19ebe21633eecdeac` |
| `docs/tasks/MEDIA-005A.md` | 6129 | `sha256:d91e00ee343b2e39e10d0bf7022317858d7ae504c36b2c7aa872bf7e2db931ad` |
| `docs/tasks/MEDIA-005B.md` | 5322 | `sha256:8ad769abfac435c447be5c817b5e9194de33ec41e99555a9b79973f61aef04e0` |
| `docs/tasks/MEDIA-006.md` | 4790 | `sha256:5148916ada30e1b691051eef8059e03800d2299b18fa61d5e1640baa4a1b44cc` |
| `docs/tasks/MODEL-001.md` | 5619 | `sha256:314e3abc75e0d2bd86dba9cf989a51ceda86a7fb972988d31ce4fd8c61459a92` |
| `docs/tasks/MODEL-003.md` | 6045 | `sha256:d65a4dea110bb89213ab15deaf992454967cf7ee4ed4c5f6a8082f3a64c94cac` |
| `docs/tasks/MODEL-CORE-001.md` | 4566 | `sha256:d8b84265a96a874a6c43b5caa81e89edc60e87ef3c634c24548c40c4b5be7782` |
| `docs/tasks/MODEL-CORE-002.md` | 5501 | `sha256:b7399e9bfda059310aafad6706a32e9fb5d4991ecb6c82d584381b25b9ee3547` |
| `docs/tasks/OAUTH-001A.md` | 2870 | `sha256:7bb838cfca960a2d51c76fa7eea902c08193c37be43b36a49f19f70a73cf6944` |
| `docs/tasks/OAUTH-001B.md` | 2872 | `sha256:2e4a64fb7e08230a6223985f7611d6271069b33f40d450c5178f5d09e65d4d8b` |
| `docs/tasks/OAUTH-001C.md` | 2816 | `sha256:958befa8f7e20d43d8b40d5a4efd7bb95aeac047e9c60578d6593c3a5cc553fc` |
| `docs/tasks/OAUTH-002A.md` | 2814 | `sha256:c00e3f0265e317022be8c4bd5a40ed17ad3dcaad14bf314bf91cd4b5b7925630` |
| `docs/tasks/OAUTH-002B.md` | 2793 | `sha256:24673d157c567c12e4c06edebe357d6e368f65d678bf8b888ae9fd7bde139a88` |
| `docs/tasks/OBS-CORE-001.md` | 4398 | `sha256:260c8d62bc932a565dfc91fc31c8148fec5e9088ec299cf180b3e05ecd688853` |
| `docs/tasks/OBS-CORE-002.md` | 4279 | `sha256:361822a3408363cfd72b554fbc9de9c66001da65d10ec9b70d96ae8b6ba04dcb` |
| `docs/tasks/OBS-CORE-003.md` | 4291 | `sha256:c5767bdb8eff0d7aa47a893ef71a41372da6600232ea871d8ef86982fd396859` |
| `docs/tasks/PILOT-001.md` | 2539 | `sha256:5f523de06106510152b700c173c9aabb36743931ce3d8ddc69560cc20a1ef18e` |
| `docs/tasks/PILOT-002.md` | 2597 | `sha256:dbb629638cbaf1233d9e703d5799c03377ae72524f8ddc9364449a39d82963e5` |
| `docs/tasks/PILOT-003.md` | 2545 | `sha256:09097c271555bc8b998b5c979edb9bacb6769389307003b49440cb72e76961d3` |
| `docs/tasks/PILOT-004.md` | 2644 | `sha256:5094604f78ceff16e92a34a30184d17c9be41404466af0e00dfe4e52ed7202e0` |
| `docs/tasks/PILOT-005.md` | 2519 | `sha256:624048b4c44a3500ec1fdaa9226584ac620886df2fbec5483064042eeeb29f0f` |
| `docs/tasks/PLAT-001.md` | 2708 | `sha256:2021eb3e0ca1b94fe71c60b8a56d43d89b25fa4c70f70a471d93498f8294373b` |
| `docs/tasks/PLAT-002.md` | 2640 | `sha256:e8c20b7cac4e93cb1e603bb204d4b6fc4df99a9ef9a8cb277fc7f95a35a0cec8` |
| `docs/tasks/PLAT-003.md` | 2682 | `sha256:1dc49b6d6e29b7d42e4996d0caf032d6d0ff5bafbd8b7ebfe9e79e354b9d4382` |
| `docs/tasks/POLICY-001.md` | 5101 | `sha256:6ed61a38f59df450268dbfa6b1fec08317b43775ec6fa0e7d2e1327dc6d2fd5b` |
| `docs/tasks/POLICY-002.md` | 4525 | `sha256:43aa936ad3c3505e8ff5c5e153bd95943a45400b8ac9606ac0b796c6ff66b5e5` |
| `docs/tasks/PROD-001.md` | 4237 | `sha256:0162d8eea53126f9279f0328975a5c32dc421da35519a5d96ba1c66409f06159` |
| `docs/tasks/PROD-002.md` | 4766 | `sha256:e84e044267d8294d2b72ad88e5f55bb8a717ea281ff8dc873397b615213d6a00` |
| `docs/tasks/PROD-003.md` | 4077 | `sha256:ea1ea359ac5e56b07095c11a0cd92bc1612d1e0a0c2340e40ec3cb3b9072777d` |
| `docs/tasks/PROD-004.md` | 4483 | `sha256:e31ec6b865942952e5c47de7a6f1b256f56fb3057f07e9628a52991fa3ca08a8` |
| `docs/tasks/PROV-001.md` | 5736 | `sha256:2de85a015e7e6f26a7a2e23fe37b33dfe8feb5776c53eef0d4b19184037a9ec2` |
| `docs/tasks/PROV-002.md` | 5905 | `sha256:d7b0528a70485f23644252e3e55e0af787b1d1a7a3abc63a0972ed789eb4520e` |
| `docs/tasks/PROV-003.md` | 5569 | `sha256:8609fdf4179a37364851032903e03e3fe3d0a964e0a7f72d9be9ab292e671c7c` |
| `docs/tasks/QA-001.md` | 4550 | `sha256:7a9c2045edb9fbdaae652b8a27cae293fbc2eb7320220787cba540aba7828be7` |
| `docs/tasks/QA-002.md` | 4980 | `sha256:5dc65b134f91a95cbd1459430588a977ff9ba6f507a4b40f1234a685094b8e1a` |
| `docs/tasks/QA-003.md` | 5343 | `sha256:8f126cb41f6f653be746d93af9b879228364a1a2ec503bc27949a100b95ae33e` |
| `docs/tasks/SCHED-001.md` | 4115 | `sha256:495f11a447f4e94c533c63948369dc652b6cc54f8fa6442856592f5965c6ca94` |
| `docs/tasks/SITE-001.md` | 6822 | `sha256:da5d3b0a96109247346761cfb1107edcb9c5ca3dafb77b3f41bf8bb945f3655d` |
| `docs/tasks/SITE-002.md` | 7967 | `sha256:fcacbc6fb21059da4eb81d16ab2f35f2922c823ade761a5c146e87b7766d71f3` |
| `docs/tasks/SITE-003.md` | 8476 | `sha256:ae5f22489b0b012ac090ef9b7cdce45f6e162da5ad1334f01279b576b575b942` |
| `docs/tasks/SITE-004.md` | 6776 | `sha256:a377e05c5144c6ddc970a491e3977d7d162b69b9717cc73100626a3aa4feb1dc` |
| `docs/tasks/SUP-001.md` | 3487 | `sha256:14274a8406ccf2da5b1ea44edc23ff6931c7ba43cd13d2f216968912c878a235` |
| `docs/tasks/SUP-002.md` | 3226 | `sha256:97f528aac3ddfcae553c7c5dbfa2922c0b7391829b995be863c75a0ce019780f` |
| `docs/tasks/TASK_CARD_TEMPLATE.md` | 1912 | `sha256:a48fa6d44c002d8ec15070180119ad5937cd501850ad5c2e5c8631dc371f4718` |
| `docs/tasks/TOPIC-001.md` | 3822 | `sha256:88f39d2f6e78645b3a10295d0567aa8b506849e56c194f8891a8dcfaefa91cdf` |
| `docs/tasks/TOPIC-002.md` | 5060 | `sha256:4d8b12cf86155fdfd472365f3b15791a301103c4ec3030ce261a00cade387b4f` |
| `docs/tasks/TOPIC-003.md` | 4816 | `sha256:e498634893c6c2656a01ec0de644d3848d13d0b008be27bbb8c1a46db5a0e107` |
| `docs/tasks/TOPIC-004.md` | 4711 | `sha256:80a2f023f7030ffb5ad5e860d5ddc0deff95c74f25656c8e6997520754e015f8` |
| `docs/tasks/TOPIC-005.md` | 4592 | `sha256:6c3e16e7b0ac2631598efebdf917e4844da985d9f9959efd7c007ea351227615` |
| `docs/tasks/TOPIC-006.md` | 4233 | `sha256:da8038740c9dfa068bfd7634e0cf4fc5259eed093e7ca0b46db1b6ffa6ea0e99` |
| `docs/tasks/TOPIC-007.md` | 5104 | `sha256:97f8cd19bc151d7ed4527bbd1d24d430b1df8853903da17a9f3ecb05b559f1f2` |
| `docs/tasks/TOPIC-008.md` | 5594 | `sha256:2cc14a318a249acaad11dc16d0338a274ac41f49c2a305f820a47d04e8450cf2` |
| `docs/tasks/WORKFLOW-CORE-001.md` | 4828 | `sha256:7e8986e3c993e1d333de9e3d584eb947929a2fdf117c2b46908882fc920b8502` |
| `docs/tasks/WORKFLOW-CORE-002.md` | 4975 | `sha256:a81fe9635ca8a6e18f73ddb7892bd60c34fb6bdc79232ee6a1ad815f47f31333` |
| `docs/tasks/WORKFLOW-CORE-003.md` | 4559 | `sha256:5151941eb2fe23b6585f097c3992692a9bee91f2943a8111b2e04c15d1c92a3b` |
| `docs/workflows/README.md` | 217 | `sha256:b5669edc2191f6b372a613724dfca501f25f27895f95dc03b8a9e1abdb520432` |
| `docs/平台发布接口调研与小红书迁移方案.md` | 10293 | `sha256:d4cf9e8f20f8b347214c169eff57d059d780948d9087796be08d51476d1b81c1` |
| `docs/真实账号自动化运营操作手册.md` | 14702 | `sha256:fcba651176a88c902eb006413bf70f9c6fb0e4091e1b7523ae29c8e3475eaac6` |
| `docs/网页管理后台测试说明.md` | 11448 | `sha256:0f6eb579d748c3dc72e288c7d9023c50fa6b8122b892073113743a5e554d2d75` |
| `docs/项目开发进度汇报.html` | 24364 | `sha256:5884106a194f7a581b6a42674a14f315602aa7630736d0704384b3de2aa88d2d` |
| `infra/__init__.py` | 47 | `sha256:8517a486e9a61a8d1e10284f75abe76808de8d787a0422021f07ba28d935cc82` |
| `infra/compose/README.md` | 434 | `sha256:1e161168885e43eef8aa36e0db56f7c3efeb1017f724da61d6ff2dd4889f20e7` |
| `infra/compose/postgresql.dev.yaml` | 327 | `sha256:de8bbf10639bb4d2e0d84fc0c4bc5d3c00a35bc28c006fe1c9c1c218833342bf` |
| `infra/compose/storage.dev.yaml` | 329 | `sha256:808305cdc492d4071c44f8aef8c520a31e7d1f078192212bae988c50fab9a43c` |
| `infra/foundation/README.md` | 860 | `sha256:a23dcec3ad35f07653da5754e88991e22e94f32c0a2fc5f351b4cf5b7df373db` |
| `infra/foundation/__init__.py` | 6456 | `sha256:12e780eb299103172e040ed80db7ae326b4c4b1ce60a1352cb6314f9da1404c5` |
| `infra/foundation/agent_output.py` | 3850 | `sha256:1cccce9183d544b790a3c8fa42b3aa8ebdbbbcf4eae6e6a79acaa741b9640731` |
| `infra/foundation/control_plane.py` | 17853 | `sha256:0a8d1ddb9ce229f40ce9a439b7ff0571ac74ef65dd1856e15363736005d04662` |
| `infra/foundation/costs.py` | 5630 | `sha256:1d9ff1c44ebd112a80cbea4430b4803c3efaba1bb35393065cc4c99b1f9be831` |
| `infra/foundation/database.py` | 8396 | `sha256:b2d01f3dd95dc905d577a3bd9a8451a9d0986795ac97fae4973668ccfdac4776` |
| `infra/foundation/event_validation.py` | 5119 | `sha256:67aa53a6d13c029075971a5a8c3d3503f8cac9a5f37fe3ad15ed05a4e4b0b2a4` |
| `infra/foundation/metrics.py` | 18565 | `sha256:295247eb7663dc5cae1b1c63fbbc686e78ee01f3a956cfee1c99a61a84226881` |
| `infra/foundation/observability.py` | 23622 | `sha256:a3c1b6b4e3d30aa2e2659d0b61e62651b0b27f7cbc309938e42f52e97224d979` |
| `infra/foundation/observation_contract.py` | 3776 | `sha256:df53eccee5054c42482eb33472b6e68009db0b14df4f1aafb8f696ae33cddbc7` |
| `infra/foundation/outbox.py` | 26570 | `sha256:a6d67caeba09688a547d4545f09f92ea60d674201be7a062702ba5bc16e54ff6` |
| `infra/foundation/platform_contracts.py` | 3526 | `sha256:2c3ef579c799afe430c13c1a44bcdb77eba0ef3f6d5060b68a1280db769a8c99` |
| `infra/foundation/redis.py` | 10940 | `sha256:fc4b2ee4818332bc20d09d36c4e2082dc181a02ceaebe716ba006a0916128cdf` |
| `infra/foundation/storage.py` | 15613 | `sha256:d5312f8641d549d2a131d2354a2641cda416af3f171fc897f39cb5d324f05e06` |
| `infra/foundation/task_claim.py` | 18678 | `sha256:baf1edb6b054fb7343c8c51b28031019af47f935e5462a1656d7473886a350cb` |
| `infra/foundation/task_failure.py` | 29891 | `sha256:a589cb75bafda68ad0579c78d471a63aeb402f133dc6b45d2939f9c8a00b6853` |
| `infra/foundation/task_failure_facade.py` | 1556 | `sha256:8bae213dd0123c039b357b4e4e90c323e5e432a2453aa82e0d4fc8da809bcbd9` |
| `infra/foundation/task_queue.py` | 13753 | `sha256:a93da17c9e8f3f85c2e46ba8a4fa73419ffbc57b01844c1eff1bb5aa3b1050b6` |
| `infra/foundation/task_replay.py` | 13707 | `sha256:15fc069430d8f28479053c79768c4e93502ca0f99814e6d6f4094d75ab0e67ec` |
| `infra/foundation/testkit.py` | 8356 | `sha256:e8c6ec04836e940bbbc552e8b50dcf46392b7a78f9d5b8ede885f2c068a6ab43` |
| `infra/foundation/tracing.py` | 8035 | `sha256:25be4e1eb3f2f525fd4f2ad511468a267f981174e2deb7a9295e996b7f1379b0` |
| `infra/policies/README.md` | 240 | `sha256:c7a0b5a63ec214200d578632ad4c1c3df57a035a4044b80606c73bcd044c1e53` |
| `infra/policies/data_processing.py` | 3736 | `sha256:3d2ccb3cfe0060fd059f621502d16673f2cb8af8d22966e0efcc8c48daf00a52` |
| `infra/policies/operational_targets.py` | 3416 | `sha256:443362dd11e2cc16a86b1d7813c3ec955e269adf97f992575e4145e2ee5c0e03` |
| `infra/policies/real_account_dependency.py` | 1724 | `sha256:bdbdfb89ae9935142e795b742396bce1a64b74637e2364ef1ab961b643c97999` |
| `infra/policies/vendor_inventory.py` | 1778 | `sha256:7a53a4fe5bc18d8c0e965bab0c1b439cdeede18bd3afa8086442e728b2b353da` |
| `infra/scripts/README.md` | 232 | `sha256:3133305471dea545dbf7503d1576841b6b72000737f4433e0f7682b253af8a40` |
| `integrations/__init__.py` | 65 | `sha256:ecd92f6702d3eb8d52976df2b51be0f95245a83269ac4a1a7be3910e8f43d866` |
| `integrations/langchain/__init__.py` | 971 | `sha256:41830854d6cd7c2018d664e7b7d0c12196c7c274c0fe8b0891f54ce0e702a170` |
| `integrations/langchain/compatibility.py` | 1520 | `sha256:32b9cd3239235340258f18c66d5b9618aebf887744e1b22566eb8045a6e101df` |
| `integrations/langchain/model.py` | 5198 | `sha256:ce8211c99c93dc7f9272e793ed77cbc8aeb4758c7915cc4f3b26b77b362c0506` |
| `integrations/langchain/parser.py` | 1949 | `sha256:24dff22112d59e8a48fed5e271946fe4ee528b7d27f3cf9280edf2d1d749fbc4` |
| `integrations/langchain/prompt.py` | 2707 | `sha256:6d8e6202e5029e2376cef66dfd3fe646e223f923f14d41a28677117984dd37e1` |
| `integrations/langchain/responses.py` | 4503 | `sha256:d588b95939c5fb291465c11aa09aa74a90422108750f8da67b291fcc9b3a405b` |
| `integrations/langchain/retriever.py` | 1617 | `sha256:a47c534a056327241b70227a7e48738dd53dfcb110b1ca66239228de6f2cbe87` |
| `integrations/langchain/tool.py` | 2666 | `sha256:a7b1bfdddcc4c9522cdfb2702791daee7f582b1c190448cd4afd16bbd1a80a80` |
| `modules/agent/__init__.py` | 1250 | `sha256:162e013fb16322fe03b8b02f3c4b52d5aa26ce3be8cdac621971ae1631e3744a` |
| `modules/agent/ledger.py` | 3118 | `sha256:f947fa4bbffca62d1fb893ed224e04f817ee5ed463884426174cbab5432c9ee2` |
| `modules/agent/planner.py` | 9254 | `sha256:b1cf373c4e4ee48498c83faf773806c4f6b6bb3b20331247537982a6933bc31f` |
| `modules/agent/qa.py` | 16993 | `sha256:b09e3fbfd69bff1ce716782b306299ab907299787007f63ce580c0198c0a4c80` |
| `modules/agent/registry.py` | 4292 | `sha256:7a338dcde397bb94916910aaa3696f246773d2489e5132e0243f0360860c761d` |
| `modules/agent/research.py` | 14723 | `sha256:345df13d9f4f74de926405013aed12cb5eb2978c4e0e7425bd53fb1d74fcaaa2` |
| `modules/agent/rights_provenance.py` | 19521 | `sha256:9502a1bc757c439023bc840a6a3855872297c794b9ffea34b5c44fc8baa2b9f6` |
| `modules/agent/runner.py` | 3858 | `sha256:629feba1b9dad6215784d89cf4bbfec6b1a764a2c557bea98227db2d75f38850` |
| `modules/agent/tools.py` | 2288 | `sha256:6fdf828bee5fc3253e7ad10d68f707b8cae2e30a2a3dd54e636fde78bad303c5` |
| `modules/agent/transform.py` | 22267 | `sha256:8f111e4c242f8e1b6c65bbea2a3162977701affa961d0d6262bd917e89787629` |
| `modules/analytics/README.md` | 2383 | `sha256:6477ad36c8cd1100aeef841e0ba6a5cfc26862c212993aed40ab37df662170a5` |
| `modules/analytics/__init__.py` | 2104 | `sha256:1e10a8a5bb62a97018f96ca2c1c98db8280e117a1daf77befee6fb7238bee57b` |
| `modules/analytics/application/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/analytics/catalog.py` | 37142 | `sha256:9c908192a044b7f9446d5cd862b50eda12f5cb41ee1dbea3e1bf982c6e6c6e19` |
| `modules/analytics/domain/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/analytics/geo_quality.py` | 17234 | `sha256:d6b50a7bb8a2d61326f852dbc1a2f14f2077511f7da6d0c954889b15821a03b8` |
| `modules/analytics/infrastructure/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/analytics/kpi.py` | 25417 | `sha256:6eb7de07752055fb69fe9a34235acfe0b7f8e15f8c82bf11416d0db07649c205` |
| `modules/analytics/observation.py` | 30715 | `sha256:38bf1c41cb6dbaa55403016b80b244ead2347e28ce79de3a5bdac86d0aabe2d6` |
| `modules/analytics/ports/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/analytics/projections/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/analytics/service.py` | 114 | `sha256:69adb2276cb72e7644c0b2cbb45edd06df428414efa45a7b2cfb47dc9f5580e0` |
| `modules/approval/__init__.py` | 164 | `sha256:d1592badd9d7516e13d290ea646d4a8acc2f195767d808cb8a9e6f9e16a9f4a4` |
| `modules/approval/service.py` | 22996 | `sha256:e0afd07b7567e983b85189e8cf37b35ff94b6e30203f96b86749ca7afb3dc669` |
| `modules/audit/README.md` | 988 | `sha256:5164a06bf25887c90400660854b7163bc65f0dd6dc1b41b37afb23e1dc799161` |
| `modules/audit/__init__.py` | 914 | `sha256:a97b9e009fb27ba0a23c4f91a46e0de76b708b0d0a8177bbf6418323d506c34a` |
| `modules/audit/application/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/audit/deletion.py` | 21857 | `sha256:ca4c91f85174962362b1f62e1607608e32683a26c4fc65efb6669b78d25f616c` |
| `modules/audit/domain/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/audit/infrastructure/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/audit/infrastructure/audit_schema.py` | 1004 | `sha256:1b5e88fd72649fbb47b8c5582b0f5b250162ddb4139d597a5215d2554775945c` |
| `modules/audit/infrastructure/deletion_schema.py` | 950 | `sha256:3ea9b517a8c86875375e591a027d3031432e4afe277fa27a0be243014652961d` |
| `modules/audit/infrastructure/local_recovery.py` | 8254 | `sha256:5dfbd1435c6a8236952190bda1065d8ed4427085a36edd584dd510d3e6fdb522` |
| `modules/audit/ports/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/audit/projections/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/audit/recovery.py` | 14142 | `sha256:c6cf47b46b12eca2a475f54d2d0e077ae954ff872a969139b43e157e9f3c58fa` |
| `modules/audit/service.py` | 17918 | `sha256:0e55943c627c86bc9cefd3c30970c6c7873c2aa68fbcd4c496c15c0383018e9d` |
| `modules/canonical_content/README.md` | 981 | `sha256:2e946a46964c5748dda89f7807c7c47c82f8ad00149ccb2270131052c479a825` |
| `modules/canonical_content/__init__.py` | 343 | `sha256:f2f6ac5de0f15274c60ef341de577df5317809f74c4ec613b002f5a50a5302a3` |
| `modules/canonical_content/application/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/canonical_content/domain/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/canonical_content/infrastructure/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/canonical_content/infrastructure/canonical_schema.py` | 11237 | `sha256:13c979cc852eec0712fc20de2a3f5cad2e335d967b700bf042eaaffd7684eb4a` |
| `modules/canonical_content/lineage.py` | 11348 | `sha256:5582813759b6b141266216df7d4787f60a523c7df9dcafc6e5ec6ad70d6058b6` |
| `modules/canonical_content/ports/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/canonical_content/projections/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/canonical_content/service.py` | 72339 | `sha256:b31d91dddf767e258406221f6a8144d9a43fcb86811d8cde9a5d965984bf3b33` |
| `modules/distribution/README.md` | 994 | `sha256:787483e08928d109818b917c5d929aa3ef8859bb8bead15dcf6e1927ac05c28e` |
| `modules/distribution/__init__.py` | 2357 | `sha256:fe221caa6043bec6b75e2c878fa3e6ad9cf7544bbe39c6118418d9f5def9f450` |
| `modules/distribution/account/__init__.py` | 424 | `sha256:749f177fd52b3ce1d5ffd03a432f9163f157872bb777ed7d4b538d17a13e48e7` |
| `modules/distribution/account/service.py` | 34488 | `sha256:3ad1d57ce23ab9fdfd4646fd584cbec8333808ab211cff49417f9d9c46e36632` |
| `modules/distribution/application/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/distribution/deadletter.py` | 26876 | `sha256:743a1cf43fa0de5722c18591f5120d72fad5aee8e3c78da4a284c3360206429c` |
| `modules/distribution/domain/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/distribution/fake.py` | 18690 | `sha256:2d84958aa65bfe00c44b8e7b8625f6a56ca9fe32f1fec83925359d3bf2175773` |
| `modules/distribution/fake_workflow.py` | 10274 | `sha256:b486f9bacce551d9a3b8f76112c1bec1f75c4751c6e63d0de91d3d43706e1fca` |
| `modules/distribution/idempotency.py` | 7385 | `sha256:b3128463138fc54fd3c11327c1acc382770f3c86c07ce6f8e87089b5e841ee48` |
| `modules/distribution/infrastructure/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/distribution/killswitch.py` | 11519 | `sha256:601916ef49a63726739862d0e75601e4f082f03a9d1c606851f6d200486053ef` |
| `modules/distribution/manual.py` | 12030 | `sha256:f0ee346caaf5ca17d801c72ae4637b56e73c7ecb46866eac26c3bedc41366420` |
| `modules/distribution/matrix.py` | 7026 | `sha256:a5f92bb8a6fdb0a9a4144265b1e6f5240606e316c8968925a8da7059a83a5bb2` |
| `modules/distribution/oauth/__init__.py` | 691 | `sha256:c4ed3eb98e9718b592fe476fd8ba12487d9fa23141c2f8e25444a07915fe0913` |
| `modules/distribution/oauth/service.py` | 31761 | `sha256:3c6b8a46c22862318efa1cadd4294f3d30133d1689fb6a2a93c5e8a2cd1b6870` |
| `modules/distribution/package_storage.py` | 17473 | `sha256:ff459bbe1df36375c3c217b37c7d8e69c4a26e1d0df70a8d6fabb1a0664a500c` |
| `modules/distribution/ports.py` | 8006 | `sha256:7ec689102e54847a40f2542eea7f9bdbba4e5b7f993852a6d4a72202fa28abcd` |
| `modules/distribution/ports/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/distribution/projections/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/distribution/reconcile.py` | 7871 | `sha256:c63adf278ff3598470eb1d52f1e44d86936ffb6fe4c19efedb851e6832f4cd49` |
| `modules/distribution/retry.py` | 8489 | `sha256:c4914947396dd2e7da403684c13bf0441a37fd96ece886d2920d2b5ab0d8d2ee` |
| `modules/distribution/service.py` | 41880 | `sha256:be5dddf6e274d4966b50c3bdbc9457ead66a11de421bbfd7d4907edeebeeb47f` |
| `modules/distribution/vertical.py` | 7395 | `sha256:25a36dad477cac04ed8910c790be7079ae18fc0b3162c2f670cbdcd1e46f7110` |
| `modules/distribution/webhook.py` | 15439 | `sha256:70167785c98e14a6666761957891e5396948254589bde5ab2eed2f04a68739bd` |
| `modules/feedback/README.md` | 1416 | `sha256:76e1e4d95675eb9abb66226a40baf6183b93c7b9b08015d7e14e8ae1d2c2da89` |
| `modules/feedback/__init__.py` | 292 | `sha256:6de03fa123fb13718b44fd313b3a80a71047eac16082f873607ecde5de85a540` |
| `modules/feedback/application/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/feedback/core/__init__.py` | 1327 | `sha256:c206543ca9a5e897477dca909efb53c5c6c894be973725091610754ebbbe4069` |
| `modules/feedback/core/contracts.py` | 11041 | `sha256:31d35058ccbe666b12c24909606c28c0bc665ad5d576225fe78b004e79672c8e` |
| `modules/feedback/core/feedback_action.py` | 11139 | `sha256:9511091c96d1feb92260304904fcaaf0e00922ec006f20522338caac130d63f5` |
| `modules/feedback/core/feedback_item.py` | 14518 | `sha256:20974a4d8dc25a4163a75c44e710f72651d7971a6ec7cfc45e403f9f287c4f9d` |
| `modules/feedback/core/feedback_recommendation.py` | 6856 | `sha256:451899d1414724e048fb358f1cc4343139506197cdfe7faee4331b007ae14364` |
| `modules/feedback/core/service.py` | 13825 | `sha256:31b22885735431668d37084b76d931076dfbb6452b697dae783fdcf79b64e3cc` |
| `modules/feedback/domain/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/feedback/exp/__init__.py` | 164 | `sha256:2051a3f44d482f76144923ac4b173223a14a086a3ede31d878feb1a23444e654` |
| `modules/feedback/exp/service.py` | 12558 | `sha256:21981d9a11a563d8e21b73ef601390855a36b6e7ab71ba0301d20ab31748103f` |
| `modules/feedback/infrastructure/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/feedback/live/__init__.py` | 164 | `sha256:749c27e9b20f22bf918ff60ae74c9e2c622345098d026966b6569b1ae8b26dea` |
| `modules/feedback/live/ports.py` | 297 | `sha256:aa52371e465eb089b27d57191adee6bc0b77b5c69587fb16a4ad3d928474b968` |
| `modules/feedback/live/service.py` | 14381 | `sha256:b7e02dd0ccd309ab6fdd6e53ba6bf68d3862ddaa858c90daffe93d132ddb5c4a` |
| `modules/feedback/ports/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/feedback/projections/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/geo_content/README.md` | 5828 | `sha256:22aa8c7bb68bdb36241756493ced135449b3d44a75775a1e575366e28d51bf2a` |
| `modules/geo_content/__init__.py` | 1769 | `sha256:63a3e97f0b5ba414554cae53610777f0aa3832b17ffc871f5226425ffd5b4854` |
| `modules/geo_content/application/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/geo_content/domain/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/geo_content/fixtures.py` | 44202 | `sha256:bbb1f6149090a4e4b2cb5618c27048b157bf9af1797b2de9f8ec9093dd45ed1d` |
| `modules/geo_content/infrastructure/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/geo_content/ports/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/geo_content/projections/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/geo_content/runs.py` | 36757 | `sha256:db4c84f7be6c3de42daab3e5643eb75c90aaeca66a61276903314237ec03bf2c` |
| `modules/geo_content/sampling.py` | 27580 | `sha256:40aef2cbf4115d1db79c2afe3666f2b625b40124be71a7cb6fded3eb1f6c1379` |
| `modules/geo_content/service.py` | 72164 | `sha256:0525f1fcbb65f006dda222051818cafbf6b71118d08e353583a05c2722133bf8` |
| `modules/geo_region/README.md` | 3022 | `sha256:330ef86711e8694c776b6c129432558dc9d99a52cfdf425eeb02a350e68dadd5` |
| `modules/geo_region/__init__.py` | 910 | `sha256:9e079d54bfc3d784f78d15eef051e2007c30a725e9c24a668550f982302c8296` |
| `modules/geo_region/application/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/geo_region/domain/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/geo_region/infrastructure/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/geo_region/policy.py` | 59186 | `sha256:5344aa977b3cc5407da775f6b50077946fe4dbfe1c3e11628d0b3531081bbc6d` |
| `modules/geo_region/ports/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/geo_region/projections/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/geo_region/service.py` | 67275 | `sha256:252d8889509bae6bd56960ec453115ee06ca434e259c9b3128ac9dacae2b87e9` |
| `modules/governance/README.md` | 990 | `sha256:103212d402527320243e32ac360510b4b50e1ef5c5dccb006c23a727bcd20b65` |
| `modules/governance/application/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/governance/domain/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/governance/infrastructure/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/governance/ports/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/governance/projections/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/iam/README.md` | 993 | `sha256:f12e99e2d64f12c08c540ef18ef02b8ceb041548dd2387e079ea79f757b13aab` |
| `modules/iam/__init__.py` | 180 | `sha256:b7eb59b5fd7f1436f985008b4e177a12a2029c04105ca33406af33098d314052` |
| `modules/iam/application/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/iam/application/__init__.py` | 119 | `sha256:9369e8576108c0a516fbc66a99e8ee4e6477b015aae6e7f4dfafeebe16990031` |
| `modules/iam/application/service.py` | 12910 | `sha256:2f877eff767df8784634841f93e69602ad570943851008e600cccf7611a4e8cd` |
| `modules/iam/domain/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/iam/domain/__init__.py` | 189 | `sha256:b4f0d22d75f7f293903262881bc4e3cf9b29b8bbdfbd57c7898c94cfe59d8095` |
| `modules/iam/domain/models.py` | 3009 | `sha256:6a022453cfa2b5069260a90bdc3b62a11bfd4528997a6f5063f605667fd16931` |
| `modules/iam/infrastructure/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/iam/ports/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/iam/projections/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/knowledge/README.md` | 977 | `sha256:052dce04a45312993b011df4680dcf571c19ab7a31a34f9dd3ded5c3bf657afc` |
| `modules/knowledge/__init__.py` | 389 | `sha256:dd29356333714384a2143a34c658cf64f6a79a79e792ab051c8926becc580bf2` |
| `modules/knowledge/application/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/knowledge/core_service.py` | 31496 | `sha256:c38204b6796754eb1d1fdc6df2dd296ad3b96f185cff78db69848c9031233c4d` |
| `modules/knowledge/domain/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/knowledge/infrastructure/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/knowledge/infrastructure/knowledge_schema.py` | 14473 | `sha256:a5e1913ca5b1746f98a1bae8f8d5c45725aee05ac6c9e7d58d61addec215efae` |
| `modules/knowledge/ports/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/knowledge/projections/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/knowledge/service.py` | 55797 | `sha256:ab135c9028056b2c019ddd9cb64e01daab74b2e1c97886f15924d07ffaa87ef8` |
| `modules/media/README.md` | 6942 | `sha256:394381f5124f9e5279fc041edb466052e984b7ac0763689f647bbcafc4d85d34` |
| `modules/media/__init__.py` | 5809 | `sha256:0e08954dcdcf150dfb4077482912ad59f7e7295114d20e55c0473f9f973d1802` |
| `modules/media/application/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/media/domain/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/media/infrastructure/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/media/local_demo_generator.py` | 3186 | `sha256:17eb781f36cdadd86208695aa4b7748d843e14b1b54b175b7dff70f78370c206` |
| `modules/media/media_asset_lineage_service.py` | 24465 | `sha256:79a16fa7e2b28cc9b47282249b519b49d5ab2cd4ae3009497d8c11b79025b77d` |
| `modules/media/media_content_qa_service.py` | 28524 | `sha256:3ddaa2a53acd45d66b44e91ada1ad78be7cf708875c3147e21be1ff3e4663840` |
| `modules/media/media_qa_service.py` | 49251 | `sha256:3faece39e75e66b33f37061c4f1ecf00536e1034f45eb5fa5907e44c3e9245c3` |
| `modules/media/output_spec_service.py` | 43064 | `sha256:7a1657bdae6ea5402644eb5d9ce9e8239d8e117da972094d3c0fbf5940b50ca8` |
| `modules/media/ports/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/media/projections/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/media/render_retry_service.py` | 48032 | `sha256:af20524d9995f189db54be7ebc39452bb177b0f0e94cd4d432b232223916e309` |
| `modules/media/render_service.py` | 48904 | `sha256:dd5c9ef07b8f42e93f765c19d3e69f536f5842cac05a5cdcc1745d07f6a903a1` |
| `modules/media/script_service.py` | 48377 | `sha256:68d5c58fd7105c2ea2c7b0e26e1381c2ae045bb859ec0cda9c7cf2c4e9d74080` |
| `modules/media/storyboard_service.py` | 42047 | `sha256:41daeabfa8b43a35d271beb3e7143ad9b43c31bbe0f128a0578a591d3d37a896` |
| `modules/media/subtitle_service.py` | 43647 | `sha256:7c71068b9acf60b23afc1c09b14606d9f2028d3f6fd5619b92f1e0c165ed19c2` |
| `modules/media/visual_asset_service.py` | 42599 | `sha256:12d44fdfdcb060c39df651d529c1bc67e309e90204017612ba58d4aa1005374f` |
| `modules/model_gateway/README.md` | 1005 | `sha256:a332ca6efe654cf4e622685c77b38a28ee562f8a1be7d6ba2509b12562e1db44` |
| `modules/model_gateway/__init__.py` | 871 | `sha256:5c29e98be94768044d5d592bb9524704d43cab3fa65a0b7970af190a6c4c4480` |
| `modules/model_gateway/application/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/model_gateway/approved_provider.py` | 8066 | `sha256:ce1256f2e219330bec0d65e0a8aa97049a8329047c39c8b4a6fea933b562635f` |
| `modules/model_gateway/budget.py` | 20144 | `sha256:e51616249c8f4cb563963158cdece5b75cbd8d4c232464ae31ab64a2c2838ec7` |
| `modules/model_gateway/console_provider.py` | 2483 | `sha256:537408ee982cf2b51cc278b153e4d84da04bc8e815db6626448b315d02c4e862` |
| `modules/model_gateway/domain/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/model_gateway/infrastructure/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/model_gateway/ports/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/model_gateway/projections/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/model_gateway/service.py` | 17409 | `sha256:7f242d7c949105e0184e9603ce1c2c291b67428feaf320cbec4f2ecae09f5a3b` |
| `modules/platforms/__init__.py` | 270 | `sha256:71a2509edfe48203d04286d4c79efc2c544bd78acdea4af4c38d7d41a89adec7` |
| `modules/platforms/routing.py` | 2636 | `sha256:e351d481aefe4619b139333a0cfbd2bc0d1868b2a1a0811cb60f74c416b6606c` |
| `modules/policy/README.md` | 975 | `sha256:954bd9759bdc72358078bfaada95d1abc3ca7de4e4844eb865808379e01ee55a` |
| `modules/policy/__init__.py` | 132 | `sha256:28504aaa39143f70752288a9ffc05d41c9638c5953f7d09e48672619317da930` |
| `modules/policy/application/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/policy/domain/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/policy/expiry.py` | 7523 | `sha256:eccd3809dd11d810e48cb5bb1df5a9fd2b958363ac7278c46e21d4297bd31c11` |
| `modules/policy/gate.py` | 15943 | `sha256:aaa1c4447c50d145d7c6249e8524a0061801a7c526702237ec8a650aa5748f3a` |
| `modules/policy/infrastructure/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/policy/ports/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/policy/projections/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/production/README.md` | 987 | `sha256:e48a2227bbd3f1ce7cdab28aada05559cabe626f2cd525cfa1e0e51f57b41712` |
| `modules/production/__init__.py` | 513 | `sha256:61d46dcd05748aeadaefcd3c661d052630d37df07d28f4232c7a740f3145618e` |
| `modules/production/application/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/production/domain/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/production/infrastructure/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/production/infrastructure/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `modules/production/infrastructure/variant_schema.py` | 3526 | `sha256:76dfded0209f974e6ddf0c04b382d47eba1e25747b8219eeaeb090a275e204ca` |
| `modules/production/ports/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/production/projections/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/production/region_rules.py` | 14096 | `sha256:4ccd22d4e5d25652ef9db3125508bc63ecef6daca423b32aacd63fc31b8309b5` |
| `modules/production/service.py` | 10710 | `sha256:5f1a2e28ba76256f833da8cd5c3227d947059d63ff5bde98faf84c9ea93b7aca` |
| `modules/production/terminology.py` | 16189 | `sha256:4750332098e0121dd96c0a55ee6bc57cc5707dc78047d44f5abe4cea9ea9b358` |
| `modules/production/variant_store.py` | 16845 | `sha256:33c5f94ecb38d3f78ddfea18c8e6bf36f44c167395bd2fe33cf8c638c1b5b928` |
| `modules/provenance/README.md` | 985 | `sha256:bc25550431fbebf44d1901ac35485c932c2d8c770b045a629c7d17f2269add7e` |
| `modules/provenance/__init__.py` | 474 | `sha256:716749a82abae9d0578728126bcb9e6b3579ad4ac8d64297d23fe6e5b8c5143a` |
| `modules/provenance/application/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/provenance/domain/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/provenance/guard.py` | 27213 | `sha256:f90a0e2b8eadc8e8282200de62f4d20487e93eba32109996f1dc07593d0fd15d` |
| `modules/provenance/infrastructure/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/provenance/infrastructure/rights_guard_schema.py` | 3844 | `sha256:85477b41b0a394632fbc47585a47f2c9835f4fb0bfc98a0f17e9af63f0129922` |
| `modules/provenance/infrastructure/rights_schema.py` | 6316 | `sha256:0a5bd066fcf7a2926d8d634dc812913099d55dfd6cff58fff50b50bb49583313` |
| `modules/provenance/infrastructure/source_schema.py` | 3689 | `sha256:17b39d350bdcdd5bdf0e841a0927101bc20de7f2630c7d5023af7bbf3364f890` |
| `modules/provenance/ports/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/provenance/projections/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/provenance/rights.py` | 34287 | `sha256:f91e7afb7700caa11292c57f2599275b026037d200dcf4bd07202396b4527c03` |
| `modules/provenance/source.py` | 30406 | `sha256:a3a489adb0349240095b438eb9c9e604350a2244ed08d8211c82c30ba32a921c` |
| `modules/qa/README.md` | 986 | `sha256:13ad3920eef42c5a5c8382028f59d2f59018f584068a0945a9cfe6efe03fc17a` |
| `modules/qa/__init__.py` | 442 | `sha256:be3712d0880c8e5419ef5b090c7b7b7089bc65652990367419effc63a7f78a83` |
| `modules/qa/advanced.py` | 16893 | `sha256:0bb41186256aaef73c736fea9984430ed2601530f78d2e2bd60baa2411bd587c` |
| `modules/qa/application/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/qa/domain/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/qa/infrastructure/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/qa/ports/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/qa/projections/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/qa/sandbox.py` | 15590 | `sha256:6c09e84bf9dd3683f2fe64f1901967d3706c62b03da2a80042230706f5f6a950` |
| `modules/qa/service.py` | 19049 | `sha256:ff3e9c17c3a72dff3cbbcdd80917986fe0cd32f6c92719bfcef43387131c61e9` |
| `modules/support/README.md` | 976 | `sha256:6c1c721d0d7d03658e5b5b85b5621ed22073eea1b51bfb394fe7fecf1228f4fb` |
| `modules/support/__init__.py` | 178 | `sha256:de732bddabb7325d292b7371f827ebc6acc09aff4d23d61acddf2a0d48569fda` |
| `modules/support/application/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/support/domain/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/support/infrastructure/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/support/local_reply_generator.py` | 945 | `sha256:7d0e61628a277be8b8a52756245da6eda17515a9d6c2557177a97ac241d3ff8b` |
| `modules/support/ports/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/support/projections/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/support/service.py` | 11485 | `sha256:4185c82de63a03e63ce66a327774ef0facd4361959c9eeebda75c334ab73735a` |
| `modules/topic/README.md` | 988 | `sha256:95494c94fd3731226bbc2e92678b83f43e4c2ebcc617f3cd0e2076881a5e6923` |
| `modules/topic/__init__.py` | 756 | `sha256:3994949e6a6a237e5470afbc0bec159f8b5dce8e4665bd83dac796da0a9d403a` |
| `modules/topic/application/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/topic/brief.py` | 29865 | `sha256:78c803d14aa727ed4ba944670f2cfee1404ec826946fb46ddf9b6f6584715fac` |
| `modules/topic/calendar.py` | 13082 | `sha256:253693b79f35106f985c06b3329b672daacb31abc29eb2fb6732d3e33365ffa3` |
| `modules/topic/domain/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/topic/infrastructure/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/topic/infrastructure/brief_schema.py` | 2961 | `sha256:810b4cd62ed9c85eb87f309cc6c567e03f5fc8a56fc0ee5bf68510c581f01d89` |
| `modules/topic/infrastructure/calendar_schema.py` | 1636 | `sha256:5927eae5a02db0f04cf775f8dafd903eb7ca16e5b85f874495ace0a011cc3608` |
| `modules/topic/infrastructure/opportunity_schema.py` | 4128 | `sha256:3e4e1b4025c655e890513c1651aef0dab2e27654067932d6fb68607bebb0a79a` |
| `modules/topic/infrastructure/signal_schema.py` | 1588 | `sha256:e19c9add3d42e7e868fa4827d290e5103c6b2b38b943c2527f83cbb83fe15e42` |
| `modules/topic/infrastructure/taxonomy_schema.py` | 630 | `sha256:d0a39ce1a43cdb9ea617825bacf38e2b3aef4b7c7f78ea148461cec8b5b80cc3` |
| `modules/topic/opportunity.py` | 30186 | `sha256:2a29fad35744bb43fe5eff8eb895ff16cc56702f172563b01a799e77894804bd` |
| `modules/topic/ports/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/topic/projections/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/topic/service.py` | 13810 | `sha256:fc50114a93806ca86502f54a7dcadc412193261e1e1b949839eb834c3602e2b9` |
| `modules/topic/signal.py` | 16232 | `sha256:3d532e3386e0dacd702c65d9d19e63fd2c6b9014b6406abf3e05b5b9feab0a9d` |
| `modules/workflow/README.md` | 986 | `sha256:506b415e138876f9129eb7d4804a55ca45cbdd2d8639fc1df8f2d73388c194bd` |
| `modules/workflow/__init__.py` | 339 | `sha256:23b497464e97fd28c5a52a14954f8b15786488d1918a9a4825faef47ff1850af` |
| `modules/workflow/application/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/workflow/dispatcher.py` | 18018 | `sha256:32a06d410979efeef4ffebb0c3fa72d159d964ee3675ee66e896e6ebdd735b0b` |
| `modules/workflow/domain/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/workflow/infrastructure/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/workflow/ports/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/workflow/projections/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `modules/workflow/service.py` | 10085 | `sha256:d9d3bc0c365a45941d9a804018502207bc9a4366c7d55a0c9917e904c5ec854c` |
| `orchestration/__init__.py` | 1161 | `sha256:a61c6f626ebcc575959c33733282e81e6fd4f5bcf01b9a55dccd41ef3716dc40` |
| `orchestration/checkpoint.py` | 10239 | `sha256:3bac1accaf29fd0efb0340280846212353f2568994901170fdcc6d7e15cf39fe` |
| `orchestration/checkpointers.py` | 286 | `sha256:f3d1f9d438a35d3890da377ffb371f3124ca7f0b3743709d16e1a79b09b6d004` |
| `orchestration/content.py` | 2504 | `sha256:529811539cb52d75bfd660a40280ae7b1df0794fcd278827a78ae26ce4360842` |
| `orchestration/distribution.py` | 1122 | `sha256:c852a35374868ded312e4d5291c0c8c65315373ebf2a15c4a066a494d077b40b` |
| `orchestration/errors.py` | 824 | `sha256:09f9dd7bf22f52cab68c2417769fa962c82f0a34d1ff3d3b34ce8f2671b9afce` |
| `orchestration/evaluation.py` | 1462 | `sha256:92d3d0c8b9f5d645e04297fbec5a94093873ce0dee5566f50d954a458a3aa14d` |
| `orchestration/feedback.py` | 1561 | `sha256:ad9204de61ebf5d9988561a308a3749f64f94f525ddfb8e1dc0f399e7509a526` |
| `orchestration/graph_registry.py` | 206 | `sha256:a79c62992347ba1e5e989ee2c92b6862ff8e76b6b72c9ed70f328eb847b4e57b` |
| `orchestration/graph_runner.py` | 205 | `sha256:325f2922537e5160c183c90f5e5d6271122f5341bb869da0d71234e36abeea50` |
| `orchestration/human.py` | 4487 | `sha256:6516a93d184ffa734cb3f49b29e1b3af0547a635476a0608eb2734940e6943f8` |
| `orchestration/langgraph_adapter.py` | 5475 | `sha256:514509c5a52ecbea9e6fb69313dcd693d84bd65c8a8b2605317e649c24407c9c` |
| `orchestration/nodes.py` | 2868 | `sha256:601528997e1d2b2bebacaaf815f876d902b879eac28543dbd816dcf4d9f88040` |
| `orchestration/observability.py` | 1402 | `sha256:1f778e56ab06f2124a3bbc34ff99b8b30feb93c696180c283cef88c97ab730b3` |
| `orchestration/reducers.py` | 772 | `sha256:ed10203e8f4003611e1bfcb4f6b06699513fceddcbe74c92f977985bd3fe8899` |
| `orchestration/registry.py` | 4718 | `sha256:d6604e1235398784b8c389bd4a970a097d4047a6bb0b5cde4431d7a0311a906d` |
| `orchestration/replay.py` | 2531 | `sha256:531a0aa030cf5d825518a611fbd41d4409b9ce41b2d154f169b3a0ece53aa68e` |
| `orchestration/routers.py` | 938 | `sha256:c8a1d37c7993e01647a65dd1b67d92de39fafe842594b7582fa48c9ebec39497` |
| `orchestration/runtime.py` | 24594 | `sha256:621aff3bcb07dcc00d26ba55d6ce8d4030e4ded9d50557fd3a72afb6948c780a` |
| `orchestration/state.py` | 9253 | `sha256:23d666fc81d8b9a3dec7fa3856b0578cd98daeb7b708ed6a697a7723a633774e` |
| `orchestration/state_lint.py` | 1154 | `sha256:a5abb2d4338defa1a1888ab59d4786d5b0bc2b0f615025a2e02bb24736f2a92a` |
| `orchestration/task_bridge.py` | 2698 | `sha256:5c029be19c2f811a4705c516b8911ca0a6a58e8b3f68de9687265ec17baef7d9` |
| `orchestration/topology.py` | 1348 | `sha256:1d7e090c957f9a8b56753ea32d37b3935539c8d907a1a68f9b667e7de67f4ce4` |
| `packages/contracts/README.md` | 1537 | `sha256:8d83f1b0270387e4df69f4680b5e20a2aa6f17ad09b9616a3aadbfdcebc3c1b7` |
| `packages/contracts/events/README.md` | 194 | `sha256:2a610edece9ceefce1be8d0453c1444acf7fa65c55b60cd9868cbc73ff160886` |
| `packages/contracts/events/account-connection_changed.schema.json` | 1804 | `sha256:6cfc5f528de4bb3ce3f4bb59a8c30d0e5a065b461db339fa70f22037175d72a9` |
| `packages/contracts/events/agent_run-completed.schema.json` | 1784 | `sha256:4fa7a52c952cb8b8c155add472adac8110100bed61645fe7c2479e2250fc19e8` |
| `packages/contracts/events/analytics-asset-observed.schema.json` | 2398 | `sha256:e9ff70cf19fb946452485bbc1161541d376d2395c790e33d1d1a5d2b7e4ea086` |
| `packages/contracts/events/analytics-content-observed.schema.json` | 2512 | `sha256:0294a61e50efa6663c4e23edcc03cc6a8eee9f1c56ed448404e560d8050a7912` |
| `packages/contracts/events/analytics-cost-observed.schema.json` | 2667 | `sha256:2991b9e456c6ddb9eb375f900d758b398c32c2d7ffd5ba0cd03ecf114d0d5866` |
| `packages/contracts/events/analytics-geo-observed.schema.json` | 2446 | `sha256:0dc2ec2d6eaa14d077d364b4b57eed60ba4498edb2c478eb3b4926f3906aec3e` |
| `packages/contracts/events/analytics-interaction-observed.schema.json` | 2515 | `sha256:6f0fb8b4f4aaed5f33f609b04b0f51ff9a934e560c4f3f9c786abb018e7e8799` |
| `packages/contracts/events/analytics-kpi_snapshot-created.schema.json` | 2339 | `sha256:d1d3a40cd1a1b05db00d1052ac7c1d1d1545cb4aafbf9b4be37c1ffe4ec8c77b` |
| `packages/contracts/events/analytics-publication-observed.schema.json` | 2434 | `sha256:f41ca91e75c3850173750b709478394ab14f34c977347a77e29a4cfd8ae2e042` |
| `packages/contracts/events/analytics-qa-observed.schema.json` | 2495 | `sha256:c8a1694697410fb6d43e8ad31d716b16e05e895c028a286aae277d0a1a709084` |
| `packages/contracts/events/analytics-risk-observed.schema.json` | 2667 | `sha256:9fc05519cae7fec6a68885044bd4425c931b832fb252cca0a25ce67c5c15de44` |
| `packages/contracts/events/analytics-support-observed.schema.json` | 2445 | `sha256:10a06ccc2260ae1cc1d492e2fd20b08c50d76bafb7cbe042da534bc8fb54deb1` |
| `packages/contracts/events/approval-approved.schema.json` | 1777 | `sha256:657a12d38eb6c87f9e9d838b54325d8d0d841ac5a2dc8a4b55da408eff646117` |
| `packages/contracts/events/approval-decision_recorded.schema.json` | 1804 | `sha256:85c021d84060fa0f2d59a35c73519155ac6d2855e414c294fa28d84f241dbbf0` |
| `packages/contracts/events/approval-expired.schema.json` | 1774 | `sha256:18804eda94d2a172f1a71d383928931d99c46eb4ae2c6e49c442fecddb4a5654` |
| `packages/contracts/events/approval-recorded.schema.json` | 1778 | `sha256:a7c53b464df20eaafb324eaaabbeb3aaef56de8120100d15e4d82e5054e293ef` |
| `packages/contracts/events/approval-rejected.schema.json` | 1777 | `sha256:3b46c6a81fa1a1cc39ff1b9275c4bc190b41fb255c667a7114c36a9076b1e95e` |
| `packages/contracts/events/approval-requested.schema.json` | 1781 | `sha256:13f38820d34fe0c6c664fdea8cdff3d9e84104dbbfb6f453b90d37e509c0d399` |
| `packages/contracts/events/approval-revoked.schema.json` | 1774 | `sha256:202e2435db7927f9e102f0f6874dc209c37b3f4011110ed8631a0905af7c8c22` |
| `packages/contracts/events/asset-approved.schema.json` | 1768 | `sha256:76e3eacd02efa986b78b9ef2f91a0b3cb825434293bb085c6dbb652b6d5961af` |
| `packages/contracts/events/asset-blocked.schema.json` | 1765 | `sha256:2f59876b560d29dddd28b5229372beb9ee5fac42734dbccfaf6f3bbb867dc0ae` |
| `packages/contracts/events/asset-created.schema.json` | 1765 | `sha256:2820b5ed2dde12beb8dc368e8daf13afbe5c65598f47fdc3922237589449e969` |
| `packages/contracts/events/asset-qa_requested.schema.json` | 1780 | `sha256:292880c1113e3d40a0bce378ab714eb74d75c35f54c3ea42f87db8d1539127dc` |
| `packages/contracts/events/asset-render_dead_lettered.schema.json` | 780 | `sha256:1d2b07fed79e5c4236bc54433d2c588a8d052b98db4914a75cba32e552b4cc03` |
| `packages/contracts/events/asset-render_failed.schema.json` | 833 | `sha256:a2d258a6d68085391936b305fe4b72fc3cf52e7b8ca14a076930d38248bc1857` |
| `packages/contracts/events/asset-render_retry_scheduled.schema.json` | 860 | `sha256:d64278b251b5be28c9265419ed85e7972d3ca0fcbf42b71368e75f3958552881` |
| `packages/contracts/events/asset-render_shot_rerendered.schema.json` | 921 | `sha256:884024dd354dff7c6aea330cb87d8e9b071f9f297cda1eb84ebfb4480fe171cd` |
| `packages/contracts/events/asset-render_started.schema.json` | 1786 | `sha256:8f70d49225fa0af506b051ae67b2673519e401f51204277bca5c0d192859f090` |
| `packages/contracts/events/asset-render_unknown.schema.json` | 825 | `sha256:b88a75693d58cb7fbd7b0751270148cb9832b46d1acfc0311978a4501bf71656` |
| `packages/contracts/events/asset-root_changed.schema.json` | 1780 | `sha256:d476f062cd9f15938c70acd1050b8ee2adbdab39f1365be868a005b617e372c4` |
| `packages/contracts/events/asset-withdrawn.schema.json` | 1771 | `sha256:d21bf3cb925b0b2def975aea8cf8e591039390fb7e358e576ec41dd3d92fd00e` |
| `packages/contracts/events/canonical-evidence_requested.schema.json` | 1810 | `sha256:292fcdb6f53904a30eb03a4df3e0f4bc283e2c11c5c089898f6aafb15f7d6fe4` |
| `packages/contracts/events/canonical-fact_checked.schema.json` | 1792 | `sha256:415c947b00d78bfd40795dfd9b52867ff3a7d142ba698df407d8275ef39f43fb` |
| `packages/contracts/events/canonical-version-approved.schema.json` | 1804 | `sha256:0be0972f1e8f06e2fe5896e07c0e58bb005cb4372f0ac27ccaf2527885cb15ea` |
| `packages/contracts/events/canonical-version-created.schema.json` | 1801 | `sha256:73665334f27db9c362e8feb5c5a30ffe5dc7df86b9b38c84ec6ce748c0524ad0` |
| `packages/contracts/events/canonical-version-superseded.schema.json` | 1810 | `sha256:f862fa43bdcb866493e308a8d64b8c5b96c17552d1236785dea3ef50ea6d2ee5` |
| `packages/contracts/events/canonical-version-withdrawn.schema.json` | 1807 | `sha256:4fe8445ff54744dd8cba4517daa796bdf1e5eac79693d36cd87a66e5301b0766` |
| `packages/contracts/events/claim-created.schema.json` | 1766 | `sha256:2169d0014fa6553d4cf1399f3b0622c8b0ede3a277c560b5f48f40ed1a80d275` |
| `packages/contracts/events/claim-freshness-changed.schema.json` | 1796 | `sha256:c2cf46d8bbc5aed46d9465ca017facfce828da1cd0f2273aa56b7afc66e1a1e6` |
| `packages/contracts/events/claim-verified.schema.json` | 1768 | `sha256:34164e5912c22c1035bbc8087b858b3a43b5b0e8af4ea2fba61d7b21cf196412` |
| `packages/contracts/events/claim-withdrawn.schema.json` | 1771 | `sha256:92e4c8639421f0f94fd1943cfff032550b2df98eabcb4418126e240df66bdfa4` |
| `packages/contracts/events/deletion-completed.schema.json` | 1774 | `sha256:cede416dc3d82ada375f9629312434246b69efb2874fa10889d4012c286557b8` |
| `packages/contracts/events/deletion-failed.schema.json` | 1765 | `sha256:a04aeada7e816da3b3cef4068e72314f6a7f58a91ad80d5da198aae8804c8c8c` |
| `packages/contracts/events/deletion-partially_completed.schema.json` | 1804 | `sha256:1002666de2780e659a0c7b1f960be86ddf40d381ce5ec64231e4ccf7c2a274ea` |
| `packages/contracts/events/deletion-queued.schema.json` | 1765 | `sha256:60447c43b161045dfaa3657f84809ab355293f918939a6fd28de3f0c78a4a037` |
| `packages/contracts/events/deletion-started.schema.json` | 1768 | `sha256:40ad907fc5e1208cdc6dcf7def0dad973b87696660c9df84affafdf0968b416a` |
| `packages/contracts/events/delivery-attempted.schema.json` | 1783 | `sha256:48e0ceb812a6f993b578ce23f02b5949a585c2b43d69e834b855ae5b05a9b0a8` |
| `packages/contracts/events/delivery-dead_lettered.schema.json` | 1792 | `sha256:448924c948a676a3da8b94a02a3e79b11e726872e4e90978ac5ead5586b7abf5` |
| `packages/contracts/events/delivery-failed.schema.json` | 1774 | `sha256:b077a40be1ecbdd935b902f956f09c6ad2069474130fcbc655bdecafe9de5bff` |
| `packages/contracts/events/delivery-retry_scheduled.schema.json` | 1798 | `sha256:93ffa339e4585109f81742e450943e8306371868a25b4733b88ceb0347ecada9` |
| `packages/contracts/events/delivery-simulated.schema.json` | 1780 | `sha256:a0402998e543ad9bea3011130d05d48c331ec80a44a5ec36aa946b0c79cdb4e1` |
| `packages/contracts/events/delivery-succeeded.schema.json` | 1783 | `sha256:1638d23c5d3d616ec981b559f93518d65bf1457e38fb18cbb3b534b76a89d25c` |
| `packages/contracts/events/delivery-unknown.schema.json` | 1763 | `sha256:f68e310255eb73f0b1903d040674813d84aa03a030173d06d9b96b0b60a5224b` |
| `packages/contracts/events/delivery-unknown_resolved.schema.json` | 1790 | `sha256:10fafece2207927dd10013cb59a58bbe39661cf6aa82bd970d9ba6164fb87653` |
| `packages/contracts/events/distribution-target-created.schema.json` | 1807 | `sha256:dc8fbbffe7b8f779c0d3c0449bd5fec95bb3357d7ce7e859c2aa166d0cf680e7` |
| `packages/contracts/events/distribution-target-retired.schema.json` | 1807 | `sha256:ddefd05da983afbc6b78aacfaa49c9623afb46899a3fe1d8377ac5d38c6aa475` |
| `packages/contracts/events/distribution-target_version-activated.schema.json` | 1837 | `sha256:b8b4ae3ce7bac1a9416ef28fb8378928d0fc71c7d6778e87d1dc4bd8ef42dfe8` |
| `packages/contracts/events/distribution-target_version-created.schema.json` | 1831 | `sha256:f85559f41b29aeb98e32f1f74b8f04560ee4f8df7249775adbdb1445e627659f` |
| `packages/contracts/events/distribution-target_version-retired.schema.json` | 1831 | `sha256:6ffafbaea0260e578833eb21728c07228ab8b81a58b8b233160c83c983ec06a6` |
| `packages/contracts/events/entity-activated.schema.json` | 1774 | `sha256:63aae440e4e652b53d262ab4876833814bc9fe65afdca0f99c003d6fabb5858f` |
| `packages/contracts/events/entity-created.schema.json` | 1769 | `sha256:c6e024d1254a6c1495181b9ede8de00e9df590cebba47702cb1a0b3ec658f3de` |
| `packages/contracts/events/entity-retired.schema.json` | 1768 | `sha256:1b2672a1528cd329fc81488c84dd488ea8bbfab8fd1ad79f946fc2e057a8138d` |
| `packages/contracts/events/event-envelope.schema.json` | 1984 | `sha256:f5c58e868c857b2524828a19ab80586787f0ad9bd760f6711ee2fc3a6133e7ec` |
| `packages/contracts/events/evidence-captured.schema.json` | 1778 | `sha256:0e5222d5e4c2550b08792130eef25b4220dfca66b7be02c5404de6a359d4db4b` |
| `packages/contracts/events/evidence-invalidated.schema.json` | 1786 | `sha256:910b654489c16513969e63258663d1a7cffd9b602ff185b9f1fe824ad40c7184` |
| `packages/contracts/events/evidence-validated.schema.json` | 1780 | `sha256:0b57d93abc4906f5143816fb6318499329a8b910cd6a6361d5622acd72f4f665` |
| `packages/contracts/events/export_package-created.schema.json` | 1792 | `sha256:2265383c634c3fe1b550274c4ff875130f0ffb03914282747f1cf9bb44bce92e` |
| `packages/contracts/events/export_package-expired.schema.json` | 1792 | `sha256:8c2a4d86a00d9dc20ab5642d10f8bf5db63e3bdf3f44d090f7bf1068c56c5f63` |
| `packages/contracts/events/export_package-revoked.schema.json` | 1792 | `sha256:b120b7bac58366fe6e35adbf89e76b56a006eae03d3e8fc51edbed52d12e4258` |
| `packages/contracts/events/feedback-action_approved.schema.json` | 1798 | `sha256:9820cc9ec8504a7e144da272cd699c554e62cf9ba2e46c38a170e2964f5fe094` |
| `packages/contracts/events/feedback-action_cancelled.schema.json` | 1801 | `sha256:43591b3f56af46599cc70f55036ff2382d15b556f50da64e00015029eaf980ec` |
| `packages/contracts/events/feedback-action_executed.schema.json` | 1798 | `sha256:bbb0e1129e2382c711c816e7b7db21729f0582682521bb2db92f1c9ffdab5a83` |
| `packages/contracts/events/feedback-action_failed.schema.json` | 1792 | `sha256:eae52b883a7e021bab87846e9a39aa8cb3e6681f954c6c207e20b5ea6f5924fd` |
| `packages/contracts/events/feedback-action_started.schema.json` | 1795 | `sha256:c7c93c9902e69e1dfaf7abae299ce82c6ce01df2f0917408932bc2e9749148e5` |
| `packages/contracts/events/feedback-approved.schema.json` | 1777 | `sha256:6b8d66f933467e913f916c8fa77cc8d358d4811f923bf82518dac23e3fb0b838` |
| `packages/contracts/events/feedback-executed.schema.json` | 1777 | `sha256:5a076601e380f628f0c9ba384771539fa8a64c3a8aac5a805d641dbda70db6c9` |
| `packages/contracts/events/feedback-expired.schema.json` | 1774 | `sha256:74f0b3cd2641ddbb1d44c2423d43ad546e869d929c59caf96c20cc674e575f0f` |
| `packages/contracts/events/feedback-recommendation_created.schema.json` | 1820 | `sha256:a170c8a09e450a1c69271b76ebf82d55f3a479a4edddcf491283c76e3c8351c4` |
| `packages/contracts/events/feedback-rejected.schema.json` | 1777 | `sha256:404130a583004b4b1f94d3b5cdad652878eb9983754762f73b80a9606ffac2e9` |
| `packages/contracts/events/geo-fixture-activated.schema.json` | 1789 | `sha256:16382b57dfbe9b52c025272730abe10b78f1ba6effa55b52b0d12def6c2f6c09` |
| `packages/contracts/events/geo-fixture-retired.schema.json` | 1783 | `sha256:ce69abc0f780d3bf070bd583caf57672f1bed62cb434d25ea3b2cda6ac70cbb5` |
| `packages/contracts/events/human_task-assigned.schema.json` | 1777 | `sha256:d09191247bd854b47cad96a1d932e7a1ff3fcd7cfe77d4ff42121e168b6cde94` |
| `packages/contracts/events/human_task-cancelled.schema.json` | 1780 | `sha256:96baa42f4db9d3a2ed8fc1d79bde34a229b571accb46ea8767fd8cabdbd77274` |
| `packages/contracts/events/human_task-claimed.schema.json` | 1774 | `sha256:3d7a945fbd849769f0c5f9be68654b125be673997ca91ad17b6994b5085f3ade` |
| `packages/contracts/events/human_task-completed.schema.json` | 1780 | `sha256:063ab2ee0be5ebf44a5f0f1280307ea2ea1b547099130e96f2bcf5bd1ec6f763` |
| `packages/contracts/events/human_task-created.schema.json` | 1774 | `sha256:1ff277c3888729bf1e69613c2c1bbd6178a8e04b5df5eeddfb49a3e8b0c930cb` |
| `packages/contracts/events/human_task-escalated.schema.json` | 1780 | `sha256:a47e440ff8f214009b5b0e89d35eb2a2c6ea201fa8020bc5941923d3c47caf09` |
| `packages/contracts/events/human_task-expired.schema.json` | 1774 | `sha256:02d491867d2fcd8ad0e6f93c44abd621beac3c05de9a774c9958b7c8f35a2ee7` |
| `packages/contracts/events/human_task-rejected.schema.json` | 1777 | `sha256:1781c720d3d1fa14dc244607aeec068bab2b2fd9b949eea86f2c3a720f58cc31` |
| `packages/contracts/events/human_task-started.schema.json` | 1774 | `sha256:74df4da1476570923c2de191048bd4caf6d1aa8d863b77e60c40fd75111ac33a` |
| `packages/contracts/events/human_task-submitted.schema.json` | 1780 | `sha256:2a9753faa9da615cc8cad47aea8b98d8e87dc92ee18c5786affabb666392ca9f` |
| `packages/contracts/events/kill_switch-paused.schema.json` | 1780 | `sha256:0e4277e6578d4bbf93c1563e59265adfdf3849aa1c9ab08f2387875e76b1e027` |
| `packages/contracts/events/kill_switch-resumed.schema.json` | 1783 | `sha256:441be03e07465f8d6d25ebfce427ab1f2996ea5615455531f45f407caaf825e9` |
| `packages/contracts/events/knowledge-core-activated.schema.json` | 1798 | `sha256:410899c302ea2873df33346f3ccbf067add12d34ae1435602b7d03d188cb05e9` |
| `packages/contracts/events/knowledge-core-retired.schema.json` | 1792 | `sha256:69f5e64b601e9c827209dc8db6a6623845dff2c4735612b5a05e7878565c2381` |
| `packages/contracts/events/knowledge-core_version-changed.schema.json` | 1816 | `sha256:5d2f863b7d48eaa5bdc86025eeb3bfab1378cbcabbaec67623d2a7ad6d82a1e0` |
| `packages/contracts/events/knowledge-core_version-verified.schema.json` | 1819 | `sha256:2754a3be123cf5cc5bac5b98beab0824bfbb72547979fc9f7823b30f76f1efde` |
| `packages/contracts/events/metric-definition-activated.schema.json` | 1807 | `sha256:3f3250921eec336d9d741a10523791068bc81e2c7e4ab00511c90be4f834cf56` |
| `packages/contracts/events/metric-definition-created.schema.json` | 1801 | `sha256:8e1f61a0350172a32c6994e4e4078e6937c794eefec74ee24d058d70437673d0` |
| `packages/contracts/events/metric-definition-retired.schema.json` | 1801 | `sha256:34de5470dfbeb16b835e6b1676e61f90768270039e252a8035056b0a497748c1` |
| `packages/contracts/events/model-call-failed.schema.json` | 1778 | `sha256:9a9af9456c968d1b0ea9d995d2ac7f82f66637ecd446035b3c6938bdc2528100` |
| `packages/contracts/events/model-call-started.schema.json` | 1781 | `sha256:a0fa292f48fcff1635bb2205ff63e9ea2bf51bb466b8f556fd1160aacebebad2` |
| `packages/contracts/events/model-call-succeeded.schema.json` | 1787 | `sha256:facf26990df8a8c854b9798b4ca81a993458538fdeaa8ac9e3280c03aad3af9c` |
| `packages/contracts/events/observation-recorded.schema.json` | 1787 | `sha256:f021498741379fac0c4c9e14a9afca2732a565ec53533010d3af42f4a83fd60f` |
| `packages/contracts/events/outbox-dead_lettered.schema.json` | 1780 | `sha256:2f4cc5ec6e7c8183768e27bc495199ecebd1b65f4f5d15b61b3ce741de464e89` |
| `packages/contracts/events/outbox-failed.schema.json` | 1759 | `sha256:adef6b778e7e47e821609eac7437614506de617bc465b81e757af82f9879c396` |
| `packages/contracts/events/outbox-publish_started.schema.json` | 1786 | `sha256:e3d3820b68fd777c61393cf9bf49aa670ed8a9fcbccfcbabce745787d0e7d781` |
| `packages/contracts/events/outbox-published.schema.json` | 1768 | `sha256:333d5a3c8a6b83d8af516504f3a4b55ca58b16b7d5be20f49fa5c9c8acb80576` |
| `packages/contracts/events/outbox-retry_scheduled.schema.json` | 1786 | `sha256:4ea8008eef80a83222a1c350ce89d143c8f062f63093a481f790a13107f94ae1` |
| `packages/contracts/events/policy-snapshot-created.schema.json` | 1795 | `sha256:dc4825dac3cea1d1f70b183a88e9f035fabec6174ef8878429da7fc7d59aaf62` |
| `packages/contracts/events/policy-snapshot-expired.schema.json` | 1795 | `sha256:4be9ce14ed3d66fad797921e98d8463f9e6d3ae7ff367af3c5d6bdba49b151b4` |
| `packages/contracts/events/policy-snapshot-revoked.schema.json` | 1795 | `sha256:e8cb4ba37c591bcede417ca0da2cc4ab195fedfa8edd521f8d2bb04d6870db3f` |
| `packages/contracts/events/publication-acknowledged.schema.json` | 1801 | `sha256:f4c7b5bfba310df4b1512a2d49ce6c20f156e25ca578bf8ce20c544dca24dc61` |
| `packages/contracts/events/publication-blocked.schema.json` | 1783 | `sha256:b5e3ef53193c80d254384f364bca707bf585d756c0acbd079db217f322a688d8` |
| `packages/contracts/events/publication-cancelled.schema.json` | 1789 | `sha256:4cf79eb0719f101f627962d21c5872ad7e24c60edfa7ba812d6704170c79f822` |
| `packages/contracts/events/publication-dispatched.schema.json` | 1795 | `sha256:5cb272d3bf96d910c34fecbe9efa44634a637471d9ec2ad628eb732a60f5eda3` |
| `packages/contracts/events/publication-failed.schema.json` | 1783 | `sha256:7e59ce50b237c36cb00356b624b4c88a2371564d30fa9986a9339c8b9a6a5afc` |
| `packages/contracts/events/publication-published.schema.json` | 1792 | `sha256:be3c124777e0c80ac2af8fd8c86c252ec1fea563741ecff3d561cb3cbd1b5d7f` |
| `packages/contracts/events/publication-queued.schema.json` | 1780 | `sha256:6ca907242a154b32fe453e967696ae8a341b254b5fcb6b5fd1e0488891ef69fa` |
| `packages/contracts/events/publication-recorded.schema.json` | 1786 | `sha256:cc1217300425458cdf1dc8e23821451f83089aa5e004b2adcca83ee0d3ac1930` |
| `packages/contracts/events/publication-removed.schema.json` | 1786 | `sha256:688bcf72ad72eab328743e452a1e08441b8a9cbb926ae8dabb674fe884289cb0` |
| `packages/contracts/events/publication-unknown.schema.json` | 1772 | `sha256:5e0ece177be204cfd81c1fdf26ac215202f050efd0cafda5c8606fd4767363dd` |
| `packages/contracts/events/publication-unknown_resolved.schema.json` | 1799 | `sha256:ca1d905d346fdf280c458b33b78bfb885a65b7d566b04f6316ed025624c718a0` |
| `packages/contracts/events/publication_intent-ready.schema.json` | 1798 | `sha256:0df5284e373afcc6750e3ba434a48782f615a4950e3e639c2398020b2dd88dc0` |
| `packages/contracts/events/refresh-requested.schema.json` | 1777 | `sha256:c4e8af5aa82e57c51d86ad794a1309dede8a5163ffb1604e6d619594e21255c3` |
| `packages/contracts/events/region-profile-created.schema.json` | 1793 | `sha256:911de4d7ab7cb7f92785f1d87b82f994183740be8a8cbdef5faf697cff81909d` |
| `packages/contracts/events/region-profile_version-activated.schema.json` | 1822 | `sha256:e2d0b5550cf5e29d59c3ba5727bec9411182f30c6b705870fa0bbbdf90ae79ba` |
| `packages/contracts/events/region-profile_version-created.schema.json` | 1816 | `sha256:e49e6a0dff04ef3feb685ff3d6756c46df9862ce9d251707515824e93542bd4a` |
| `packages/contracts/events/region-profile_version-retired.schema.json` | 1816 | `sha256:922cef5600c71ec31f012f49ab3c047024da7082dc8688594ed5b843133c6c2f` |
| `packages/contracts/events/rights-version-complaint_hold.schema.json` | 1813 | `sha256:4df6b11f0f97604243b0dcdd8135832cc5b2d5f1ae34fb058d9180e66c6ebd2f` |
| `packages/contracts/events/rights-version-created.schema.json` | 1792 | `sha256:fc75f273033ff63c00aeb369c5323030634b6e70f7d287bf9e07f9def50b0cec` |
| `packages/contracts/events/rights-version-expired.schema.json` | 1792 | `sha256:cce8f4cae85a479cfbfc9233d49f513e382726927a24da0618a243f34e6731de` |
| `packages/contracts/events/rights-version-revoked.schema.json` | 1792 | `sha256:f2970d41925be46d96d800ae21cbeed6190bd62991284f194e6a5ae78baa92ba` |
| `packages/contracts/events/rights-version-verified.schema.json` | 1795 | `sha256:cd05431251b0f13b12dfb1b4a55b51178a0aaa26f811a7dc6379b47253f22c37` |
| `packages/contracts/events/site-page_version-published.schema.json` | 1807 | `sha256:32b993b1cf8102c3a44cc7b2d5f3de8fe0bef52647f789cddf96584265e8a00d` |
| `packages/contracts/events/site-page_version-ready.schema.json` | 1795 | `sha256:24773957c601d0eede53c516155e97ee3819c19767a6a3674657e72cf34422f7` |
| `packages/contracts/events/site-page_version-rolled_back.schema.json` | 1813 | `sha256:5fb0efe7fb0f3ff8c81ab294c153c6c2b52e47355156daeb6a04994ce157ba1e` |
| `packages/contracts/events/site-page_version-superseded.schema.json` | 1810 | `sha256:b4564df2e1507e14fcfb88c00fd2dddb82c2f3270dc4ddd223d05ab01e98616b` |
| `packages/contracts/events/source-blocked.schema.json` | 1768 | `sha256:f0ef16c8bb7a495f03f6af6554aba648e04cb35fbcf43d180ce855d252cc1343` |
| `packages/contracts/events/source-expired.schema.json` | 1768 | `sha256:e5fb0fd8489652d8c5ee5c297f68f4d598be45a5f693b41da3eea6beb70c0d2b` |
| `packages/contracts/events/source-ingested.schema.json` | 1771 | `sha256:2b0e14439697cd8708f59e550dff733b5259e81f0b89dfa4469cc5ac2dd24112` |
| `packages/contracts/events/source-quarantined.schema.json` | 1780 | `sha256:b868b9aaf1454e8c22abdb7865e361504526ddaa7d305c3cd3b9004d3384dbf5` |
| `packages/contracts/events/source-revoked.schema.json` | 1768 | `sha256:3510b82e8d31ef21a5e2073b05faa3878001928b0bb0ce6725e0d29e233bd7fc` |
| `packages/contracts/events/source-snapshot-blocked.schema.json` | 1795 | `sha256:eed43aac463bd4d8f0d759208490e48f13e645b9586dc3a02dd095381a391e8a` |
| `packages/contracts/events/source-snapshot-expired.schema.json` | 1795 | `sha256:fd81118cf0685a1fe20f056e417d806308366e06c49a3ca8252b4ecbb4771690` |
| `packages/contracts/events/source-snapshot-quarantined.schema.json` | 1807 | `sha256:9c72f86306212a8ca1b553c952ff0313335198e2bbcd0bbde4ad6a05a0f97407` |
| `packages/contracts/events/source-snapshot-revoked.schema.json` | 1795 | `sha256:e377944ef344d68854f292384bc4593e6680a7d72ee44646e98b690b78aff4ed` |
| `packages/contracts/events/source-snapshot-usable.schema.json` | 1792 | `sha256:360240ae674a3d7b5402699a3eab675770afbc7398e9fb88e29cad8779acf6fd` |
| `packages/contracts/events/source-usable.schema.json` | 1765 | `sha256:95f920ffdbf77c6c7561bede19669caaab4fd8220a76f53bad54aefac0cc9e82` |
| `packages/contracts/events/task_job-cancelled.schema.json` | 1774 | `sha256:05f5db780dab187b79f30ccd740220f83f924b47e36172219853e452f5025834` |
| `packages/contracts/events/task_job-dead_lettered.schema.json` | 1786 | `sha256:a1dda956927c4b2f867079ccc938149e52b0c91c93a53acb2e32c34f72405aad` |
| `packages/contracts/events/task_job-failed.schema.json` | 1765 | `sha256:001629edaffa4cd5d68dc1d84928e8dda28db159719b36a935496089acdaa6c3` |
| `packages/contracts/events/task_job-leased.schema.json` | 1765 | `sha256:3513998a39d2ab65cdd1815301b7cee05102647225f7e508a3a77225d9087857` |
| `packages/contracts/events/task_job-queued.schema.json` | 1765 | `sha256:8f7787dc9422cdbec0e3ee867c2b3ce697406d2d7f548898554629d754940ab9` |
| `packages/contracts/events/task_job-retry_scheduled.schema.json` | 1792 | `sha256:9796097d1d50f768d811297779ba1a30699fba426982975cacb40eecb0b52b68` |
| `packages/contracts/events/task_job-started.schema.json` | 1768 | `sha256:b4d907180e057ddf45b5094040d23f59a972a4348fad6dc5b43d0cfe312727c9` |
| `packages/contracts/events/task_job-succeeded.schema.json` | 1774 | `sha256:bd3c044046afabd97eff463f63fa4fb74276a1e92de3d0b16b7c3086a10cd5e3` |
| `packages/contracts/events/topic-brief-approved.schema.json` | 1786 | `sha256:433da91299e8569d9c6788b47b036fc1011c97360ca60ee7811971249cc2be74` |
| `packages/contracts/events/topic-brief-created.schema.json` | 1783 | `sha256:7f4ebe2a7acf5f25e32660dc6910e98cdcda2e480c767e447036760829dcfd96` |
| `packages/contracts/events/topic-brief-deferred.schema.json` | 1786 | `sha256:eb6b63d5829a68128ba968c5307108993860d08bb09ca25c5fe45dac8ba2a9f8` |
| `packages/contracts/events/topic-brief-rejected.schema.json` | 1786 | `sha256:eaae6df0866dd42ccb7d14dc0e505e02b069b371d89f5bcf48a8603f302f3a1d` |
| `packages/contracts/events/topic-brief-superseded.schema.json` | 1792 | `sha256:bc652d86ddb326aba6a87d8d37d7ab838c393a32da624561f9847bddb7d8d001` |
| `packages/contracts/events/topic-monitoring-started.schema.json` | 1798 | `sha256:43ca967ed5b277f42ea1e89474052db23d472f0fa4ebe0584737aa4451132d15` |
| `packages/contracts/events/topic-opportunity-approved.schema.json` | 1804 | `sha256:388c51429e2900566b029c3f19e7c73aba20b5fe5f10179757e6fe4051af9554` |
| `packages/contracts/events/topic-opportunity-created.schema.json` | 1802 | `sha256:70bea54807a1e6151592a423ca1e719a1e071df935ed6be77f26f926a01f2a4e` |
| `packages/contracts/events/topic-opportunity-rejected.schema.json` | 1804 | `sha256:3ae9f8fd6c57acdecc68dfc0ad57567788e50fa9113777d6de166eee9a36a2fd` |
| `packages/contracts/events/topic-opportunity-scored.schema.json` | 1798 | `sha256:665409004b44c00b350cfc6b4be7bbd645949871be85830bda74aa63b2f2590b` |
| `packages/contracts/events/topic-production-started.schema.json` | 1798 | `sha256:524928b3f30bfb9bc61efe18d7d7b5cac80202ebdac06424eb1f63a655c1a686` |
| `packages/contracts/events/topic-refresh-started.schema.json` | 1789 | `sha256:fd46e693b2f84c0bd16922e4ff99fb8e9c04562addb4d0fbe364a98ca6094977` |
| `packages/contracts/events/topic-retired.schema.json` | 1765 | `sha256:dbbbb7340efe926ac1fe90ee90b35839ed2ec7791429b4d941e2d4e9a8dd9fca` |
| `packages/contracts/events/topic-signal-created.schema.json` | 1787 | `sha256:f3d01f62d7bd54a8dbba3805f93d0a613f42d61d56ad12274c6563d031f234d0` |
| `packages/contracts/events/topic-signal-rejected.schema.json` | 1053 | `sha256:dbec86ae3a753c37b636ae072d99dd77fc4bc2c27477b1000d0a78cb647f473d` |
| `packages/contracts/events/topic_signal-rejected.schema.json` | 1790 | `sha256:a5ddb266123d8a462ba6f52e60da058c746a56218d8e896b9bef053366bad04c` |
| `packages/contracts/events/variant-approved.schema.json` | 1774 | `sha256:6e11e9c38b695da95b0ed9ba9cdd38a59ce466e2fe80acc27013dbb0057da7d7` |
| `packages/contracts/events/variant-created.schema.json` | 1771 | `sha256:10d7a9da810424bf35e4c36d9e99963d6570e1b93d9aeb89d514a62f3be66aba` |
| `packages/contracts/events/variant-draft_created.schema.json` | 1789 | `sha256:a5ec592b10806da4d2e9cbf22234a7610a8ffc2db0628be5dfcdcf51070a9d08` |
| `packages/contracts/events/variant-localized.schema.json` | 1777 | `sha256:8b5c1d1e12b19a5f6dd29b4003cdb4d94191ca9b3668e81eb2d01bb7411eecbd` |
| `packages/contracts/events/variant-qa_requested.schema.json` | 1786 | `sha256:0dba4bf04368cf19b3c849d94ceb3d7707d130a3753cbee4337db617d0ebec9c` |
| `packages/contracts/events/variant-root_changed.schema.json` | 1786 | `sha256:a08e1aa606cb602a74af91247755632a139b7e02a4dd555c939cb317d35bd24d` |
| `packages/contracts/events/variant-withdrawn.schema.json` | 1777 | `sha256:e1a65edf7e2b3162a2af9104fac3e37356b72ac3ecb36a5c0bdefd9f6d685fd6` |
| `packages/contracts/events/webhook-dead_lettered.schema.json` | 1783 | `sha256:ba28aff3c728929e8adee8c31e14d5533dfae50da5376ba89be81f5febb57804` |
| `packages/contracts/events/webhook-deduplicated.schema.json` | 1780 | `sha256:8d29de882b89266dd47f5b41de861e6fb30ae58bf0dc2756b8f9e3f1027e3d4b` |
| `packages/contracts/events/webhook-processed.schema.json` | 1771 | `sha256:039fef99f5e98659ee3da79ac8f38fb37d484b955f9415d5a5850d174f04b3c2` |
| `packages/contracts/events/webhook-rejected.schema.json` | 1768 | `sha256:1363134d05fb377f314f8dcb10d00fb748477344a8b0cda4455a2dec3ed08c26` |
| `packages/contracts/jsonschema/README.md` | 300 | `sha256:7949d776d99bb869b182f44cf1ce4ee4cd83f604676b35b6b9e6327f42a6ee85` |
| `packages/contracts/jsonschema/account-connection.schema.json` | 4565 | `sha256:6f54dd205fedc1e1aef849e7f14a40964a785e71016f47d6be48f1121b05197c` |
| `packages/contracts/jsonschema/account-profile.schema.json` | 1375 | `sha256:91edf526f2e8fcb44c7014d7caad622ebaf4cbf1fa553ddbc8cba5084ed9ede5` |
| `packages/contracts/jsonschema/agent-definition.schema.json` | 1169 | `sha256:fbe7c4a6a496fa8e09efafbdf3d81d35fd170dee07b4e43292be3f4f52b9c7f5` |
| `packages/contracts/jsonschema/agent-output.schema.json` | 1014 | `sha256:7abcb732813776b490921c8d66b8cf011da0b13f7e16e905832408a9befada77` |
| `packages/contracts/jsonschema/agent-run.schema.json` | 1228 | `sha256:b1841e0c17f966f68303437518dd75f622eb1a269dbb4fb719ee6d36b9fcb8a2` |
| `packages/contracts/jsonschema/agent.schema.json` | 476 | `sha256:a835c3150bf3f87079812cc9cabf9e8315090eb02d748a0fcc4b07214b1b306f` |
| `packages/contracts/jsonschema/analytics-event-catalog.schema.json` | 2908 | `sha256:03d95bd043f5b2ddbd9074c3239825cb015fa5db243f8babaace954d0730569f` |
| `packages/contracts/jsonschema/analytics-geo-quality-snapshot.schema.json` | 2730 | `sha256:404ac954ec813c271f259fdce47c5693a375b51b3410a033071847f2af8eae35` |
| `packages/contracts/jsonschema/analytics-kpi-snapshot.schema.json` | 4510 | `sha256:1d673493f25e7c921e06db3cebd8895df556f8b3bee2e36b103b40d72ac7b953` |
| `packages/contracts/jsonschema/analytics.schema.json` | 483 | `sha256:6b62c9421f6b2c4a03b5a83866b7032426556b45579a0b507957f59c603b82e1` |
| `packages/contracts/jsonschema/api-contract-baseline.schema.json` | 1680 | `sha256:52b3d5d1aa8204eef0a10c10959311ba5e78d2371e75730f7272eda24252cea2` |
| `packages/contracts/jsonschema/api-error.schema.json` | 1089 | `sha256:656744b8e771f4a48491b0ed8e540ba161a28a407356233cc1ce9098a73dfdd9` |
| `packages/contracts/jsonschema/approval-decision.schema.json` | 1394 | `sha256:5325fdf83bb437d3dc03df08a7ddcc332d209bf93af6cef2da6fbdb89f69a352` |
| `packages/contracts/jsonschema/approval.schema.json` | 4830 | `sha256:f89d6c7d4f78d2e52dafc8910fed648a9fd8aa719857cc8db4ceb6322116154c` |
| `packages/contracts/jsonschema/approved-model-provider.schema.json` | 1868 | `sha256:30cf33d1d012d4706b20cafddbb9cda7fede9f33581fa17276b0d7ec84de5b46` |
| `packages/contracts/jsonschema/architecture-guard.schema.json` | 1410 | `sha256:6b4a9e26525702713140b5909272bb5220b39279cf75127450bba3a0107e3f78` |
| `packages/contracts/jsonschema/asset-version.schema.json` | 3157 | `sha256:f0ca9fb8c8e27caa4eac30cc0d9058c0958a9cd07a65c5c34fef8671a5655a29` |
| `packages/contracts/jsonschema/asset.schema.json` | 963 | `sha256:acfd8ddb339180c5818500e0b16088f5c32358723adee3ba5c12af888f4fc55a` |
| `packages/contracts/jsonschema/audit-log.schema.json` | 1998 | `sha256:e97013bdca7d1e78f01fcacfb810983d6d74b807e3cf61121cfba6a0b468f25d` |
| `packages/contracts/jsonschema/audit.schema.json` | 399 | `sha256:ef1fa1029a3006a887c08c56b41064a09358a2d138de436642f0e986e2833cd3` |
| `packages/contracts/jsonschema/authorization-evidence.schema.json` | 1985 | `sha256:1ca1bf3b5586831f947068260e14a6af25cb9608e523bf135a4299646852b87a` |
| `packages/contracts/jsonschema/branch-protection.schema.json` | 1973 | `sha256:90db8ff79be47ac2f225d3cb89a6a7347304ff17432ec1e998ad65e5a14320a2` |
| `packages/contracts/jsonschema/canonical-content-version.schema.json` | 8848 | `sha256:088e1a3f2ee5fbb93c6087e4be4d275ae3c37167b140092322e825bd293d6f6b` |
| `packages/contracts/jsonschema/canonical-content.schema.json` | 1393 | `sha256:5344cf92be3bcf5ac67d6da86eac33536ac4d3343b797939406c67846bfe681f` |
| `packages/contracts/jsonschema/canonical_content.schema.json` | 391 | `sha256:01d70c39688a22c8a214d7f6a341747efbb9b5761b8c22ffd22fbc659865ae48` |
| `packages/contracts/jsonschema/claim.schema.json` | 3620 | `sha256:4fbe27e7e4f06b01d752d3e8d047d3b6d4a7d09eaf76e2f748a951036d0c55d2` |
| `packages/contracts/jsonschema/content-variant.schema.json` | 1267 | `sha256:5203ccf8d22b5cdf32d656e7dc07670a904ffab6a951a7340c87fff274679c91` |
| `packages/contracts/jsonschema/correlation-context.schema.json` | 804 | `sha256:f3b662b85bc815bdb9b80ef5e75612900738724068b3aaf10d65828d86bc8c21` |
| `packages/contracts/jsonschema/cost-record.schema.json` | 1586 | `sha256:ad4f9a3feee274bb00f1fee8c5e23e23b965d60b4e19d367333f3cd8f5002756` |
| `packages/contracts/jsonschema/data-processing-policy.schema.json` | 4073 | `sha256:729c8bd9f859b58dd483c4d04c58c90f78747d26f9ebe6797d7eb1beeba9c125` |
| `packages/contracts/jsonschema/database-config.schema.json` | 1907 | `sha256:783e981b2117aa68f59bf00d9040e5a0c698059c725b269e2620b99b4f0778e0` |
| `packages/contracts/jsonschema/deletion-request.schema.json` | 1338 | `sha256:6567aefb18eff56533ab8c7efb0d8e3e52c704111edeab9e39f6aedf1e41990b` |
| `packages/contracts/jsonschema/delivery-attempt.schema.json` | 6141 | `sha256:5208a762f780b62317094db6cd500b00cd52180fea6efe1fd43b9eb947e315ed` |
| `packages/contracts/jsonschema/delivery-mode.schema.json` | 266 | `sha256:13391ff21ededf528d08531c72acf691134c6a1f8dc3bd7e1e3a124389fa5b3e` |
| `packages/contracts/jsonschema/distribution-target-version.schema.json` | 7802 | `sha256:c88c5b3a96d137d694626fe3f44e68203bc9c66301c3b507292d02c114a5f8b9` |
| `packages/contracts/jsonschema/distribution-target.schema.json` | 1636 | `sha256:0b4a4af419e61e2996bc2e0ef0f62dda0e096584b6ab7b4cf106dc11cb6e9d7c` |
| `packages/contracts/jsonschema/distribution.schema.json` | 634 | `sha256:0bcc4d9bf0518b59024adf52626b9f13cc8eb86c48f9a39787edd6944190f2e3` |
| `packages/contracts/jsonschema/distribution_account.schema.json` | 460 | `sha256:e0db118b2f996c252e091dd3409a05a9bbd864b66dc851497a77344cea7323cf` |
| `packages/contracts/jsonschema/distribution_oauth.schema.json` | 392 | `sha256:f08baf97f27b30cb1e21d8e84896a9e9d4858b43795862232585e841a1127a6b` |
| `packages/contracts/jsonschema/entity.schema.json` | 1575 | `sha256:d54e622afe4b85693510419771c160a7bd6733cee348f0362f1e64157c2acf66` |
| `packages/contracts/jsonschema/eval-run.schema.json` | 3570 | `sha256:2429f39e153fc23207c36cbf684516e3b56d7a81bea4b5edd8fd0fce895a67e9` |
| `packages/contracts/jsonschema/evaluation.schema.json` | 491 | `sha256:8492ab7e2992711e606ee4ecfe37bdb581a5766daa28ff751438e3882fb8419f` |
| `packages/contracts/jsonschema/event-compatibility-baseline.schema.json` | 757 | `sha256:8e2a18e4bac50e50a3d514965a5ed6bcff9287471d785b26461656027d60f59e` |
| `packages/contracts/jsonschema/event-envelope.schema.json` | 1984 | `sha256:f5c58e868c857b2524828a19ab80586787f0ad9bd760f6711ee2fc3a6133e7ec` |
| `packages/contracts/jsonschema/evidence.schema.json` | 3792 | `sha256:71bb7ab2f2985e524b9dde8f14b550cde9eacf23b065953b93cef5ffe1438fb7` |
| `packages/contracts/jsonschema/export-package.schema.json` | 1746 | `sha256:ce1d661126ecdfb1d1efcbd6a70b265635d0d5ab3b0e4e4202b17746ecbc8c84` |
| `packages/contracts/jsonschema/feature-flag.schema.json` | 749 | `sha256:60909f4e0ee5a4a8b6c320553e9e7720581d06d9346fd0829ec503d8f0c598df` |
| `packages/contracts/jsonschema/feedback-action.schema.json` | 2813 | `sha256:1012b7c9cd77a85daf4e7c1a68c9e92d60b5ccea3da3dd02f11444f5e310f10d` |
| `packages/contracts/jsonschema/feedback-experiment.schema.json` | 1964 | `sha256:7fb84ad70eced58046db0bc5517a7be6b0c8e890e891bdefc3bc8e0b17348edf` |
| `packages/contracts/jsonschema/feedback-item.schema.json` | 2835 | `sha256:cfa689fbca48a31325d51d01abc9082fa54914ac733de857eb07771640f9540c` |
| `packages/contracts/jsonschema/feedback-recommendation.schema.json` | 1341 | `sha256:bf6f106de18b7201a03469ca956e718973194538ecdc0f415c3f3501f41fb480` |
| `packages/contracts/jsonschema/feedback-scoring-version.schema.json` | 771 | `sha256:0532e4742382b4407ff33326c6b2028c3223007a1df0675de15f08e63f64236b` |
| `packages/contracts/jsonschema/feedback.schema.json` | 408 | `sha256:80852dc46f30a224fc07ac4dcf24e51ec547aed156060be6cfc6e1d2135353b4` |
| `packages/contracts/jsonschema/foundation.schema.json` | 1308 | `sha256:d104684803157b16626bb02d65c1eb00066e6cd4d619d4a621c4e89f4083ba32` |
| `packages/contracts/jsonschema/geo-content-assessment.schema.json` | 4786 | `sha256:9939a0181489c716ce4b32a5702b1fb39ff4a44c8eca967236c37dbe1268bcb7` |
| `packages/contracts/jsonschema/geo-query-fixture.schema.json` | 3206 | `sha256:b083ad40bd89b97d6a9d54fc9e9f94e1084ebb883fde6bf2034c68964b4286bd` |
| `packages/contracts/jsonschema/geo-run.schema.json` | 2593 | `sha256:cf89c82df13072a8b910ca886134a5213cdb391766e8251264329b9d66d1078f` |
| `packages/contracts/jsonschema/geo_content.schema.json` | 424 | `sha256:bae34b8b085ffda4c3e127e529ae0581134b06698225c5870cb9f94a1eb740d2` |
| `packages/contracts/jsonschema/geo_region.schema.json` | 364 | `sha256:ba4f944d87ea88b8a13cd91544cc5a707374579a32826de456e8b7c78f032045` |
| `packages/contracts/jsonschema/golden-set-version.schema.json` | 1613 | `sha256:a4a59e8d37e2225f926fc4af995c8f4c2325a8a69186e199920b2b37d06f109b` |
| `packages/contracts/jsonschema/governance.schema.json` | 849 | `sha256:68140d9b15974e6f59be37c91c692a9b25b19cec5e508c20837b937599a1683e` |
| `packages/contracts/jsonschema/graph-attempt.schema.json` | 866 | `sha256:fea52259abeb3881ac1c25bbae21954a6a1b9f3c47f7f042111c633431c60134` |
| `packages/contracts/jsonschema/graph-definition.schema.json` | 793 | `sha256:3fa6563a51bcfcdc07f906429a0a8dae0e2973106f38be1b08ea5a420f388e49` |
| `packages/contracts/jsonschema/graph-state.schema.json` | 2050 | `sha256:9ae3e669bfd81a020aa02579537c474afb292d7b0c22a599a2644f8c6e8bb607` |
| `packages/contracts/jsonschema/human-interrupt.schema.json` | 1017 | `sha256:6b31b9c350ccd942a8338800625432c724c70fd0ce1f20e89ddd6dd699bbf6e8` |
| `packages/contracts/jsonschema/human-task.schema.json` | 3770 | `sha256:c99b8eac48d011667683bc1d7e0e5913ff7b62845a4c8cd08e10a16dc80f59ef` |
| `packages/contracts/jsonschema/iam.schema.json` | 470 | `sha256:388813b90f3b3b641f0ed6da65fedf765a901b09d7673e5dddeec6002088cb37` |
| `packages/contracts/jsonschema/internal-iam.schema.json` | 1204 | `sha256:12a0000b6a46467e39487ce936464deaf0e40916d3f4a38176a3323746f1371f` |
| `packages/contracts/jsonschema/kill-switch.schema.json` | 2710 | `sha256:2603526b97c68606bdd272c470ddb36c75a363ae0682bff217870ef7d709a59d` |
| `packages/contracts/jsonschema/knowledge-core-version.schema.json` | 2610 | `sha256:2d4a21f32634e915cba4f9d9909e0455861df076f4291c026eb9c0ff1b16eddd` |
| `packages/contracts/jsonschema/knowledge-core.schema.json` | 1472 | `sha256:8d74e56abc587f8948f087957500452b8df7e29d9d7f6d7fe21995f776718cd4` |
| `packages/contracts/jsonschema/knowledge.schema.json` | 521 | `sha256:90e8e410cb6357f719f2f89bfa0074241fd52c9a6fce34f6f3c2b7d9e174fb05` |
| `packages/contracts/jsonschema/knowledge_site.schema.json` | 310 | `sha256:0f6f9a81a850b281abb7c146ee7c5aedc8ee16c332697d8abe88c3e136e4ee28` |
| `packages/contracts/jsonschema/lineage-query.schema.json` | 1194 | `sha256:7b0e6f8f4d2d9912cb0bb45b00a7aca8cda62f36205f36a72aae3b5f83b6d308` |
| `packages/contracts/jsonschema/media-asset-lineage.schema.json` | 1860 | `sha256:e292e72909185291fa6a90471ff74f473e77461d76d1b1500aff58557bebb9d9` |
| `packages/contracts/jsonschema/media-output-spec-version.schema.json` | 4130 | `sha256:23bc67f5951d6dbe17cbf7a2376effe79ea57e107289beb9cf8b14a8e9d1e7a2` |
| `packages/contracts/jsonschema/media-output-spec.schema.json` | 1487 | `sha256:1cc97423fa34c730d348f0b8bdc3c3b4121298675d26f023bc4f303654de5e4e` |
| `packages/contracts/jsonschema/media-script-version.schema.json` | 5053 | `sha256:4bfd1cd22c10e609c637c196fdf986950fbf3f64f3d4bd28fdf348294052bf4e` |
| `packages/contracts/jsonschema/media-script.schema.json` | 1159 | `sha256:547b2d046da55e242e5eda50424d5f2eaaec653ffaf680d14b08a37cc893fc1d` |
| `packages/contracts/jsonschema/media-storyboard-version.schema.json` | 4571 | `sha256:35897fc994f061e9e6b6e4be24686cceeee230f06f67b5414e7da0d8bd726020` |
| `packages/contracts/jsonschema/media-storyboard.schema.json` | 1056 | `sha256:ced2e2d08027a5a82fa04dbbc8da802d3bf526bdceeb99bcfab9ffc5d528d971` |
| `packages/contracts/jsonschema/media-subtitle-version.schema.json` | 5044 | `sha256:255f26a95d59b96497f753a9713e109a392b2440c34c4eca55ba7f329abc80e1` |
| `packages/contracts/jsonschema/media-subtitle.schema.json` | 1200 | `sha256:08043e1ae8cce1d3b5f79d5c9984cf403e2052f74681ef0960622777954d7f75` |
| `packages/contracts/jsonschema/media-visual-asset-set-version.schema.json` | 4063 | `sha256:de790e3859f6d7c5a6f83c121854a381cd16cff4d4efb6528e36c2063fd8c530` |
| `packages/contracts/jsonschema/media-visual-asset-set.schema.json` | 1202 | `sha256:028dacdaaae481301d0383f5d276b6e9277c60051dabb38476889e70c89cf80a` |
| `packages/contracts/jsonschema/media.schema.json` | 331 | `sha256:33e68b4cf3d3edfaa078f3602ec32f922abf2fde5274511d138e45b2c79a0adf` |
| `packages/contracts/jsonschema/metric-definition.schema.json` | 3197 | `sha256:7749144aecfd4752b06b5d8744a74a8a2cd5cfc739da380e117e8b19b11cb47d` |
| `packages/contracts/jsonschema/metrics-baseline.schema.json` | 3285 | `sha256:9534093fa75e334c1771d1228a412716304833e6bcdb628371a3c8f22f2f8c41` |
| `packages/contracts/jsonschema/migration-baseline.schema.json` | 2137 | `sha256:d7ae95e988db63866ca1b6259172c120a6ce46dbf2c1142035d1f45305d9e67a` |
| `packages/contracts/jsonschema/model-budget-decision.schema.json` | 1334 | `sha256:e987bf685ac5416c6f387e2ddd485d8a94b9e676591894b40945ebd127cbee5b` |
| `packages/contracts/jsonschema/model-budget-policy.schema.json` | 1388 | `sha256:81ed8c9668f3b4a817f2321814274018161a9b1f342aab0fe53757f3d1a775a5` |
| `packages/contracts/jsonschema/model-call.schema.json` | 967 | `sha256:6fffe472001ada9e1a770a0fc40e2223c4546540b4972d46fe4291b7e1b01fdc` |
| `packages/contracts/jsonschema/model-gateway.schema.json` | 1106 | `sha256:4e9d7b88dd2efdf426de9e1090234c63fcd43c84c381ac968b3bd4f7067e3076` |
| `packages/contracts/jsonschema/model_gateway.schema.json` | 500 | `sha256:5f23fe1b62ae84b5dac4602ec248c528e7372942040602b87285bd37f680dc39` |
| `packages/contracts/jsonschema/node-execution.schema.json` | 1110 | `sha256:f805d7364adcdb4dd0e87e368013c19edcc61bbb4efcf0071706693a7ae20b6a` |
| `packages/contracts/jsonschema/oauth-authorization-session.schema.json` | 1333 | `sha256:12306785717a50ac6bf80af2702ab498111645d31a478aba12d3bf97e952b85d` |
| `packages/contracts/jsonschema/observation.schema.json` | 3902 | `sha256:8702f41c6f2935cb3188977676b8199ce88f42de1a76b8fa51fbf6cb083a96ba` |
| `packages/contracts/jsonschema/operational-targets.schema.json` | 6066 | `sha256:5014dca6dd7daafcb5575e0a379baceab4be7bae4bcfcc394997f6e2b40df455` |
| `packages/contracts/jsonschema/operations.schema.json` | 355 | `sha256:a76447e5d835dc94d159a57473152683bf0365bc993ca02b66f865d809d3fd26` |
| `packages/contracts/jsonschema/outbox-event.schema.json` | 3534 | `sha256:b4617d8f93bbf5cb3b01139d22a4b68f7caa06133ea1fa210d61dad0efd841f6` |
| `packages/contracts/jsonschema/pilot-run.schema.json` | 1295 | `sha256:631713903f3f7fb9e7ec92e58e222bfa2831e470cc2f8c681afcad48f49de7fc` |
| `packages/contracts/jsonschema/planner-input.schema.json` | 772 | `sha256:6f2591181e6fa0c02d67128d433674d151e8c67fc01bebefae0ae9a1a408145a` |
| `packages/contracts/jsonschema/planner-output.schema.json` | 1850 | `sha256:c24718326fc284726aeb898bead988cfbd216429cf61d964121f3528e4895a1f` |
| `packages/contracts/jsonschema/platform.schema.json` | 1268 | `sha256:a576e8c8dd685fda2d69bfe821dbd76bffb78ffed0d0f958615f40cd4f95e0fd` |
| `packages/contracts/jsonschema/platform_adapter.schema.json` | 509 | `sha256:b30a273a6f5ae9589fdaf2412c2cc1968f5b5cfd0af92abdf692ed995fbdf7a5` |
| `packages/contracts/jsonschema/policy-card.schema.json` | 2642 | `sha256:fd7262ff1ac4a6c82d64d62dafa49a259ef94327e175c31607766756e0af9f15` |
| `packages/contracts/jsonschema/policy-decision.schema.json` | 2777 | `sha256:cbb073f1032feb931b93bacf833f11f622fa46eb6c7334180c327e29a4f6261b` |
| `packages/contracts/jsonschema/policy-snapshot.schema.json` | 4301 | `sha256:e713864f5f161bc7a3d878ded687a3bd9cff248450817e576a2944f306332995` |
| `packages/contracts/jsonschema/policy.schema.json` | 346 | `sha256:c40c0a4c2a5bf5edd479fbc94eed2d86dc445c1f3b76f9bd68a436b407091f06` |
| `packages/contracts/jsonschema/production.schema.json` | 358 | `sha256:a45373dae1e1a627fb797b3e0ba9cdcac05229efb02cd9c4fac6b4b325380f34` |
| `packages/contracts/jsonschema/prompt-template.schema.json` | 766 | `sha256:90c3e4aef21a2d1789c9ca482ba48532f3a9335eacd800b5aacbb73623d51a14` |
| `packages/contracts/jsonschema/prompt-version.schema.json` | 1394 | `sha256:10a3850a9d432dfbd95532a1e756fc1b89b01eef298eb589f00e91eb886340d2` |
| `packages/contracts/jsonschema/provenance.schema.json` | 477 | `sha256:1d9f3a168b5eb2944e6ab3004f7ca3e2c4fe947e29316067ca58b0487dcffeb8` |
| `packages/contracts/jsonschema/publication-intent.schema.json` | 4435 | `sha256:d3d45977c4d9d6f9a9e8399559445bb08fff557c321c67f8df2808cf5cc3ee16` |
| `packages/contracts/jsonschema/publication-record.schema.json` | 3522 | `sha256:7d0a04e85c50f7783656c983621fd40dd29be7153561497961a698e934618959` |
| `packages/contracts/jsonschema/publisher-capability.schema.json` | 1231 | `sha256:c2e5106997766955d76f8d36dd1e71ef8d463b175d13984117f2eec36fb252ea` |
| `packages/contracts/jsonschema/qa-agent-input.schema.json` | 1502 | `sha256:58f12ae8b6c8354326c2fd6557a0bccc2c15eaa32fc19c044dafe1852f3aaa64` |
| `packages/contracts/jsonschema/qa-agent-output.schema.json` | 2193 | `sha256:cf001f6bc17fb1e53a8e964177a3e6e5704661bcd94038716f5145b00e9adf46` |
| `packages/contracts/jsonschema/qa-report.schema.json` | 5205 | `sha256:f07eb0d88b92500a3c62c671325b3f15b492eac0da9c91e41fb5db76cb6c969f` |
| `packages/contracts/jsonschema/qa.schema.json` | 467 | `sha256:7e8e49f217fcc919436e3aa30fe4c9ced8140c8f0ea29402080facf17d888ba2` |
| `packages/contracts/jsonschema/raci-policy.schema.json` | 3279 | `sha256:294c9927ab20a3d62fe7cfd5a088d42ad001f67da54b13e6da19a872f3dc9212` |
| `packages/contracts/jsonschema/real-account-dependency.schema.json` | 3070 | `sha256:bfea325e61f66758003e863929ee4b3ad665485e6e485bf7132574af998393d1` |
| `packages/contracts/jsonschema/redis-config.schema.json` | 2380 | `sha256:2cdb8c1e65790159ca7b19bc48d32a049f1e58a4216811d5da742cdb4f47843b` |
| `packages/contracts/jsonschema/refresh-recommendation.schema.json` | 1244 | `sha256:ebd9956a5c74d048521e894c6474285345c77c197b51882bac1d57bdbd57a27e` |
| `packages/contracts/jsonschema/region-check-decision.schema.json` | 3760 | `sha256:6f571c6290d113d9ec7e689b910c08c3014b1518257b98e9663b5c11e930886d` |
| `packages/contracts/jsonschema/region-deletion-policy.schema.json` | 2947 | `sha256:979f0e3506f4f3d8b975dab266cf9e0c1c6fd6160446f0243a1104a0fe52e2fd` |
| `packages/contracts/jsonschema/region-profile-version.schema.json` | 4353 | `sha256:ede68909033c9753d8addfd795c77d90b1e07fd0ab9ac2704b4630357868281c` |
| `packages/contracts/jsonschema/region-profile.schema.json` | 1211 | `sha256:c3e1d650d79a93f03136b781fdc92115c5871f853d20eefff95667ea83a93665` |
| `packages/contracts/jsonschema/region-rule-decision.schema.json` | 2119 | `sha256:656152f746d893d3887befe5466d70f2835536193f508017c0621c768209429c` |
| `packages/contracts/jsonschema/regression-threshold-version.schema.json` | 1574 | `sha256:93ebbdd7bb3afe8d1c0d610cb9615507de74b0c1ba27246db768d3db08b7f377` |
| `packages/contracts/jsonschema/release-levels.schema.json` | 2009 | `sha256:6274cce78b1ca9bb14f09b5be6ae6a81a50536e90bffcb09ed5dc31dcb14c804` |
| `packages/contracts/jsonschema/render-job.schema.json` | 6933 | `sha256:a43f3640413e42dfa3d59332aa6a1b999363745432b01609af24fa9d87c19077` |
| `packages/contracts/jsonschema/render-retry.schema.json` | 4061 | `sha256:1b921ab4cb0ff21dc8b5b8b8b60c8e6ced9e182c4a583e562c5dadac6bf61371` |
| `packages/contracts/jsonschema/research-input.schema.json` | 1494 | `sha256:4430108f1579a6254ed2a2cb653f160a606be32cf121fb9b4a3eff7e7b9fc2a0` |
| `packages/contracts/jsonschema/research-output.schema.json` | 2531 | `sha256:b1129b973c23b6047b745809fc4f9676ef6c84a31a7e44d2196ec205947f6f32` |
| `packages/contracts/jsonschema/retrieval-result.schema.json` | 792 | `sha256:fd7b96422025862be033005fb5302b14a2c2b08c220208fc410716b66e2b4256` |
| `packages/contracts/jsonschema/rights-provenance-input.schema.json` | 3242 | `sha256:41aeafbb4ea7703db9d126ee14114f1641a54afe0e86d19b65bc1c188b18087e` |
| `packages/contracts/jsonschema/rights-provenance-output.schema.json` | 3245 | `sha256:9dcf0b4c049af463b48222e19c83d9a0e25808f4039f050a2f6787a2a234622a` |
| `packages/contracts/jsonschema/rights-record-version.schema.json` | 4154 | `sha256:7f4d7ee59881f1d61bdab46642611cd7c24716acc4b6d8befedfe3530423f9c7` |
| `packages/contracts/jsonschema/rights-record.schema.json` | 1209 | `sha256:194d510dbaa2cd2134890252312690ae86b729fb66a7f4c2eff7c8d5af36fe25` |
| `packages/contracts/jsonschema/risk-policy.schema.json` | 5320 | `sha256:449c66aa0aacaca1384a7a36868eb902c28b8998749d8112c099b3a82767628e` |
| `packages/contracts/jsonschema/runtime-entry.schema.json` | 2241 | `sha256:5634bc0d7f86e3274b077f8697c6645577af5ee8bbc4e030fa1e673eec89eb14` |
| `packages/contracts/jsonschema/sandbox-run.schema.json` | 2271 | `sha256:6658a1d71606050013bb2cd70c5d2cbda7c900f45c16701bd9113ed387c71ebb` |
| `packages/contracts/jsonschema/scheduler-job.schema.json` | 926 | `sha256:67bbda290f7640b9b8a500d77d28caca8e66727e521c7cab3949cf502dec93cd` |
| `packages/contracts/jsonschema/scheduler.schema.json` | 488 | `sha256:a40911830d80e465147fd124a53f75440637b22253deeb488d2b3a9bf9c242a4` |
| `packages/contracts/jsonschema/site-page-version.schema.json` | 3809 | `sha256:963a269ba29b1a22151cccc69d12c9245779a01468d4ad5b786a09cb080bacb5` |
| `packages/contracts/jsonschema/site-publication.schema.json` | 3028 | `sha256:d04946d167c4491f144a4430f84b703050a4387f4caba84b77de73fec09594d9` |
| `packages/contracts/jsonschema/site-quality-report.schema.json` | 5032 | `sha256:9f2930a2e6f1cfc52f845fe72e6089cc40c9395eb5daf5255bb002b5fca06704` |
| `packages/contracts/jsonschema/site-structured-data.schema.json` | 5594 | `sha256:81f9808a1ded87133270efb6c6a151a98388b8ad518e79d5f63ed691a3ac8617` |
| `packages/contracts/jsonschema/source-snapshot.schema.json` | 1591 | `sha256:fc906d98e78c5b2757725f6c5935dd6f7676b327eebb7c391be4dca501bd0635` |
| `packages/contracts/jsonschema/source.schema.json` | 1685 | `sha256:c5f3a33ab29e8d2ba4ce4ea4535aa8a0d9b266c515f03acc0d047d71a92e9470` |
| `packages/contracts/jsonschema/storage-config.schema.json` | 2050 | `sha256:2591190cd176d12e0d8efe145d20ded7e5c9011f01ccd80e39da4d31bbd3bd4b` |
| `packages/contracts/jsonschema/storage-object.schema.json` | 1387 | `sha256:448560a7fcf3c66293a427f4f1870be1741919741267b9cf5821040182ba2343` |
| `packages/contracts/jsonschema/structured-log.schema.json` | 1410 | `sha256:e5f6e4fa9421ede4bec3f394b634cb54c570af2b99e3c46ca1ce3e1ba33a7811` |
| `packages/contracts/jsonschema/supply-chain.schema.json` | 867 | `sha256:f3429f358db21e88746fc56148073fc83319e9d0b294f9b1bae6660de09e41c4` |
| `packages/contracts/jsonschema/support-message.schema.json` | 1183 | `sha256:74fbccb0b71b47ca699c0a664810a3ad80903aecc959aae29acc91eb3ba40687` |
| `packages/contracts/jsonschema/support-thread.schema.json` | 1702 | `sha256:05d53fb416b98f5d0921f832c353f8adb7f950203968146cf18f37f97a87b8de` |
| `packages/contracts/jsonschema/support.schema.json` | 482 | `sha256:502b818d7f7271663ddf1df469a5b74301c18777d4e9f207f8f27095e7bd558a` |
| `packages/contracts/jsonschema/synthetic-fixture.schema.json` | 2889 | `sha256:794e5383af290276131dd4070e7a9b62cf36eca71e0eafbfc335c87eba4b0a31` |
| `packages/contracts/jsonschema/task-failure.schema.json` | 1402 | `sha256:114644a26efefd9baa77887fb657e9859b7a3e88504838ead21cecda6731a113` |
| `packages/contracts/jsonschema/task-job.schema.json` | 3420 | `sha256:2170c5b3eeb23ba90648f48a136015c5e0bd5ea7069cb39b53b6e7d7477d8612` |
| `packages/contracts/jsonschema/task-queue-config.schema.json` | 2783 | `sha256:6820de67dd952adb3f6a48c3fc566735c5b957a6e7d5a9a05b43fe9c01ae8410` |
| `packages/contracts/jsonschema/tech-stack-baseline.schema.json` | 2557 | `sha256:153bf9abf141520bf95eaa8073068d6b501bc143c16911a34bb4a773574d48dd` |
| `packages/contracts/jsonschema/terminology-version.schema.json` | 1232 | `sha256:5595b369de02e2a92f93dfeeb7795f4ebaa6fb81c193bb54f620de5903969699` |
| `packages/contracts/jsonschema/token-lease.schema.json` | 1148 | `redacted:credential-name-marker; metadata-only` |
| `packages/contracts/jsonschema/tool-definition.schema.json` | 747 | `sha256:f36a1d771aba78f278d6b94c9a4edca6ab3037acf3a1d648f7ea793849203c41` |
| `packages/contracts/jsonschema/topic-brief.schema.json` | 5173 | `sha256:df9021c762692eb17c86d7010b9704153958f2e63e54cdb250f12874f736dc8c` |
| `packages/contracts/jsonschema/topic-opportunity.schema.json` | 3573 | `sha256:d92211efd20d4fae69f8c4d6094edc362d61f72f3f9f179db5491920483c089e` |
| `packages/contracts/jsonschema/topic-score-snapshot.schema.json` | 1782 | `sha256:53162c4a94eaf1839c3b7cd70fc8cc2448f5468697c8cdb5d5b169ff04f453cb` |
| `packages/contracts/jsonschema/topic-signal-import-row.schema.json` | 1444 | `sha256:8c36332c4fc373166166ec1ba77cb78e5ff4c55e4b2e2f1a3f26b0ad968fb026` |
| `packages/contracts/jsonschema/topic-signal.schema.json` | 2679 | `sha256:e02b5b78209794dbb5eee5d4be1ac10f9d7c510df1ece6e373561865768fe8f6` |
| `packages/contracts/jsonschema/topic-taxonomy.schema.json` | 1363 | `sha256:08580c5cb8db2bbe6e6424656921705126ac46938c9513232487fd5d11ff0e43` |
| `packages/contracts/jsonschema/topic.schema.json` | 467 | `sha256:5af98f239b70408d3be087a0f82648aa961cd99f1806e76fb68ec0455ca4c311` |
| `packages/contracts/jsonschema/tracing-cost-baseline.schema.json` | 3213 | `sha256:2928f4aa426cb05ffaddb23313f6e700b0b249e8724e6e9b41bd0afa2131f897` |
| `packages/contracts/jsonschema/transform-input.schema.json` | 3168 | `sha256:9f4c1b07daa41007e43898da9f3ac2d6f34cdb32d7b3249f760df30eae29dd83` |
| `packages/contracts/jsonschema/transform-output.schema.json` | 2112 | `sha256:62a2be33bb25672e41880587802bebbce8d6d0e11bf3e884d6ebce2dc4ba7d62` |
| `packages/contracts/jsonschema/translation-memory-entry.schema.json` | 881 | `sha256:8a872fedbda7f698642955fcf01569c1c83b7c2e72dfffc711cfc979b64116f1` |
| `packages/contracts/jsonschema/variant-draft.schema.json` | 2232 | `sha256:589332f5ab5549b713a7f85bce7ff445570c20b8fd1899630cb58e2dfd8d75df` |
| `packages/contracts/jsonschema/variant-version.schema.json` | 4257 | `sha256:62e49a74b0b1846b525d021e6c3fe74d36f55226c341ebc5835c936895dfe77a` |
| `packages/contracts/jsonschema/vendor-inventory.schema.json` | 2967 | `sha256:795fb21ada2166dd2ed43916d57df3dc9910df32711ce44d72adc52ab5416593` |
| `packages/contracts/jsonschema/vertical-scope.schema.json` | 1963 | `sha256:55385d1be27e91eba0e34f2ab1f2ba5d5c7d09d17432d1078b12de50eb886dbc` |
| `packages/contracts/jsonschema/webhook-receipt.schema.json` | 2234 | `sha256:a1861ab5b5f625594a6939803c381b2f49419e6604ff05f3d726e00de6d27cdf` |
| `packages/contracts/jsonschema/workflow-run.schema.json` | 1101 | `sha256:16cb65b12a3a924b4a890211ca8323dbd2a5775fc49671f5653c448f25ca6369` |
| `packages/contracts/jsonschema/workflow-step.schema.json` | 1184 | `sha256:7c583154b7dc781b51c1768d37616b7af75862df3052a08de271d483a49c28b6` |
| `packages/contracts/jsonschema/workflow.schema.json` | 340 | `sha256:86a58389ce2a177fbeb471803c6b45a0d174c8ad64162dd263cfd607ada7eacf` |
| `packages/contracts/openapi/openapi.yaml` | 27813 | `sha256:d7ebd148d25f1d1efa87811383bf99f46055e06797f09f486bdbaa8cbc3e988e` |
| `packages/db/migrations/__init__.py` | 76 | `sha256:46fedfd64d5dac6ee50d93dd4fe1edf273e3220963309dd87f66c02488bc126c` |
| `packages/db/migrations/env.py` | 1545 | `sha256:dfc3c817df08c81f50b52318497de6f500912aa6c25cd8e7b851c6890bd00982` |
| `packages/db/migrations/planned/README.md` | 225 | `sha256:027df97c76cdee9fa42a850cb6df86f58a12d79fb169b7ecdf0599dcf5bbb4db` |
| `packages/db/migrations/script.py.mako` | 476 | `sha256:df840a71446cb20ef3fecc9664b44722913cf40af55719ed70123baeece453a3` |
| `packages/db/migrations/versions/20260915_gov_001_governance_scope.sql` | 963 | `sha256:21541f7d274c45d0108a2cd3073c5df99f5d66f21a8173c6ea25d295b83767cf` |
| `packages/db/migrations/versions/20260915_gov_002_release_levels.sql` | 448 | `sha256:ba9ff526a5c45d50a30645c6495ab3ae5634f7fc6b560e839010b6d6e2261932` |
| `packages/db/migrations/versions/20260915_gov_003_raci_policy.sql` | 570 | `sha256:c1753f7b9c71d7941830fa6ebc66362d473361371494e1375297ae8f5f2c54a6` |
| `packages/db/migrations/versions/20260915_gov_004_risk_policy.sql` | 590 | `sha256:87531de51a1c04b169766bc1d9d688d2a775158de7b4dcfaa25d12641599a5be` |
| `packages/db/migrations/versions/20260915_gov_005_policy_card.sql` | 1390 | `sha256:173a83ec704507fb4bd8b97af1e85d9566ad7f8a6ba5322ee54ae386b718253e` |
| `packages/db/migrations/versions/20260915_gov_006_tech_stack_baseline.sql` | 606 | `sha256:5c55d57103e2b31113d675109b21758150112ef7eec1d2a09d6e17267dc6683e` |
| `packages/db/migrations/versions/20260916_found_000_repository_inventory.sql` | 748 | `sha256:8bf6bc905eb40bb5d8c2f8b8ee3cf0acd7f3b421c14cda9b8a8071ae379ef24e` |
| `packages/db/migrations/versions/20260916_found_001_repository_baseline.sql` | 821 | `sha256:0be3c69bf221e9d5db72c051c297233531fc7e1601b0d1065158b8abade5d601` |
| `packages/db/migrations/versions/20260916_found_002_runtime_entry_baseline.sql` | 652 | `sha256:5a24158771e0f5231e392fcad86eed83570286f849aeadeec09fed70fd87ff5d` |
| `packages/db/migrations/versions/20260916_found_003a_database_baseline.sql` | 869 | `sha256:b0e157ec8c635b7f1c59011ee6455c1d4b84a9111c07d4c3d4ae38ae744d90dd` |
| `packages/db/migrations/versions/20260916_found_003b_storage_baseline.sql` | 1603 | `sha256:74e67c4f5476438663c725d3f1da7d940c6af23d397cc7820859cfb055e60c3d` |
| `packages/db/migrations/versions/20260916_found_003d_task_jobs.sql` | 1619 | `sha256:0ad6015ea6126c9ab7e1efe172c679c17f6d113e7e1315af8216659755d86892` |
| `packages/db/migrations/versions/20260916_found_004a_migration_baseline.py` | 2606 | `sha256:3088efaea0e90d27a62027af0d3233149f96deae1828c3d84e5434bb3d14aa59` |
| `packages/db/migrations/versions/20260916_found_004b_outbox.py` | 4077 | `sha256:4aace5655e5f3b2af60e6a45006435d863ad02ca2c4ba11eaf46754c39322d92` |
| `packages/db/migrations/versions/20260916_found_004c_task_leases.py` | 1636 | `sha256:90d711b1ff9f53ed2cf7b7e20081931238094c65280d0498dee66356f0a15d15` |
| `packages/db/migrations/versions/20260916_found_004d_failure_retry.py` | 4103 | `sha256:77ac77c9ff4b9b7c3edfaca4272952835da3741ea4fe62a5a5a64dd07379b1d3` |
| `packages/db/migrations/versions/20260916_found_004e_replay.py` | 409 | `sha256:2b55e411df41772b8bfb165eb4112dca9db0b9700cb2884c79ed7da20e568085` |
| `packages/db/migrations/versions/20260916_found_004f_api_observability.py` | 508 | `sha256:f9ddd7234e7440c8f8b5d6abc611ebe91972e61194aa55ca0f151ac414aa4017` |
| `packages/db/migrations/versions/20260916_found_006a_health_metrics.py` | 442 | `sha256:5159eac629b9d41ea6a2454d72edbee731a3e49aa8d2027dea799f6c968e3243` |
| `packages/db/migrations/versions/20260916_found_006b_tracing_cost.py` | 442 | `sha256:96b5313ded9748a63514e9ea5da2afb73be9a69ec51f16e8be2e959d22b4749f` |
| `packages/db/migrations/versions/20260916_found_007a_openapi.py` | 295 | `sha256:a3e9c8b8a82eb3fe3e4b97569bd0e2a6aaf1484ea3412ad50c31a90d865eb9af` |
| `packages/db/migrations/versions/20260916_found_007b_events.py` | 285 | `sha256:5d4a242d5b7d76cab2c68fcdb247e072a2e9fd598cfec4326f751ab02cc804cc` |
| `packages/db/migrations/versions/20260916_found_007c_agent_output.py` | 258 | `sha256:df611e2552beb7ac8c8d257cf80b622424ae640e9f6d755254171f9e55a27f21` |
| `packages/db/migrations/versions/20260916_found_007d_core_contracts.py` | 340 | `sha256:899bb5ae439c17de966e667ee2a9787081b3eefb8156026d7f319d81fc0b8b95` |
| `packages/db/migrations/versions/20260918_account_core_001.py` | 374 | `sha256:5a108b95a978d855cbcbefb7ba99421ff030c4e4104e303823d942020225c740` |
| `packages/db/migrations/versions/20260918_agent_core_001.py` | 378 | `sha256:8401e38423addc327f0907c65467656d1fa21b41a9dbf251727bca861bac629a` |
| `packages/db/migrations/versions/20260918_agent_core_002.py` | 378 | `sha256:3a84579c312ea999739b1bcaa664cb96209c54e128c9f433ee7520eed849eef2` |
| `packages/db/migrations/versions/20260918_agent_core_003.py` | 370 | `sha256:0b5e834c3341a4a6719a2771cd5b6a2a35e2554d06d85ab82a272b126d6ffed9` |
| `packages/db/migrations/versions/20260918_agent_core_004.py` | 381 | `sha256:3a1510db5e55ebc726552cf34de564a4cdb411ab1150981b3585121478df581c` |
| `packages/db/migrations/versions/20260918_canon_001.py` | 9828 | `sha256:e3822403cd1a4ad2b928b16289866a64905b6412f77486388742081df923b7e9` |
| `packages/db/migrations/versions/20260918_canon_002.py` | 3311 | `sha256:fcb1c73648a1bbee3af43a4ffa506659054993fe40e0227031371917104a9707` |
| `packages/db/migrations/versions/20260918_canon_003.py` | 1126 | `sha256:ad1edec8564aafbda66655fd5fe40b1aeb85333c07432b907d8afcd18d762855` |
| `packages/db/migrations/versions/20260918_canon_004.py` | 1422 | `sha256:a023ac1445a110e1e05af48d54cd98fed969d75c3bc8bb6bbeda5d798d245cf2` |
| `packages/db/migrations/versions/20260918_canon_005.py` | 4328 | `sha256:f0f2ca73c2ddbd7f8be51535b5e76141255545a966078747c2d028f41a72d803` |
| `packages/db/migrations/versions/20260918_feedback_core_001.py` | 434 | `sha256:8af8bb51131ba7a2752df54d98c315fa11adba846b8b000a81d5b6f572fe27c7` |
| `packages/db/migrations/versions/20260918_found_003c_redis.py` | 365 | `sha256:40772c0d9f65d7b299a8a8896dd5ac42c55da165c5a33186b8a4adc9469ff4f0` |
| `packages/db/migrations/versions/20260918_found_008_control_plane.py` | 4626 | `sha256:8679afa05b89c9ad2d40062a8120717879bc5f51c2d17855577857dc74977991` |
| `packages/db/migrations/versions/20260918_found_009_testkit.py` | 377 | `sha256:f4443a1ccbf83122838d04d18e8a2b073e6616402234305ffd9951ed9951e459` |
| `packages/db/migrations/versions/20260918_found_010_platform_contracts.py` | 350 | `sha256:7678a481cb452ffb8cb3179385ed7a45f3cf835529dc2ecf67c27ec79a55b173` |
| `packages/db/migrations/versions/20260918_found_011_architecture_guard.py` | 345 | `sha256:99c4eb3faf5a64ebceb55fa04a9adf6714ed12f5910ae3c49d671d9ad96c033f` |
| `packages/db/migrations/versions/20260918_found_012a_ci.py` | 359 | `sha256:e84502e7bf9df589a0bb594a6856f70c6227106e8d3a8a259b4d832ccfc5c4fa` |
| `packages/db/migrations/versions/20260918_found_012b_supply_chain.py` | 395 | `sha256:d083adad609204a78fa906cf5e229da94b2f8a59db38d2ef8259c9633aab4c39` |
| `packages/db/migrations/versions/20260918_found_013_registry.py` | 367 | `sha256:259c3fbba4c244477182903333ef5f7d7682d2ed8804bb2fe31eacbe7c8d5b2c` |
| `packages/db/migrations/versions/20260918_geo_region_core_001.py` | 386 | `sha256:17ae302791d6d68287650594af40276bf8ca6641c104457e2f746efa0b69029f` |
| `packages/db/migrations/versions/20260918_gov_007_data_processing_policy.py` | 1306 | `sha256:0621dff90d5fe2c234cc44c602c5f8faf1f7918dc5b958db550fca9402d7dc56` |
| `packages/db/migrations/versions/20260918_gov_008_operational_targets.py` | 1279 | `sha256:575dcf6cf96a094a608e9f5a74146e71ac677d1fa5799530a175027f029b872d` |
| `packages/db/migrations/versions/20260918_gov_009_account_dependency.py` | 1267 | `sha256:6972ef03399be9afab7f58650c1acf52aa3a5b83b0d7eb0ce8e11617cee8c727` |
| `packages/db/migrations/versions/20260918_gov_010_vendor_inventory.py` | 1225 | `sha256:e03b77cf20de7bbf049dac954f5e460f40445fb69ba705f33e705a2bafeb6ddc` |
| `packages/db/migrations/versions/20260918_iam_core_001.py` | 365 | `sha256:4b8d29d832208e9b453ed7a6a205c1c42a5657c783e58ebaaeacd1e776bb3363` |
| `packages/db/migrations/versions/20260918_know_001.py` | 17914 | `sha256:5f2e418777604d4ef83ee9916da319bee79a3b5191746dc2d5acf2da40ede999` |
| `packages/db/migrations/versions/20260918_know_002.py` | 8572 | `sha256:952114f9ceec5b6c216b204e4577696c56add1c315e353d916e2cf78623963c6` |
| `packages/db/migrations/versions/20260918_model_core_001.py` | 393 | `sha256:056d8cae30c5eb2d5cfcdf39b05ee8730278b6840eb39a3707f59f7ffe64a5bc` |
| `packages/db/migrations/versions/20260918_model_core_002.py` | 380 | `sha256:6e0e3c7bf5f003bda6901cffb21adb729a99aa824660851b918d40e6d26f6ee2` |
| `packages/db/migrations/versions/20260918_obs_core_001.py` | 2628 | `sha256:7c44ff7e0e7e9d244ecb4ef6124db704e218575ab08f5f4f61f17d32bb387654` |
| `packages/db/migrations/versions/20260918_obs_core_002.py` | 779 | `sha256:d1cc975037e2e1eeb975e65ba0e06d5a37f9f8cc264cf1918b246231636ed9ec` |
| `packages/db/migrations/versions/20260918_obs_core_003.py` | 1694 | `sha256:d6487d3ffcb951a71342315e4bba75492e77928269969704ebcade48440ee6df` |
| `packages/db/migrations/versions/20260918_prov_001.py` | 11488 | `sha256:86864d192acdc91ec7ed06c45644c37beedae242539b62e52aa4649177f5f489` |
| `packages/db/migrations/versions/20260918_prov_002.py` | 13294 | `sha256:6bcd5d69580409039560a1c7bb4acbc4fb902ee390b4a1821b933e79d2d40bdf` |
| `packages/db/migrations/versions/20260918_prov_003.py` | 7854 | `sha256:a629f11f4307da4c00fc9554bc55c525cd4549afe2412a6357d0d82de870cfdb` |
| `packages/db/migrations/versions/20260918_sched_001.py` | 399 | `sha256:f22a0b8882229ec7bd941db938c83c53793ef9091eae542a89c7ed8a2d440350` |
| `packages/db/migrations/versions/20260918_topic_001.py` | 1149 | `sha256:08decd45caaf0a80920a3b28f4ebff752a8958e87d99f6585e28db9bf1ae386e` |
| `packages/db/migrations/versions/20260918_topic_002.py` | 3997 | `sha256:4273539c89684dde23eef6eceb14b8d7ecba066d97bd8f27bb032e1a5c6a95c4` |
| `packages/db/migrations/versions/20260918_topic_003.py` | 5210 | `sha256:a99e647ed215488e401ebb2615504e1cdc3c3bd6b9b2f88ef8f10d521008d241` |
| `packages/db/migrations/versions/20260918_topic_004.py` | 3757 | `sha256:400e98b392d2e14412b1b15f125588c17c11269a134d0a3c6d0ecebb9535a3a3` |
| `packages/db/migrations/versions/20260918_topic_005.py` | 3974 | `sha256:0d2f69f70a0162995cef617418cf1c3a68d47f9928a9b0617815376c72f9a461` |
| `packages/db/migrations/versions/20260918_topic_006.py` | 2948 | `sha256:bca5ce339f3d3b125b3625c32e7775657fc659b27ebb12c84a5f72ec0260ee85` |
| `packages/db/migrations/versions/20260918_topic_007.py` | 2454 | `sha256:2b80c5a555dd5e7aa8ed12f9815ca8f2e9ba0d5e3fec1727d13596b7cb7f4f61` |
| `packages/db/migrations/versions/20260918_topic_008.py` | 3072 | `sha256:4354770ff7145dcee3301a36cb8689cff8baacd62b90dbd2484240b07eeb8616` |
| `packages/db/migrations/versions/20260918_workflow_core_001.py` | 392 | `sha256:b866f1d5183bb94adbb0f2532fdbd7af61d96252eba42b6c3c9e5d907dee19fe` |
| `packages/db/migrations/versions/20260918_workflow_core_002.py` | 434 | `sha256:d675e83cacb68e2daa27a85ac1e76446f3ec8bdaf1b6819f2d14d352c3407005` |
| `packages/db/migrations/versions/20260918_workflow_core_003.py` | 415 | `sha256:4901fa4c431738afdae6feccd5934984488ec87022438316dcd4162e379f1c78` |
| `packages/db/migrations/versions/20260919_agent_core_005a.py` | 391 | `sha256:71cb43f99a2a42c955630267ab4be669d95978b247b133e52bc0b6c999684ef1` |
| `packages/db/migrations/versions/20260919_agent_core_005b.py` | 387 | `sha256:c426dff1ba3170118cd398d03eede461aab0ded9712b0767c0630460ff6312c9` |
| `packages/db/migrations/versions/20260919_agent_core_005c.py` | 395 | `sha256:0504e7bb028aac0e1f887bca87986f9207adb79872e60231834190f6835e4081` |
| `packages/db/migrations/versions/20260919_agent_core_005d.py` | 387 | `sha256:f7928bb80062ec1b52aa66119b976e20828f45d2d98877d0b88a47ffab8fce7a` |
| `packages/db/migrations/versions/20260919_agent_core_005e.py` | 381 | `sha256:6d5d591323b54f4151cbe9796d935b43fbb1424118594839aa93e97e10bd7557` |
| `packages/db/migrations/versions/20260919_approval_001.py` | 382 | `sha256:66c342b84f58f287968f8b071824a70de4907504362272ccca2de398db02b65d` |
| `packages/db/migrations/versions/20260919_approval_002.py` | 409 | `sha256:8baab0fae449b2e3488f576c3922f724c14cbfdff629761937ccf81bbe2f4194` |
| `packages/db/migrations/versions/20260919_canon_006.py` | 1721 | `sha256:cfb70812d130f5f7f7e86b2160a7fabf09fd38f985004fa2a7b2113e04a96a40` |
| `packages/db/migrations/versions/20260919_dist_001.py` | 375 | `sha256:8c3aa85dd84401f972eef1b9b3b98ade868e817ec95f0664cf3f3558889f1c0e` |
| `packages/db/migrations/versions/20260919_dist_002.py` | 372 | `sha256:068cccdded716661f4eab3ed81e3b864af8cf81b1ded5141dc5eba7846aa3f37` |
| `packages/db/migrations/versions/20260919_dist_003a.py` | 374 | `sha256:bc1fb7f1cef05c3f6ade5430666cbeb653c76b1b10f27efa78c5e66f80a90639` |
| `packages/db/migrations/versions/20260919_dist_003b.py` | 378 | `sha256:43ec4ec8be23c0b0cd3dff95b4ead0ab8e0755d3d731a2587c09fb196b204135` |
| `packages/db/migrations/versions/20260919_dist_004.py` | 375 | `sha256:4a0e6a1d66c92ef6ecf4c1dc7b98a1700f92170b0471582d99f3913e5d999c0e` |
| `packages/db/migrations/versions/20260919_dist_005a.py` | 374 | `sha256:0be8058b6c75d148134a683ceb80b245a5d247a297a4cd0710acddb2be3d1456` |
| `packages/db/migrations/versions/20260919_dist_005b.py` | 374 | `sha256:23509471a38f7740f3b3f94d98c8a9d0b6b3fb54c26b37fe688309c2e3bb0a75` |
| `packages/db/migrations/versions/20260919_dist_006a.py` | 369 | `sha256:0aab68f8ade2580c9ccb2d8c13a19f5c9585f6afbb2247385004dfcc000bbef9` |
| `packages/db/migrations/versions/20260919_dist_006b.py` | 374 | `sha256:0a557cdfca7aed727f1df623d705ff66959a5061504da0fff62b7b7ceb782caf` |
| `packages/db/migrations/versions/20260919_dist_006c.py` | 372 | `sha256:5ebc095ddd37b93015517063fd7c292081fc99efeaa9649be5953dfdcbd60351` |
| `packages/db/migrations/versions/20260919_dist_007.py` | 370 | `sha256:edebaec22e3e17d4a0ae3be3f91e1937989007ad3e2d6642b6b63ba98dc99610` |
| `packages/db/migrations/versions/20260919_dist_008a.py` | 385 | `sha256:ce51eab777262b24c42af1fb369ef54c2314479adf259d94d6e063d36cb4b193` |
| `packages/db/migrations/versions/20260919_dist_008b.py` | 376 | `sha256:e9cc8c982fe41bd438ca73ee68c514b01133e29a98454979622a254185fbb8ac` |
| `packages/db/migrations/versions/20260919_dist_009.py` | 375 | `sha256:58bce1a6a3890c1781a16382509175e4c7120b52058a25591856294ebcdc33e2` |
| `packages/db/migrations/versions/20260919_dist_010.py` | 365 | `sha256:4759e6c7d751efacce6108959e777ae0659961b62979389595146d6d920cb58d` |
| `packages/db/migrations/versions/20260919_dist_011.py` | 375 | `sha256:874f1036dd0ad337ff0e348ed7f5806c1636b416e3e9a4ec4fd3098b70887d9f` |
| `packages/db/migrations/versions/20260919_eval_001.py` | 7705 | `sha256:365349db445a76767a7314440ce41d75e7f4673de43c4e224cfaeaf215e42de2` |
| `packages/db/migrations/versions/20260919_feedback_core_002.py` | 382 | `sha256:cd2f33bab1653a2f896396ffc09c811b93d733b00015bb34214c1b118a08eeef` |
| `packages/db/migrations/versions/20260919_geo_content_001.py` | 4026 | `sha256:293c8a46b95b8f60a53949ae72e256d802fb791a08efcf6b83dc90d7fef0e7e1` |
| `packages/db/migrations/versions/20260919_geo_content_002.py` | 3398 | `sha256:834e8f781d2d4928e4b99e32fe0bedd1c14fe45070ce6fbf5808d1b238852d33` |
| `packages/db/migrations/versions/20260919_model_001.py` | 369 | `sha256:a613a8d315feffdd4495a3b7f4471d9bfa23ce7d3473ad0798c70c1deb494390` |
| `packages/db/migrations/versions/20260919_model_003.py` | 5975 | `sha256:fbf2950936d2376e36b0a28baefcbb284ee8cf75591e0fdf357a0b68036402a6` |
| `packages/db/migrations/versions/20260919_policy_001.py` | 378 | `sha256:c6806fd5a66621c36e2d151d9cbd9ce9f88153b3f4047e2e0ef72b8cbdce4f84` |
| `packages/db/migrations/versions/20260919_policy_002.py` | 393 | `sha256:6c12507eb7f4a552469ca7db4851061072de69a98e6e991780da40865326f74d` |
| `packages/db/migrations/versions/20260919_prod_001.py` | 384 | `sha256:3fe7b22fd5f19f61b284941bb7d47b8dd538ee4a87c58c963c297c8d10269f5d` |
| `packages/db/migrations/versions/20260919_prod_002.py` | 7195 | `sha256:8ecd8c8d606b691d9305ae4a65a4be72401af6178eac1a716cf965fefac5802e` |
| `packages/db/migrations/versions/20260919_prod_003.py` | 4299 | `sha256:3e1743ff78ec001669057450ac4714deafa6d70370f0261504bc1e9001403bb6` |
| `packages/db/migrations/versions/20260919_prod_004.py` | 381 | `sha256:a73ba3070bf200e7b8ec58cada2e443ef96084f9fb341f731b31b985c4f46a11` |
| `packages/db/migrations/versions/20260919_qa_001.py` | 373 | `sha256:41555413e90b81169f4e92084d6a69afe74a06e835fca4736dc7ebedef969fc7` |
| `packages/db/migrations/versions/20260919_qa_002.py` | 380 | `sha256:5548fe45b777ab628532b7d89ce06c30c1694aebd4a2d7dff13fdb9de7aa4a64` |
| `packages/db/migrations/versions/20260919_qa_003.py` | 384 | `sha256:0f9280cef348781725d5fda884a56a0ad60a18ece931a32d9a66415b91fefe82` |
| `packages/db/migrations/versions/20260919_site_001.py` | 7261 | `sha256:f411f8787b69022b20c81146f457174257c60a6c8115d8c6164aa5e9bfeddd2e` |
| `packages/db/migrations/versions/20260919_site_002.py` | 4059 | `sha256:96b40c5aac8f11e0c46ba13dc4ab8920952107839fa1acf923376334e905508b` |
| `packages/db/migrations/versions/20260919_site_003.py` | 630 | `sha256:a63d2b2680336915586315bd7f0f4fdfbbb79e8e5c3ba4bb369b9ca514970560` |
| `packages/db/migrations/versions/20260920_analytics_001.py` | 14919 | `sha256:e36b7bc82cf576e746f0703485c6bbf10904fa64203163b28d31c5c3ccbdcbae` |
| `packages/db/migrations/versions/20260920_analytics_002.py` | 13637 | `sha256:348b3705a657d380232f47b5f06daec2164987cbef3c4b240a2016b6eaa25f57` |
| `packages/db/migrations/versions/20260920_analytics_003.py` | 6075 | `sha256:e8e530aeb8e111f7b9ad07d1453356c30407ae122aabf0a1dcdeb6555696c383` |
| `packages/db/migrations/versions/20260920_geo_content_003.py` | 10506 | `sha256:1674f19009e76333b571b525a16c00b505b66de8070009f4b50194fba4a04b7e` |
| `packages/db/migrations/versions/20260920_geo_region_001.py` | 17197 | `sha256:4c438d4464ffdc6ac3ab0b48c4c83b772e611705155823f2302480ded2db711a` |
| `packages/db/migrations/versions/20260920_geo_region_002.py` | 19579 | `sha256:f2bd10758a719c1f42f8a614c7281e5226763240c77f842035a0bc1d92ff772a` |
| `packages/db/migrations/versions/20260920_media_001.py` | 20333 | `sha256:b5e4884f6825bad22289bec43f6160934010f30959b548a40d10d58439615098` |
| `packages/db/migrations/versions/20260920_media_002.py` | 26996 | `sha256:fd77e3135c9eb44bee9dbaf5d4001c9a5d4f630a7ea4def4ff6c1882dc6859ab` |
| `packages/db/migrations/versions/20260920_media_003a.py` | 27144 | `sha256:38df522a7d5066252eb7398f2853552c08137d081f011386d7fd127aee898e0f` |
| `packages/db/migrations/versions/20260920_media_003b.py` | 23679 | `sha256:462eebc91312e141c53f0f44fd8590e0c31b77df49fb8e0ab44879042b566b00` |
| `packages/db/migrations/versions/20260920_media_003c.py` | 37836 | `sha256:02b52955b7b9dc1fa312cee7880244463326f543ec4f597893f1a3690fd2a43b` |
| `packages/db/migrations/versions/20260920_media_004a.py` | 24261 | `sha256:1683cfc108314d428c44290ab667df6843cdb4d7ec690d2cbdc01a81ae1edaed` |
| `packages/db/migrations/versions/20260920_media_004b.py` | 21703 | `sha256:aaaafeca87fb2d7c3b27ebb40b20fdd056cdd82c0cbe7a906587602a8ab0b173` |
| `packages/db/migrations/versions/20260920_media_005a.py` | 12128 | `sha256:63c386a19c95507f82467ef249b73788b4c3e881aac162f441293ce0be025065` |
| `packages/db/migrations/versions/20260920_media_005b.py` | 5447 | `sha256:20f4ddac166de90292aaffc9494d12dab34ad0fba565d0bceb61ad591a644eea` |
| `packages/db/migrations/versions/20260920_media_006.py` | 10333 | `sha256:68687c22f7ff8f85338d87ee2806fba4a73a2ea19dc41f81da80e1d3fd68cce4` |
| `packages/db/migrations/versions/20260920_site_004.py` | 10156 | `sha256:f4d91b4bd975cec8b3a4ad10212534b74fe2d3a94d24050ba58524fb03e8b030` |
| `packages/db/migrations/versions/20260921_analytics_004.py` | 5889 | `sha256:8089a4baa467e53588f1f441c73ede0f009f1d9769824c03bb7f0fb5d6455dff` |
| `packages/db/migrations/versions/20260921_feedback_core_003.py` | 5674 | `sha256:10b13da1add198a2164eb569a1d36db7e04cd41476f4f474f140dcd9e88a47b4` |
| `packages/db/migrations/versions/20260921_feedback_core_004.py` | 5017 | `sha256:5867199fffd12a3f1b7ff2a5d307a9109424239ce01a3a48cce72c1b08741341` |
| `packages/db/migrations/versions/20260921_feedback_core_005.py` | 5007 | `sha256:0d4403493036000c945e3c2dfad426b0695607b7917ecc1abbb7b2288a05ef4b` |
| `packages/db/migrations/versions/20260921_feedback_exp_001.py` | 4065 | `sha256:7735e35de64a7dfe2870b04e553ee567513de9ec424a789507553d0365fde45c` |
| `packages/db/migrations/versions/20260921_sup_001.py` | 3093 | `sha256:7b01c762b87efc20ebce020c4924e7819d1f35a82db00760a91ff93191f5cc12` |
| `packages/db/migrations/versions/20260921_sup_002.py` | 2310 | `sha256:e391ac9c961dd452607b037f4aa79ea2054abd32eb52319397a4cfbfd106aa89` |
| `packages/observability/README.md` | 267 | `sha256:ce35f6193a1241ce4076fb216c2c32d8aa115531dbff41aabd5319938adb9dc3` |
| `packages/observability/__init__.py` | 162 | `sha256:835cc931d3e9b2ca8c458b088fdf9ccb273e7e84296855b0f771de26874d3f28` |
| `packages/observability/trace.py` | 3972 | `sha256:2ea2fa4e8ba7744cf29d79cbec592b5b8211c9a4f2f996f070d9a762aa5ab8c9` |
| `packages/prompt_registry/README.md` | 484 | `sha256:a868fbcfdefca08f5dc1119089c0e17590dd9b003f1b13ac0886d2fc5524bd28` |
| `packages/prompt_registry/__init__.py` | 179 | `sha256:35649091bcfa3d4eeab67bb7b8b0dd2fcba87d11abe2e20f78691506c56ed564` |
| `packages/prompt_registry/service.py` | 30996 | `sha256:45fb04f8ee0e10be724b777840928811ea8526e103de86bc45982fcacf63b49c` |
| `packages/testkit/README.md` | 574 | `sha256:2da92c4febebdcca5cda4c9258989d693cd0aed274ea414c79eed1770a5fd4a1` |
| `packages/testkit/__init__.py` | 470 | `sha256:591c4dd46af751033761ac159b0571f3240bb59436a9f0d5d3655fc6d4b23f54` |
| `pelican_bicycle.html` | 4057 | `sha256:0d48320e2b4311c8e6c8bfc3ec263f0577ac13fdd341605a54a37e1e564ac644` |
| `pyproject.toml` | 375 | `sha256:eb5e532f4c56c7fa388381d50531d566446d6b93da2419d7ca928eb784c928b6` |
| `requirements-browser.txt` | 110 | `sha256:e6d18b18abf171322e708d053871999c954d1986ec517512854ac04655bed0e4` |
| `requirements-v3.lock` | 3740 | `sha256:1d6196bb3fcd0f6c2c8063918296a2533ae3616d69088e1576b40bfb52e1936a` |
| `requirements.lock` | 313 | `sha256:d8ec5d9c0928273a5f1a2a1b6c9a3b19a75b4eb7e46561aad6bf3d795505e943` |
| `requirements.txt` | 166 | `sha256:794a30850550d8200eb67d54e248f861b27172ecc14cbf9c2440eb5146edb161` |
| `scripts/bootstrap_foundation_db.py` | 3130 | `sha256:0bac286bf763a8f8e5f395f418bbd6220c6f1f365280ea1e5bfc975bbee44a12` |
| `scripts/check_architecture.py` | 4219 | `sha256:056484199a6c71f2376ad34adf451e2ab43250e914448ec0668956f973ae10c1` |
| `scripts/check_ci_configuration.py` | 2255 | `sha256:5d48496d528cf0ee9449a452a21d6572bdd9f888a6b51c4e73dc83aaf844a5a1` |
| `scripts/check_event_compatibility.py` | 14996 | `sha256:eaf95c341a4d8e330177092a6c3580000774be349e0c3714a8d13b4a24e59a46` |
| `scripts/check_foundation_contracts.py` | 1429 | `sha256:82c82f48dcb9b920d6191866b75496faab406c04c531951cb0d86094403db6e7` |
| `scripts/check_json_schemas.py` | 3397 | `sha256:a4674d0e5faafedaf21d2584a91e64ee73ad254e7496892c88795ddd46d4f3ae` |
| `scripts/check_langgraph_task_registry.py` | 2024 | `sha256:5a9c085f67d4d9848bfbb9fabe6442649152a678724eebb866f17f6da6e50016` |
| `scripts/check_lockfiles.py` | 3195 | `sha256:876f83cbd6699ce68bd81eb7ea6ee55402fb4cd8a3b609752a46d9fe6e2132fc` |
| `scripts/check_migrations.py` | 7201 | `sha256:48c813d1a614900592da3fdbb7d4c0cb404b97dd2df38f9554580098b92b092e` |
| `scripts/check_openapi_compatibility.py` | 13634 | `sha256:da4b8b65a6b0ed5086f3d689f19f2f0d28a04e1482cdfafd6dc181de31958ac4` |
| `scripts/check_openapi_contract.py` | 5329 | `sha256:410c78acc878525ddee13969da9dc06b26c96538624bb5d81d6d6eed2542b673` |
| `scripts/check_plan_consistency.py` | 23934 | `sha256:26664bc9db73f341258c25e8892950d08c575c8bd384bf3817b9d0da2eef348c` |
| `scripts/check_secrets.py` | 1894 | `redacted:credential-name-marker; metadata-only` |
| `scripts/check_supply_chain.py` | 4800 | `sha256:5fb9b054760c1bf75a8ad0f5bd3d66d032b981223e7e869a061c35f2347ccc5f` |
| `scripts/check_task_card_precision.py` | 1912 | `sha256:5b99576f9835a65c80c4a5d5a27c0548583de128187b40e0965597d107d8803b` |
| `scripts/check_task_card_registry_refs.py` | 1484 | `sha256:a70eafc3d989942f0fa9e61a27e14d69b5252989f8c1608cd4b8fa6d17fb0c2d` |
| `scripts/check_v3_completion_evidence.py` | 2360 | `sha256:2de829da51edbf44fa23689490a26e2b9e0a41823c64321b4f2ddf27cf47bfde` |
| `scripts/generate-demo-content.py` | 714 | `sha256:3e5cfbb11a4974059f8ad226d664fb38f428132bdbd4d1152e2fcfb74f39421e` |
| `scripts/generate_contract_manifest.py` | 3362 | `sha256:acbaf418c94899097ae599b1b8663924670b7065d44f7b6d1e3f5c6ff2d02875` |
| `scripts/generate_event_compatibility_baseline.py` | 2492 | `sha256:bd02e5bbfa525130241ef76058143fa1c1af21070bab2aeeb1c08e79afb6ec0f` |
| `scripts/generate_event_registry.py` | 7672 | `sha256:0d71e7126aba7c710adc2bec94812b6c2e232e1762b85b8155b8b61e7d65c499` |
| `scripts/generate_json_schemas.py` | 43772 | `sha256:97a3c4895ddbb2a9b2a20e9062dcf98f263e306f50ed6328accb15c1d6200a65` |
| `scripts/generate_migration_manifest.py` | 17043 | `sha256:4b36664a13261cfd83dcf06a9862fa90060c985e4f2def91f3e8f4c1a0aa475f` |
| `scripts/generate_state_registry.py` | 1959 | `sha256:853590fcb2159809a39bc09dd7ae3d8541ded167e8722f387292ed4e0d5b7b73` |
| `scripts/generate_task_cards.py` | 3336 | `sha256:c1a41746312aba12ce1130d839dc02f406385a550a37cb9101873a3be770a3f9` |
| `scripts/generate_task_registry.py` | 58473 | `sha256:ca307184e7be636e690103f7ea6702d761bded25009fbb0a21e7cb8b84321539` |
| `scripts/open-xhs-session.py` | 18012 | `sha256:ce4dee456f6fc398177c4af79184a7f6643d70fe15f72e14252d1d0e79ed4e5b` |
| `scripts/prepare-xhs-draft.py` | 4479 | `sha256:3801de621f5d06af87f4353d06f7a110dfcd87d09e2e4691e5a2d8d5040737d8` |
| `scripts/repo_inventory.py` | 18479 | `sha256:f2a469a06c788a4449c7db7257c59a6dbaf828aa9cd9989365d8f01690cb56ad` |
| `scripts/restart-web-console.ps1` | 627 | `sha256:20ab63ddb90f1043036389e8d0df3828352e38b2e6039847b3510545466c1202` |
| `scripts/setup-browser-dependencies.ps1` | 234 | `sha256:a96476f918a1cafd32b118fd383e733527575c31de63c39faf9e50b8294e4b32` |
| `scripts/smoke_foundation.py` | 1554 | `sha256:d4943f9fc0c2899145f5ca99dfa31ef181ff4fcd9e72e17217376de0e5c67c46` |
| `scripts/start-web-console.ps1` | 582 | `sha256:fe46e03fd2143071634967026afdf72018f0ab81905fa23072bee0739dd14d37` |
| `scripts/start-workflow.ps1` | 2097 | `sha256:9fbb5eb3849f4b41aebc7473ff070c2b0ddfd3f0c80a7ca514db007e9f909362` |
| `scripts/start-xhs-login.ps1` | 167 | `sha256:0f418e9a703934fefad8ea2d83f623eb544f4e7db29ee5b0b64cc1a51fb67cc5` |
| `scripts/start-xhs-login.py` | 2385 | `sha256:cb89b1b7a27201cf137ad4f8827f7bdb827ac924e53f76a37a74e342bea99ed4` |
| `tests/accessibility/README.md` | 243 | `sha256:67b53f18b556cac2dfb0a1f0aa5a2828967494b724bcb2401ad100cf74fdef8c` |
| `tests/accessibility/test_site_004.py` | 3301 | `sha256:551f4759f6d8dbf1eb19413fdde54d08b3ae46882095c53e1cdc3069fe84098d` |
| `tests/contract/test_analytics_001_contract.py` | 4987 | `sha256:c02b2c8a8b5bb96cdb2660843d421886d2f57dd366035dc6fc1db4eba479fade` |
| `tests/contract/test_analytics_002_contract.py` | 2539 | `sha256:be2e53b99b9196d3a27b897c4605481d1b2fe7b677cc4d6b849de142ac22c5b9` |
| `tests/contract/test_analytics_003_contract.py` | 1258 | `sha256:c94f348a348fdc5e092b24ce80748e9e83e859a8705ee8737ccbc4fb0527a055` |
| `tests/contract/test_analytics_004_contract.py` | 1219 | `sha256:3c53084cdae90bab072ac71c1baaa6dd78624d0cee57196de34dd1d105278b6b` |
| `tests/contract/test_completed_task_evidence.py` | 1491 | `sha256:bca172e55a0f94a84b56aae7f8cf7ad72b22e567cf4a4fd2f3dc730860e08fe6` |
| `tests/contract/test_feedback_core_003_contract.py` | 1160 | `sha256:6c118ad17e3ac2ce2765b9d58bd02c84fbb94111b1aa42f8c2e6e327a9f5a17a` |
| `tests/contract/test_feedback_core_004_contract.py` | 1163 | `sha256:89a0a9972592c06464b32a02ea6ba2027dffa8102c9487302cf4a60f4b2207cc` |
| `tests/contract/test_feedback_core_005_contract.py` | 1139 | `sha256:f7cb1a91375c7b9409b1d1d2eeb4e60b28f10b68d6e9ab0e6a9ecd917c385bbc` |
| `tests/contract/test_feedback_exp_001_contract.py` | 1003 | `sha256:11f05b69fe421fd0889c79ba01603c70a4fc23a7590435b5e7b9019eee7eff8b` |
| `tests/contract/test_feedback_live_contract.py` | 1543 | `sha256:0e7d84689388d8f8bc9906c55586a51c51df578f6c4aa6d502ac9580a142b17a` |
| `tests/contract/test_found_000_inventory.py` | 4904 | `sha256:d633c49468f61b5520331e2e9e5a3686fa466cf9b2a08f2f21ca18c29950c96b` |
| `tests/contract/test_found_001_repository_baseline.py` | 5346 | `sha256:9764b83c70e3a1c050fab9e5a91e6556b4feb43bcbd7c0274f7550d16379be01` |
| `tests/contract/test_found_002_runtime_entries.py` | 6071 | `sha256:1d75d91889074e101d33a1e6fe84763bfee9e10ee160ddfd5bd78b5e0c03b208` |
| `tests/contract/test_found_003a_database.py` | 5849 | `sha256:40a15a4f622fe256c6c628b9e5c3f8ddba880e71c99171bc7ceb182b905260fc` |
| `tests/contract/test_found_003b_key_policy.py` | 4149 | `sha256:c1bf20789f207d6da23c7539bb19c5242753adf8aee5d14d7eb341d168cecdd9` |
| `tests/contract/test_found_003b_storage.py` | 8286 | `sha256:4c24577111c3abb2a08514d1f999f5e22002ccd143cacec8cd80b4a62b5bac51` |
| `tests/contract/test_found_003c_redis.py` | 4239 | `sha256:d95e070419aacc867958360668dcc46527bfd1cc95550b279a24aedf2d7a2651` |
| `tests/contract/test_found_003d_task_jobs.py` | 4446 | `sha256:be677e8c283e1027bbde32e47c1bb942adcffa3c541383c4ba778142086d200b` |
| `tests/contract/test_found_004a_migrations.py` | 5860 | `sha256:fd18a11caa90588fe35ac9eccf0dd0376eea911097fb6ee2bb0a9db012752473` |
| `tests/contract/test_found_004b_outbox.py` | 9873 | `sha256:e2e1160d3ad259b7e37f2890df1c8b490ee41875fb77beaab3ac523045f1655d` |
| `tests/contract/test_found_004c_task_claim.py` | 6565 | `sha256:1e2ae5de1cb4abc651048784ecf6f201a4ad64f77005dd5d19a753eb07d598ea` |
| `tests/contract/test_found_004d_failure_retry.py` | 2175 | `sha256:1a4687ff8bf195f4db84ca7b2557736b7f64976ec546f5c21b432c003325aa53` |
| `tests/contract/test_found_004e_replay.py` | 1106 | `sha256:8e5cccd455fca11f93d06023242e9210c699201c89d899eb7c70539ccbcf3539` |
| `tests/contract/test_found_005_observability.py` | 2262 | `sha256:5da9e665d6be6ede7b63091852d5636d611cd266ded1d576fae61dc79d3d4b37` |
| `tests/contract/test_found_006a_metrics.py` | 3196 | `sha256:7e64102d59ae71613e939a03b91b8bceb2fd2020a92dee2c4ee529dcee361499` |
| `tests/contract/test_found_006b_tracing_cost.py` | 2408 | `sha256:399aa54aa948b8f92070a8a5e8b620e1a235c37cc545599b16b08cb03af647cd` |
| `tests/contract/test_found_007a_constraint_regressions.py` | 1182 | `sha256:56b27d491259247f881452dfa3d3677b537e20815dda7f2e05422d77b74f2b0f` |
| `tests/contract/test_found_007a_openapi.py` | 4295 | `sha256:5f68b68118748bc66a490827d360fa2c0de3ce381251516c5a3f9b4055056556` |
| `tests/contract/test_found_007b_envelope_regressions.py` | 7675 | `sha256:cd67b80602031931744e0fb5cc916e58bd7680648af13596af900da12813bd9f` |
| `tests/contract/test_found_007b_events.py` | 2821 | `sha256:258bc6855f61a6d65ea3e52e0826a86e2cfc772b5ce7291b939f08f3cf1de4a4` |
| `tests/contract/test_found_007b_versioned_consumers.py` | 6539 | `sha256:fe424bf97ac2063ff2f2ca65a8e56360cee99ecc9eed9f2171f0f3c222d92f6f` |
| `tests/contract/test_found_007c_agent_output.py` | 4382 | `sha256:4675955355eaca37e178581af6227343fc5c9b0b2f0b9426ee2ed98906f292d2` |
| `tests/contract/test_found_007d_approval_schema.py` | 1789 | `sha256:ac1ca2a8753d4b2296161cbe70409357ea97c032946539ac31cffc6b4619e4e6` |
| `tests/contract/test_found_007d_core_schemas.py` | 7330 | `sha256:05095b495322a29d5f2e847fc56bcd364a65c713c0bb317d18269f2396bf44a8` |
| `tests/contract/test_found_007d_cross_fields.py` | 3896 | `sha256:4fad8e93c35e024a11bebd9d83d02090d6531dbc0b9b41220cab8d9d74a3d5bd` |
| `tests/contract/test_found_007d_gate.py` | 1229 | `sha256:678238cba60d8cd213a1c1168cf0397b42a324c4931ca1b1831691258daf19a9` |
| `tests/contract/test_found_007d_observation_binding.py` | 3881 | `sha256:1b6342f8110602da073489209d4212dcd0fc780d1fb41049b619966f9f239e5d` |
| `tests/contract/test_found_008_control_plane.py` | 3017 | `sha256:8e09975f51234053475a1264a20273c9912af7b8ec28f4d514d5ad3257433b14` |
| `tests/contract/test_found_009_testkit_contract.py` | 1989 | `sha256:0938ca98a8b8f3b00953d9e5f2b812435aa2aeeec6bfe315bc2730a79e525156` |
| `tests/contract/test_found_010_platform_contracts.py` | 3355 | `sha256:b8c9d4b226f66f652629120f4d31d36a4f16298fc8acfb4da5d0abe7ac9fca95` |
| `tests/contract/test_found_011_architecture_guard.py` | 2365 | `sha256:77a1fc0c92e16fd7723c354ac819d23e9ed2826aed8bde219536335cf6c45174` |
| `tests/contract/test_found_012a_ci.py` | 1865 | `sha256:aa238768786a7f0ccdf5ee15d2b17087176160eac5a92607a319cd1f887c1b5f` |
| `tests/contract/test_found_012b_supply_chain.py` | 739 | `sha256:0871b4658949d6e8123306af3fa4bf1a7a7065053aef704358d500add6dade07` |
| `tests/contract/test_found_013_registry.py` | 1113 | `sha256:1d6bead1334e272f3b4b4037de58c317d4f6bfe009ba4f746745e7460b26c5f0` |
| `tests/contract/test_geo_content_002_contract.py` | 1500 | `sha256:31ff3a1cb9e10d3aecb18fee607f6592dfe96067f8721a4b5ca02b3cff0126d6` |
| `tests/contract/test_geo_content_003_contract.py` | 3013 | `sha256:1b235f70d890c0f702b27dae456573088f5b56dc4e225b1f3b06521a57c97d59` |
| `tests/contract/test_geo_region_001_contract.py` | 3171 | `sha256:ababd01827b423cb0b9d91e80c967033e190353cb8eee44d92263d6851ec4a5e` |
| `tests/contract/test_geo_region_002_contract.py` | 4232 | `sha256:289ca29f221cc8bfbb9112502b7f28384215a18dcd69b360ab4adf353624e4e1` |
| `tests/contract/test_geo_region_002_migration_contract.py` | 1222 | `sha256:7a028951ead34b54aff6c665b4c88e29f9bd5b54d5ff59bd1dde351f780a16f8` |
| `tests/contract/test_gov_001_migration.py` | 1344 | `sha256:2d37df5c941cc2695ea893f9395a100d1a05e7912bdfb4a9beefec4e8d7338d3` |
| `tests/contract/test_gov_001_scope.py` | 1471 | `sha256:c91d71f5e7a459897080681731cb11bc0d919fe4b20947c840270a02503e4456` |
| `tests/contract/test_gov_002_release_levels.py` | 2032 | `sha256:5682980e9080858f61d62f9127c2d0cf3e6f41d277a3572f80b9c27ff9ac4007` |
| `tests/contract/test_gov_003_raci.py` | 2482 | `sha256:13240fb950b79441cb6cf06d094cddda924ddd776f12476d7034c883a703ee11` |
| `tests/contract/test_gov_004_risk_policy.py` | 4993 | `sha256:942419b156fe8cd2511e15f2769bb9c2d9df5cd9917eb173598720e3702056d7` |
| `tests/contract/test_gov_005_policy_card.py` | 4160 | `sha256:03144caa15339f27653c7369f2639a90652022e5f8684d105954c4328a3e95f2` |
| `tests/contract/test_gov_006_tech_stack.py` | 3071 | `sha256:a86bffa4f99acd84ac4da9e2013e01babed6735365ce8cdff1ab3e574655b7e3` |
| `tests/contract/test_gov_007_data_processing.py` | 4760 | `sha256:3dc27ff464c2261e8ebffef63169d1ae02bb6392f82133001aa5a751c859745a` |
| `tests/contract/test_gov_008_operational_targets.py` | 4099 | `sha256:dba5dc806b9141fc972c6eb44bc57a9260677571e216b98237643e60b40fa5fc` |
| `tests/contract/test_gov_009_account_dependency.py` | 3569 | `sha256:83c55d506bc1ba6afd56fcb385cd15b17f49b51c2da2b6671d17e835d061036b` |
| `tests/contract/test_gov_010_vendor_inventory.py` | 3242 | `sha256:4180fd845bd7f635d1995b771a9783109115e68fecc217c1fd79d48295031cb8` |
| `tests/contract/test_media_001_contract.py` | 4714 | `sha256:c28bf9e4b4034d2fc1c56436b9ca1dc847f849a5ce827d175dc4f74c0c677056` |
| `tests/contract/test_media_002_contract.py` | 1870 | `sha256:f255e962a3bf10df68f855d146b5a24d3e16c51d4ac7fa0f963019069e325d62` |
| `tests/contract/test_media_003a_contract.py` | 1738 | `sha256:8b04b8fc92cbadfb4a996b377955bde34e10da76a3063028a8b1427b5a96879b` |
| `tests/contract/test_media_003b_contract.py` | 1936 | `sha256:d7db8fded98cb58b8068d8ab70d166c55eeb68519bdc6d3fa1aa9018bd60f12f` |
| `tests/contract/test_media_003c_contract.py` | 950 | `sha256:199973d20035dd7d0150347c355a125827e934fc7b3de28e119a92478e77e640` |
| `tests/contract/test_media_003c_postgres_sql.py` | 1615 | `sha256:9f2b5649b2cf46236d490d2b141e6d57e545373ff7e395902fe2d99ac25f46f1` |
| `tests/contract/test_media_004a_contract.py` | 1887 | `sha256:732b4e450b76d55344d0fc6750e646c17f4a18e6135faeb2a0ae25d5c24af9b4` |
| `tests/contract/test_media_004a_postgres_sql.py` | 1535 | `sha256:38eecdbe87bce0c3c0deeb8a9f5de6df2ab2c4a24a7bc4c0f6783fd65da93c87` |
| `tests/contract/test_media_004b_contract.py` | 3676 | `sha256:23fdcec15a2bba5eb257f7ce5468a82028180a8c205801b9e0510e200a372e01` |
| `tests/contract/test_media_005a_contract.py` | 3298 | `sha256:f5f9c1c4b411c72e7d515376aeb5d017afb7f2bcb0f8bd1b6dca51ea04b59df3` |
| `tests/contract/test_media_005b_contract.py` | 2070 | `sha256:5af289ff9dec687acb6110e9a059ab5eea3c94307f5d61e35b3a1081d75e43bb` |
| `tests/contract/test_media_006_contract.py` | 2947 | `sha256:53801d03e636fb5df116228d78d0ac9e1bb5d6d458c5151039d6f18d18098c35` |
| `tests/contract/test_oauth_contracts.py` | 1863 | `sha256:2b741fd546d45759dfb2f3ac68657f18079f28ab4f8a242cf7e9f9cd107514c9` |
| `tests/contract/test_site_004_contract.py` | 3388 | `sha256:2ebbd601970e57f4b0a0ff38a6b73931366195fa6dc0fcab764cc371f01099b6` |
| `tests/contract/test_support_contracts.py` | 454 | `sha256:de0fff4656c2b8f799eb59c02ed09f65e77b398ba93a6261bc8c8eb1dec442bf` |
| `tests/contract/test_v3_completion_evidence.py` | 431 | `sha256:0cf69884b7ab756709d78d1e085eb440a70309ae4f2a0240a894ff4f1a038919` |
| `tests/contract/test_v3_task_precision.py` | 1012 | `sha256:965e2696408d6b9c0c2ebe59ed21270bcf422a30c88a9339005eac1dd03c3b8d` |
| `tests/e2e/README.md` | 216 | `sha256:96345feb84990c4d1eaf3f81c73ff3441dfbcfa7febddf47790b0d74ee83cf45` |
| `tests/integration/.gitkeep` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `tests/integration/README.md` | 258 | `sha256:570256ea12f94624066798edc37cd4e70e4e40023da3db5a8c5b95e48d040a65` |
| `tests/integration/conftest.py` | 365 | `sha256:4fa599d39fb04f37b5ce20a11d4268412f9279c7763778bdbff2b7f5b50d322f` |
| `tests/integration/test_account_connection_models.py` | 2603 | `sha256:0010037103219db11132813afa3bd804570c4e17cf81c9890a1f62c4dab0e71d` |
| `tests/integration/test_agent_core_005b_research.py` | 3331 | `sha256:aeb34e595d9f7de2b9eb3d7254c21f93621f626582ef7e28d079cd885d483136` |
| `tests/integration/test_agent_core_005c_rights_provenance.py` | 4273 | `sha256:dc43f6e36b9acd71957dd25de842d7056fc6677f17d778f6d0e14cf8b42c6e4b` |
| `tests/integration/test_agent_core_005d_transform.py` | 3519 | `sha256:93e23f23f7971bd5aa0e44937806296a702a7b264be9fbb7608bdccca349a664` |
| `tests/integration/test_agent_core_005e_qa.py` | 3319 | `sha256:be2777b0c2fca85343454e3eef8883c3cf978ab6f9cfcfc31456faf76d7ecd7b` |
| `tests/integration/test_analytics_001_migration.py` | 3955 | `sha256:9c961125d7748430470dd4fd4b490bb59e0c3616dbd05568f92cfb1723a0eece` |
| `tests/integration/test_analytics_002_migration.py` | 4686 | `sha256:86af5fed30effa76c78a04daace40df75a45513357b9419d9f8860ec641845c6` |
| `tests/integration/test_analytics_003_migration.py` | 1940 | `sha256:fda681b29b8efb7da04987b66895ce324f50cbb325c26c35cee8c4cdd6e8d762` |
| `tests/integration/test_analytics_004_migration.py` | 1887 | `sha256:c2e57b4cb15180a535ab1ba909417987f26fb96e1c34e3307fe5a9863277c672` |
| `tests/integration/test_audit_persistence.py` | 2334 | `sha256:e452ff075aff2a31f72ef1b495eadc468d3b13ab85b9fcbeb1d39f4f5ffb29db` |
| `tests/integration/test_canonical_content_api.py` | 2537 | `sha256:749b7dcac7b61ce853324f1820e761dd128bef8ececd77e8d06d12b7bed774c7` |
| `tests/integration/test_console_startup.py` | 3017 | `sha256:6b752ed627089d05c0a6ca09e5643f355109b1b9e198c57ef64be91da880743b` |
| `tests/integration/test_deletion_persistence.py` | 1743 | `sha256:03051ff7f73c0ce051db5aa42992a7db9787f890445bdc86917883398edd3b65` |
| `tests/integration/test_dist_010_fake_workflow.py` | 3873 | `sha256:c2f9a2c888d72461adca1c54ef5cf9f38a33abc9d91739350187b6475d1e18b3` |
| `tests/integration/test_dist_011_webhook_ingress.py` | 2546 | `sha256:a104f88f335d27cb6ce374538aa4f0665e711f73cd8563991860b1b50816e8dc` |
| `tests/integration/test_eval_001_offline_gateway.py` | 3754 | `sha256:62ea17719380d0bfe8ff02c5604f65538126e539d66d9511b4249f32fd359798` |
| `tests/integration/test_feedback_core_002_recommendation.py` | 3445 | `sha256:f4f72b1483662263fffe10edd6088f0059b6d96960fee3d174f28cbd8923fb97` |
| `tests/integration/test_feedback_core_003_migration.py` | 1560 | `sha256:d4218b6b6509873791d10494372662724706275b77beabacbad2d6df75867a59` |
| `tests/integration/test_feedback_core_004_migration.py` | 1568 | `sha256:95d8d92bc90a6e05acf10ec785f5a4bfa54493a14296b4e46cb255e195bcf546` |
| `tests/integration/test_feedback_core_005_migration.py` | 1561 | `sha256:fb4a5ebc7036d5036f8bdfd3db679a76aaf635e242b3426482817219efe75809` |
| `tests/integration/test_feedback_exp_001_migration.py` | 830 | `sha256:63b447eb038b8f7537bbd285b7f69aec22b279849e7f0d9079baf03203a75c10` |
| `tests/integration/test_found_003a_connection_fixture.py` | 594 | `sha256:d7757405ec895a6facb387b5894ee66f99507e51f9745b52c7b34a63c78559be` |
| `tests/integration/test_found_003b_fake_storage.py` | 537 | `sha256:36a68758eb09d2c44ceaecc36b5154b7eb4d35bd10e63a9a5f827c21b187f03d` |
| `tests/integration/test_found_003d_polling_config.py` | 2968 | `sha256:c46fd2304f7e9afbaa7b12abcbae6b5e7b687d8df590f6abc19125d0615e1dab` |
| `tests/integration/test_found_004b_outbox_integration.py` | 5671 | `sha256:1f14669b2cc614fa22e8cdb7f13acb130848641361e51a58a714a139db8b0792` |
| `tests/integration/test_found_004c_task_claim_integration.py` | 4647 | `sha256:a0a8e8e7fde647862976ad6bb62c6e29d946731ca6ca1b3b1d249a9dc2cce308` |
| `tests/integration/test_found_004d_failure_retry_integration.py` | 8909 | `sha256:1999f2f038753487034fb64cf7a22cb871cdcc1b5125f23af024542c8930004f` |
| `tests/integration/test_found_004e_replay_integration.py` | 9009 | `sha256:eacbbdd5857cfbfe3a0247a13b1c851be0e546edf56d52fe40dc5917c949331c` |
| `tests/integration/test_found_005_observability_integration.py` | 2752 | `sha256:a20785fc9cd242db5e4a2d70a912c173f1b7614660499b176b8e5fb680ddbec0` |
| `tests/integration/test_found_006a_metrics_integration.py` | 4569 | `sha256:6b3c9f40a5d097baf5a50d3ab31f46a0d653610c991d29c9c99e6ca494268d47` |
| `tests/integration/test_found_006b_tracing_cost_integration.py` | 8293 | `sha256:d03e1ef4c6de0054140bf17a9a3fa4c1a5497d49cd89de2fcd598de728257bab` |
| `tests/integration/test_found_007a_openapi_integration.py` | 2071 | `sha256:5cdbd86ff22857bfd99133fab95acabe2016295bb0b2782ff7c89fa9a04f2c7d` |
| `tests/integration/test_found_007b_events_integration.py` | 2768 | `sha256:c5a0c992c9e49cee41516faa92ea533271779f83a1ed3d4095b82c067ba41df5` |
| `tests/integration/test_found_008_control_plane_integration.py` | 12176 | `sha256:26d0ca3815212091dc8f9f1275e7c4b984ceb4ff450460c50605bb9811027766` |
| `tests/integration/test_found_009_fixture_storage.py` | 3085 | `sha256:e67ff0525f06c2fe687e1c87e72591a49f8f8825f8acab8cec3172b6ee35389f` |
| `tests/integration/test_foundation_bootstrap.py` | 1923 | `sha256:22082f694cb3dc26f8db198413e94927f4826236207c074242a22078c856d0a8` |
| `tests/integration/test_foundation_failure_facade.py` | 5271 | `sha256:25a5c7198e5d4ae620483cc81456bdfb6899fc08b433858fa539df5c45c3a7ca` |
| `tests/integration/test_foundation_worker_runtime.py` | 10062 | `sha256:c44ccdc96c529ddd1c038b53a831b3a7e78b214074f9fa8720f063cb6ae29386` |
| `tests/integration/test_geo_content_001.py` | 2157 | `sha256:3666dc3fbdd55d6e508d5dc00b19caf25a6f8583e95689b295d38c32e5b70e09` |
| `tests/integration/test_geo_content_002.py` | 2067 | `sha256:6d827e393070b1af2a9f92cabadfb20c81409c0a624988430a6c0bc76e701a14` |
| `tests/integration/test_geo_content_003.py` | 10848 | `sha256:710f9126acbb2bdd70b981f5ba638746e0d1c6c76261511f6237066e6f692821` |
| `tests/integration/test_geo_region_001.py` | 9472 | `sha256:0e589217ef35770992e65fb3fe3ecfa16b6535719536b6c85089d5a41f4da5dc` |
| `tests/integration/test_geo_region_002_migration.py` | 5258 | `sha256:b6d79c8ce586bfd073229e93ea13e6dafed1a3f89924cac72a41c46264fcae26` |
| `tests/integration/test_geo_region_002_site_render.py` | 3785 | `sha256:afae8865f2007e8d1156d080f3710881008245e60aa54c37a2b42d15acece5c5` |
| `tests/integration/test_iam_core_001_api.py` | 1363 | `sha256:c3283404357af43840ae92229afb6be3dd697231ee7b906e9efe968077a8fc82` |
| `tests/integration/test_knowledge_api.py` | 3904 | `sha256:de3313811517038a210eb93fae4e782fadd8878721d1ce6ebcea2c83873716b7` |
| `tests/integration/test_knowledge_core_api.py` | 4321 | `sha256:a36ada0937a51554ff631ede84a41f52a677f1f8733a6ac0b5d455ecc1d4f699` |
| `tests/integration/test_local_draft_api.py` | 4059 | `sha256:ee303b31a37821ce8d5281d4438b778701b11d725ab982f54c2bb58b105e0fe9` |
| `tests/integration/test_local_recovery_drill.py` | 3886 | `sha256:1569e5e166abcc5256ad4484d42ac24440917313f19063679cbb108736110f61` |
| `tests/integration/test_media_001.py` | 6752 | `sha256:29f7feaaa7ee8c0f1b036b1a8f81eaf80a7578658fb604c04c7a6abf8d51bf34` |
| `tests/integration/test_media_001_migration.py` | 8617 | `sha256:17bab71f8fc760ec9c56c4bbaec08da605b86cce643525b879ae798c121b1033` |
| `tests/integration/test_media_002.py` | 5968 | `sha256:cd808a46b300e48958aa6b251973d10034430b8fa07bb401e94065c13cbda40e` |
| `tests/integration/test_media_002_migration.py` | 11700 | `sha256:afd147ce9baef4e528aacb05e22211a0268f41ead5774ff8e35ba5e232f0744e` |
| `tests/integration/test_media_003a.py` | 5662 | `sha256:02a50e661cd730c0c9a2691860311a71f25747a30ad4888c74a3a640132d3521` |
| `tests/integration/test_media_003a_migration.py` | 6645 | `sha256:2cf7cd7aca5a6c2e3f998483954cf01b20a9d17f8dcdcaf9b412e9ca69e81169` |
| `tests/integration/test_media_003b.py` | 2479 | `sha256:fb653641297615611fc6a934f8272c412ff431d6b43ddb3cbc3612a657f71f39` |
| `tests/integration/test_media_003b_migration.py` | 6939 | `sha256:26fa3398b950fa38fa84f4b21f15c5e927403af63e16bebc9cae61e2f11b3411` |
| `tests/integration/test_media_003c.py` | 1390 | `sha256:abcabea07488e4d5b8c3c1bb93234f7b791e2bfbfe55dab5e990b3874191b058` |
| `tests/integration/test_media_003c_migration.py` | 6245 | `sha256:848ed1eb91e21b0d14a492f405ff4b293f4e0cdaf08d5aa7ad0d22f61173b14f` |
| `tests/integration/test_media_004a.py` | 3378 | `sha256:37022f3a3eb197912cfd0e4863cbbb8c3f1ef8d4ce2eab68982c97f39a4fe830` |
| `tests/integration/test_media_004a_migration.py` | 8534 | `sha256:bad9ef55dfdaf9bc889bf8bac8351244c4adda7c6a9d0c8ece147d8f989a2d87` |
| `tests/integration/test_media_004b.py` | 3348 | `sha256:5ae0c0dde796ee3b664aad392412d3a269cb84523e236ba2e3c68cdec523817f` |
| `tests/integration/test_media_004b_migration.py` | 4108 | `sha256:3b3762edfc279b25d82d6f301472c8197c692a5ab672473ee1638b1433a0e9b6` |
| `tests/integration/test_media_005a_migration.py` | 3798 | `sha256:a4f16607189e26c13d0d4f9ef72f8017c69a0e12a721357a43220779dffb9971` |
| `tests/integration/test_media_005b_migration.py` | 3046 | `sha256:3efab055e35ac8c4578dcea702c87fe79c4bad31c747cd07ee7912dd3cdc9e15` |
| `tests/integration/test_media_006_migration.py` | 3279 | `sha256:2a7926cf168ae26d947c962b968e504484075402b588bfecb594038e36998ae7` |
| `tests/integration/test_model_001_optional_provider.py` | 2151 | `sha256:131516641fa1f53e066369be0ee598e6be53452d1b1343399a54277f1c5dd3f8` |
| `tests/integration/test_provenance.py` | 2026 | `sha256:db7aa1930fcb3748bb92d7aa8d61cbffa87d13e2457fe802a2a6dfdae0cc01bd` |
| `tests/integration/test_rights_api.py` | 2407 | `sha256:be0571c8aa05f479b0ed194ce7e50fbef7239750315ffd54685410cb3013341e` |
| `tests/integration/test_rights_guard_api.py` | 2323 | `sha256:2c296283aff863411ea4077aa4bc7c9f20b7a0775969184e2c53695a8ed61320` |
| `tests/integration/test_site_001.py` | 4254 | `sha256:9f87611aed2060ec2cace1dd97b66cbf439f018caa25d923bdd33b6f9bef1099` |
| `tests/integration/test_site_002.py` | 5055 | `sha256:6130607e6d95891c95d3bf14dcabca06892a47dde084a4f751da313ec04bebb7` |
| `tests/integration/test_site_003.py` | 1217 | `sha256:c230593e7fc0b90c29164ef5fe352d4d5757ea84c9fc3a9aa43badc199a0eb8d` |
| `tests/integration/test_site_004_migration.py` | 5758 | `sha256:15b0e347fc25e518d77fb0de0ba05e2c7d0a06f1977c097d45e3c9e9437e885d` |
| `tests/integration/test_site_004_quality.py` | 3008 | `sha256:423f149ae8a7dc658dc3bb6e7a1f01b1cddf7782b98c425f4fc3f1b55dc58b18` |
| `tests/integration/test_sup_001_migration.py` | 767 | `sha256:b661169ed1d211497899b47ca8509228692728f6622aec9124f5a67bc310f29f` |
| `tests/integration/test_sup_002_migration.py` | 905 | `sha256:cc9d517d384a26ce4e3e234654b866c679fe1938ace2ce7b0a3216ff16bdf435` |
| `tests/integration/test_topic_brief.py` | 6631 | `sha256:25aed5aaaa66fd4379baf0dc5904ee3ecc40ab8f18bcfb19ce27f69dff2df48c` |
| `tests/integration/test_topic_calendar.py` | 3646 | `sha256:2686a434e0ca4e0ba836b578f62862f89fac13be4b8c0b0ef32af2ec1d45f76b` |
| `tests/integration/test_topic_opportunity.py` | 6862 | `sha256:fd202749b10b3032f3915a0ca9da7ef8c36bd07f7fab3452b2e6ee80c42762a3` |
| `tests/integration/test_topic_signal_import.py` | 4840 | `sha256:36ae3ea7653ef5bc8e5b50ecd4bf55ccdb9a6047224820c3c2d76ae542b86c75` |
| `tests/integration/test_topic_state_machine.py` | 2371 | `sha256:0e797f21c994b5e3178773728d72234f2ce5af5c00e62119e21ba58dc3a96659` |
| `tests/integration/test_topic_taxonomy_persistence.py` | 1534 | `sha256:41c7d10f5bc698700ab003b79f744b19527536f7a92be6da4b418bce9d4b14b5` |
| `tests/integration/test_variant_draft.py` | 2154 | `sha256:6e89890639ca7dfbc402bbd58311ab2fa016f14ed9ae549cfaf9cd01fcf8e42b` |
| `tests/integration/test_variant_store.py` | 8927 | `sha256:c235503edf6ac7f37e1401c1d6357772a36e14e3e8767ae6bf287530cf256149` |
| `tests/integration/test_workflow_core_002_api.py` | 3084 | `sha256:685caa20237ee7b0becaa99c8189ec0f30ba2b1188cda9f54687ed32e903334b` |
| `tests/integration/test_xhs_browser_preparation.py` | 3228 | `sha256:c03a62ec49b0daded5913576cd929947895ebb703914963b460e77725b7a592f` |
| `tests/integration/test_xhs_inbox_navigation.py` | 5693 | `sha256:da0b4e38416950bf311ff46c3de90f77b5dfe773640f447a2eff3b2d8fd515d4` |
| `tests/integration/test_xhs_inbox_operator.py` | 3738 | `sha256:31dab1f21343cdd6e7c52d708f9c979a080babb175d0e2654eb78bb6f7c401e5` |
| `tests/integration/test_xhs_launch_status.py` | 6079 | `sha256:59e3b8bcc3ec87f0a410c39fadd00f04e326540569be7b2ac20ac581a420e4c6` |
| `tests/integration/test_zpproxy_responses.py` | 2646 | `sha256:91e661372132a009574244cb0fdeb41a231093fb36e88106c06235b3a102eb4e` |
| `tests/replay/README.md` | 265 | `sha256:9fee8beefbef9dfa662759a30f00e82177fe2ff53de5b737fb74c64ec7e4bcd3` |
| `tests/security/README.md` | 233 | `sha256:885531c96c32b9f721256f9aec8f4c4ca0f0b21d257ac46cd4f5bc7c59902fb8` |
| `tests/unit/README.md` | 279 | `sha256:e415d88e64126c5e05e8dd3b28a3651122bd997c918aafd208d099779e511bd0` |
| `tests/unit/agent/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/unit/agent/test_ledger.py` | 1162 | `sha256:19a8cb04cee5039e2bcf13ac80400e3fd9fdb3a447a722a9e866e4ac3409719f` |
| `tests/unit/agent/test_planner.py` | 5060 | `sha256:47f4255316bc7afab31e5087fd311e36b6e441d04c2816f638747479522e7148` |
| `tests/unit/agent/test_qa.py` | 6104 | `sha256:eadd03ae6182eac85a50cc75217c51ee0dfdb4be156a7a8b639102109ea2fd05` |
| `tests/unit/agent/test_registry.py` | 2344 | `sha256:92ada28f750df2d8682753243658f559018d6675dfb6d7dfdb4cc2becc5d405f` |
| `tests/unit/agent/test_research.py` | 6026 | `sha256:35b7844ad6ad2415d0a5f6ae2f07d045295ebc8afc8c3bc4392ee3e861a8ba79` |
| `tests/unit/agent/test_rights_provenance.py` | 8379 | `sha256:74da859874a000967e9a9d78459ae2730ed12e5397cefeda9612bb4db8d13ddc` |
| `tests/unit/agent/test_runner.py` | 2272 | `sha256:1aee05da4f32e09f6a58341d7d9f300640c22c8457e680360632c85e22a8f327` |
| `tests/unit/agent/test_tools.py` | 1261 | `sha256:fcf4aa190f42b7c87d26423cb7199de75d62f6316c56567856b894da37f9cc83` |
| `tests/unit/agent/test_transform.py` | 6970 | `sha256:d635aefb1db13bad814d72e93e45e7a585510cc7b5e9210a0e4acf6c2769dca7` |
| `tests/unit/analytics/test_geo_quality_service.py` | 3769 | `sha256:512797456e244b8315308da7dd19ab84b36fdfa80328bad9f76d12ad4bb18b0a` |
| `tests/unit/analytics/test_kpi_service.py` | 4711 | `sha256:774c61c7b4966084008576f3a5cee8651265a6133e833a9c4acbe04e8f8a6831` |
| `tests/unit/analytics/test_metric_definition_service.py` | 7349 | `sha256:892bbcf137d16e8cd4f41496c4267b31483b5e91e68f845972364b0e9bdd90ac` |
| `tests/unit/analytics/test_observation_service.py` | 8492 | `sha256:1920ac6645431a2fe07bf2d68cdff19e281384de6fd84a22c684f8d0baedcf2b` |
| `tests/unit/approval/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/unit/approval/test_service.py` | 9258 | `sha256:5c583e34ac7b9fdd164159454e525ca83a6c4cce3a7d7911b748c2c69bce1c9c` |
| `tests/unit/audit/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/unit/audit/test_deletion.py` | 5218 | `sha256:5f1ecae683a837c4aa942f5d7ddebef083676f38f4e1acf6990315c36aec3e9f` |
| `tests/unit/audit/test_recovery.py` | 4427 | `sha256:5e66b3b31481d95bd81261e1c49b235342f2c417574c89df716b2c2eace8d1e7` |
| `tests/unit/audit/test_service.py` | 3843 | `sha256:cb1a1f7f06a6a0160d7b69394a5214ebd4d987a91b4d681aee50c49354ee0b42` |
| `tests/unit/canonical_content/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/unit/canonical_content/test_lineage.py` | 8279 | `sha256:a95c413bfe0bba140849cc79de3e5e4653f96729cd5ec536ec0ca28f5cc1a9be` |
| `tests/unit/canonical_content/test_service.py` | 11957 | `sha256:abbc3c39c086159a4a8abb8e998bc011c9d1ceac6009356e542024ffa3d7912a` |
| `tests/unit/distribution/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/unit/distribution/test_deadletter.py` | 7146 | `sha256:78fb94a1d751506faeb31c97025146fc8723fa82cfc762cf063a2ad487bb7f47` |
| `tests/unit/distribution/test_fake.py` | 4935 | `sha256:3c7844f857957a6c427a6c2e61466ec3563f1bdb31e0dfe2aa62d502727f153c` |
| `tests/unit/distribution/test_idempotency.py` | 5275 | `sha256:e1d327118fc663480578e8b13db0b3bfd8ab482723f70112952dc257ba533946` |
| `tests/unit/distribution/test_killswitch.py` | 7333 | `sha256:5f3f40fb93441dd3b440323e0424580c44ff3e495c1d0299e2687888a8162fec` |
| `tests/unit/distribution/test_manual.py` | 3650 | `sha256:de860d93829f91cbbb786c7f2b5d654e224535d6ee75ef6cdc8be34ffbc9b566` |
| `tests/unit/distribution/test_matrix.py` | 2927 | `sha256:6ac0beb57627bc02f4a2810dc973b52fecdf1f7ee38d8c2eee516fec93f43838` |
| `tests/unit/distribution/test_package_storage.py` | 5416 | `sha256:9bc913d94d4522a9c8d7b76cd4ca9c6fcc3be429469fb3383b4fb8ebf7587594` |
| `tests/unit/distribution/test_ports.py` | 3500 | `sha256:5d0eef3fdd4898f3ac3ce9b69f4fa314331abe8e6dd19146fdf85378a8a20177` |
| `tests/unit/distribution/test_reconcile.py` | 4869 | `sha256:1a51e89ca697f6f47858b195f607ca5e32a479af00d299a581d4c3424ed71674` |
| `tests/unit/distribution/test_retry.py` | 3348 | `sha256:3c3b22b9a3676c294beff6b5bba4916809f49e30663bc4db2c57b1a60f1b4437` |
| `tests/unit/distribution/test_service.py` | 8968 | `sha256:fca383367dd5c685457d4d9789a9dc2636b3c6db3861ce7d92838450b782694c` |
| `tests/unit/distribution/test_target_immutability.py` | 5115 | `sha256:ca7a974b8a3707133e46eba2d28adde23807deee427a8e9bbffb370faba2b637` |
| `tests/unit/distribution/test_vertical_slice.py` | 4566 | `sha256:7529450a9cd7faa11346c4a8d1e6b9bd0c3b1c3b02abac02d897155a1e84e736` |
| `tests/unit/distribution/test_webhook.py` | 6973 | `sha256:537b8f9c723d718250a88671422cdd402f420b769df4ff7b3aa2bda3881263a6` |
| `tests/unit/distribution_account/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/unit/distribution_account/test_connections.py` | 11310 | `sha256:dfb7d7f02b51ec30a1906bc5fa97265ed7b284a09ebceb3694e6efed3e90db88` |
| `tests/unit/distribution_account/test_service.py` | 2183 | `sha256:dbb69b4111573082c0ccd3b9df9343e0d095485b68bebe2a1f53c0c64284685b` |
| `tests/unit/distribution_oauth/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/unit/distribution_oauth/test_service.py` | 8357 | `sha256:36f16ad04fd84b6a5ae0b07ea360c075e1ec9ace522a72f5b1a2f8d9d84cbe85` |
| `tests/unit/evaluation/__init__.py` | 1 | `sha256:01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `tests/unit/evaluation/test_service.py` | 13593 | `sha256:8c43e124e34f0cdd273956544a605950c0fafb0968dc33cd397ced680cf85187` |
| `tests/unit/feedback/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/unit/feedback/test_contracts.py` | 3376 | `sha256:60007fb04c741a20e2238c148cb68c329f3ec7c320132c041787ed24eded1225` |
| `tests/unit/feedback/test_experiment_service.py` | 2694 | `sha256:78047a112087db7fe60195474b173eb7f27e009884478ca1cfd42e9a9af3c93a` |
| `tests/unit/feedback/test_feedback_action.py` | 2864 | `sha256:df2cc7ea43f4b7b6239884265a8281d83903f7c646b6b817a1480e5bedc994d7` |
| `tests/unit/feedback/test_feedback_item_service.py` | 3120 | `sha256:89636224f5babc5a90799ae44629cf300a02559515eaa4273dab14c5b60fe00e` |
| `tests/unit/feedback/test_feedback_recommendation.py` | 1965 | `sha256:247e51639867e51ae644caa8cb6537babea926ba2d66e66bf36b8011341dcc8e` |
| `tests/unit/feedback/test_live_feedback_service.py` | 5314 | `sha256:7614459aa3cf3d6087c3437c45e9a08a8ac8436a3de9b07607bfe4c692d65a8e` |
| `tests/unit/feedback/test_recommendation_service.py` | 5842 | `sha256:1168315911a5ff22fe7db84dc81b8742558ba6240e07662f52951ffef8c8140a` |
| `tests/unit/geo_content/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/unit/geo_content/test_fixture_service.py` | 12591 | `sha256:e13929d890dd1e40483478a673ea23309582570ad395f447dd9a4859417a7e59` |
| `tests/unit/geo_content/test_geo_run_service.py` | 15284 | `sha256:451c4c28f45ad7d6bff3d67f63c18513eed2088ca2bec3043178ab77354184ee` |
| `tests/unit/geo_content/test_rules_adversarial.py` | 13989 | `sha256:cc1c05796229cba4a3d1908252ee6a39677539e0aa2b7e82fef97ac8732159a8` |
| `tests/unit/geo_content/test_service.py` | 6738 | `sha256:322554c3ff314c9bd4d87831166dae1581b837ee388fb7e1f220dce7d8b44e83` |
| `tests/unit/geo_region/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/unit/geo_region/test_policy.py` | 13090 | `sha256:fe5cb263373dfd3a99741c45652338e7395dd47245e1580343a578812dc25835` |
| `tests/unit/geo_region/test_region_service.py` | 7672 | `sha256:7116042513909a930f6e433fc5022c85faa9bb8f998172cae167c7116ffe4c62` |
| `tests/unit/geo_region/test_service.py` | 2041 | `sha256:344fe49b22e6b678243aa5d872a88219302348be10462d8a816f28bd4ccff8a0` |
| `tests/unit/iam/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/unit/iam/test_security.py` | 6076 | `sha256:cd6bc1d38aa07bd577dee1472b7f5ecee6541db12b3d4cb2ff9eb860b4b8955a` |
| `tests/unit/iam/test_service.py` | 2409 | `sha256:5579edad6fce25f18c5e4e28a5e577c32a8dab9d42c0ebee05ec0c0d267f5d0c` |
| `tests/unit/knowledge/test_core_service.py` | 7449 | `sha256:754eadf9335c2756aef23f6d9348a57ea304ea6b1a2e98ae2f4057ef327af255` |
| `tests/unit/knowledge/test_service.py` | 8254 | `sha256:aa099f88ed45c736687b093ac5a71eb61ace7f4748fd512e4cea3397b4f6fe39` |
| `tests/unit/knowledge_site/test_site_page.py` | 7758 | `sha256:d718d969146dd748af2e84f4e96a82da812f6c50cf90a36342f57067f8f2e628` |
| `tests/unit/knowledge_site/test_site_quality.py` | 8992 | `sha256:264174101944e5b8a2d5294c5e646373402e9183cbc2f91c9074122f95008300` |
| `tests/unit/knowledge_site/test_site_render.py` | 9583 | `sha256:c1487c0c6db9067e3ef10c928b67640e158433764b329108502489637c0ef04d` |
| `tests/unit/knowledge_site/test_site_structured_data.py` | 7296 | `sha256:8f1f17a9f896b708b0c0a6b6cb9a9f95fc51ff6a9f9b09651ae5e0de32770b13` |
| `tests/unit/langchain/test_compatibility.py` | 442 | `sha256:3a95861167aec72cd390952b74c974b35dec957ecbfd7f6f1161e0acd8f45d34` |
| `tests/unit/langchain/test_ports.py` | 2486 | `sha256:b57de9da80ad98c5b951924734fcdc245e8a03e9afe874b785f2df4e1a159c71` |
| `tests/unit/media/test_media_asset_lineage_service.py` | 6276 | `sha256:118a6060bd8c54cc5ed92441879100876d676779f7ace7a2c56db285aa454bec` |
| `tests/unit/media/test_media_content_qa_service.py` | 4361 | `sha256:ae8ddeea938b2130023b72449ec2381cdc2d93b416707cf026117bf83884150a` |
| `tests/unit/media/test_media_output_spec_service.py` | 4006 | `sha256:5b2d32ab01833a035a27fe7e59dff3f58032bcf0dd8d6f64202759ccf2284f75` |
| `tests/unit/media/test_media_qa_service.py` | 6031 | `sha256:b867b29588194ab76956b1b110c301a59466d6447921f3c0273519db2b033940` |
| `tests/unit/media/test_media_render_retry_service.py` | 8468 | `sha256:be390ea544ca3969a6b685abab7e19e28b49c64642c88c806d1864f2333ad30d` |
| `tests/unit/media/test_media_render_service.py` | 9219 | `sha256:6167c005906c92565d47408119219c694a2aa36f37e7dd75462e983410d36b33` |
| `tests/unit/media/test_media_script_service.py` | 10869 | `sha256:aa39f2bc285d34512f93b7dc4f1f534374492fc611c0702f4dda6f861f3902fe` |
| `tests/unit/media/test_media_storyboard_service.py` | 12387 | `sha256:9719332380bd3f6654f93a92c37b385a5371f651848ddc04ea9386d0c627bb45` |
| `tests/unit/media/test_media_subtitle_service.py` | 8694 | `sha256:1252ddb20a29841985bab23eeb8b5bad28fc450eea2c8a1c54c968c88f839dd6` |
| `tests/unit/media/test_media_visual_asset_service.py` | 9457 | `sha256:7fedcce2de13c154051e0acd5c20dc1c00048494ac55c08587db93a5a12565bd` |
| `tests/unit/model_gateway/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/unit/model_gateway/test_approved_provider.py` | 7170 | `sha256:f7dfc381a28a7e731dc1770a5c86509acb4121c2319b6ee686361deb4724f452` |
| `tests/unit/model_gateway/test_budget.py` | 7668 | `sha256:15d95f18f9eaaa2e96431cdd1388fb325397c2015d6ea2dda20e88d2579b7402` |
| `tests/unit/model_gateway/test_gateway.py` | 1824 | `sha256:342241ba3e87acebc0eb333ee8d767dfc97fffd7291af75f8cf6e4cd9b6714c5` |
| `tests/unit/model_gateway/test_service.py` | 1961 | `sha256:4bd2bfbb43e7e20b0a43645b207ada2d060214d673521b3bac19f04df9f697f7` |
| `tests/unit/orchestration/test_content_graph.py` | 920 | `sha256:f84be70bde8f798bced4fc074f847a3a0128e31250adad9ed4bc3f8c1ab7cc4f` |
| `tests/unit/orchestration/test_langgraph_adapter.py` | 858 | `sha256:4cd056ada9b9f2bda430421ad0e03f11564dcf7cd10e5873fd8f965b244102b8` |
| `tests/unit/orchestration/test_ports_and_replay.py` | 2314 | `sha256:e2ec048b8a1b839b9687ae7bb9d8fdeb77fdab04a5c54c16e7821929b97641d8` |
| `tests/unit/orchestration/test_production_boundaries.py` | 4259 | `sha256:af13aeaf8b870894a29a0c76762d4534209766c926715d216a4783516fd697ab` |
| `tests/unit/orchestration/test_runtime.py` | 5336 | `sha256:749f3ac9ae795cd4448738ab9bf243221180bf91d5c78c408c6b4ae2fc77a259` |
| `tests/unit/orchestration/test_state_lint.py` | 487 | `sha256:80d762651397987041ddead0a0b8f707d498151e180601bd6407e3069e26436a` |
| `tests/unit/orchestration/test_task_feedback_topology.py` | 1844 | `sha256:8e8a5f60b24c9d19ef6e4a176c39b24e4ff629fccd5e129d59e3601d2482c5f9` |
| `tests/unit/platform_adapter/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/unit/platform_adapter/test_fake_official_server.py` | 6230 | `sha256:71e3ec9b6bb8eaf9ce1170635468a121b7577a6f1cfb0e23ea56fcade58bf8f2` |
| `tests/unit/policy/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/unit/policy/test_expiry.py` | 3170 | `sha256:726508c25f3b5d7a537593a5f06dc4b0117120fcf67c4c90d331d705c336dd1e` |
| `tests/unit/policy/test_gate.py` | 4861 | `sha256:01c49e6d8c21730ac0e34d796bfeee27edbed25e412da9280f6ab111314eb03a` |
| `tests/unit/production/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/unit/production/test_region_rules.py` | 5890 | `sha256:4be3dfad092dd1d73caffa7aac72c75987a9309e70b0c6554c635d13cd1c4503` |
| `tests/unit/production/test_terminology.py` | 6183 | `sha256:36d48e95d9c1ec988829d3c0ea1ba97fe2f15f97abfd5413a613680bc584c05a` |
| `tests/unit/production/test_variant_draft.py` | 4576 | `sha256:b5955662b94bece900ec75a9ea667acec24b2dd7fe22e493ea98d3f8f0596f2e` |
| `tests/unit/provenance/test_rights.py` | 9016 | `sha256:7eefc3b18582b0d0080a1242189e7d3fdf80ab8dc9cc2c5dad84b1643dfbbfb8` |
| `tests/unit/provenance/test_rights_guard.py` | 7698 | `sha256:7ac966ceb7e304b2373c4a2958532101c467b1faf68631d27e29dff91d6a4463` |
| `tests/unit/provenance/test_source.py` | 7354 | `sha256:104c06219bd0d7852e0d2f2cfe0af70234acd0c32e38d0c60f3bdcbb4a33e37b` |
| `tests/unit/qa/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/unit/qa/test_advanced.py` | 4414 | `sha256:659e018deae2b936c1cb786d9aca0575a7888644ba1c827199de9a50946a5ffb` |
| `tests/unit/qa/test_sandbox.py` | 4606 | `sha256:0a58ac0d2a4b06e06946a41bb9d028874fd9f3950ad7d1fa449c676bb31b0819` |
| `tests/unit/qa/test_service.py` | 6319 | `sha256:bd37e96f227fd03f734f910cb21c2a3fe231d9711ebc4e69a1b4e87adf1c97d6` |
| `tests/unit/scheduler/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/unit/scheduler/test_service.py` | 3840 | `sha256:1cfcc5c3fdc202848def24af74105cefb4cae6277f456922df3d1953355a8542` |
| `tests/unit/support/test_inbox_service.py` | 2359 | `sha256:3567220ba5fdd78fb9d42acca784026dc53d8a9f3f787712d33ade466d65cae7` |
| `tests/unit/test_console_provider.py` | 1811 | `sha256:0809ef8bc24d80a96462682f2ba2f37fa487bff0e197387258e43b8ce9c8eecb` |
| `tests/unit/test_found_009_testkit.py` | 1859 | `sha256:08a9817d07d43037398fe447717a51a7956004dbb77ede3d86c53ab75a9cf717` |
| `tests/unit/test_found_010_platform_registry.py` | 1433 | `sha256:aa39396db54dbf2327f768a738d9c484cfe3a9f06275c23df0d769d62504cb5a` |
| `tests/unit/test_local_demo_generator.py` | 452 | `sha256:03399cd990e1304cef74c04d173f60d7c27295fe60a1d16fc5751d4bb79e467d` |
| `tests/unit/test_local_reply_generator.py` | 520 | `sha256:aa4ba41006621a91799e2f0e89ecbdda8ec66cf1165e8d3ca5e5bdcec9e3ad70` |
| `tests/unit/test_platform_routing.py` | 1522 | `sha256:e2453a1b3290de1112e5e10e7557ba65325141f3a1df418213927cadbf9c050d` |
| `tests/unit/topic/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/unit/topic/test_brief.py` | 11826 | `sha256:34f0f2db830db78af6618a36e5685c8926a685d56251e870c8c479257f18539b` |
| `tests/unit/topic/test_calendar.py` | 5723 | `sha256:2dc90de7a09aa2a8dec861998f3b6edeffe6a7cd8794f9a64d9e2e8e14b15abf` |
| `tests/unit/topic/test_opportunity.py` | 10125 | `sha256:ef51933c97b4d53e70c206811cf3979f44ab4053298a41539944bfa407fe2806` |
| `tests/unit/topic/test_service.py` | 3947 | `sha256:0c08b5c7977eda3f095b76cc126391f3a99c84410e76d4b4d2cd828b33a46ad5` |
| `tests/unit/topic/test_signal_import.py` | 5444 | `sha256:297f8e9598a3fcf986a74e97fdbfc4541c6e3e5291e775c011212e12c3cbd8b8` |
| `tests/unit/topic/test_state_machine.py` | 5023 | `sha256:83bfcebf4c3e037dfe5c1b6d318a6a1f3917817693864e0b197ff736d7c3eca1` |
| `tests/unit/workflow/__init__.py` | 0 | `sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `tests/unit/workflow/test_dispatcher.py` | 3542 | `sha256:f10fc6502fadb993cfcaa374e149d1290c8a5be8af824653b0d0ed606195b7c9` |
| `tests/unit/workflow/test_service.py` | 4549 | `sha256:1dc3b3af3ceff98c5abaaa66856ba43a3c87a82a0a4e7001001e8d93abb55015` |
