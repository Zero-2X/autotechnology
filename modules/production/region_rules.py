"""Deterministic GEO_REGION preflight for Variant drafts and versions."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Mapping
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .service import ProductionError, _hash, _text, _uuid


_SCHEMA = json.loads((Path(__file__).resolve().parents[2] /
                      "packages/contracts/jsonschema/region-rule-decision.schema.json").read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_time(value: Any, field: str, *, required: bool = True) -> datetime | None:
    if value is None:
        if required:
            raise ProductionError("REGION_RULE_INPUT_INVALID", f"{field} is required")
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ProductionError("REGION_RULE_INPUT_INVALID", f"{field} must be ISO-8601") from exc
    else:
        raise ProductionError("REGION_RULE_INPUT_INVALID", f"{field} must be ISO-8601")
    if parsed.tzinfo is None:
        raise ProductionError("REGION_RULE_INPUT_INVALID", f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _check(code: str, status: str, field: str, message: str, observed: Any, expected: Any) -> dict[str, Any]:
    return {"code": code, "status": status, "field": field, "message": message,
            "observed": observed, "expected": expected}


def _rule_name(value: Any) -> tuple[str, bool, tuple[str, ...], tuple[str, ...]] | None:
    if isinstance(value, str) and value.strip():
        return value.strip(), True, (), ()
    if not isinstance(value, Mapping):
        return None
    label = value.get("term", value.get("topic", value.get("text", value.get("disclosure", value.get("id", value.get("name"))))))
    if not isinstance(label, str) or not label.strip():
        return None
    required = value.get("required", value.get("mandatory", True)) is not False
    markets = value.get("markets", value.get("market", ()))
    platforms = value.get("platforms", value.get("platform", ()))
    if isinstance(markets, str):
        markets = (markets,)
    if isinstance(platforms, str):
        platforms = (platforms,)
    return label.strip(), required, tuple(str(item) for item in markets or ()), tuple(str(item) for item in platforms or ())


class RegionRuleService:
    """Evaluate a region profile without writing domain facts."""

    def __init__(self) -> None:
        self.audit: list[dict[str, Any]] = []
        self._results: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._lock = RLock()

    def evaluate(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
                 idempotency_key: str, region_profile_version: Mapping[str, Any],
                 variant: Mapping[str, Any], context: Mapping[str, Any] | None = None,
                 evaluated_at: datetime | str | None = None) -> dict[str, Any]:
        tenant = _uuid(org_id, "org_id")
        actor = _uuid(actor_id, "actor_id")
        trace = _text(trace_id, "trace_id", 256)
        key = _text(idempotency_key, "idempotency_key", 200)
        if not isinstance(region_profile_version, Mapping) or not isinstance(variant, Mapping):
            raise ProductionError("REGION_RULE_INPUT_INVALID", "region profile and variant must be objects")
        region = deepcopy(dict(region_profile_version))
        candidate = deepcopy(dict(variant))
        if region.get("org_id") != tenant or candidate.get("org_id") != tenant:
            raise ProductionError("TENANT_SCOPE_VIOLATION", "region or variant is outside this organization")
        region_id = _uuid(region.get("id"), "region_profile_version_id")
        canonical_id = _uuid(candidate.get("canonical_content_version_id"), "canonical_content_version_id")
        variant_id = candidate.get("id")
        if variant_id is not None:
            variant_id = _uuid(variant_id, "variant_id")
        locale = _text(candidate.get("locale"), "locale", 64)
        market = _text(candidate.get("market"), "market", 64)
        ctx = dict(context or {})
        check_time = _parse_time(evaluated_at if evaluated_at is not None else ctx.get("evaluated_at", datetime.now(timezone.utc)), "evaluated_at")
        assert check_time is not None
        request_material = {
            "region": region, "variant": candidate, "context": ctx, "evaluated_at": _stamp(check_time),
        }
        request_hash = _hash(request_material)
        with self._lock:
            previous = self._results.get((tenant, key))
            if previous is not None:
                if previous[0] != request_hash:
                    raise ProductionError("IDEMPOTENCY_KEY_REUSED", "region rule request differs from prior request")
                return deepcopy(previous[1])
            checks: list[dict[str, Any]] = []
            required_disclosures: list[str] = []
            matched_restrictions: list[str] = []

            profile_status = region.get("status")
            checks.append(_check("REGION_ACTIVE", "pass" if profile_status == "active" else "fail", "status",
                                 "Region version is active" if profile_status == "active" else "Region version is not active",
                                 profile_status, "active"))
            try:
                valid_from = _parse_time(region.get("valid_from"), "valid_from")
                valid_to = _parse_time(region.get("valid_to"), "valid_to")
            except ProductionError as exc:
                checks.append(_check("REGION_VALIDITY_INVALID", "fail", "validity", str(exc),
                                     {"valid_from": region.get("valid_from"), "valid_to": region.get("valid_to")},
                                     "timezone-aware interval"))
                valid_from = valid_to = None
            if valid_from is not None and valid_to is not None:
                valid = valid_from <= check_time < valid_to
                checks.append(_check("REGION_IN_VALIDITY", "pass" if valid else "fail", "validity",
                                     "Evaluation time is within the Region version validity" if valid else "Region version is expired or not yet valid",
                                     _stamp(check_time), {"valid_from": _stamp(valid_from), "valid_to": _stamp(valid_to)}))

            locales = region.get("locales")
            locale_ok = isinstance(locales, (list, tuple)) and locale in locales
            checks.append(_check("LOCALE_ALLOWED", "pass" if locale_ok else "fail", "locale",
                                 "Locale is allowed" if locale_ok else "Locale is not allowed by Region version",
                                 locale, locales if isinstance(locales, (list, tuple)) else []))
            region_market = region.get("region_code")
            market_ok = isinstance(region_market, str) and market == region_market
            checks.append(_check("MARKET_ALLOWED", "pass" if market_ok else "fail", "market",
                                 "Market matches Region version" if market_ok else "Market does not match Region version",
                                 market, region_market))

            for field, code in (("units", "UNITS_ALLOWED"), ("currency", "CURRENCY_ALLOWED"), ("timezone", "TIMEZONE_ALLOWED"), ("data_region", "DATA_RESIDENCY_ALLOWED")):
                expected = region.get("data_residency") if field == "data_region" else region.get(field)
                observed = ctx.get(field, candidate.get(field, expected))
                field_ok = observed == expected and isinstance(expected, str) and bool(expected)
                checks.append(_check(code, "pass" if field_ok else "fail", field,
                                     f"{field} matches Region version" if field_ok else f"{field} does not match Region version",
                                     observed, expected))

            platform = ctx.get("platform", candidate.get("platform"))
            eligible_platforms = region.get("platform_eligibility")
            if platform is not None and isinstance(eligible_platforms, (list, tuple)) and eligible_platforms:
                platform_ok = platform in eligible_platforms
                checks.append(_check("PLATFORM_ELIGIBLE", "pass" if platform_ok else "fail", "platform",
                                     "Platform is eligible" if platform_ok else "Platform is not eligible in this Region",
                                     platform, eligible_platforms))
            elif platform is not None:
                checks.append(_check("PLATFORM_ELIGIBLE", "review", "platform",
                                     "Region has no explicit platform eligibility list", platform, eligible_platforms or []))

            text_parts: list[str] = []
            for value in (candidate.get("title"), candidate.get("abstract"), candidate.get("topic"), ctx.get("topic"), ctx.get("content")):
                if isinstance(value, str):
                    text_parts.append(value)
            for block in candidate.get("blocks", candidate.get("body", {}).get("blocks", []) if isinstance(candidate.get("body"), Mapping) else []):
                if isinstance(block, Mapping):
                    for field in ("localized_text", "text", "disclosure"):
                        if isinstance(block.get(field), str):
                            text_parts.append(block[field])
            searchable = "\n".join(text_parts).casefold()
            for raw in region.get("restricted_topics", []) if isinstance(region.get("restricted_topics"), list) else []:
                rule = _rule_name(raw)
                if rule is None:
                    checks.append(_check("REGION_RULE_INVALID", "fail", "restricted_topics",
                                         "Restricted topic rule is malformed", raw, "string or topic object"))
                    continue
                label, _required, markets, platforms = rule
                if markets and market not in markets:
                    continue
                if platforms and platform not in platforms:
                    continue
                if label.casefold() in searchable:
                    matched_restrictions.append(label)
            if matched_restrictions:
                checks.append(_check("RESTRICTED_TOPIC", "fail", "restricted_topics",
                                     "Content matches a restricted topic", sorted(set(matched_restrictions)), []))
            else:
                checks.append(_check("RESTRICTED_TOPIC", "pass", "restricted_topics",
                                     "No restricted topic matched", [], []))

            disclosure_values: list[str] = []
            for value in (candidate.get("disclosure"), ctx.get("disclosure")):
                if isinstance(value, str) and value.strip():
                    disclosure_values.append(value)
            for raw in region.get("disclosure_rules", []) if isinstance(region.get("disclosure_rules"), list) else []:
                rule = _rule_name(raw)
                if rule is None:
                    checks.append(_check("REGION_RULE_INVALID", "fail", "disclosure_rules",
                                         "Disclosure rule is malformed", raw, "string or disclosure object"))
                    continue
                label, required, markets, platforms = rule
                if not required or (markets and market not in markets) or (platforms and platform not in platforms):
                    continue
                required_disclosures.append(label)
                present = any(label.casefold() in value.casefold() for value in disclosure_values)
                checks.append(_check("DISCLOSURE_REQUIRED", "pass" if present else "fail", "disclosure",
                                     "Required disclosure is present" if present else "Required disclosure is missing",
                                     disclosure_values, label))

            failed = [item for item in checks if item["status"] == "fail"]
            reviewed = [item for item in checks if item["status"] == "review"]
            status = "blocked" if failed else "review" if reviewed else "eligible"
            material = {
                "org_id": tenant, "variant_id": variant_id, "canonical_content_version_id": canonical_id,
                "region_profile_version_id": region_id, "locale": locale, "market": market,
                "status": status, "checks": checks, "required_disclosures": sorted(set(required_disclosures)),
                "matched_restrictions": sorted(set(matched_restrictions)), "evaluated_at": _stamp(check_time),
                "policy_snapshot_ref": region.get("policy_snapshot_ref", region.get("policy_snapshot_id")),
            }
            decision = {"id": str(uuid4()), **material, "decision_hash": _hash(material),
                        "actor_id": actor, "trace_id": trace}
            errors = list(_VALIDATOR.iter_errors(decision))
            if errors:
                raise ProductionError("INVALID_REGION_DECISION", errors[0].message)
            self.audit.append({"event_type": "production.region_preflight.evaluated", "org_id": tenant,
                               "actor_id": actor, "trace_id": trace, "idempotency_key": key,
                               "request_hash": request_hash, "decision_hash": decision["decision_hash"],
                               "status": status})
            self._results[(tenant, key)] = (request_hash, deepcopy(decision))
            return deepcopy(decision)


__all__ = ["RegionRuleService"]
