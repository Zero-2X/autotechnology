"""Deterministic MEDIA-001 script templates and immutable human edits.

This module deliberately has no model, network, renderer, or platform
dependency. It turns one explicitly selected, approved VariantVersion and
verified Claim snapshots into a bounded 30/60/90 second script. Human edits
append a new version while preserving timing and lineage fields.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from functools import wraps
from threading import RLock
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID, uuid5

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "packages" / "contracts" / "jsonschema"
MEDIA_SCRIPT_VALIDATOR = Draft202012Validator(
    json.loads((CONTRACTS / "media-script.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
MEDIA_SCRIPT_VERSION_VALIDATOR = Draft202012Validator(
    json.loads((CONTRACTS / "media-script-version.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
VARIANT_VERSION_VALIDATOR = Draft202012Validator(
    json.loads((CONTRACTS / "variant-version.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
CLAIM_VALIDATOR = Draft202012Validator(
    json.loads((CONTRACTS / "claim.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)

TEMPLATE_VERSION = "media-script-v1"
SYSTEM_ACTOR = UUID("00000000-0000-4000-8000-000000000001")
SCRIPT_NAMESPACE = UUID("79791ec8-2048-55d9-90e4-9e4102ecebe1")
VERSION_NAMESPACE = UUID("f5f3a458-95b5-53c9-8b21-6bc319365657")
HASH_RE = re.compile(r"^[A-Fa-f0-9]{64}$")
SPACE_RE = re.compile(r"\s+")
SENTENCE_RE = re.compile(r"^.*?(?:[.!?。！？](?=\s|$)|$)", re.DOTALL)
CJK_LOCALES = frozenset({"zh", "ja", "ko"})
DURATION_BUDGETS = {30: 75, 60: 150, 90: 225}
TIMELINES = {
    30: ((0, 4_000), (4_000, 26_000), (26_000, 30_000)),
    60: ((0, 7_000), (7_000, 53_000), (53_000, 60_000)),
    90: ((0, 10_000), (10_000, 80_000), (80_000, 90_000)),
}
CTA = {
    "cjk": "查看完整内容，了解更多细节。",
    "spaced": "Review the full source for details.",
}


class VariantVersionPort(Protocol):
    def get_version(self, *, org_id: str, version_id: str) -> Mapping[str, Any]: ...


class ClaimPort(Protocol):
    def get_claim(self, *, org_id: str, claim_id: str) -> Mapping[str, Any]: ...


class MediaScriptError(ValueError):
    """Stable, non-sensitive failure at the MEDIA-001 application boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class MediaScriptResult(dict[str, Any]):
    """Detached mapping returned by create and edit commands.

    It is a real ``dict`` so API adapters and JSON encoders can serialize it,
    while ``as_contract`` still gives callers an explicit detached copy.
    """

    def __init__(self, value: Mapping[str, Any]) -> None:
        super().__init__(deepcopy(dict(value)))

    def as_contract(self) -> dict[str, Any]:
        return deepcopy(dict(self))


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise MediaScriptError("INVALID_MEDIA_SCRIPT_INPUT", "input must be finite JSON") from exc


