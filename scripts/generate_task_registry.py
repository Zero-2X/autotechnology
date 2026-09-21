"""Generate the machine task registry from the checked Markdown plan.

The Markdown checklist remains the human entry point during planning.  The generated
YAML is the machine source consumed by Codex/CI.  This script deliberately fails when
the document contains a composite or duplicate checkbox ID.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

try:
    import yaml
except ImportError as exc:  # pragma: no cover - bootstrap diagnostic
    raise SystemExit("PyYAML is required: python -m pip install pyyaml") from exc


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "AI跨境技术内容自动化工作流开发清单_审计与优化版.md"
REGISTRY = ROOT / "docs" / "task-registry.yaml"


PREFIX_MODULES = [
    ("GEO_CONTENT", "geo_content"),
    ("GEO_REGION", "geo_region"),
    ("AGENT-CORE", "agent"),
    ("ACCOUNT-CORE", "distribution_account"),
    ("IAM-CORE", "iam"),
    ("WORKFLOW-CORE", "workflow"),
    ("MODEL-CORE", "model_gateway"),
    ("OBS-CORE", "audit"),
    ("FEEDBACK-CORE", "feedback"),
    ("FEEDBACK-LIVE", "feedback"),
    ("FEEDBACK-EXP", "feedback"),
    ("GOV", "governance"),
    ("FOUND", "foundation"),
    ("IAM", "iam"),
    ("ACCOUNT", "distribution_account"),
    ("TOPIC", "topic"),
    ("PROV", "provenance"),
    ("KNOW", "knowledge"),
    ("CANON", "canonical_content"),
    ("PROD", "production"),
    ("QA", "qa"),
    ("POLICY", "policy"),
    ("APPROVAL", "approval"),
    ("WORKFLOW", "workflow"),
    ("MODEL", "model_gateway"),
    ("SCHED", "scheduler"),
    ("OAUTH", "distribution_oauth"),
    ("EVAL", "evaluation"),
    ("OBS", "audit"),
    ("SITE", "knowledge_site"),
    ("MEDIA", "media"),
    ("DIST", "distribution"),
    ("PLAT", "platform_adapter"),
    ("ANALYTICS", "analytics"),
    ("SUP", "support"),
    ("PILOT", "operations"),
]

MODULE_PATHS = {
    "governance": "docs/governance",
    "foundation": "infra/foundation",
    "iam": "modules/iam",
    "distribution_account": "modules/distribution/account",
    "topic": "modules/topic",
    "provenance": "modules/provenance",
    "knowledge": "modules/knowledge",
    "canonical_content": "modules/canonical_content",
    "production": "modules/production",
    "qa": "modules/qa",
    "policy": "modules/policy",
    "approval": "modules/approval",
    "agent": "modules/agent",
    "workflow": "modules/workflow",
    "model_gateway": "modules/model_gateway",
    "scheduler": "apps/scheduler",
    "distribution_oauth": "modules/distribution/oauth",
    "evaluation": "packages/prompt_registry",
    "audit": "modules/audit",
    "knowledge_site": "apps/knowledge-site",
    "geo_content": "modules/geo_content",
    "geo_region": "modules/geo_region",
    "media": "modules/media",
    "distribution": "modules/distribution",
    "platform_adapter": "adapters/platforms",
    "analytics": "modules/analytics",
    "feedback": "modules/feedback",
    "support": "modules/support",
    "operations": "docs/runbooks",
    "unassigned": "docs",
}

EXTRA_ALLOWED = {
    "foundation": ["apps", "packages", "infra", "deploy/environments/dev", "deploy/environments/staging", "scripts", "docs"],
    "governance": ["docs/adr", "infra/policies"],
    "iam": ["apps/api", "tests/security"],
    "distribution_account": ["apps/api", "adapters/contract", "tests/security"],
    "distribution_oauth": ["apps/api", "adapters/contract", "adapters/platforms", "deploy/environments/staging", "tests/security"],
    "platform_adapter": ["adapters/contract", "tests/contract", "tests/replay"],
    "distribution": ["adapters/contract", "adapters/manual", "adapters/fake", "tests/replay"],
    "knowledge_site": ["apps/api", "tests/accessibility", "tests/e2e"],
    "media": ["apps/worker", "adapters/fake", "tests/accessibility"],
    "scheduler": ["apps/worker", "tests/integration"],
    "operations": ["apps/web-console", "tests/e2e"],
    "evaluation": ["tests/eval", "tests/replay"],
    "audit": ["packages/observability", "infra/scripts", "tests/security"],
    "support": ["adapters/fake", "apps/web-console"],
}

SHARED_PATHS = [
    "packages/contracts",
    "packages/db/migrations",
    "tests/unit",
    "tests/integration",
    "tests/contract",
]

TASK_EXTRA_ALLOWED = {
    "FOUND-001": ["modules", "adapters/contract", "adapters/fake", "adapters/manual", "README.md", "CONTRIBUTING.md", "CODEOWNERS"],
    "CANON-005": ["docs/foundation"],
    "GEO_REGION-002": ["apps/knowledge-site"],
    "MEDIA-001": ["docs/foundation"],
    "MEDIA-002": ["docs/foundation"],
    "MEDIA-003A": ["docs/foundation"],
    "MEDIA-003B": ["docs/foundation"],
    "MEDIA-003C": ["docs/foundation"],
    "MEDIA-004A": ["docs/foundation"],
    "MEDIA-004B": ["docs/foundation"],
    "MEDIA-005A": ["docs/foundation"],
    "MEDIA-005B": ["docs/foundation"],
    "MEDIA-006": ["docs/foundation"],
}

PHASE_TIERS = {0: "P0", 1: "P0", 2: "P0", 3: "P0", 4: "P0", 5: "P1", 6: "P1", 7: "P0", 8: "M2", 9: "P1", 10: "M3"}
PRIORITY = {"P0": "critical", "P1": "high", "M2": "normal", "M3": "low"}

# A phase is a delivery grouping, not a promise that every item in it blocks
# the first vertical slice.  These items improve scale, provider coverage or
# operations and therefore stay outside the account-free core gate.
TIER_OVERRIDES = {
    "FOUND-003C": "P1",       # Redis is optional for the DB-polling baseline.
    "FOUND-012B": "P1",       # SBOM signing can follow the first executable slice.
    "AGENT-CORE-005A": "P1",
    "AGENT-CORE-005B": "P1",
    "AGENT-CORE-005C": "P1",
    "AGENT-CORE-005D": "P1",
    "AGENT-CORE-005E": "P1",
    "SCHED-001": "P1",        # Manual trigger is sufficient for the first slice.
    "OBS-CORE-002": "P1",     # Disaster recovery drill follows the local slice.
    "OBS-CORE-003": "P1",     # Deletion propagation is implemented before production data.
    "EVAL-001": "P1",
    "MODEL-003": "P1",
    "DIST-005A": "P1",        # Platform-specific mapping is post-core.
    "DIST-005B": "P1",        # Provider quota policy is post-core.
}


def task_group(task_id: str) -> str:
    parts = task_id.split("-")
    if len(parts) >= 3 and parts[1] in {"CORE", "LIVE", "EXP"}:
        return "-".join(parts[:2])
    return parts[0]


def module_for(task_id: str) -> str:
    for prefix, module in PREFIX_MODULES:
        if task_id == prefix or task_id.startswith(prefix + "-"):
            return module
    return "unassigned"


def parse_tasks() -> tuple[list[dict], dict[int, str]]:
    lines = DOCUMENT.read_text(encoding="utf-8").splitlines()
    phase: int | None = None
    phase_names: dict[int, str] = {}
    tasks: list[dict] = []
    for line_no, line in enumerate(lines, 1):
        heading = re.match(r"^###\s+阶段\s+(\d+)[：:]?\s*(.*)$", line)
        if heading:
            phase = int(heading.group(1))
            phase_names[phase] = heading.group(2).strip()
            continue
        match = re.match(r"^\s*-\s*\[([ xX])\]\s*`([^`]+)`\s*(.*)$", line)
        if match:
            if phase is None:
                raise SystemExit(f"task before a phase heading at line {line_no}")
            tasks.append({"id": match.group(2).strip(), "title": match.group(3).strip(),
                          "phase": phase, "source_line": line_no,
                          "status": "done" if match.group(1).lower() == "x" else "planned"})
    ids = [t["id"] for t in tasks]
    composite = [t["id"] for t in tasks if "/" in t["id"]]
    if composite:
        raise SystemExit("composite checkbox IDs: " + ", ".join(composite))
    duplicate = sorted({task_id for task_id in ids if ids.count(task_id) > 1})
    if duplicate:
        raise SystemExit("duplicate checkbox IDs: " + ", ".join(duplicate))
    return tasks, phase_names


# Cross-module prerequisites. Same-group sequencing is added automatically below.
CROSS = {
    "GOV-002": ["GOV-001"], "GOV-003": ["GOV-001"], "GOV-004": ["GOV-001", "GOV-002"],
    "GOV-005": ["GOV-004"], "GOV-006": ["GOV-001"], "GOV-007": ["GOV-001"],
    "GOV-008": ["GOV-002", "GOV-003", "GOV-007"], "GOV-009": ["GOV-003"], "GOV-010": ["GOV-007"],
    "FOUND-001": ["FOUND-000", "GOV-006"], "FOUND-002": ["FOUND-001"], "FOUND-003D": ["FOUND-003A"],
    "FOUND-004A": ["FOUND-003A"], "FOUND-004B": ["FOUND-004A"], "FOUND-004C": ["FOUND-003D", "FOUND-004B"],
    "FOUND-004D": ["FOUND-004C"], "FOUND-004E": ["FOUND-004D"], "FOUND-005": ["FOUND-001"],
    "FOUND-006A": ["FOUND-005"], "FOUND-006B": ["FOUND-005"],
    "FOUND-007A": ["FOUND-001", "FOUND-004A"], "FOUND-007B": ["FOUND-001", "FOUND-004A"],
    "FOUND-007C": ["FOUND-001", "FOUND-004A"], "FOUND-007D": ["FOUND-001", "FOUND-007A", "FOUND-007B"],
    "FOUND-008": ["FOUND-005"], "FOUND-009": ["FOUND-003A", "FOUND-003B", "FOUND-005"],
    "FOUND-010": ["FOUND-007A", "FOUND-007B", "FOUND-009", "GOV-005"], "FOUND-011": ["FOUND-001"],
    "FOUND-012A": ["FOUND-001"], "FOUND-012B": ["FOUND-012A"], "FOUND-013": ["FOUND-001", "FOUND-007D"],
    "IAM-CORE-001": ["FOUND-005", "FOUND-004A"], "ACCOUNT-CORE-001": ["FOUND-010", "IAM-CORE-001", "GOV-005"],
    "GEO_REGION-CORE-001": ["FOUND-004A", "GOV-007"], "MODEL-CORE-001": ["FOUND-007C", "FOUND-009"],
    "MODEL-CORE-002": ["MODEL-CORE-001", "FOUND-004B"], "AGENT-CORE-001": ["MODEL-CORE-001", "FOUND-007C"],
    "AGENT-CORE-002": ["AGENT-CORE-001", "MODEL-CORE-002"], "AGENT-CORE-003": ["AGENT-CORE-002"],
    "AGENT-CORE-004": ["AGENT-CORE-002", "FOUND-004A"], "WORKFLOW-CORE-001": ["FOUND-004B"],
    "WORKFLOW-CORE-002": ["WORKFLOW-CORE-001", "FOUND-004A"], "WORKFLOW-CORE-003": ["WORKFLOW-CORE-002", "FOUND-004B"],
    "FEEDBACK-CORE-001": ["FOUND-007B", "FOUND-004A"], "SCHED-001": ["GEO_REGION-CORE-001", "FOUND-004C"],
    "OBS-CORE-001": ["FOUND-005", "FOUND-006A", "FOUND-006B", "FOUND-004B"],
    "OBS-CORE-002": ["FOUND-003A", "FOUND-003B", "FOUND-004A", "OBS-CORE-001"],
    "OBS-CORE-003": ["OBS-CORE-002", "WORKFLOW-CORE-002"],
    "TOPIC-001": ["IAM-CORE-001", "FOUND-007A"], "TOPIC-002": ["TOPIC-001"], "TOPIC-003": ["TOPIC-002"],
    "TOPIC-004": ["TOPIC-003"], "TOPIC-005": ["TOPIC-004"], "TOPIC-006": ["TOPIC-003", "TOPIC-004"], "TOPIC-007": ["TOPIC-003"],
    "TOPIC-008": ["TOPIC-004", "TOPIC-006"],
    "PROV-001": ["TOPIC-002", "FOUND-003A", "FOUND-003B"], "PROV-002": ["PROV-001"], "PROV-003": ["PROV-002", "WORKFLOW-CORE-002"],
    "KNOW-001": ["PROV-001"], "KNOW-002": ["KNOW-001", "PROV-002"], "CANON-001": ["TOPIC-004", "KNOW-002"],
    "CANON-002": ["CANON-001"], "CANON-003": ["CANON-002", "TOPIC-004"], "CANON-004": ["CANON-003", "KNOW-001", "PROV-002"],
    # Freshness/refresh can be triggered manually in the account-free core;
    # scheduler integration is an optional P1 follow-up and must not block P0.
    "CANON-005": ["CANON-004", "WORKFLOW-CORE-002"], "CANON-006": ["CANON-002", "CANON-004"],
    "AGENT-CORE-005A": ["AGENT-CORE-002", "TOPIC-004", "WORKFLOW-CORE-001"], "AGENT-CORE-005B": ["AGENT-CORE-002", "PROV-001", "KNOW-001"],
    "AGENT-CORE-005C": ["AGENT-CORE-002", "PROV-002", "CANON-002", "AGENT-CORE-005B"], "AGENT-CORE-005D": ["AGENT-CORE-002", "CANON-002", "KNOW-001"],
    "AGENT-CORE-005E": ["AGENT-CORE-002"], "MODEL-001": ["MODEL-CORE-002", "GOV-010", "CANON-002"],
    # M1 uses a deterministic/Fake TransformPort; the optional Transform Agent
    # is integrated later without making the core variant path depend on P1.
    "PROD-001": ["CANON-002"], "PROD-002": ["PROD-001", "GEO_REGION-CORE-001"], "PROD-003": ["PROD-002"],
    "PROD-004": ["PROD-002", "GEO_REGION-CORE-001"], "QA-001": ["PROD-002", "CANON-004", "KNOW-002"],
    "QA-002": ["PROD-002", "PROD-003", "PROV-002"], "QA-003": ["PROD-002", "FOUND-009"],
    "POLICY-001": ["QA-001", "QA-002", "QA-003", "GOV-004", "GOV-005", "GEO_REGION-CORE-001"], "POLICY-002": ["POLICY-001", "GOV-005"],
    "APPROVAL-001": ["POLICY-001", "WORKFLOW-CORE-002", "IAM-CORE-001"], "APPROVAL-002": ["APPROVAL-001", "IAM-CORE-001"], "EVAL-001": ["MODEL-CORE-002", "AGENT-CORE-001", "GOV-008"],
    "MODEL-003": ["MODEL-CORE-002", "GOV-008"], "SITE-001": ["PROD-002", "CANON-006"], "SITE-002": ["SITE-001"], "SITE-003": ["SITE-001"],
    "GEO_CONTENT-001": ["SITE-001", "CANON-006"],
    # Keep the card's explicit prerequisite set visible in the generator too.
    # Phase 5 already anchors these tasks to PROD-002, but relying on the
    # implicit anchor makes the cross-module contract easy to drift.
    "GEO_CONTENT-002": ["PROD-002", "SITE-002", "GEO_CONTENT-001"],
    "GEO_CONTENT-003": ["GEO_CONTENT-002", "FOUND-009"],
    "GEO_REGION-001": ["GEO_REGION-CORE-001", "PROD-003"], "GEO_REGION-002": ["GEO_REGION-001", "SITE-002"], "SITE-004": ["SITE-002", "GEO_REGION-002"],
    "MEDIA-001": ["PROD-002", "CANON-006"], "MEDIA-002": ["MEDIA-001", "PROV-002"], "MEDIA-003A": ["MEDIA-001", "PROD-002"],
    "MEDIA-003B": ["MEDIA-002", "PROV-002"], "MEDIA-003C": ["MEDIA-001"], "MEDIA-004A": ["MEDIA-001", "MEDIA-002", "MEDIA-003A", "MEDIA-003B", "MEDIA-003C"],
    "MEDIA-004B": ["MEDIA-004A", "FOUND-004D"], "MEDIA-005A": ["MEDIA-004A"], "MEDIA-005B": ["MEDIA-005A", "PROV-002", "QA-001"], "MEDIA-006": ["MEDIA-005B", "CANON-006"],
    "DIST-001": ["FOUND-010", "ACCOUNT-CORE-001", "POLICY-001"], "DIST-002": ["DIST-001", "FOUND-010"], "DIST-003A": ["DIST-001", "PROD-002"],
    "DIST-003B": ["DIST-003A", "FOUND-003B"], "DIST-004": ["DIST-002", "FOUND-009"], "DIST-005A": ["DIST-002", "DIST-004"], "DIST-005B": ["DIST-005A", "FOUND-004D"],
    "DIST-006A": ["DIST-001", "FOUND-004B"], "DIST-006B": ["DIST-006A", "DIST-004"], "DIST-006C": ["DIST-006B", "FOUND-004D", "FOUND-004E"],
    "DIST-007": ["DIST-003A", "DIST-004", "POLICY-001", "FOUND-008"], "DIST-008A": ["DIST-001", "FOUND-004A"], "DIST-008B": ["DIST-007", "POLICY-002", "FOUND-008"],
    "DIST-009": ["CANON-006", "PROD-002", "QA-001", "APPROVAL-001", "DIST-003A", "DIST-007"], "DIST-010": ["DIST-006C", "DIST-009", "DIST-004"],
    "FEEDBACK-CORE-002": ["FEEDBACK-CORE-001", "DIST-010", "CANON-005"], "ACCOUNT-001A": ["DIST-008A", "GOV-009"], "ACCOUNT-001B": ["ACCOUNT-001A", "IAM-CORE-001"],
    "ACCOUNT-001C": ["ACCOUNT-001B", "DIST-008A", "POLICY-001"], "OAUTH-001A": ["ACCOUNT-001A", "DIST-002"], "OAUTH-001B": ["OAUTH-001A"], "OAUTH-001C": ["OAUTH-001B"],
    "OAUTH-002A": ["OAUTH-001C"], "OAUTH-002B": ["OAUTH-002A"], "ACCOUNT-002": ["ACCOUNT-001B", "OAUTH-002B"], "IAM-CORE-002": ["IAM-CORE-001", "ACCOUNT-001B"],
    "ACCOUNT-003": ["ACCOUNT-002", "FOUND-008", "DIST-006C"], "PLAT-001": ["OAUTH-001A", "DIST-002"], "PLAT-002": ["PLAT-001", "ACCOUNT-003"], "PLAT-003": ["PLAT-001", "DIST-010"],
    "ANALYTICS-001": ["FOUND-007B", "DIST-010"], "ANALYTICS-002": ["FEEDBACK-CORE-001", "ANALYTICS-001"], "ANALYTICS-003": ["ANALYTICS-002", "DIST-010"],
    "ANALYTICS-004": ["ANALYTICS-002", "GEO_CONTENT-003", "GEO_REGION-002"], "FEEDBACK-CORE-003": ["FEEDBACK-CORE-001", "ANALYTICS-002"],
    "FEEDBACK-CORE-004": ["FEEDBACK-CORE-003", "TOPIC-007", "CANON-005", "PROD-002", "EVAL-001"], "FEEDBACK-LIVE-001": ["ANALYTICS-003", "PLAT-003", "ACCOUNT-002"],
    "FEEDBACK-CORE-005": ["FEEDBACK-CORE-004", "POLICY-001", "WORKFLOW-CORE-002"],
    "FEEDBACK-LIVE-001": ["ANALYTICS-003", "PLAT-003", "ACCOUNT-002", "FEEDBACK-CORE-005"],
    # Experiments can run on synthetic/manual observations; live attribution
    # is an optional M2 input rather than a P1 prerequisite.
    "FEEDBACK-EXP-001": ["ANALYTICS-003", "EVAL-001"], "SUP-001": ["ANALYTICS-002", "KNOW-002", "POLICY-001", "PLAT-003"], "SUP-002": ["SUP-001", "GOV-004"],
    "PILOT-001": ["PLAT-002", "ACCOUNT-002"], "PILOT-002": ["PILOT-001", "FEEDBACK-LIVE-001", "ANALYTICS-003"], "PILOT-003": ["PILOT-002", "ACCOUNT-002"],
    "PILOT-004": ["PILOT-003", "OBS-CORE-002", "DIST-010"], "PILOT-005": ["PILOT-004", "PILOT-002"],
}

PHASE_ANCHOR = {1: ["GOV-006", "FOUND-000"], 2: ["FOUND-011"], 3: ["TOPIC-004"], 4: ["CANON-002"], 5: ["PROD-002"], 6: ["PROD-002"], 7: ["POLICY-001"], 8: ["DIST-010", "GOV-009"], 9: ["DIST-010"], 10: ["PLAT-002"]}


def contract_refs_for(task_id: str, module: str) -> list[str]:
    """Return concrete object-level contract paths for a task.

    A module-level union remains the fallback for governance and future tasks,
    but core build tasks point at the exact records they create or change.  This
    prevents Codex from treating a large aggregate schema as an invitation to
    implement unrelated objects.
    """
    exact: dict[str, list[str]] = {
        "FOUND-000": ["foundation"], "FOUND-001": ["foundation", "branch-protection"], "FOUND-002": ["foundation", "runtime-entry"],
        "FOUND-003A": ["foundation"], "FOUND-003B": ["foundation"], "FOUND-003C": ["foundation"],
        "FOUND-003D": ["task-job", "task-queue-config"], "FOUND-004A": ["foundation", "migration-baseline"], "FOUND-004B": ["outbox-event", "event-envelope"],
        "FOUND-004C": ["task-job", "event-envelope"], "FOUND-004D": ["task-job", "task-failure", "human-task"], "FOUND-004E": ["task-job"],
        "FOUND-005": ["foundation", "api-error", "correlation-context", "structured-log"], "FOUND-006A": ["foundation"], "FOUND-006B": ["foundation"],
        "FOUND-007A": ["foundation"], "FOUND-007B": ["foundation"], "FOUND-007C": ["agent-definition"],
        "FOUND-007D": ["foundation"], "FOUND-008": ["kill-switch"], "FOUND-009": ["foundation"],
        "FOUND-010": ["platform", "distribution-target", "distribution-target-version", "publication-intent", "delivery-attempt"],
          "FOUND-011": ["foundation"], "FOUND-012A": ["foundation"], "FOUND-012B": ["foundation", "supply-chain"],
        "FOUND-013": ["foundation"],
        "IAM-CORE-001": ["internal-iam"], "IAM-CORE-002": ["internal-iam"],
        "ACCOUNT-CORE-001": ["account-profile", "distribution-target", "distribution-target-version"],
        "GEO_REGION-CORE-001": ["region-profile", "region-profile-version"],
        "MODEL-CORE-001": ["model-gateway", "model-call"], "MODEL-CORE-002": ["model-gateway", "model-call"],
        "AGENT-CORE-001": ["agent-definition"], "AGENT-CORE-002": ["agent-run"],
        "AGENT-CORE-003": ["agent-run"], "AGENT-CORE-004": ["agent-run", "model-call"],
        "WORKFLOW-CORE-001": ["workflow-run", "human-task", "task-job"],
        "WORKFLOW-CORE-002": ["workflow-run", "workflow-step", "human-task"],
        "WORKFLOW-CORE-003": ["outbox-event", "task-job"], "FEEDBACK-CORE-001": ["observation", "feedback-item", "feedback-scoring-version"],
        "SCHED-001": ["scheduler-job"], "OBS-CORE-001": ["audit-log", "outbox-event"],
        "OBS-CORE-002": ["deletion-request"], "OBS-CORE-003": ["deletion-request"],
        "TOPIC-001": ["topic-taxonomy"], "TOPIC-002": ["topic-signal"], "TOPIC-003": ["topic-opportunity", "topic-score-snapshot"],
        "TOPIC-004": ["topic-brief"], "TOPIC-005": ["topic-opportunity"], "TOPIC-006": ["topic-opportunity"],
        "TOPIC-007": ["topic-score-snapshot"], "TOPIC-008": ["topic-brief"],
        "PROV-001": ["source", "source-snapshot"], "PROV-002": ["rights-record", "rights-record-version"],
        "PROV-003": ["rights-record", "rights-record-version"],
        "KNOW-001": ["entity", "claim", "evidence"], "KNOW-002": ["knowledge-core", "knowledge-core-version"],
        "CANON-001": ["canonical-content", "canonical-content-version"], "CANON-002": ["canonical-content-version"],
        "CANON-003": ["canonical-content-version"], "CANON-004": ["canonical-content-version", "claim", "evidence"],
        "CANON-005": ["canonical-content-version"], "CANON-006": ["lineage-query"],
        "AGENT-CORE-005A": ["agent-run", "planner-input", "planner-output"], "AGENT-CORE-005B": ["agent-run", "research-input", "research-output", "source-snapshot"], "AGENT-CORE-005C": ["agent-run", "rights-provenance-input", "rights-provenance-output", "rights-record-version"],
        "AGENT-CORE-005D": ["agent-run", "transform-input", "transform-output", "variant-draft", "canonical-content-version"], "AGENT-CORE-005E": ["agent-run", "qa-agent-input", "qa-agent-output", "qa-report", "human-task"],
        "MODEL-001": ["model-gateway", "model-call", "approved-model-provider"],
        "MODEL-003": ["model-gateway", "model-call", "model-budget-policy", "model-budget-decision"],
        "PROD-001": ["variant-version", "variant-draft"], "PROD-002": ["content-variant", "variant-version"],
        "PROD-003": ["variant-version", "terminology-version", "translation-memory-entry"],
        "PROD-004": ["variant-version", "region-profile-version", "region-rule-decision"],
        "QA-001": ["qa-report", "claim", "evidence"], "QA-002": ["qa-report", "variant-version"],
        "QA-003": ["sandbox-run"], "POLICY-001": ["policy-snapshot", "policy-decision"],
        "POLICY-002": ["policy-snapshot", "policy-decision"], "APPROVAL-001": ["approval"],
        "APPROVAL-002": ["approval", "approval-decision"],
        "EVAL-001": ["prompt-version", "golden-set-version", "regression-threshold-version", "eval-run"],
        "SITE-001": ["site-page-version"], "SITE-002": ["site-page-version", "site-publication"],
        "SITE-003": ["site-page-version", "site-structured-data"],
        "SITE-004": ["site-page-version", "site-quality-report"], "GEO_CONTENT-001": [
            "geo-content-assessment", "site-page-version", "canonical-content-version",
            "claim", "evidence", "source-snapshot", "rights-record-version",
        ],
        "GEO_CONTENT-002": ["geo-query-fixture"], "GEO_CONTENT-003": ["geo-run"],
        "GEO_REGION-001": ["region-profile", "region-profile-version", "geo_region"],
        "GEO_REGION-002": ["region-profile-version", "region-check-decision", "region-deletion-policy"],
        "MEDIA-001": ["asset-version", "media-script", "media-script-version"], "MEDIA-002": ["asset-version", "rights-record-version", "media-storyboard", "media-storyboard-version"],
        "MEDIA-003A": ["media-subtitle", "media-subtitle-version"], "MEDIA-003B": ["asset-version", "rights-record-version", "media-visual-asset-set", "media-visual-asset-set-version"], "MEDIA-003C": ["asset-version", "media-visual-asset-set-version", "media-output-spec", "media-output-spec-version"], "MEDIA-004A": ["render-job", "asset-version"],
        "MEDIA-004B": ["render-job", "task-failure", "render-retry"], "MEDIA-005A": ["qa-report", "render-job", "media-output-spec-version", "media-subtitle-version"],
        "MEDIA-005B": ["qa-report", "asset-version", "render-job"], "MEDIA-006": ["asset-version", "media-asset-lineage"],
        "DIST-001": ["distribution-target", "distribution-target-version", "publication-intent", "export-package", "delivery-attempt", "publication-record"],
        "DIST-002": ["publisher-capability"], "DIST-003A": ["export-package"], "DIST-003B": ["export-package"],
        "DIST-004": ["publication-record", "delivery-attempt"], "DIST-005A": ["publisher-capability"],
        "DIST-005B": ["delivery-attempt"], "DIST-006A": ["publication-intent", "delivery-attempt"],
        "DIST-006B": ["publication-record", "delivery-attempt"], "DIST-006C": ["publication-record", "human-task"],
        "DIST-007": ["publication-intent", "distribution-target-version"], "DIST-008A": ["distribution-target-version"],
        "DIST-008B": ["publication-intent", "kill-switch"], "DIST-009": ["publication-intent", "export-package"],
        "DIST-010": ["delivery-attempt", "publication-record"], "DIST-011": ["webhook-receipt"],
        "FEEDBACK-CORE-002": ["observation", "feedback-item"], "FEEDBACK-CORE-003": ["feedback-item"],
        "FEEDBACK-CORE-004": ["feedback-item", "feedback-recommendation"], "FEEDBACK-CORE-005": ["feedback-action"],
        "FEEDBACK-LIVE-001": ["observation"], "FEEDBACK-EXP-001": ["eval-run", "feedback-experiment"],
        "ACCOUNT-001A": ["account-profile", "account-connection"], "ACCOUNT-001B": ["authorization-evidence"],
        "ACCOUNT-001C": ["distribution-target-version"], "ACCOUNT-002": ["account-connection"],
        "ACCOUNT-003": ["account-connection", "kill-switch"], "OAUTH-001A": ["oauth-authorization-session"],
        "OAUTH-001B": ["oauth-authorization-session"], "OAUTH-001C": ["authorization-evidence"],
        "OAUTH-002A": ["token-lease"], "OAUTH-002B": ["token-lease"],
        "PLAT-001": ["publisher-capability"], "PLAT-002": ["publisher-capability"], "PLAT-003": ["publisher-capability"],
        "ANALYTICS-001": ["metric-definition", "analytics-event-catalog"], "ANALYTICS-002": ["observation"],
        "ANALYTICS-003": ["observation", "analytics-kpi-snapshot"], "ANALYTICS-004": ["observation", "analytics-geo-quality-snapshot"],
        "SUP-001": ["support-thread", "support-message"], "SUP-002": ["support-thread", "support-message"],
        "PILOT-001": ["pilot-run"], "PILOT-002": ["pilot-run"], "PILOT-003": ["pilot-run"],
        "PILOT-004": ["pilot-run"], "PILOT-005": ["pilot-run"],
    }
    if task_id == "GOV-001":
        return [
            "packages/contracts/jsonschema/governance.schema.json",
            "packages/contracts/jsonschema/vertical-scope.schema.json",
        ]
    if task_id == "GOV-005":
        return [
            "packages/contracts/jsonschema/governance.schema.json",
            "packages/contracts/jsonschema/policy-card.schema.json",
            "packages/contracts/jsonschema/policy-snapshot.schema.json",
        ]
    if task_id == "FOUND-003A":
        return ["packages/contracts/jsonschema/foundation.schema.json", "packages/contracts/jsonschema/database-config.schema.json", "packages/contracts/openapi/openapi.yaml"]
    if task_id == "FOUND-003B":
        return ["packages/contracts/jsonschema/foundation.schema.json", "packages/contracts/jsonschema/storage-config.schema.json", "packages/contracts/jsonschema/storage-object.schema.json"]
    if task_id == "FOUND-006A":
        return ["packages/contracts/jsonschema/foundation.schema.json", "packages/contracts/jsonschema/metrics-baseline.schema.json", "packages/contracts/openapi/openapi.yaml"]
    if task_id == "FOUND-006B":
        return ["packages/contracts/jsonschema/foundation.schema.json", "packages/contracts/jsonschema/tracing-cost-baseline.schema.json", "packages/contracts/jsonschema/cost-record.schema.json", "packages/contracts/jsonschema/correlation-context.schema.json"]
    if task_id == "FOUND-007A":
        return ["packages/contracts/jsonschema/foundation.schema.json", "packages/contracts/events/event-envelope.schema.json", "packages/contracts/jsonschema/api-contract-baseline.schema.json", "packages/contracts/openapi/openapi.yaml"]
    if task_id == "FOUND-007B":
        return ["packages/contracts/jsonschema/foundation.schema.json", "packages/contracts/events/event-envelope.schema.json", "packages/contracts/jsonschema/event-compatibility-baseline.schema.json"]
    if task_id == "FOUND-007C":
        return ["packages/contracts/jsonschema/agent-definition.schema.json", "packages/contracts/jsonschema/agent-output.schema.json", "packages/contracts/jsonschema/foundation.schema.json"]
    if task_id == "FOUND-007D":
        return [
            "packages/contracts/jsonschema/foundation.schema.json",
            "packages/contracts/events/event-envelope.schema.json",
            "packages/contracts/jsonschema/topic-signal.schema.json",
            "packages/contracts/jsonschema/topic-opportunity.schema.json",
            "packages/contracts/jsonschema/topic-brief.schema.json",
            "packages/contracts/jsonschema/topic-score-snapshot.schema.json",
            "packages/contracts/jsonschema/canonical-content.schema.json",
            "packages/contracts/jsonschema/canonical-content-version.schema.json",
            "packages/contracts/jsonschema/variant-version.schema.json",
            "packages/contracts/jsonschema/content-variant.schema.json",
            "packages/contracts/jsonschema/asset.schema.json",
            "packages/contracts/jsonschema/asset-version.schema.json",
            "packages/contracts/jsonschema/publication-intent.schema.json",
            "packages/contracts/jsonschema/delivery-attempt.schema.json",
            "packages/contracts/jsonschema/export-package.schema.json",
            "packages/contracts/jsonschema/publication-record.schema.json",
            "packages/contracts/jsonschema/observation.schema.json",
            "packages/contracts/jsonschema/feedback-item.schema.json",
            "packages/contracts/jsonschema/source.schema.json",
            "packages/contracts/jsonschema/source-snapshot.schema.json",
            "packages/contracts/jsonschema/entity.schema.json",
            "packages/contracts/jsonschema/claim.schema.json",
            "packages/contracts/jsonschema/evidence.schema.json",
            "packages/contracts/jsonschema/knowledge-core.schema.json",
            "packages/contracts/jsonschema/knowledge-core-version.schema.json",
            "packages/contracts/jsonschema/platform.schema.json",
            "packages/contracts/jsonschema/rights-record.schema.json",
            "packages/contracts/jsonschema/rights-record-version.schema.json",
            "packages/contracts/jsonschema/distribution-target.schema.json",
            "packages/contracts/jsonschema/distribution-target-version.schema.json",
            "packages/contracts/jsonschema/account-profile.schema.json",
            "packages/contracts/jsonschema/authorization-evidence.schema.json",
            "packages/contracts/jsonschema/policy-decision.schema.json",
            "packages/contracts/jsonschema/account-connection.schema.json",
            "packages/contracts/jsonschema/region-profile.schema.json",
            "packages/contracts/jsonschema/region-profile-version.schema.json",
            "packages/contracts/jsonschema/policy-snapshot.schema.json",
            "packages/contracts/jsonschema/metric-definition.schema.json",
            "packages/contracts/jsonschema/approval.schema.json",
            "packages/contracts/jsonschema/approval-decision.schema.json",
            "packages/contracts/jsonschema/human-task.schema.json",
            "packages/contracts/jsonschema/feedback-action.schema.json",
            "packages/contracts/jsonschema/task-job.schema.json",
            "packages/contracts/jsonschema/outbox-event.schema.json",
            "packages/contracts/jsonschema/task-failure.schema.json",
            "packages/contracts/jsonschema/site-page-version.schema.json",
            "packages/contracts/jsonschema/geo-query-fixture.schema.json",
            "packages/contracts/jsonschema/geo-run.schema.json",
            "packages/contracts/jsonschema/webhook-receipt.schema.json",
            "packages/contracts/jsonschema/deletion-request.schema.json",
            "packages/contracts/jsonschema/kill-switch.schema.json",
        ]
    if task_id == "FOUND-012B":
        return ["packages/contracts/jsonschema/foundation.schema.json", "packages/contracts/jsonschema/supply-chain.schema.json"]
    if task_id == "GOV-002":
        return [
            "packages/contracts/jsonschema/governance.schema.json",
            "packages/contracts/jsonschema/release-levels.schema.json",
        ]
    if task_id == "GOV-003":
        return [
            "packages/contracts/jsonschema/governance.schema.json",
            "packages/contracts/jsonschema/raci-policy.schema.json",
        ]
    if task_id == "GOV-004":
        return [
            "packages/contracts/jsonschema/governance.schema.json",
            "packages/contracts/jsonschema/risk-policy.schema.json",
        ]
    if task_id == "GOV-006":
        return [
            "packages/contracts/jsonschema/governance.schema.json",
            "packages/contracts/jsonschema/tech-stack-baseline.schema.json",
        ]
    if task_id == "GOV-007":
        return [
            "packages/contracts/jsonschema/governance.schema.json",
            "packages/contracts/jsonschema/data-processing-policy.schema.json",
        ]
    if task_id == "GOV-008":
        return [
            "packages/contracts/jsonschema/governance.schema.json",
            "packages/contracts/jsonschema/operational-targets.schema.json",
        ]
    if task_id == "GOV-009":
        return [
            "packages/contracts/jsonschema/governance.schema.json",
            "packages/contracts/jsonschema/real-account-dependency.schema.json",
        ]
    if task_id == "GOV-010":
        return [
            "packages/contracts/jsonschema/governance.schema.json",
            "packages/contracts/jsonschema/vendor-inventory.schema.json",
        ]
    if task_id == "FOUND-002":
        return [
            "packages/contracts/jsonschema/foundation.schema.json",
            "packages/contracts/jsonschema/runtime-entry.schema.json",
            "packages/contracts/openapi/openapi.yaml",
        ]
    if task_id == "FOUND-004B":
        return [
            "packages/contracts/jsonschema/outbox-event.schema.json",
            "packages/contracts/events/event-envelope.schema.json",
        ]
    if task_id == "FOUND-004C":
        return [
            "packages/contracts/jsonschema/task-job.schema.json",
            "packages/contracts/events/event-envelope.schema.json",
        ]
    if task_id == "FOUND-008":
        return [
            "packages/contracts/jsonschema/kill-switch.schema.json",
            "packages/contracts/jsonschema/feature-flag.schema.json",
            "packages/contracts/jsonschema/delivery-mode.schema.json",
            "packages/contracts/events/kill_switch-paused.schema.json",
            "packages/contracts/events/kill_switch-resumed.schema.json",
        ]
    if task_id == "FOUND-009":
        return [
            "packages/contracts/jsonschema/synthetic-fixture.schema.json",
            "packages/contracts/jsonschema/storage-object.schema.json",
            "packages/contracts/jsonschema/foundation.schema.json",
        ]
    if task_id == "FOUND-011":
        return [
            "packages/contracts/jsonschema/foundation.schema.json",
            "packages/contracts/jsonschema/architecture-guard.schema.json",
        ]
    if task_id == "FOUND-012A":
        return [
            "packages/contracts/jsonschema/foundation.schema.json",
        ]
    if task_id == "FOUND-012B":
        return [
            "packages/contracts/jsonschema/foundation.schema.json",
            "packages/contracts/jsonschema/supply-chain.schema.json",
        ]
    if task_id == "FOUND-013":
        return [
            "packages/contracts/jsonschema/foundation.schema.json",
          ]
    if task_id == "FOUND-003C":
        return [
            "packages/contracts/jsonschema/foundation.schema.json",
            "packages/contracts/jsonschema/redis-config.schema.json",
        ]
    names = exact.get(task_id, [module])
    refs = [f"packages/contracts/jsonschema/{name}.schema.json" for name in names]
    if task_id.startswith(("FOUND-007", "WORKFLOW-", "MODEL-", "AGENT-", "DIST-", "PLAT-", "OAUTH-")):
        refs.append("packages/contracts/events/event-envelope.schema.json")
    return refs


def migration_refs_for(task_id: str, module: str) -> list[str]:
    """Return a deterministic migration plan path, even before code exists."""
    if task_id == "GOV-001":
        return ["packages/db/migrations/versions/20260915_gov_001_governance_scope.sql"]
    if task_id == "GOV-002":
        return ["packages/db/migrations/versions/20260915_gov_002_release_levels.sql"]
    if task_id == "GOV-003":
        return ["packages/db/migrations/versions/20260915_gov_003_raci_policy.sql"]
    if task_id == "GOV-004":
        return ["packages/db/migrations/versions/20260915_gov_004_risk_policy.sql"]
    if task_id == "GOV-005":
        return ["packages/db/migrations/versions/20260915_gov_005_policy_card.sql"]
    if task_id == "GOV-006":
        return ["packages/db/migrations/versions/20260915_gov_006_tech_stack_baseline.sql"]
    if task_id == "GOV-007":
        return ["packages/db/migrations/versions/20260918_gov_007_data_processing_policy.py"]
    if task_id == "GOV-008":
        return ["packages/db/migrations/versions/20260918_gov_008_operational_targets.py"]
    if task_id == "GOV-009":
        return ["packages/db/migrations/versions/20260918_gov_009_account_dependency.py"]
    if task_id == "GOV-010":
        return ["packages/db/migrations/versions/20260918_gov_010_vendor_inventory.py"]
    if task_id == "FOUND-000":
        return ["packages/db/migrations/versions/20260916_found_000_repository_inventory.sql"]
    if task_id == "FOUND-001":
        return ["packages/db/migrations/versions/20260916_found_001_repository_baseline.sql"]
    if task_id == "FOUND-002":
        return ["packages/db/migrations/versions/20260916_found_002_runtime_entry_baseline.sql"]
    if task_id == "FOUND-003D":
        return ["packages/db/migrations/versions/20260916_found_003d_task_jobs.sql"]
    if task_id == "FOUND-003A":
        return ["packages/db/migrations/versions/20260916_found_003a_database_baseline.sql"]
    if task_id == "FOUND-003B":
        return ["packages/db/migrations/versions/20260916_found_003b_storage_baseline.sql"]
    if task_id == "FOUND-006A":
        return ["packages/db/migrations/versions/20260916_found_006a_health_metrics.py"]
    if task_id == "FOUND-006B":
        return ["packages/db/migrations/versions/20260916_found_006b_tracing_cost.py"]
    if task_id == "FOUND-007A":
        return ["packages/db/migrations/versions/20260916_found_007a_openapi.py"]
    if task_id == "FOUND-007B":
        return ["packages/db/migrations/versions/20260916_found_007b_events.py"]
    if task_id == "FOUND-007C":
        return ["packages/db/migrations/versions/20260916_found_007c_agent_output.py"]
    if task_id == "FOUND-007D":
        return ["packages/db/migrations/versions/20260916_found_007d_core_contracts.py"]
    if task_id == "FOUND-004A":
        return ["packages/db/migrations/versions/20260916_found_004a_migration_baseline.py"]
    if task_id == "FOUND-004B":
        return ["packages/db/migrations/versions/20260916_found_004b_outbox.py"]
    if task_id == "FOUND-004C":
        return ["packages/db/migrations/versions/20260916_found_004c_task_leases.py"]
    if task_id == "FOUND-004D":
        return ["packages/db/migrations/versions/20260916_found_004d_failure_retry.py"]
    if task_id == "FOUND-004E":
        return ["packages/db/migrations/versions/20260916_found_004e_replay.py"]
    if task_id == "FOUND-005":
        return ["packages/db/migrations/versions/20260916_found_004f_api_observability.py"]
    if task_id == "FOUND-008":
        return ["packages/db/migrations/versions/20260918_found_008_control_plane.py"]
    if task_id == "FOUND-009":
        return ["packages/db/migrations/versions/20260918_found_009_testkit.py"]
    if task_id == "FOUND-010":
        return ["packages/db/migrations/versions/20260918_found_010_platform_contracts.py"]
    if task_id == "FOUND-011":
        return ["packages/db/migrations/versions/20260918_found_011_architecture_guard.py"]
    if task_id == "FOUND-012A":
        return ["packages/db/migrations/versions/20260918_found_012a_ci.py"]
    if task_id == "FOUND-013":
        return ["packages/db/migrations/versions/20260918_found_013_registry.py"]
    if task_id == "FOUND-003C":
        return ["packages/db/migrations/versions/20260918_found_003c_redis.py"]
    if task_id == "FOUND-012B":
        return ["packages/db/migrations/versions/20260918_found_012b_supply_chain.py"]
    if task_id == "IAM-CORE-001":
        return ["packages/db/migrations/versions/20260918_iam_core_001.py"]
    if task_id == "ACCOUNT-CORE-001":
        return ["packages/db/migrations/versions/20260918_account_core_001.py"]
    if task_id == "GEO_REGION-CORE-001":
        return ["packages/db/migrations/versions/20260918_geo_region_core_001.py"]
    if task_id == "MODEL-CORE-001":
        return ["packages/db/migrations/versions/20260918_model_core_001.py"]
    if task_id == "MODEL-CORE-002":
        return ["packages/db/migrations/versions/20260918_model_core_002.py"]
    if task_id == "AGENT-CORE-001":
        return ["packages/db/migrations/versions/20260918_agent_core_001.py"]
    if task_id == "AGENT-CORE-002":
        return ["packages/db/migrations/versions/20260918_agent_core_002.py"]
    if task_id == "AGENT-CORE-003":
        return ["packages/db/migrations/versions/20260918_agent_core_003.py"]
    if task_id == "AGENT-CORE-004":
        return ["packages/db/migrations/versions/20260918_agent_core_004.py"]
    if task_id == "WORKFLOW-CORE-001":
        return ["packages/db/migrations/versions/20260918_workflow_core_001.py"]
    if task_id == "WORKFLOW-CORE-002":
        return ["packages/db/migrations/versions/20260918_workflow_core_002.py"]
    if task_id == "WORKFLOW-CORE-003":
        return ["packages/db/migrations/versions/20260918_workflow_core_003.py"]
    if task_id == "FEEDBACK-CORE-001":
        return ["packages/db/migrations/versions/20260918_feedback_core_001.py"]
    if task_id == "SCHED-001":
        return ["packages/db/migrations/versions/20260918_sched_001.py"]
    if task_id == "OBS-CORE-001":
        return ["packages/db/migrations/versions/20260918_obs_core_001.py"]
    if task_id == "OBS-CORE-002":
        return ["packages/db/migrations/versions/20260918_obs_core_002.py"]
    if task_id == "OBS-CORE-003":
        return ["packages/db/migrations/versions/20260918_obs_core_003.py"]
    if task_id == "TOPIC-001":
        return ["packages/db/migrations/versions/20260918_topic_001.py"]
    if task_id == "TOPIC-002":
        return ["packages/db/migrations/versions/20260918_topic_002.py"]
    if task_id == "TOPIC-003":
        return ["packages/db/migrations/versions/20260918_topic_003.py"]
    if task_id == "TOPIC-004":
        return ["packages/db/migrations/versions/20260918_topic_004.py"]
    if task_id == "TOPIC-005":
        return ["packages/db/migrations/versions/20260918_topic_005.py"]
    if task_id == "TOPIC-006":
        return ["packages/db/migrations/versions/20260918_topic_006.py"]
    if task_id == "TOPIC-007":
        return ["packages/db/migrations/versions/20260918_topic_007.py"]
    if task_id == "TOPIC-008":
        return ["packages/db/migrations/versions/20260918_topic_008.py"]
    if task_id == "PROV-001":
        return ["packages/db/migrations/versions/20260918_prov_001.py"]
    if task_id == "PROV-002":
        return ["packages/db/migrations/versions/20260918_prov_002.py"]
    if task_id == "PROV-003":
        return ["packages/db/migrations/versions/20260918_prov_003.py"]
    if task_id == "KNOW-001":
        return ["packages/db/migrations/versions/20260918_know_001.py"]
    if task_id == "KNOW-002":
        return ["packages/db/migrations/versions/20260918_know_002.py"]
    if task_id == "CANON-001":
        return ["packages/db/migrations/versions/20260918_canon_001.py"]
    if task_id == "CANON-002":
        return ["packages/db/migrations/versions/20260918_canon_002.py"]
    if task_id == "CANON-003":
        return ["packages/db/migrations/versions/20260918_canon_003.py"]
    if task_id == "CANON-004":
        return ["packages/db/migrations/versions/20260918_canon_004.py"]
    if task_id == "CANON-005":
        return ["packages/db/migrations/versions/20260918_canon_005.py"]
    if task_id == "CANON-006":
        return ["packages/db/migrations/versions/20260919_canon_006.py"]
    if task_id == "AGENT-CORE-005A":
        return ["packages/db/migrations/versions/20260919_agent_core_005a.py"]
    if task_id == "PROD-001":
        return ["packages/db/migrations/versions/20260919_prod_001.py"]
    if task_id == "PROD-002":
        return ["packages/db/migrations/versions/20260919_prod_002.py"]
    if task_id == "PROD-003":
        return ["packages/db/migrations/versions/20260919_prod_003.py"]
    if task_id == "PROD-004":
        return ["packages/db/migrations/versions/20260919_prod_004.py"]
    if task_id == "QA-001":
        return ["packages/db/migrations/versions/20260919_qa_001.py"]
    if task_id == "QA-002":
        return ["packages/db/migrations/versions/20260919_qa_002.py"]
    if task_id == "QA-003":
        return ["packages/db/migrations/versions/20260919_qa_003.py"]
    if task_id == "POLICY-001":
        return ["packages/db/migrations/versions/20260919_policy_001.py"]
    if task_id == "POLICY-002":
        return ["packages/db/migrations/versions/20260919_policy_002.py"]
    if task_id == "APPROVAL-001":
        return ["packages/db/migrations/versions/20260919_approval_001.py"]
    if task_id == "APPROVAL-002":
        return ["packages/db/migrations/versions/20260919_approval_002.py"]
    if task_id == "DIST-001":
        return ["packages/db/migrations/versions/20260919_dist_001.py"]
    if task_id == "DIST-002":
        return ["packages/db/migrations/versions/20260919_dist_002.py"]
    if task_id == "DIST-003A":
        return ["packages/db/migrations/versions/20260919_dist_003a.py"]
    if task_id == "DIST-003B":
        return ["packages/db/migrations/versions/20260919_dist_003b.py"]
    if task_id == "DIST-004":
        return ["packages/db/migrations/versions/20260919_dist_004.py"]
    if task_id == "DIST-005A":
        return ["packages/db/migrations/versions/20260919_dist_005a.py"]
    if task_id == "DIST-005B":
        return ["packages/db/migrations/versions/20260919_dist_005b.py"]
    if task_id == "DIST-006A":
        return ["packages/db/migrations/versions/20260919_dist_006a.py"]
    if task_id == "DIST-006B":
        return ["packages/db/migrations/versions/20260919_dist_006b.py"]
    if task_id == "DIST-006C":
        return ["packages/db/migrations/versions/20260919_dist_006c.py"]
    if task_id == "DIST-007":
        return ["packages/db/migrations/versions/20260919_dist_007.py"]
    if task_id == "DIST-008A":
        return ["packages/db/migrations/versions/20260919_dist_008a.py"]
    if task_id == "DIST-008B":
        return ["packages/db/migrations/versions/20260919_dist_008b.py"]
    if task_id == "DIST-009":
        return ["packages/db/migrations/versions/20260919_dist_009.py"]
    if task_id == "DIST-010":
        return ["packages/db/migrations/versions/20260919_dist_010.py"]
    if task_id == "DIST-011":
        return ["packages/db/migrations/versions/20260919_dist_011.py"]
    if task_id == "FEEDBACK-CORE-002":
        return ["packages/db/migrations/versions/20260919_feedback_core_002.py"]
    if task_id == "AGENT-CORE-005B":
        return ["packages/db/migrations/versions/20260919_agent_core_005b.py"]
    if task_id == "AGENT-CORE-005C":
        return ["packages/db/migrations/versions/20260919_agent_core_005c.py"]
    if task_id == "AGENT-CORE-005D":
        return ["packages/db/migrations/versions/20260919_agent_core_005d.py"]
    if task_id == "AGENT-CORE-005E":
        return ["packages/db/migrations/versions/20260919_agent_core_005e.py"]
    if task_id == "MODEL-001":
        return ["packages/db/migrations/versions/20260919_model_001.py"]
    if task_id == "EVAL-001":
        return ["packages/db/migrations/versions/20260919_eval_001.py"]
    if task_id == "MODEL-003":
        return ["packages/db/migrations/versions/20260919_model_003.py"]
    if task_id == "SITE-001":
        return ["packages/db/migrations/versions/20260919_site_001.py"]
    if task_id == "SITE-002":
        return ["packages/db/migrations/versions/20260919_site_002.py"]
    if task_id == "SITE-003":
        return ["packages/db/migrations/versions/20260919_site_003.py"]
    if task_id == "SITE-004":
        return ["packages/db/migrations/versions/20260920_site_004.py"]
    if task_id == "GEO_CONTENT-001":
        return ["packages/db/migrations/versions/20260919_geo_content_001.py"]
    if task_id == "GEO_CONTENT-002":
        return ["packages/db/migrations/versions/20260919_geo_content_002.py"]
    if task_id == "GEO_CONTENT-003":
        return ["packages/db/migrations/versions/20260920_geo_content_003.py"]
    if task_id == "GEO_REGION-001":
        return ["packages/db/migrations/versions/20260920_geo_region_001.py"]
    if task_id == "GEO_REGION-002":
        return ["packages/db/migrations/versions/20260920_geo_region_002.py"]
    if task_id == "MEDIA-001":
        return ["packages/db/migrations/versions/20260920_media_001.py"]
    if task_id == "MEDIA-002":
        return ["packages/db/migrations/versions/20260920_media_002.py"]
    if task_id == "MEDIA-003A":
        return ["packages/db/migrations/versions/20260920_media_003a.py"]
    if task_id == "MEDIA-003B":
        return ["packages/db/migrations/versions/20260920_media_003b.py"]
    if task_id == "MEDIA-003C":
        return ["packages/db/migrations/versions/20260920_media_003c.py"]
    if task_id == "MEDIA-004A":
        return ["packages/db/migrations/versions/20260920_media_004a.py"]
    if task_id == "MEDIA-004B":
        return ["packages/db/migrations/versions/20260920_media_004b.py"]
    if task_id == "MEDIA-005A":
        return ["packages/db/migrations/versions/20260920_media_005a.py"]
    if task_id == "MEDIA-005B":
        return ["packages/db/migrations/versions/20260920_media_005b.py"]
    if task_id == "MEDIA-006":
        return ["packages/db/migrations/versions/20260920_media_006.py"]
    if task_id == "ANALYTICS-001":
        return ["packages/db/migrations/versions/20260920_analytics_001.py"]
    if task_id == "ANALYTICS-002":
        return ["packages/db/migrations/versions/20260920_analytics_002.py"]
    if task_id == "ANALYTICS-003":
        return ["packages/db/migrations/versions/20260920_analytics_003.py"]
    if task_id == "ANALYTICS-004":
        return ["packages/db/migrations/versions/20260921_analytics_004.py"]
    if task_id == "FEEDBACK-CORE-003":
        return ["packages/db/migrations/versions/20260921_feedback_core_003.py"]
    if task_id == "FEEDBACK-CORE-004":
        return ["packages/db/migrations/versions/20260921_feedback_core_004.py"]
    if task_id == "FEEDBACK-CORE-005":
        return ["packages/db/migrations/versions/20260921_feedback_core_005.py"]
    if task_id == "FEEDBACK-EXP-001":
        return ["packages/db/migrations/versions/20260921_feedback_exp_001.py"]
    if task_id == "SUP-001":
        return ["packages/db/migrations/versions/20260921_sup_001.py"]
    if task_id == "SUP-002":
        return ["packages/db/migrations/versions/20260921_sup_002.py"]
    return [f"packages/db/migrations/planned/{task_id.lower().replace('-', '_')}.sql"]


def readiness_for(task_id: str, contract_refs: list[str]) -> str:
    """Compute a conservative planning readiness label from local artifacts.

    ``readiness`` is metadata, not a business status.  A task is only ready for
    implementation when its card contains a concrete implementation section,
    extra acceptance scenarios, and rollback guidance.  Missing or generic cards
    remain visible in the registry but are prevented by the Codex gate.
    """
    card = ROOT / "docs" / "tasks" / f"{task_id}.md"
    if not card.exists():
        return "needs_refinement"
    text = card.read_text(encoding="utf-8")
    if task_id in {"GOV-001", "GOV-002"} and "## 实现规格" in text and "## 补充场景" in text and "## 回滚" in text:
        return "ready_for_implementation"
    contracts_exist = all((ROOT / ref.split("#", 1)[0]).exists() for ref in contract_refs)
    concrete = "## 实现规格" in text and "补充场景" in text and "回滚" in text
    if concrete and contracts_exist:
        return "ready_for_implementation"
    if contracts_exist:
        return "contract_ready"
    return "needs_refinement"


def external_dependencies_for(task_id: str, phase: int) -> list[str]:
    deps: list[str] = []
    if task_id == "MODEL-001":
        deps.append("EXT-MODEL-001")
    # Stage 9 explicitly accepts site, QA, GEO, manual and fake observations.
    # Only the real-account stage, live feedback, and real pilot work are gated
    # by EXT-ACCOUNT-001.  Applying the dependency to every later phase would
    # incorrectly block the account-free analytics/feedback path.
    if phase == 8 or task_id.startswith(("FEEDBACK-LIVE-", "PILOT-")):
        deps.append("EXT-ACCOUNT-001")
    if task_id == "FOUND-003B":
        deps.append("EXT-STORAGE-001")
    return deps


def acceptance_for(task: dict) -> dict:
    tid = task["id"]
    title = task["title"]
    return {
        "given": ["所有前置任务已完成", "TenantContext、trace_id 和 Idempotency-Key 可用"],
        "when": [f"执行 {tid} 的公开用例或内部命令"],
        "then": [title, "输出契约、审计事件和指定测试结果可复现"],
    }


def build_registry(tasks: list[dict], phase_names: dict[int, str]) -> dict:
    ids = {t["id"] for t in tasks}
    position = {t["id"]: i for i, t in enumerate(tasks)}
    deps = {t["id"]: set(CROSS.get(t["id"], [])) for t in tasks}
    for t in tasks:
        deps[t["id"]].update(PHASE_ANCHOR.get(t["phase"], []))
        deps[t["id"]].discard(t["id"])
    previous_group: dict[str, str] = {}
    for t in tasks:
        tid = t["id"]
        group = task_group(tid)
        if tid == "DIST-011":
            deps[tid].add("DIST-010")
        elif group in previous_group:
            deps[tid].add(previous_group[group])
        previous_group[group] = tid
    for tid, values in deps.items():
        missing = sorted(d for d in values if d not in ids)
        future = sorted(d for d in values if d in position and position[d] >= position[tid])
        if missing:
            raise SystemExit(f"{tid} has missing dependency IDs: {missing}")
        if future:
            raise SystemExit(f"{tid} has a future dependency: {future}")

    result_tasks = []
    for t in tasks:
        tid, phase = t["id"], t["phase"]
        module = module_for(tid)
        group = task_group(tid)
        tier = TIER_OVERRIDES.get(tid, PHASE_TIERS.get(phase, "P1"))
        if tid == "MODEL-001":
            tier = "P1"
        if group in {"FEEDBACK-LIVE", "SUP"}:
            tier = "M2"
        primary = MODULE_PATHS[module]
        # Feedback work is intentionally split into independently owned subtrees.
        # This lets CORE, LIVE, and EXP work proceed in the same phase without
        # falsely claiming the whole modules/feedback tree as an exclusive path.
        if module == "feedback":
            primary = {
                "FEEDBACK-CORE": "modules/feedback/core",
                "FEEDBACK-LIVE": "modules/feedback/live",
                "FEEDBACK-EXP": "modules/feedback/exp",
            }.get(group, primary)
        allowed = list(dict.fromkeys([primary, *EXTRA_ALLOWED.get(module, []), *TASK_EXTRA_ALLOWED.get(tid, []), *SHARED_PATHS]))
        forbidden = ["deploy/environments/prod/secrets", "secrets", "**/*.pem", "**/*secret*.json", "**/*token*.json"]
        if phase < 8 and module not in {"platform_adapter", "distribution_oauth"}:
            forbidden = ["adapters/platforms", "deploy/environments/prod", *forbidden]
        test_module = module.replace("-", "_")
        test_command = f"python -m pytest tests/unit/{test_module} tests/integration --maxfail=1"
        if module in {"governance", "foundation", "operations"}:
            test_command = "python -m pytest tests/contract tests/integration --maxfail=1"
        if tid == "FOUND-000":
            test_command = "python scripts/repo_inventory.py --check"
        elif tid == "FOUND-013":
            test_command = "python scripts/check_plan_consistency.py"
        contract_refs = contract_refs_for(tid, module)
        owned_paths = [primary, "packages/testkit"] if tid == "FOUND-009" else [primary]
        outputs = (
            ["deterministic_fake_clock", "synthetic_fixture_kit", "private_storage_fixture", "fixture_audit_snapshot"]
            if tid == "FOUND-009" else [f"{tid}.implementation", f"{tid}.tests", "audit_evidence"]
        )
        acceptance = acceptance_for(t)
        if tid == "FOUND-009":
            acceptance["then"] = [
                "相同 seed、时间和操作生成相同租户上下文、私有对象元数据与审计快照",
                "时钟不等待墙上时间且拒绝回拨；跨租户、冲突写入和敏感内容泄漏均被拒绝",
                "不调用网络、模型或平台适配器",
            ]
        result_tasks.append({
            "id": tid,
            "phase": phase,
            "phase_name": phase_names.get(phase, ""),
            "group": group,
            "module": module,
            "title": t["title"],
            "owner": f"team/{module}",
            "priority": PRIORITY[tier],
            "tier": tier,
            "depends_on": sorted(deps[tid], key=lambda x: position[x]),
            "contract_refs": contract_refs,
            "migration_refs": migration_refs_for(tid, module),
            "task_spec_ref": f"docs/tasks/{tid}.md",
            "inputs": ["predecessor_artifacts", "tenant_context", "idempotency_key"],
            "outputs": outputs,
            "acceptance": acceptance,
            "allowed_paths": allowed,
            "forbidden_paths": list(dict.fromkeys(forbidden)),
            "owned_paths": owned_paths,
            "exclusive_paths": owned_paths,
            "shared_paths": SHARED_PATHS,
            "expected_paths": [primary],
            "test_command": test_command,
            "gate": re.sub(r"[^a-z0-9]+", "_", tid.lower()).strip("_") + "_acceptance",
            "external_dependencies": external_dependencies_for(tid, phase),
            "readiness": readiness_for(tid, contract_refs),
            "status": t["status"],
            "source_line": t["source_line"],
        })
    return {
        "schema_version": 1,
        "source_document": str(DOCUMENT.relative_to(ROOT)).replace("\\", "/"),
        "generated_by": "scripts/generate_task_registry.py",
        "task_count": len(result_tasks),
        "allowed_statuses": ["planned", "in_progress", "blocked", "done"],
        "path_policy": {
            "shared_paths_are_coordinated": True,
            "exclusive_paths_must_be_allowed": True,
            "parallel_conflict_rule": "same-phase exclusive path overlap requires a transitive dependency",
        },
        "phase_names": phase_names,
        "tasks": result_tasks,
    }


def main() -> int:
    tasks, phase_names = parse_tasks()
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    registry = build_registry(tasks, phase_names)
    REGISTRY.write_text(yaml.safe_dump(registry, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"wrote {REGISTRY} ({registry['task_count']} tasks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
