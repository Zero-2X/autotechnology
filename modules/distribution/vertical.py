"""Credential-free Canonical-to-Manual-Export vertical slice for DIST-009."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping
from uuid import UUID

from .service import DistributionError, DistributionService, _hash, _text, _uuid


class VerticalSliceError(DistributionError):
    """Stable errors for the first no-account distribution slice."""


class ManualExportVerticalSliceService:
    """Gate predecessor artifacts before creating one private manual export."""

    rule_version = "dist-009/v1"

    def __init__(self, *, distribution: DistributionService) -> None:
        self.distribution = distribution
        self.audit: list[dict[str, Any]] = []
        self._commands: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}

    def run(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        canonical_version: Mapping[str, Any], variant_version: Mapping[str, Any], qa_report: Mapping[str, Any],
        approval: Mapping[str, Any], target_version_id: UUID | str, policy_decision: Mapping[str, Any],
        payload_snapshot: Mapping[str, Any], region_profile_version_id: UUID | str,
        capability_snapshot_hash: str, intent_key: str, created_at: Any = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        canonical = self._artifact(canonical_version, tenant, "canonical_version")
        variant = self._artifact(variant_version, tenant, "variant_version")
        report = self._artifact(qa_report, tenant, "qa_report")
        approval_value = self._artifact(approval, tenant, "approval")
        if canonical.get("status") not in {"fact_checked", "approved"} or canonical.get("freshness_status") in {"withdrawn", "stale", "expired", "conflict"}:
            raise VerticalSliceError("CANONICAL_NOT_READY", "Canonical version must be fact_checked/approved and fresh")
        if variant.get("status") != "approved":
            raise VerticalSliceError("VARIANT_NOT_APPROVED", "VariantVersion must be approved")
        if variant.get("canonical_content_version_id") != canonical.get("id"):
            raise VerticalSliceError("LINEAGE_MISMATCH", "VariantVersion does not reference the supplied Canonical version")
        if report.get("subject_id") != variant.get("id") or report.get("status") != "passed":
            raise VerticalSliceError("QA_NOT_PASSED", "QA report must pass for the supplied VariantVersion")
        if approval_value.get("status") != "approved":
            raise VerticalSliceError("APPROVAL_NOT_GRANTED", "approved Approval is required for manual export")
        if approval_value.get("approval_type") not in {"distribution", "content"}:
            raise VerticalSliceError("APPROVAL_NOT_FOR_DISTRIBUTION", "Approval type is not valid for distribution")
        if policy_decision.get("org_id") != tenant or policy_decision.get("final_decision") != "allow":
            raise VerticalSliceError("POLICY_BLOCKED", "Policy decision must allow the vertical slice")
        target = self.distribution.view_target_version(org_id=tenant, target_version_id=target_version_id)
        if target.get("account_connection_id") is not None or "manual_export" not in target.get("eligible_delivery_modes", []):
            raise VerticalSliceError("MANUAL_EXPORT_TARGET_REQUIRED", "the first vertical slice requires an account-free manual target")
        if variant.get("org_id") != tenant or canonical.get("org_id") != tenant or report.get("org_id") != tenant:
            raise VerticalSliceError("TENANT_SCOPE_VIOLATION", "predecessor artifact is outside this organization")
        request = {
            "canonical_id": canonical["id"], "canonical_hash": canonical.get("content_hash"),
            "variant_id": variant["id"], "variant_hash": variant.get("snapshot_hash"),
            "qa_id": report["id"], "qa_status": report["status"], "approval_id": approval_value["id"],
            "target_version_id": target["id"], "payload_snapshot": payload_snapshot,
            "policy_decision": policy_decision, "region_profile_version_id": str(region_profile_version_id),
            "capability_snapshot_hash": capability_snapshot_hash, "intent_key": intent_key,
        }
        digest = _hash(request)
        prior = self._commands.get((tenant, key))
        if prior is not None:
            if prior[0] != digest:
                raise VerticalSliceError("IDEMPOTENCY_KEY_REUSED", "vertical slice request differs from prior request")
            return deepcopy(prior[1])
        intent = self.distribution.create_publication_intent(
            org_id=tenant, actor_id=actor, trace_id=trace, idempotency_key=f"{key}:intent",
            variant_version_id=variant["id"], asset_version_ids=[], target_version_id=target["id"],
            delivery_mode="manual_export", region_profile_version_id=region_profile_version_id,
            payload_snapshot=payload_snapshot, capability_snapshot_hash=capability_snapshot_hash,
            intent_key=intent_key, policy_snapshot_id=target.get("policy_snapshot_id"),
            approval_id=approval_value["id"], created_at=created_at,
        )
        execution = self.distribution.execute(
            org_id=tenant, actor_id=actor, trace_id=trace, idempotency_key=f"{key}:execute",
            intent_id=intent["id"], policy_decision=policy_decision, approval=approval_value, executed_at=created_at,
        )
        package = execution.get("export_package")
        if not isinstance(package, Mapping) or not str(package.get("storage_object_ref", "")).startswith("private://"):
            raise VerticalSliceError("PRIVATE_EXPORT_REQUIRED", "vertical slice must produce a private ExportPackage")
        result = {"stages": {
            "canonical": {"id": canonical["id"], "status": canonical["status"]},
            "variant": {"id": variant["id"], "status": variant["status"]},
            "qa": {"id": report["id"], "status": report["status"]},
            "approval": {"id": approval_value["id"], "status": approval_value["status"]},
            "publication_intent": deepcopy(execution["intent"]), "export_package": deepcopy(package),
        }, "side_effect_triggered": False, "trace_id": trace}
        self._commands[(tenant, key)] = (digest, deepcopy(result))
        self.audit.append({"event_type": "distribution.vertical_slice.completed", "org_id": tenant,
                           "actor_id": actor, "trace_id": trace, "idempotency_key": key,
                           "input_hash": digest, "output_hash": _hash(result), "side_effect_triggered": False})
        return deepcopy(result)

    @staticmethod
    def _artifact(value: Mapping[str, Any], tenant: str, name: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise VerticalSliceError("INVALID_VERTICAL_INPUT", f"{name} must be an object")
        item = deepcopy(dict(value))
        if item.get("org_id") != tenant:
            raise VerticalSliceError("TENANT_SCOPE_VIOLATION", f"{name} is outside this organization")
        if not item.get("id"):
            raise VerticalSliceError("INVALID_VERTICAL_INPUT", f"{name}.id is required")
        return item


__all__ = ["ManualExportVerticalSliceService", "VerticalSliceError"]