def _hash(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _time(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise MediaScriptError("INVALID_MEDIA_SCRIPT_INPUT", f"{field} must be ISO-8601") from exc
    else:
        raise MediaScriptError("INVALID_MEDIA_SCRIPT_INPUT", f"{field} must be ISO-8601")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MediaScriptError("INVALID_MEDIA_SCRIPT_INPUT", f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _uuid(value: Any, field: str, *, code: str = "INVALID_MEDIA_SCRIPT_CONTEXT") -> str:
    try:
        return str(value if isinstance(value, UUID) else UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise MediaScriptError(code, f"{field} must be a UUID") from exc


def _text(value: Any, field: str, maximum: int, *, code: str = "INVALID_MEDIA_SCRIPT_INPUT") -> str:
    if not isinstance(value, str):
        raise MediaScriptError(code, f"{field} must be text")
    result = value.strip()
    if not result or len(result) > maximum:
        raise MediaScriptError(code, f"{field} has an invalid length")
    if any(ord(char) < 0x20 and char not in "\t\n\r" for char in result):
        raise MediaScriptError(code, f"{field} contains a control character")
    return result


def _json_safe(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return _stamp(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise MediaScriptError("INVALID_MEDIA_SCRIPT_INPUT", "input contains a non-JSON value")


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    if hasattr(value, "as_contract"):
        candidate = value.as_contract()
        if isinstance(candidate, Mapping):
            return deepcopy(dict(candidate))
    raise MediaScriptError("INVALID_MEDIA_SCRIPT_INPUT", f"{field} must be an object")


def _schema_error(validator: Draft202012Validator, value: Mapping[str, Any], code: str) -> None:
    errors = sorted(validator.iter_errors(value), key=lambda item: (list(item.absolute_path), item.message))
    if errors:
        path = "/" + "/".join(str(item) for item in errors[0].absolute_path)
        raise MediaScriptError(code, f"contract validation failed at {path}: {errors[0].message}")


def _context(
    *, org_id: UUID | str | None, actor_id: UUID | str | None, tenant_context: Any,
) -> tuple[str, str]:
    context_org = context_actor = None
    if tenant_context is not None:
        if isinstance(tenant_context, Mapping):
            context_org = tenant_context.get("org_id") or tenant_context.get("tenant_id")
            context_actor = tenant_context.get("actor_id") or tenant_context.get("user_id")
        else:
            context_org = getattr(tenant_context, "org_id", None) or getattr(tenant_context, "tenant_id", None)
            context_actor = getattr(tenant_context, "actor_id", None) or getattr(tenant_context, "user_id", None)
    supplied_org = _uuid(org_id, "org_id") if org_id is not None else None
    supplied_actor = _uuid(actor_id, "actor_id") if actor_id is not None else None
    resolved_org = _uuid(context_org, "tenant_context.org_id") if context_org is not None else supplied_org
    resolved_actor = _uuid(context_actor, "tenant_context.actor_id") if context_actor is not None else supplied_actor
    if supplied_org is not None and resolved_org != supplied_org:
        raise MediaScriptError("TENANT_SCOPE_VIOLATION", "tenant context and org_id differ")
    if supplied_actor is not None and context_actor is not None and resolved_actor != supplied_actor:
        raise MediaScriptError("TENANT_SCOPE_VIOLATION", "tenant context and actor_id differ")
    if resolved_org is None:
        raise MediaScriptError("INVALID_MEDIA_SCRIPT_CONTEXT", "org_id is required")
    return resolved_org, resolved_actor or str(SYSTEM_ACTOR)


def _is_cjk(locale: str) -> bool:
    return locale.split("-", 1)[0].lower() in CJK_LOCALES


def _normal_text(value: str) -> str:
    return SPACE_RE.sub(" ", value).strip()


def _units(value: str, cjk: bool) -> int:
    return sum(1 for character in value if not character.isspace()) if cjk else len(value.split())


def _truncate(value: str, limit: int, cjk: bool) -> str:
    value = _normal_text(value)
    if limit <= 0:
        return ""
    if not cjk:
        return " ".join(value.split()[:limit])
    result: list[str] = []
    used = 0
    for character in value:
        if not character.isspace():
            if used >= limit:
                break
            used += 1
        if result or not character.isspace():
            result.append(character)
    return "".join(result).strip()


def _first_sentence(value: str) -> str:
    normalized = _normal_text(value)
    match = SENTENCE_RE.match(normalized)
    return (match.group(0) if match else normalized).strip()


def _claim_ids(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else [value]
    return sorted({_uuid(item, field, code="CLAIM_REFERENCE_INVALID") for item in values})


def _extract_extensions(raw: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], Any, Any, str | None]:
    source_map = raw.pop("source_map", None)
    global_claim_ids = raw.pop("claim_ids", None)
    title = raw.pop("title", None)
    extensions: list[dict[str, Any]] = []
    body = raw.get("body")
    if isinstance(body, Mapping) and isinstance(body.get("blocks"), Sequence):
        body_copy = deepcopy(dict(body))
        cleaned_blocks: list[Any] = []
        for item in body_copy["blocks"]:
            if not isinstance(item, Mapping):
                cleaned_blocks.append(item)
                extensions.append({})
                continue
            block = dict(item)
            extensions.append({
                "claim_id": block.pop("claim_id", None),
                "claim_ids": block.pop("claim_ids", None),
                "claim_refs": block.pop("claim_refs", None),
            })
            cleaned_blocks.append(block)
        body_copy["blocks"] = cleaned_blocks
        raw["body"] = body_copy
    return raw, extensions, source_map, global_claim_ids, title


def _normalise_variant(value: Any) -> tuple[dict[str, Any], list[dict[str, Any]], Any, Any, str | None]:
    raw = _json_safe(_mapping(value, "variant_version"))
    raw, extensions, source_map, global_claim_ids, title = _extract_extensions(raw)
    _schema_error(VARIANT_VERSION_VALIDATOR, raw, "VARIANT_VERSION_INVALID")
    return raw, extensions, source_map, global_claim_ids, title


def _source_bindings(
    *, variant: Mapping[str, Any], block_extensions: Sequence[Mapping[str, Any]],
    source_map: Any, global_claim_ids: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    blocks = variant["body"]["blocks"]
    ordered_ids = [str(block["block_id"]) for block in blocks]
    if len(set(ordered_ids)) != len(ordered_ids):
        raise MediaScriptError("VARIANT_VERSION_INVALID", "Variant block_id values must be unique")
    binding: dict[str, set[str]] = {identity: set() for identity in ordered_ids}
    global_ids: list[str] = []
    if isinstance(global_claim_ids, Mapping):
        for block_id, values in global_claim_ids.items():
            identity = str(block_id)
            if identity not in binding:
                raise MediaScriptError("CLAIM_REFERENCE_INVALID", "claim_ids references an unknown block")
            binding[identity].update(_claim_ids(values, f"claim_ids.{identity}"))
    else:
        global_ids = _claim_ids(global_claim_ids, "claim_ids")
    for index, extension in enumerate(block_extensions):
        for key in ("claim_id", "claim_ids", "claim_refs"):
            binding[ordered_ids[index]].update(_claim_ids(extension.get(key), f"body.blocks[{index}].{key}"))
    if source_map is not None:
        if not isinstance(source_map, Sequence) or isinstance(source_map, (str, bytes, bytearray)):
            raise MediaScriptError("CLAIM_REFERENCE_INVALID", "source_map must be an array")
        for index, item in enumerate(source_map):
            if not isinstance(item, Mapping):
                raise MediaScriptError("CLAIM_REFERENCE_INVALID", f"source_map[{index}] must be an object")
            identity = str(item.get("block_id", "")).strip()
            if identity not in binding:
                raise MediaScriptError("CLAIM_REFERENCE_INVALID", "source_map references an unknown block")
            for key in ("claim_id", "claim_ids", "claim_refs"):
                binding[identity].update(_claim_ids(item.get(key), f"source_map[{index}].{key}"))
    result = []
    all_ids: set[str] = set(global_ids)
    for block in blocks:
        identity = str(block["block_id"])
        refs = sorted(binding[identity] | set(global_ids))
        if refs:
            result.append({"block_id": identity, "text": _normal_text(block["localized_text"]), "claim_refs": refs})
            all_ids.update(refs)
    if not result or not all_ids:
        raise MediaScriptError("CLAIM_REFERENCE_REQUIRED", "at least one Variant block must reference a Claim")
    return result, sorted(all_ids)


def _normalise_claim_collection(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        items = [value] if "id" in value else list(value.values())
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = list(value)
    else:
        raise MediaScriptError("CLAIM_REFERENCE_INVALID", "claims must be an object or array")
    result: dict[str, Any] = {}
    for index, item in enumerate(items):
        candidate = _mapping(item, f"claims[{index}]")
        identity = _uuid(candidate.get("id"), f"claims[{index}].id", code="CLAIM_REFERENCE_INVALID")
        if identity in result:
            raise MediaScriptError("CLAIM_REFERENCE_INVALID", "claims contains a duplicate id")
        result[identity] = candidate
    return result


def _optional_time(value: Any, field: str) -> datetime | None:
    return None if value is None else _time(value, field)


def _audit_failures(method: Any) -> Any:
    """Keep rejection evidence bounded and free of input/provider payloads."""

    @wraps(method)
    def wrapped(self: "MediaScriptService", *args: Any, **kwargs: Any) -> Any:
        try:
            return method(self, *args, **kwargs)
        except MediaScriptError as exc:
            context = kwargs.get("tenant_context")
            raw_org = kwargs.get("org_id")
            raw_actor = kwargs.get("actor_id")
            if context is not None:
                if isinstance(context, Mapping):
                    raw_org = context.get("org_id") or context.get("tenant_id") or raw_org
                    raw_actor = context.get("actor_id") or context.get("user_id") or raw_actor
                else:
                    raw_org = getattr(context, "org_id", None) or getattr(context, "tenant_id", None) or raw_org
                    raw_actor = getattr(context, "actor_id", None) or getattr(context, "user_id", None) or raw_actor
            try:
                safe_org = _uuid(raw_org, "org_id") if raw_org is not None else None
            except MediaScriptError:
                safe_org = None
            try:
                safe_actor = _uuid(raw_actor, "actor_id") if raw_actor is not None else str(SYSTEM_ACTOR)
            except MediaScriptError:
                safe_actor = str(SYSTEM_ACTOR)
            trace = kwargs.get("trace_id")
            safe_trace = trace[:256] if isinstance(trace, str) else "media-script"
            script_id = kwargs.get("media_script_id")
            try:
                safe_script = _uuid(script_id, "media_script_id") if script_id is not None else None
            except MediaScriptError:
                safe_script = None
            try:
                stamp = _stamp(self._now(None, "audit_at"))
            except Exception:
                stamp = _stamp(datetime.now(timezone.utc))
            with self.store._lock:
                self.store.audit.append({
                    "operation": method.__name__, "org_id": safe_org, "media_script_id": safe_script,
                    "version_id": None, "version_no": kwargs.get("expected_version_no"),
                    "policy_snapshot_id": None, "request_hash": None, "snapshot_hash": None,
                    "status": "rejected", "error_code": exc.code, "actor_id": safe_actor,
                    "trace_id": safe_trace, "duration_ms": 0, "cost_units": 0, "created_at": stamp,
                })
            raise

    return wrapped


class InMemoryMediaScriptStore:
    """Tenant-scoped append-only script/version fixture with atomic commands."""

    def __init__(self) -> None:
        self.scripts: dict[str, dict[str, Any]] = {}
        self.versions: dict[str, dict[str, Any]] = {}
        self.versions_by_script: dict[str, list[str]] = {}
        self.roots_by_source: dict[tuple[str, str, int], str] = {}
        self.commands: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self._lock = RLock()

    def replay(self, *, org_id: str, namespace: str, idempotency_key: str, request_hash: str) -> dict[str, Any] | None:
        with self._lock:
            prior = self.commands.get((org_id, namespace, idempotency_key))
            if prior is None:
                return None
            if prior["request_hash"] != request_hash:
                raise MediaScriptError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
            return deepcopy(prior["response"])

    def create(
        self, *, root: Mapping[str, Any], version: Mapping[str, Any], namespace: str,
        idempotency_key: str, request_hash: str, audit: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            command_key = (str(root["org_id"]), namespace, idempotency_key)
            prior = self.commands.get(command_key)
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise MediaScriptError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return deepcopy(prior["response"])
            natural = (str(root["org_id"]), str(root["variant_version_id"]), int(root["duration_seconds"]))
            if natural in self.roots_by_source:
                raise MediaScriptError("SCRIPT_ALREADY_EXISTS", "a script already exists for this VariantVersion and duration")
            root_copy, version_copy = deepcopy(dict(root)), deepcopy(dict(version))
            self.scripts[root_copy["id"]] = root_copy
            self.versions[version_copy["id"]] = version_copy
            self.versions_by_script[root_copy["id"]] = [version_copy["id"]]
            self.roots_by_source[natural] = root_copy["id"]
            response = {"media_script": root_copy, "version": version_copy}
            self.commands[command_key] = {"request_hash": request_hash, "response": deepcopy(response)}
            self.audit.append(deepcopy(dict(audit)))
            return deepcopy(response)

    def append_version(
        self, *, org_id: str, media_script_id: str, expected_version_no: int,
        root: Mapping[str, Any], version: Mapping[str, Any], namespace: str,
        idempotency_key: str, request_hash: str, audit: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            command_key = (org_id, namespace, idempotency_key)
            prior = self.commands.get(command_key)
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise MediaScriptError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return deepcopy(prior["response"])
            current_root = self.scripts.get(media_script_id)
            if current_root is None or current_root["org_id"] != org_id:
                raise MediaScriptError("TENANT_SCOPE_VIOLATION", "media script is outside this organization")
            current = self.versions[current_root["current_version_id"]]
            if int(current["version_no"]) != expected_version_no:
                raise MediaScriptError("VERSION_CONFLICT", "media script current version changed")
            version_copy = deepcopy(dict(version))
            if version_copy["id"] in self.versions:
                raise MediaScriptError("SCRIPT_VERSION_IMMUTABLE", "media script version already exists")
            root_copy = deepcopy(dict(root))
            self.versions[version_copy["id"]] = version_copy
            self.versions_by_script[media_script_id].append(version_copy["id"])
            self.scripts[media_script_id] = root_copy
            response = {"media_script": root_copy, "version": version_copy}
            self.commands[command_key] = {"request_hash": request_hash, "response": deepcopy(response)}
            self.audit.append(deepcopy(dict(audit)))
            return deepcopy(response)

    def get_script(self, *, org_id: str, media_script_id: str) -> dict[str, Any]:
        with self._lock:
            value = self.scripts.get(media_script_id)
            if value is None or value["org_id"] != org_id:
                raise MediaScriptError("TENANT_SCOPE_VIOLATION", "media script is outside this organization")
            return deepcopy(value)

    def get_version(self, *, org_id: str, version_id: str) -> dict[str, Any]:
        with self._lock:
            value = self.versions.get(version_id)
            if value is None or value["org_id"] != org_id:
                raise MediaScriptError("TENANT_SCOPE_VIOLATION", "media script version is outside this organization")
            return deepcopy(value)

    def list_versions(self, *, org_id: str, media_script_id: str) -> list[dict[str, Any]]:
        root = self.get_script(org_id=org_id, media_script_id=media_script_id)
        with self._lock:
            return [deepcopy(self.versions[item]) for item in self.versions_by_script[root["id"]]]

    def list_scripts(self, *, org_id: str) -> list[dict[str, Any]]:
        with self._lock:
            values = [deepcopy(item) for item in self.scripts.values() if item["org_id"] == org_id]
        return sorted(values, key=lambda item: (item["created_at"], item["id"]))


class MediaScriptService:
    """Create deterministic templates and immutable, text-only edit versions."""

    def __init__(
        self, *, variant_port: VariantVersionPort | Any | None = None,
        claim_port: ClaimPort | Any | None = None, store: InMemoryMediaScriptStore | None = None,
        clock: Any | None = None,
    ) -> None:
        self.variant_port = variant_port
        self.claim_port = claim_port
        self.store = store or InMemoryMediaScriptStore()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def audit_log(self) -> tuple[dict[str, Any], ...]:
        with self.store._lock:
            return tuple(deepcopy(self.store.audit))

    @property
    def audit(self) -> tuple[dict[str, Any], ...]:
        return self.audit_log

    def _now(self, value: Any | None, field: str) -> datetime:
        return _time(value if value is not None else self.clock(), field)

    def _variant(
        self, *, tenant: str, value: Any, version_id: Any,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], Any, Any, str | None]:
        expected = _uuid(version_id, "variant_version_id", code="VARIANT_VERSION_NOT_FOUND") if version_id is not None else None
        candidate = value
        wrapper_source = wrapper_claim_ids = wrapper_title = None
        if candidate is None:
            if expected is None or self.variant_port is None:
                raise MediaScriptError("VARIANT_VERSION_NOT_FOUND", "an exact VariantVersion is required")
            try:
                if hasattr(self.variant_port, "get_version"):
                    candidate = self.variant_port.get_version(org_id=tenant, version_id=expected)
                elif callable(self.variant_port):
                    candidate = self.variant_port(org_id=tenant, version_id=expected)
                else:
                    raise TypeError("variant port has no get_version operation")
            except MediaScriptError:
                raise
            except Exception as exc:
                raise MediaScriptError("DEPENDENCY_UNAVAILABLE", "VariantVersion lookup failed") from exc
        if isinstance(candidate, Mapping) and "version" in candidate:
            wrapper = dict(candidate)
            wrapper_source = wrapper.get("source_map")
            wrapper_claim_ids = wrapper.get("claim_ids")
            wrapper_title = wrapper.get("title")
            candidate = wrapper["version"]
        try:
            variant, extensions, inline_source, inline_claim_ids, title = _normalise_variant(candidate)
        except MediaScriptError as exc:
            # The public gate has a stable reason for an approved version
            # whose policy binding was omitted.  The base Variant schema
            # intentionally rejects that conditional field first, so map the
            # contract error to the domain decision code here.
            if isinstance(candidate, Mapping) and candidate.get("status") == "approved" and candidate.get("policy_snapshot_id") is None:
                raise MediaScriptError("VARIANT_NOT_APPROVED", "approved VariantVersion must bind a PolicySnapshot") from exc
            raise
        identity = _uuid(variant.get("id"), "variant_version.id", code="VARIANT_VERSION_NOT_FOUND")
        if expected is not None and identity != expected:
            raise MediaScriptError("VARIANT_VERSION_NOT_FOUND", "VariantVersion port returned a different version")
        if _uuid(variant.get("org_id"), "variant_version.org_id") != tenant:
            raise MediaScriptError("TENANT_SCOPE_VIOLATION", "VariantVersion is outside this organization")
        if variant.get("status") != "approved":
            raise MediaScriptError("VARIANT_NOT_APPROVED", "VariantVersion must be approved")
        if variant.get("policy_snapshot_id") is None:
            raise MediaScriptError("VARIANT_NOT_APPROVED", "approved VariantVersion must bind a PolicySnapshot")
        _uuid(variant["policy_snapshot_id"], "variant_version.policy_snapshot_id", code="VARIANT_NOT_APPROVED")
        if not HASH_RE.fullmatch(str(variant.get("snapshot_hash", ""))):
            raise MediaScriptError("VARIANT_VERSION_INVALID", "VariantVersion snapshot_hash is invalid")
        return (
            variant, extensions,
            inline_source if inline_source is not None else wrapper_source,
            inline_claim_ids if inline_claim_ids is not None else wrapper_claim_ids,
            title if title is not None else wrapper_title,
        )

    def _claims(
        self, *, tenant: str, claim_ids: Sequence[str], provided: Any,
        variant: Mapping[str, Any], at: datetime,
    ) -> dict[str, dict[str, Any]]:
        available = _normalise_claim_collection(provided)
        result: dict[str, dict[str, Any]] = {}
        for identity in sorted(claim_ids):
            candidate = available.get(identity)
            if candidate is None:
                if self.claim_port is None:
                    raise MediaScriptError("CLAIM_REFERENCE_INVALID", "referenced Claim was not supplied")
                try:
                    if hasattr(self.claim_port, "get_claim"):
                        candidate = self.claim_port.get_claim(org_id=tenant, claim_id=identity)
                    elif callable(self.claim_port):
                        candidate = self.claim_port(org_id=tenant, claim_id=identity)
                    else:
                        raise TypeError("claim port has no get_claim operation")
                except MediaScriptError:
                    raise
                except (KeyError, LookupError) as exc:
                    raise MediaScriptError("CLAIM_REFERENCE_INVALID", "referenced Claim does not exist") from exc
                except Exception as exc:
                    raise MediaScriptError("DEPENDENCY_UNAVAILABLE", "Claim lookup failed") from exc
            claim = _json_safe(_mapping(candidate, f"claim[{identity}]"))
            _schema_error(CLAIM_VALIDATOR, claim, "CLAIM_REFERENCE_INVALID")
            if _uuid(claim.get("id"), "claim.id", code="CLAIM_REFERENCE_INVALID") != identity:
                raise MediaScriptError("CLAIM_REFERENCE_INVALID", "Claim port returned a different Claim")
            if _uuid(claim.get("org_id"), "claim.org_id") != tenant:
                raise MediaScriptError("TENANT_SCOPE_VIOLATION", "Claim is outside this organization")
            if claim.get("status") != "verified":
                raise MediaScriptError("CLAIM_NOT_VERIFIED", "Claim must be verified")
            if claim.get("freshness_status") != "fresh":
                raise MediaScriptError("CLAIM_NOT_FRESH", "Claim must be fresh")
            valid_from = _optional_time(claim.get("valid_from"), "claim.valid_from")
            valid_to = _optional_time(claim.get("valid_to"), "claim.valid_to")
            review_due = _optional_time(claim.get("review_due_at"), "claim.review_due_at")
            if (valid_from is not None and at < valid_from) or (valid_to is not None and at >= valid_to):
                raise MediaScriptError("CLAIM_NOT_FRESH", "Claim is outside its validity interval")
            if review_due is not None and at >= review_due:
                raise MediaScriptError("CLAIM_NOT_FRESH", "Claim review is due")
            versions = {str(item) for item in claim.get("applicable_versions", [])}
            allowed_versions = {
                str(variant["id"]), str(variant["content_variant_id"]),
                str(variant["canonical_content_version_id"]), str(variant["version_no"]),
            }
            regions = {str(item) for item in claim.get("applicable_regions", [])}
            locales = {str(item).lower() for item in claim.get("applicable_locales", [])}
            if versions and not variant.get("__skip_applicability__") and versions.isdisjoint(allowed_versions):
                raise MediaScriptError("CLAIM_NOT_APPLICABLE", "Claim does not apply to this VariantVersion")
            if regions and not variant.get("__skip_applicability__") and str(variant["market"]) not in regions and str(variant["region_profile_version_id"]) not in regions:
                raise MediaScriptError("CLAIM_NOT_APPLICABLE", "Claim does not apply to this market")
            if locales and not variant.get("__skip_applicability__") and str(variant["locale"]).lower() not in locales:
                raise MediaScriptError("CLAIM_NOT_APPLICABLE", "Claim does not apply to this locale")
            if not HASH_RE.fullmatch(str(claim.get("content_hash", ""))):
                raise MediaScriptError("CLAIM_REFERENCE_INVALID", "Claim content_hash is invalid")
            result[identity] = claim
        return result

    @staticmethod
    def _segments(
        *, duration: int, locale: str, bound_blocks: Sequence[Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], int, float]:
        cjk = _is_cjk(locale)
        budget = DURATION_BUDGETS[duration]
        cta = CTA["cjk" if cjk else "spaced"]
        cta_units = _units(cta, cjk)
        first = bound_blocks[0]
        hook_limit = max(1, min(budget // 5, budget - cta_units - 1))
        hook = _truncate(_first_sentence(str(first["text"])), hook_limit, cjk)
        if not hook:
            raise MediaScriptError("SCRIPT_TEMPLATE_INVALID", "Claim-backed hook text is empty")
        remaining = budget - _units(hook, cjk) - cta_units
        body_parts: list[str] = []
        body_blocks: list[str] = []
        body_claims: set[str] = set()
        for block in bound_blocks:
            if remaining <= 0:
                break
            part = _truncate(str(block["text"]), remaining, cjk)
            if not part:
                continue
            body_parts.append(part)
            body_blocks.append(str(block["block_id"]))
            body_claims.update(str(item) for item in block["claim_refs"])
            remaining -= _units(part, cjk)
        body = _normal_text(" ".join(body_parts))
        if not body:
            raise MediaScriptError("SCRIPT_TEMPLATE_INVALID", "Claim-backed body text is empty")
        intervals = TIMELINES[duration]
        segments = [
            {
                "sequence": 1, "kind": "hook", "start_ms": intervals[0][0], "end_ms": intervals[0][1],
                "text": hook, "claim_refs": list(first["claim_refs"]),
                "source_block_ids": [str(first["block_id"])], "edit_origin": "template",
            },
            {
                "sequence": 2, "kind": "body", "start_ms": intervals[1][0], "end_ms": intervals[1][1],
                "text": body, "claim_refs": sorted(body_claims),
                "source_block_ids": body_blocks, "edit_origin": "template",
            },
            {
                "sequence": 3, "kind": "cta", "start_ms": intervals[2][0], "end_ms": intervals[2][1],
                "text": cta, "claim_refs": [], "source_block_ids": [], "edit_origin": "template",
            },
        ]
        total = sum(_units(item["text"], cjk) for item in segments)
        rate = 4.0 if cjk else 2.5
        return segments, total, round(min(float(duration), total / rate), 3)

    @_audit_failures
    def create_script(
        self, variant_version: Any | None = None, *, variant_version_id: UUID | str | None = None,
        duration_seconds: int, source_map: Any | None = None, claim_ids: Any | None = None,
        claims: Any | None = None, org_id: UUID | str | None = None,
        tenant_context: Any | None = None, actor_id: UUID | str | None = None,
        trace_id: str = "media-script-create", idempotency_key: str,
        created_at: Any | None = None,
    ) -> MediaScriptResult:
        tenant, actor = _context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
        trace = _text(trace_id, "trace_id", 256)
        key = _text(idempotency_key, "idempotency_key", 200)
        if type(duration_seconds) is not int or duration_seconds not in DURATION_BUDGETS:
            raise MediaScriptError("SCRIPT_DURATION_INVALID", "duration_seconds must be 30, 60, or 90")
        at = self._now(created_at, "created_at")
        variant, extensions, inline_source, inline_claim_ids, inline_title = self._variant(
            tenant=tenant, value=variant_version, version_id=variant_version_id,
        )
        bindings, referenced_ids = _source_bindings(
            variant=variant, block_extensions=extensions,
            source_map=source_map if source_map is not None else inline_source,
            global_claim_ids=claim_ids if claim_ids is not None else inline_claim_ids,
        )
        request_hash = _hash({
            "operation": "create", "variant_version_id": variant["id"],
            "variant_snapshot_hash": str(variant["snapshot_hash"]).lower(),
            "duration_seconds": duration_seconds,
            "bindings": [{"block_id": item["block_id"], "claim_refs": item["claim_refs"]} for item in bindings],
            "template_version": TEMPLATE_VERSION,
        })
        replay = self.store.replay(org_id=tenant, namespace="create", idempotency_key=key, request_hash=request_hash)
        if replay is not None:
            return MediaScriptResult(replay)
        claim_map = self._claims(tenant=tenant, claim_ids=referenced_ids, provided=claims, variant=variant, at=at)
        segments, word_count, estimated = self._segments(
            duration=duration_seconds, locale=variant["locale"], bound_blocks=bindings,
        )
        root_id = str(uuid5(SCRIPT_NAMESPACE, f"{tenant}:{variant['id']}:{duration_seconds}"))
        claim_snapshots = [
            {"claim_id": identity, "content_hash": str(claim_map[identity]["content_hash"]).lower()}
            for identity in referenced_ids
        ]
        title_value = inline_title if isinstance(inline_title, str) and inline_title.strip() else segments[0]["text"]
        title = _normal_text(title_value)[:512].strip()
        material = {
            "org_id": tenant, "media_script_id": root_id, "variant_version_id": variant["id"],
            "version_no": 1, "duration_seconds": duration_seconds, "locale": variant["locale"],
            "market": variant["market"], "region_profile_version_id": variant["region_profile_version_id"],
            "policy_snapshot_id": variant["policy_snapshot_id"], "template_version": TEMPLATE_VERSION,
            "status": "draft", "title": title, "segments": segments, "claim_refs": referenced_ids,
            "claim_snapshot_hashes": claim_snapshots,
            "source_variant_snapshot_hash": str(variant["snapshot_hash"]).lower(),
            "word_count": word_count, "estimated_duration_seconds": estimated,
            "human_edited": False, "edit_reason": None, "supersedes_version_id": None,
        }
        snapshot_hash = _hash(material)
        version_id = str(uuid5(VERSION_NAMESPACE, f"{root_id}:1:{snapshot_hash}"))
        stamp = _stamp(at)
        version = {"id": version_id, **material, "snapshot_hash": snapshot_hash, "created_by": actor, "created_at": stamp}
        root = {
            "id": root_id, "org_id": tenant, "variant_version_id": variant["id"],
            "duration_seconds": duration_seconds, "current_version_id": version_id,
            "status": "draft", "created_by": actor, "created_at": stamp, "updated_at": stamp,
        }
        _schema_error(MEDIA_SCRIPT_VALIDATOR, root, "INVALID_MEDIA_SCRIPT")
        _schema_error(MEDIA_SCRIPT_VERSION_VALIDATOR, version, "INVALID_MEDIA_SCRIPT_VERSION")
        response = self.store.create(
            root=root, version=version, namespace="create", idempotency_key=key, request_hash=request_hash,
            audit={
                "operation": "create", "org_id": tenant, "media_script_id": root_id,
                "version_id": version_id, "version_no": 1, "variant_version_id": variant["id"],
                "policy_snapshot_id": variant["policy_snapshot_id"], "request_hash": request_hash,
                "snapshot_hash": snapshot_hash, "status": "created", "actor_id": actor,
                "trace_id": trace, "created_at": stamp,
            },
        )
        return MediaScriptResult(response)

    @_audit_failures
    def edit_script(
        self, *, media_script_id: UUID | str, expected_version_no: int, segment_edits: Any,
        edit_reason: str, claims: Any | None = None, variant_version: Any | None = None,
        org_id: UUID | str | None = None, tenant_context: Any | None = None,
        actor_id: UUID | str | None = None, trace_id: str = "media-script-edit",
        idempotency_key: str, edited_at: Any | None = None,
    ) -> MediaScriptResult:
        tenant, actor = _context(org_id=org_id, actor_id=actor_id, tenant_context=tenant_context)
        script_id = _uuid(media_script_id, "media_script_id")
        trace = _text(trace_id, "trace_id", 256)
        key = _text(idempotency_key, "idempotency_key", 200)
        reason = _text(edit_reason, "edit_reason", 1000, code="SCRIPT_EDIT_INVALID")
        if type(expected_version_no) is not int or expected_version_no < 1:
            raise MediaScriptError("VERSION_CONFLICT", "expected_version_no must be a positive integer")
        if isinstance(segment_edits, Mapping):
            raw_edits = [{"sequence": sequence, "text": text} for sequence, text in segment_edits.items()]
        elif isinstance(segment_edits, Sequence) and not isinstance(segment_edits, (str, bytes, bytearray)):
            raw_edits = list(segment_edits)
        else:
            raise MediaScriptError("SCRIPT_EDIT_INVALID", "segment_edits must be an object or array")
        if not raw_edits:
            raise MediaScriptError("SCRIPT_EDIT_INVALID", "at least one segment edit is required")
        edits: dict[int, str] = {}
        for index, item in enumerate(raw_edits):
            if not isinstance(item, Mapping) or set(item) != {"sequence", "text"}:
                raise MediaScriptError("SCRIPT_EDIT_INVALID", f"segment_edits[{index}] may contain only sequence and text")
            sequence = item["sequence"]
            if type(sequence) is not int or sequence not in {1, 2, 3} or sequence in edits:
                raise MediaScriptError("SCRIPT_EDIT_INVALID", "segment edit sequences must be unique values 1, 2, or 3")
            edits[sequence] = _text(item["text"], f"segment_edits[{index}].text", 20_000, code="SCRIPT_EDIT_INVALID")
        request_hash = _hash({
            "operation": "edit", "media_script_id": script_id, "expected_version_no": expected_version_no,
            "segment_edits": [{"sequence": sequence, "text": edits[sequence]} for sequence in sorted(edits)],
            "edit_reason": reason,
        })
        replay = self.store.replay(org_id=tenant, namespace="edit", idempotency_key=key, request_hash=request_hash)
        if replay is not None:
            return MediaScriptResult(replay)
        root = self.store.get_script(org_id=tenant, media_script_id=script_id)
        current = self.store.get_version(org_id=tenant, version_id=root["current_version_id"])
        if int(current["version_no"]) != expected_version_no:
            raise MediaScriptError("VERSION_CONFLICT", "media script current version changed")
        at = self._now(edited_at, "edited_at")
        if variant_version is None and self.variant_port is None:
            # ScriptVersion retains every field needed for edit invariants.  A
            # caller that has no Variant port can still re-check Claim state;
            # applicability was already frozen at creation and is represented
            # by the immutable Claim refs/snapshot hashes.
            variant = {
                "id": current["variant_version_id"], "content_variant_id": current["variant_version_id"],
                "canonical_content_version_id": current["variant_version_id"], "version_no": 1,
                "locale": current["locale"], "market": current["market"],
                "region_profile_version_id": current["region_profile_version_id"],
                "__skip_applicability__": True,
            }
        else:
            variant, _, _, _, _ = self._variant(
                tenant=tenant, value=variant_version, version_id=current["variant_version_id"],
            )
            if str(variant["snapshot_hash"]).lower() != str(current["source_variant_snapshot_hash"]).lower():
                raise MediaScriptError("VARIANT_SNAPSHOT_MISMATCH", "VariantVersion snapshot changed for this script")
        current_claims = self._claims(
            tenant=tenant, claim_ids=current["claim_refs"], provided=claims, variant=variant, at=at,
        )
        segments = deepcopy(current["segments"])
        changed = False
        for segment in segments:
            sequence = int(segment["sequence"])
            if sequence in edits and segment["text"] != edits[sequence]:
                changed = True
                segment["text"] = edits[sequence]
                segment["edit_origin"] = "human"
        if not changed:
            raise MediaScriptError("SCRIPT_EDIT_INVALID", "segment edits do not change the current version")
        cjk = _is_cjk(current["locale"])
        word_count = sum(_units(item["text"], cjk) for item in segments)
        if word_count > DURATION_BUDGETS[int(current["duration_seconds"])]:
            raise MediaScriptError("SCRIPT_EDIT_INVALID", "edited script exceeds its spoken-unit budget")
        rate = 4.0 if cjk else 2.5
        estimated = round(min(float(current["duration_seconds"]), word_count / rate), 3)
        claim_snapshots = [
            {"claim_id": identity, "content_hash": str(current_claims[identity]["content_hash"]).lower()}
            for identity in current["claim_refs"]
        ]
        version_no = expected_version_no + 1
        material = {
            "org_id": tenant, "media_script_id": script_id,
            "variant_version_id": current["variant_version_id"], "version_no": version_no,
            "duration_seconds": current["duration_seconds"], "locale": current["locale"],
            "market": current["market"], "region_profile_version_id": current["region_profile_version_id"],
            "policy_snapshot_id": current["policy_snapshot_id"], "template_version": TEMPLATE_VERSION,
            "status": "edited", "title": current["title"], "segments": segments,
            "claim_refs": list(current["claim_refs"]), "claim_snapshot_hashes": claim_snapshots,
            "source_variant_snapshot_hash": current["source_variant_snapshot_hash"],
            "word_count": word_count, "estimated_duration_seconds": estimated,
            "human_edited": True, "edit_reason": reason, "supersedes_version_id": current["id"],
        }
        snapshot_hash = _hash(material)
        version_id = str(uuid5(VERSION_NAMESPACE, f"{script_id}:{version_no}:{snapshot_hash}"))
        stamp = _stamp(at)
        version = {"id": version_id, **material, "snapshot_hash": snapshot_hash, "created_by": actor, "created_at": stamp}
        updated_root = {**root, "current_version_id": version_id, "updated_at": stamp}
        _schema_error(MEDIA_SCRIPT_VALIDATOR, updated_root, "INVALID_MEDIA_SCRIPT")
        _schema_error(MEDIA_SCRIPT_VERSION_VALIDATOR, version, "INVALID_MEDIA_SCRIPT_VERSION")
        response = self.store.append_version(
            org_id=tenant, media_script_id=script_id, expected_version_no=expected_version_no,
            root=updated_root, version=version, namespace="edit", idempotency_key=key,
            request_hash=request_hash,
            audit={
                "operation": "edit", "org_id": tenant, "media_script_id": script_id,
                "version_id": version_id, "version_no": version_no,
                "variant_version_id": current["variant_version_id"],
                "policy_snapshot_id": current["policy_snapshot_id"], "request_hash": request_hash,
                "snapshot_hash": snapshot_hash, "status": "edited", "actor_id": actor,
                "trace_id": trace, "created_at": stamp,
            },
        )
        return MediaScriptResult(response)

    def get_script(
        self, *, media_script_id: UUID | str, org_id: UUID | str | None = None,
        tenant_context: Any | None = None,
    ) -> dict[str, Any]:
        tenant, _ = _context(org_id=org_id, actor_id=None, tenant_context=tenant_context)
        return self.store.get_script(org_id=tenant, media_script_id=_uuid(media_script_id, "media_script_id"))

    def get_version(
        self, *, version_id: UUID | str, org_id: UUID | str | None = None,
        tenant_context: Any | None = None,
    ) -> dict[str, Any]:
        tenant, _ = _context(org_id=org_id, actor_id=None, tenant_context=tenant_context)
        return self.store.get_version(org_id=tenant, version_id=_uuid(version_id, "version_id"))

    def list_versions(
        self, *, media_script_id: UUID | str, org_id: UUID | str | None = None,
        tenant_context: Any | None = None,
    ) -> list[dict[str, Any]]:
        tenant, _ = _context(org_id=org_id, actor_id=None, tenant_context=tenant_context)
        return self.store.list_versions(org_id=tenant, media_script_id=_uuid(media_script_id, "media_script_id"))

    def list_scripts(
        self, *, org_id: UUID | str | None = None, tenant_context: Any | None = None,
    ) -> list[dict[str, Any]]:
        tenant, _ = _context(org_id=org_id, actor_id=None, tenant_context=tenant_context)
        return self.store.list_scripts(org_id=tenant)


ScriptService = MediaScriptService
MediaScriptStore = InMemoryMediaScriptStore


__all__ = [
    "ClaimPort", "DURATION_BUDGETS", "InMemoryMediaScriptStore", "MediaScriptError",
    "MediaScriptResult", "MediaScriptService", "MediaScriptStore", "ScriptService",
    "TEMPLATE_VERSION", "TIMELINES", "VariantVersionPort",
]
