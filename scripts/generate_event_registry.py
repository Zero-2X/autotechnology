"""Generate the machine event registry from the plan's event and state tables.

The Markdown document remains the human source while planning.  This generator
copies the event names, resolves aggregate types, and attaches the state-table
rows that produce each event.  A consumer can therefore distinguish a state
transition from an append-only fact or a worker-control event without guessing
from the event name.
"""
from __future__ import annotations

from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "AI跨境技术内容自动化工作流开发清单_审计与优化版.md"
OUTPUT = ROOT / "docs/contracts/event-registry.yaml"

AGGREGATES = {
    "topic": "Topic",
    "source": "Source",
    "rights": "RightsRecordVersion",
    "policy": "PolicySnapshot",
    "distribution": "DistributionTarget",
    "region": "RegionProfileVersion",
    "canonical": "CanonicalContentVersion",
    "variant": "VariantVersion",
    "asset": "AssetVersion",
    "publication": "PublicationRecord",
    "export_package": "ExportPackage",
    "delivery": "DeliveryAttempt",
    "metric": "MetricDefinition",
    "observation": "Observation",
    "analytics": "Observation",
    "feedback": "FeedbackItem",
    "refresh": "TopicOpportunity",
    "account": "AccountConnection",
    "approval": "Approval",
    "human_task": "HumanTask",
    "task_job": "TaskJob",
    "outbox": "OutboxEvent",
    "agent_run": "AgentRun",
    "model": "ModelCall",
    "site": "SitePageVersion",
    "geo": "GeoQueryFixture",
    "webhook": "WebhookReceipt",
    "deletion": "DeletionRequest",
    "kill_switch": "KillSwitch",
}

# Prefixes are a useful default, but several event families use a different
# aggregate from their namespace (for example a publication intent event and
# an immutable approval decision). Keep these exceptions explicit so the
# generated registry remains an accurate contract index rather than relying on
# a consumer to infer aggregate identity from a string prefix.
EVENT_AGGREGATES = {
    "source.snapshot.quarantined": "SourceSnapshot",
    "source.snapshot.usable": "SourceSnapshot",
    "source.snapshot.expired": "SourceSnapshot",
    "source.snapshot.revoked": "SourceSnapshot",
    "source.snapshot.blocked": "SourceSnapshot",
    "entity.activated": "Entity",
    "entity.retired": "Entity",
    "entity.created": "Entity",
    "claim.created": "Claim",
    "claim.verified": "Claim",
    "claim.withdrawn": "Claim",
    "claim.freshness.changed": "Claim",
    "evidence.captured": "Evidence",
    "evidence.validated": "Evidence",
    "evidence.invalidated": "Evidence",
    "knowledge.core.activated": "KnowledgeCore",
    "knowledge.core.retired": "KnowledgeCore",
    "knowledge.core_version.verified": "KnowledgeCoreVersion",
    "knowledge.core_version.changed": "KnowledgeCoreVersion",
    "variant.created": "ContentVariant",
    "variant.root_changed": "ContentVariant",
    "asset.created": "Asset",
    "asset.root_changed": "Asset",
    "publication_intent.ready": "PublicationIntent",
    "approval.decision_recorded": "ApprovalDecision",
    "analytics.kpi_snapshot.created": "AnalyticsKpiSnapshot",
}


def event_names() -> list[str]:
    lines = DOCUMENT.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "### 5.2 业务事件")
    fence = next(i for i in range(start, len(lines)) if lines[i].strip() == "```text")
    end = next(i for i in range(fence + 1, len(lines)) if lines[i].strip() == "```")
    names = [line.strip() for line in lines[fence + 1 : end] if re.fullmatch(r"[a-z0-9_.]+", line.strip())]
    if not names:
        raise SystemExit("no event names found")
    if len(names) != len(set(names)):
        raise SystemExit("duplicate event names found")
    return names


def state_transitions() -> dict[str, list[dict[str, str]]]:
    """Read the transition rows in section 4.5 keyed by emitted event."""
    lines = DOCUMENT.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "### 4.5 关键状态转换表")
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("### "))
    result: dict[str, list[dict[str, str]]] = {}
    for line in lines[start:end]:
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        if len(cells) < 6 or cells[0] == "对象":
            continue
        event = cells[5].strip("`")
        if not re.fullmatch(r"[a-z0-9_.]+", event):
            continue
        result.setdefault(event, []).append(
            {"aggregate": cells[0], "from_state": cells[1], "command": cells[2], "to_state": cells[4]}
        )
    return result


CONTROL_PREFIXES = ("task_job.", "outbox.", "human_task.", "webhook.", "deletion.")


def event_kind(name: str, transitions: dict[str, list[dict[str, str]]]) -> str:
    if name.startswith(CONTROL_PREFIXES):
        return "control"
    if name in transitions:
        return "transition"
    return "append_only"


def side_effect_scope(name: str) -> str:
    if name == "delivery.simulated":
        return "fake"
    if name in {
        "publication.dispatched",
        "publication.acknowledged",
        "publication.published",
        "publication.failed",
        "publication.unknown",
        "publication.unknown_resolved",
        "publication.removed",
        "delivery.attempted",
        "delivery.succeeded",
        "delivery.failed",
        "delivery.unknown",
        "delivery.unknown_resolved",
    }:
        return "conditional"
    return "none"


def replay_policy(name: str) -> str:
    if name.endswith("unknown") or name.endswith("unknown_resolved"):
        return "manual_resolution"
    if side_effect_scope(name) == "conditional":
        return "query_before_side_effect_replay"
    if name.startswith(CONTROL_PREFIXES):
        return "idempotent_control_replay"
    return "idempotent_projection_replay"


def main() -> None:
    transitions = state_transitions()
    entries = []
    for name in event_names():
        prefix = name.split(".", 1)[0]
        rows = transitions.get(name, [])
        aggregate = EVENT_AGGREGATES.get(name, AGGREGATES.get(prefix, prefix))
        if rows and name not in EVENT_AGGREGATES:
            aggregate = rows[0]["aggregate"]
        entries.append(
            {
                "event_type": name,
                "producer": prefix,
                "aggregate_type": aggregate,
                "event_kind": event_kind(name, transitions),
                "side_effect_scope": side_effect_scope(name),
                "ordering_key": "aggregate_id",
                "consumer_dedupe_key": "event_id",
                "schema_ref": f"packages/contracts/events/{name.replace('.', '-')}.schema.json",
                "replay_policy": replay_policy(name),
                "state_transitions": [
                    {
                        "from_state": row["from_state"],
                        "command": row["command"],
                        "to_state": row["to_state"],
                    }
                    for row in rows
                ],
            }
        )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        yaml.safe_dump(
            {"schema_version": 1, "source_document": DOCUMENT.name, "events": entries},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT} ({len(entries)} events)")


if __name__ == "__main__":
    main()
