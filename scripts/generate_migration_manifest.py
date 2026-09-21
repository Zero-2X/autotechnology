"""Generate a non-executable migration plan linked to every task ID.

The files under ``packages/db/migrations/planned`` are intentionally absent until
the owning task enters implementation.  This manifest records the expected table
surface and prevents a task from silently creating unrelated tables.
"""
from __future__ import annotations

from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs/task-registry.yaml"
OUT = ROOT / "docs/contracts/migration-manifest.yaml"

TABLES = {
    "governance": ["organizations", "feature_flags", "kill_switches", "policy_versions", "policy_snapshots", "policy_decisions"],
    "foundation": ["task_jobs", "task_failures", "outbox_events", "inbox_events"],
    "iam": ["users", "organizations", "organization_memberships", "roles", "permissions", "role_bindings"],
    "distribution_account": ["account_profiles", "account_connections", "authorization_evidences", "distribution_targets", "distribution_target_versions"],
    "topic": ["topics", "topic_signals", "topic_opportunities", "topic_briefs", "topic_score_snapshots"],
    "provenance": ["sources", "source_snapshots", "rights_records", "rights_record_versions"],
    "knowledge": ["entities", "claims", "evidences", "knowledge_cores", "knowledge_core_versions", "entity_claims", "claim_evidences", "knowledge_commands", "knowledge_events"],
    "canonical_content": ["canonical_contents", "canonical_content_versions", "canonical_claims"],
    "production": ["content_variants", "variant_versions"],
    "qa": ["qa_reports", "sandbox_runs"],
    "policy": ["policy_versions", "policy_snapshots", "policy_decisions"],
    "approval": ["approvals", "approval_decisions"],
    "agent": ["agent_definitions", "agent_runs", "model_calls"],
    "workflow": ["workflow_runs", "workflow_steps", "human_tasks", "task_jobs"],
    "model_gateway": ["model_providers", "model_calls", "prompt_versions"],
    "scheduler": ["scheduler_jobs"],
    "distribution_oauth": ["oauth_authorization_sessions", "token_leases", "authorization_evidences"],
    "evaluation": ["eval_runs"],
    "audit": ["audit_logs", "deletion_requests", "outbox_events"],
    "knowledge_site": ["site_pages", "site_page_versions", "site_publications"],
    "geo_content": ["geo_query_fixtures", "geo_runs", "geo_content_checks", "geo_content_commands"],
    "geo_region": ["region_profiles", "region_profile_versions"],
    "media": ["assets", "asset_versions", "asset_rights", "asset_claims", "render_jobs", "media_render_jobs", "media_render_job_inputs", "media_render_artifacts", "media_render_commands", "media_render_failures", "media_render_retry_schedules", "media_render_retry_commands", "media_render_rerender_targets", "media_qa_reports", "media_qa_findings", "media_qa_commands", "media_qa_content_evaluations", "media_asset_lineage_edges", "media_asset_lineage_checks", "media_asset_lineage_commands"],
    "distribution": ["distribution_targets", "distribution_target_versions", "publication_intents", "export_packages", "delivery_attempts", "publication_records"],
    "platform_adapter": ["platform_capability_versions", "webhook_receipts"],
    "analytics": ["metric_definitions", "observations", "attribution_events"],
    "feedback": ["feedback_items", "feedback_actions", "observations"],
    "support": ["support_threads", "support_tickets", "support_drafts"],
    "operations": ["pilot_runs", "risk_events", "budgets", "budget_usages"],
}


