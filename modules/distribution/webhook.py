"""Credential-free WebhookPort and fixture ingress for DIST-011."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping, TypedDict
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .service import DistributionError, _EVENT_VALIDATOR, _hash, _stamp, _text, _time, _uuid


_ROOT = Path(__file__).resolve().parents[2]
_RECEIPT_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/jsonschema/webhook-receipt.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)


class WebhookReceipt(TypedDict):
    id: str
    org_id: str
    platform_id: str
    external_event_id: str
    signature_valid: bool
    payload_hash: str
    raw_payload_ref: str
    dedupe_key: str
    status: str
    processing_attempts: int
    last_error: str | None
    replay_count: int
    received_at: str
    processed_at: str | None
    rejected_at: str | None


class WebhookError(DistributionError):
    """Stable deterministic webhook ingress errors."""


def sign_fixture_payload(payload: Mapping[str, Any], secret: str) -> str:
    """Return the fixture HMAC format accepted by ``FakeWebhookPort``."""

    if not isinstance(secret, str) or not secret:
        raise WebhookError("INVALID_WEBHOOK_SECRET", "fixture secret must be nonempty text")
    body = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class FakeWebhookPort:
    """Accept signed fixture events and keep replay/dead-letter state in memory."""

    adapter_ref = "fake:webhook@v1"

    def __init__(self, *, verification_secrets: Mapping[UUID | str, str], max_attempts: int = 2) -> None:
        if type(max_attempts) is not int or max_attempts < 1:
            raise WebhookError("INVALID_WEBHOOK_CONFIG", "max_attempts must be positive")
        self.verification_secrets = {_uuid(platform, "platform_id"): secret for platform, secret in verification_secrets.items()}
        if not self.verification_secrets or any(not isinstance(secret, str) or not secret for secret in self.verification_secrets.values()):
            raise WebhookError("INVALID_WEBHOOK_CONFIG", "verification secrets must be nonempty")
        self.max_attempts = max_attempts
        self.receipts: dict[tuple[str, str], dict[str, Any]] = {}
        self.payloads: dict[tuple[str, str], dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.audit: list[dict[str, Any]] = []
        self._commands: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._lock = RLock()

    def receive(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
        idempotency_key: str, platform_id: UUID | str, external_event_id: str,
        raw_payload: Mapping[str, Any], signature: str,
        received_at: datetime | str | None = None,
        handler: Callable[[Mapping[str, Any]], Mapping[str, Any] | None] | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        platform = _uuid(platform_id, "platform_id")
        trace, key, external_id = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200), _text(external_event_id, "external_event_id", 256)
        if not isinstance(raw_payload, Mapping):
            raise WebhookError("INVALID_WEBHOOK_PAYLOAD", "raw_payload must be an object")
        at = _time(received_at, "received_at") or datetime.now(timezone.utc)
        payload = deepcopy(dict(raw_payload))
        payload_hash = _hash(payload)
        dedupe_key = f"{platform}:{external_id}"
        digest = _hash({"operation": "receive", "platform_id": platform, "external_event_id": external_id,
                        "payload_hash": payload_hash, "signature": signature})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            existing = self.receipts.get((tenant, dedupe_key))
            if existing is not None:
                if existing["payload_hash"] != payload_hash:
                    raise WebhookError("EXTERNAL_EVENT_CONFLICT", "external event id was reused with a different payload")
                result = self._deduplicated(tenant, actor, trace, key, existing, at)
                self._commands[(tenant, key)] = (digest, deepcopy(result))
                return result

            valid_signature = self._signature_valid(platform, payload, signature)
            if not valid_signature:
                receipt = self._new_receipt(tenant, platform, external_id, payload_hash, dedupe_key, at,
                                            signature_valid=False, status="rejected", last_error="INVALID_SIGNATURE")
                result = self._store_rejected(tenant, actor, trace, key, receipt, payload, "INVALID_SIGNATURE", at)
            else:
                errors = sorted(_EVENT_VALIDATOR.iter_errors(payload), key=lambda error: list(error.path))
                if errors:
                    receipt = self._new_receipt(tenant, platform, external_id, payload_hash, dedupe_key, at,
                                                signature_valid=True, status="rejected", last_error="INVALID_EVENT_SCHEMA")
                    result = self._store_rejected(tenant, actor, trace, key, receipt, payload, "INVALID_EVENT_SCHEMA", at)
                elif payload["org_id"] != tenant:
                    receipt = self._new_receipt(tenant, platform, external_id, payload_hash, dedupe_key, at,
                                                signature_valid=True, status="rejected", last_error="TENANT_SCOPE_VIOLATION")
                    result = self._store_rejected(tenant, actor, trace, key, receipt, payload, "TENANT_SCOPE_VIOLATION", at)
                else:
                    receipt = self._new_receipt(tenant, platform, external_id, payload_hash, dedupe_key, at,
                                                signature_valid=True, status="received", last_error=None)
                    result = self._process(tenant, actor, trace, key, receipt, payload, handler, at)
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self._audit("webhook.received", tenant, actor, trace, key, digest, result)
            return deepcopy(result)

    ingest = receive
    fixture_ingress = receive

    def replay(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
        idempotency_key: str, receipt_id: UUID | str, manual_confirmation: bool,
        handler: Callable[[Mapping[str, Any]], Mapping[str, Any] | None] | None = None,
        replayed_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Retry a stored receipt after explicit confirmation; never calls a platform."""

        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key, identity = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200), _uuid(receipt_id, "receipt_id")
        if not manual_confirmation:
            raise WebhookError("MANUAL_CONFIRMATION_REQUIRED", "webhook replay requires explicit confirmation")
        at = _time(replayed_at, "replayed_at") or datetime.now(timezone.utc)
        digest = _hash({"operation": "replay", "receipt_id": identity, "manual_confirmation": True, "replayed_at": _stamp(at)})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            stored_key = next((lookup for lookup, value in self.receipts.items() if lookup[0] == tenant and value["id"] == identity), None)
            if stored_key is None:
                raise WebhookError("WEBHOOK_RECEIPT_NOT_FOUND", "webhook receipt is not available in organization")
            receipt = deepcopy(self.receipts[stored_key])
            if not receipt["signature_valid"] or receipt["status"] not in {"dead_letter", "received"}:
                raise WebhookError("INVALID_REPLAY_STATE", "only verified processing failures or dead-letter receipts can be replayed")
            payload = deepcopy(self.payloads[stored_key])
            receipt["replay_count"] += 1
            result = self._process(tenant, actor, trace, key, receipt, payload, handler, at)
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self._audit("webhook.replayed", tenant, actor, trace, key, digest, result)
            return deepcopy(result)

    def _process(self, tenant: str, actor: str, trace: str, key: str, receipt: dict[str, Any],
                 payload: Mapping[str, Any], handler: Callable[[Mapping[str, Any]], Mapping[str, Any] | None] | None,
                 at: datetime) -> dict[str, Any]:
        receipt["processing_attempts"] += 1
        handler_result: Mapping[str, Any] | None = None
        if handler is not None:
            try:
                handler_result = handler(deepcopy(payload))
            except Exception as exc:  # noqa: BLE001 - fixture failure is part of the contract
                receipt["last_error"] = str(exc)[:512] or "HANDLER_FAILED"
                receipt["status"] = "dead_letter" if receipt["processing_attempts"] >= self.max_attempts else "received"
                if receipt["status"] == "dead_letter":
                    receipt["processed_at"] = None
                    receipt["rejected_at"] = None
                self._save(receipt, payload)
                event_type = "webhook.dead_lettered" if receipt["status"] == "dead_letter" else "webhook.rejected"
                event = self._event(event_type, tenant, actor, trace, key, receipt, receipt["last_error"], at)
                return {"receipt": deepcopy(receipt), "event": event, "handler_result": None,
                        "side_effect_triggered": False}
        receipt["status"] = "processed"
        receipt["last_error"] = None
        receipt["processed_at"] = _stamp(at)
        receipt["rejected_at"] = None
        self._save(receipt, payload)
        event = self._event("webhook.processed", tenant, actor, trace, key, receipt, None, at)
        return {"receipt": deepcopy(receipt), "event": event, "handler_result": deepcopy(dict(handler_result or {})),
                "side_effect_triggered": False}

    def _store_rejected(self, tenant: str, actor: str, trace: str, key: str, receipt: dict[str, Any],
                        payload: Mapping[str, Any], reason: str, at: datetime) -> dict[str, Any]:
        self._save(receipt, payload)
        event = self._event("webhook.rejected", tenant, actor, trace, key, receipt, reason, at)
        return {"receipt": deepcopy(receipt), "event": event, "handler_result": None, "side_effect_triggered": False}

    def _deduplicated(self, tenant: str, actor: str, trace: str, key: str, existing: Mapping[str, Any], at: datetime) -> dict[str, Any]:
        receipt = deepcopy(dict(existing))
        duplicate = deepcopy(receipt)
        duplicate["status"] = "deduplicated"
        self._validate_receipt(duplicate)
        event = self._event("webhook.deduplicated", tenant, actor, trace, key, duplicate, "external event already received", at)
        return {"receipt": duplicate, "event": event, "handler_result": None, "deduplicated": True, "side_effect_triggered": False}

    def _new_receipt(self, tenant: str, platform: str, external_id: str, payload_hash: str, dedupe_key: str,
                     at: datetime, *, signature_valid: bool, status: str, last_error: str | None) -> dict[str, Any]:
        return {"id": str(uuid4()), "org_id": tenant, "platform_id": platform, "external_event_id": external_id,
                "signature_valid": signature_valid, "payload_hash": payload_hash,
                "raw_payload_ref": f"private://webhook/{tenant}/{external_id}", "dedupe_key": dedupe_key,
                "status": status, "processing_attempts": 0, "last_error": last_error,
                "replay_count": 0, "received_at": _stamp(at), "processed_at": None, "rejected_at": _stamp(at) if status == "rejected" else None}

    def _save(self, receipt: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
        self._validate_receipt(receipt)
        identity = (receipt["org_id"], receipt["dedupe_key"])
        self.receipts[identity] = deepcopy(dict(receipt))
        self.payloads[identity] = deepcopy(dict(payload))

    @staticmethod
    def _validate_receipt(receipt: Mapping[str, Any]) -> None:
        errors = sorted(_RECEIPT_VALIDATOR.iter_errors(dict(receipt)), key=lambda error: list(error.path))
        if errors:
            raise WebhookError("INVALID_WEBHOOK_RECEIPT", errors[0].message)

    def _signature_valid(self, platform: str, payload: Mapping[str, Any], signature: str) -> bool:
        secret = self.verification_secrets.get(platform)
        if secret is None or not isinstance(signature, str):
            return False
        expected = sign_fixture_payload(payload, secret)
        return hmac.compare_digest(expected, signature.strip())

    def _prior(self, tenant: str, key: str, digest: str) -> dict[str, Any] | None:
        prior = self._commands.get((tenant, key))
        if prior is None:
            return None
        if prior[0] != digest:
            raise WebhookError("IDEMPOTENCY_KEY_REUSED", "webhook command differs from prior request")
        return deepcopy(prior[1])

    def _event(self, event_type: str, tenant: str, actor: str, trace: str, key: str,
               receipt: Mapping[str, Any], reason: str | None, at: datetime) -> dict[str, Any]:
        version = int(receipt["processing_attempts"]) + int(receipt["replay_count"])
        payload = {"aggregate_id": receipt["id"], "aggregate_version": max(1, version),
                   "from_state": None, "to_state": receipt["status"],
                   "command": event_type, "snapshot_hash": _hash(receipt), "reason": reason}
        event = {"event_id": str(uuid4()), "event_type": event_type, "event_schema_version": 1,
                 "occurred_at": _stamp(at), "org_id": tenant, "trace_id": trace,
                 "aggregate_type": "WebhookReceipt", "aggregate_id": receipt["id"],
                 "aggregate_version": payload["aggregate_version"], "actor_type": "service", "actor_id": actor,
                 "idempotency_key": key, "payload": payload, "payload_hash": _hash(payload)}
        errors = list(_EVENT_VALIDATOR.iter_errors(event))
        if errors:
            raise WebhookError("INVALID_WEBHOOK_EVENT", errors[0].message)
        self.events.append(deepcopy(event))
        return event

    def _audit(self, event_type: str, tenant: str, actor: str, trace: str, key: str,
               digest: str, result: Mapping[str, Any]) -> None:
        self.audit.append({"event_type": event_type, "org_id": tenant, "actor_id": actor,
                           "trace_id": trace, "idempotency_key": key, "input_hash": digest,
                           "output_hash": _hash(result)})


WebhookPort = FakeWebhookPort
WebhookIngressService = FakeWebhookPort


__all__ = ["FakeWebhookPort", "WebhookError", "WebhookIngressService", "WebhookPort", "WebhookReceipt", "sign_fixture_payload"]