def main() -> None:
    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    migrations = []
    for task in registry.get("tasks", []):
        module = task.get("module", "unassigned")
        migrations.append(
            {
                "task_id": task["id"],
                "migration_ref": task["migration_refs"][0],
                "status": task.get("status", "planned"),
                "path_kind": "planned" if "/planned/" in task["migration_refs"][0].replace("\\", "/") else "real",
                "exists": (ROOT / task["migration_refs"][0]).exists(),
                "verification_status": (
                    "not_started" if task.get("status", "planned") in {"planned", "blocked"}
                    else "verified_by_contract_test" if task.get("status") == "done" and (task["id"] in {
                        "GOV-001", "GOV-002", "GOV-003", "GOV-004", "GOV-005", "GOV-006", "GOV-007", "GOV-008", "GOV-009", "GOV-010", "FOUND-000", "FOUND-001", "FOUND-002", "FOUND-003A", "FOUND-003B", "FOUND-003C", "FOUND-003D", "FOUND-004A", "FOUND-004B", "FOUND-004C", "FOUND-004D", "FOUND-004E", "FOUND-005", "FOUND-006A", "FOUND-006B", "FOUND-007A", "FOUND-007B", "FOUND-007C", "FOUND-007D", "FOUND-008", "FOUND-009", "FOUND-010", "FOUND-011", "FOUND-012A", "FOUND-012B", "FOUND-013", "IAM-CORE-001", "ACCOUNT-CORE-001", "GEO_REGION-CORE-001", "MODEL-CORE-001", "MODEL-CORE-002", "AGENT-CORE-001", "AGENT-CORE-002", "AGENT-CORE-003", "AGENT-CORE-004", "AGENT-CORE-005A", "AGENT-CORE-005B", "AGENT-CORE-005C", "WORKFLOW-CORE-001", "WORKFLOW-CORE-002", "WORKFLOW-CORE-003", "FEEDBACK-CORE-001", "FEEDBACK-CORE-002", "SCHED-001", "OBS-CORE-001", "OBS-CORE-002", "OBS-CORE-003", "TOPIC-001", "TOPIC-002", "TOPIC-003", "TOPIC-004", "TOPIC-005", "TOPIC-006", "TOPIC-007", "TOPIC-008", "PROV-001", "PROV-002", "PROV-003", "KNOW-001", "KNOW-002", "CANON-001", "CANON-002", "CANON-003", "CANON-004", "CANON-005", "CANON-006", "PROD-001", "PROD-002", "PROD-003", "PROD-004", "QA-001", "QA-002", "QA-003", "POLICY-001", "POLICY-002", "APPROVAL-001", "APPROVAL-002", "DIST-001", "DIST-002", "DIST-003A", "DIST-003B", "DIST-004", "DIST-005A", "DIST-005B", "DIST-006A", "DIST-006B", "DIST-006C", "DIST-007", "DIST-008A", "DIST-008B", "DIST-009", "DIST-010", "DIST-011",
                    } or task["id"] in {"AGENT-CORE-005D", "AGENT-CORE-005E", "MODEL-001", "EVAL-001", "MODEL-003", "SITE-001", "SITE-002", "SITE-003", "SITE-004", "GEO_CONTENT-001", "GEO_CONTENT-002", "GEO_CONTENT-003", "GEO_REGION-001", "GEO_REGION-002", "MEDIA-001", "MEDIA-004B", "MEDIA-005A", "MEDIA-005B", "MEDIA-006", "ANALYTICS-001", "ANALYTICS-002"})
                    else "required"
                ),
                "owner": task["owner"],
                "tables_in_scope": (
                    ["governance_scopes", *TABLES.get(module, [])] if task["id"] == "GOV-001"
                    else ["release_level_policies", *TABLES.get(module, [])] if task["id"] == "GOV-002"
                    else ["raci_policies", *TABLES.get(module, [])] if task["id"] == "GOV-003"
                    else ["risk_policies", *TABLES.get(module, [])] if task["id"] == "GOV-004"
                    else ["data_processing_policy_versions"] if task["id"] == "GOV-007"
                    else ["operational_target_versions"] if task["id"] == "GOV-008"
                    else ["account_dependency_versions"] if task["id"] == "GOV-009"
                    else ["vendor_inventory_versions"] if task["id"] == "GOV-010"
                    else ["repository_inventory_snapshots"] if task["id"] == "FOUND-000"
                    else ["canonical_lineage_queries"] if task["id"] == "CANON-006"
                    else ["repository_branch_protection_baselines"] if task["id"] == "FOUND-001"
                    else ["runtime_entry_baselines"] if task["id"] == "FOUND-002"
                    else ["database_connection_baselines"] if task["id"] == "FOUND-003A"
                    else ["storage_object_baselines", "storage_object_metadata"] if task["id"] == "FOUND-003B"
                    else ["task_jobs"] if task["id"] == "FOUND-003D"
                    else ["migration_framework_baselines"] if task["id"] == "FOUND-004A"
                    else ["business_states", "outbox_events"] if task["id"] == "FOUND-004B"
                    else ["task_job_leases"] if task["id"] == "FOUND-004C"
                    else ["task_failures", "human_tasks"] if task["id"] == "FOUND-004D"
                    else ["task_jobs"] if task["id"] == "FOUND-004E"
                    else [] if task["id"] == "FOUND-005"
                    else ["foundation_feature_flags", "foundation_kill_switch", "foundation_control_commands", "foundation_control_audit"] if task["id"] == "FOUND-008"
                    else [] if task["id"] == "FOUND-009"
                    else [] if task["id"] == "FOUND-010"
                    else [] if task["id"] == "FOUND-011"
                    else [] if task["id"] == "FOUND-012A"
                    else [] if task["id"] == "FOUND-013"
                    else [] if task["id"] == "FOUND-003C"
                    else ["audit_logs", "audit_commands"] if task["id"] == "OBS-CORE-001"
                    else ["audit_recovery_queue_pauses"] if task["id"] == "OBS-CORE-002"
                    else ["audit_deletion_requests", "audit_deletion_stages", "audit_deletion_manual_tasks", "audit_deletion_commands"] if task["id"] == "OBS-CORE-003"
                    else [] if task["id"] == "IAM-CORE-001"
                    else [] if task["id"] == "ACCOUNT-CORE-001"
                    else [] if task["id"] == "GEO_REGION-CORE-001"
                    else [] if task["id"] == "MODEL-CORE-001"
                    else [] if task["id"] in {"MODEL-CORE-002", "MODEL-001"}
	                    else ["model_budget_policies", "model_budget_usage", "model_budget_reservations", "model_budget_commands"] if task["id"] == "MODEL-003"
                    else ["site_pages", "site_page_versions", "site_page_commands"] if task["id"] == "SITE-001"
                    else ["site_publications"] if task["id"] == "SITE-002"
                    else [] if task["id"] == "SITE-003"
                    else ["site_quality_reports"] if task["id"] == "SITE-004"
                    else ["geo_content_checks", "geo_content_commands"] if task["id"] == "GEO_CONTENT-001"
                    else ["geo_query_fixtures"] if task["id"] == "GEO_CONTENT-002"
                    else ["geo_runs"] if task["id"] == "GEO_CONTENT-003"
                    else ["region_policy_decisions"] if task["id"] == "GEO_REGION-002"
                    else ["media_scripts", "media_script_versions", "media_script_claim_refs", "media_script_commands"] if task["id"] == "MEDIA-001"
                    else ["media_storyboards", "media_storyboard_versions", "media_storyboard_shots", "media_storyboard_asset_refs", "media_storyboard_commands"] if task["id"] == "MEDIA-002"
                    else ["media_subtitles", "media_subtitle_versions", "media_subtitle_tracks", "media_subtitle_cues", "media_subtitle_commands"] if task["id"] == "MEDIA-003A"
                    else ["media_visual_asset_sets", "media_visual_asset_set_versions", "media_visual_asset_items", "media_visual_asset_commands"] if task["id"] == "MEDIA-003B"
                    else ["media_output_specs", "media_output_spec_versions", "media_output_spec_items", "media_output_spec_commands"] if task["id"] == "MEDIA-003C"
                    else ["media_render_jobs", "media_render_job_inputs", "media_render_artifacts", "media_render_commands"] if task["id"] == "MEDIA-004A"
                    else ["media_render_failures", "media_render_retry_schedules", "media_render_retry_commands", "media_render_rerender_targets"] if task["id"] == "MEDIA-004B"
                    else ["media_qa_reports", "media_qa_findings", "media_qa_commands"] if task["id"] == "MEDIA-005A"
                    else ["media_qa_content_evaluations"] if task["id"] == "MEDIA-005B"
                    else ["media_asset_lineage_edges", "media_asset_lineage_checks", "media_asset_lineage_commands"] if task["id"] == "MEDIA-006"
                    else ["metric_definitions", "metric_definition_state_events", "analytics_metric_definition_commands"] if task["id"] == "ANALYTICS-001"
                    else ["observations", "analytics_observation_commands"] if task["id"] == "ANALYTICS-002"
                    else ["analytics_kpi_snapshots", "analytics_kpi_snapshot_commands"] if task["id"] == "ANALYTICS-003"
                    else [] if task["id"] == "AGENT-CORE-001"
                    else [] if task["id"] == "AGENT-CORE-002"
                    else [] if task["id"] == "AGENT-CORE-003"
                    else [] if task["id"] == "AGENT-CORE-004"
                    else [] if task["id"] in {"AGENT-CORE-005A", "AGENT-CORE-005B", "AGENT-CORE-005C", "AGENT-CORE-005D", "AGENT-CORE-005E"}
                    else ["evaluation_prompt_versions", "evaluation_golden_set_versions", "evaluation_threshold_versions", "eval_runs", "evaluation_commands"] if task["id"] == "EVAL-001"
                    else [] if task["id"] == "PROD-001"
                    else ["content_variants", "variant_versions", "variant_commands", "variant_events"] if task["id"] == "PROD-002"
                    else ["production_terminology_versions", "production_translation_memory", "production_terminology_commands"] if task["id"] == "PROD-003"
                    else [] if task["id"] in {"PROD-004", "QA-001", "QA-002", "QA-003", "POLICY-001", "POLICY-002", "APPROVAL-001", "APPROVAL-002", "DIST-001", "DIST-002", "DIST-003A", "DIST-003B", "DIST-004", "DIST-005A", "DIST-005B", "DIST-006A", "DIST-006B", "DIST-006C", "DIST-007", "DIST-008A", "DIST-008B", "DIST-009", "DIST-010", "DIST-011"}
                    else ["topic_taxonomies", "topic_commands"] if task["id"] == "TOPIC-001"
                    else ["topic_signals", "topic_signal_imports", "topic_signal_events"] if task["id"] == "TOPIC-002"
                    else ["topic_scoring_versions", "topic_opportunities", "topic_score_snapshots", "topic_opportunity_commands", "topic_opportunity_events"] if task["id"] == "TOPIC-003"
                    else ["topic_briefs", "topic_brief_commands", "topic_brief_events"] if task["id"] == "TOPIC-004"
                    else ["topic_editorial_plans", "topic_editorial_commands", "topic_editorial_audit"] if task["id"] == "TOPIC-005"
                    else ["topic_opportunity_state_events"] if task["id"] == "TOPIC-006"
                    else ["topic_score_snapshot_verifications"] if task["id"] == "TOPIC-007"
                    else ["topic_briefs"] if task["id"] == "TOPIC-008"
                    else ["sources", "source_snapshots", "source_commands", "source_events", "source_snapshot_state_events"] if task["id"] == "PROV-001"
                    else ["rights_records", "rights_record_versions", "rights_commands", "rights_events"] if task["id"] == "PROV-002"
                    else ["rights_guard_commands", "rights_guard_decisions", "rights_expiry_reminders", "rights_lineage_edges", "rights_derivative_blocks"] if task["id"] == "PROV-003"
                    else ["entities", "claims", "evidences", "entity_claims", "claim_evidences", "knowledge_commands", "knowledge_events"] if task["id"] == "KNOW-001"
                    else ["knowledge_cores", "knowledge_core_versions", "knowledge_conflict_sets", "knowledge_core_commands"] if task["id"] == "KNOW-002"
                    else ["canonical_contents", "canonical_content_versions", "canonical_claims", "canonical_commands", "canonical_events"] if task["id"] == "CANON-001"
                    else ["canonical_content_version_diffs"] if task["id"] == "CANON-002"
                    else ["canonical_content_versions"] if task["id"] == "CANON-003"
                    else [] if task["id"] in {"WORKFLOW-CORE-001", "WORKFLOW-CORE-002", "WORKFLOW-CORE-003", "FEEDBACK-CORE-001", "FEEDBACK-CORE-002", "SCHED-001"}
                    else TABLES.get(module, [])
                ),
                "rules": [
                    "one owner migration per task",
                    "expand/contract for breaking changes",
                    "org_id and tenant-scoped foreign keys for tenant-owned tables",
                    "no destructive SQL in the expand step",
                ],
            }
        )
    value = {
        "schema_version": 1,
        "status": "baseline",
        "migration_tool": "alembic_or_existing_repository_tool",
        "lifecycle": {
            "planned": "planned path may be absent and is documentation only",
            "in_progress": "real migration revision must exist and pass lint plus disposable database execution",
            "done": "real migration must be executed and verification evidence recorded",
            "blocked": "retain current reference and record dependency, owner, fallback and next review time",
        },
        "execution_rule": "planned paths are documentation; in_progress requires a real revision; done requires executed verification evidence",
        "migrations": migrations,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
    print(f"wrote {OUT} ({len(migrations)} task migrations)")


if __name__ == "__main__":
    main()
