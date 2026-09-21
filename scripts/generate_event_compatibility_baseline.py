"""Generate the immutable FOUND-007B event compatibility snapshot."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs/contracts/event-registry.yaml"
EVENT_DIR = ROOT / "packages/contracts/events"
OUTPUT = ROOT / "docs/foundation/event-compatibility-baseline-v1.yaml"


def _payload_snapshot(schema: dict[str, Any]) -> dict[str, Any]:
    payload = schema.get("allOf", [{}, {}])[1].get("properties", {}).get("payload", {})
    return {
        "required": list(payload.get("required", [])),
        "constraints": {key: payload.get(key) for key in ("minProperties", "maxProperties", "additionalProperties") if key in payload},
        "properties": {
            name: {key: value[key] for key in ("type", "const", "enum", "format", "minLength", "maxLength", "minimum", "maximum", "pattern") if key in value}
            for name, value in (payload.get("properties") or {}).items()
            if isinstance(value, dict)
        },
    }


def main() -> None:
    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    events = []
    for entry in registry.get("events", []):
        ref = Path(entry["schema_ref"])
        schema = json.loads((ROOT / ref).read_text(encoding="utf-8"))
        events.append({
            "event_type": entry["event_type"],
            "schema_ref": entry["schema_ref"],
            "event_schema_version": schema.get("allOf", [{}, {}])[1].get("properties", {}).get("event_schema_version", {}).get("const"),
            "producer": entry.get("producer"),
            "aggregate_type": entry.get("aggregate_type"),
            "event_kind": entry.get("event_kind"),
            "side_effect_scope": entry.get("side_effect_scope"),
            "replay_policy": entry.get("replay_policy"),
            "payload": _payload_snapshot(schema),
        })
    OUTPUT.write_text(yaml.safe_dump({"baseline_key": "event-compatibility", "baseline_version": 1, "registry": "docs/contracts/event-registry.yaml", "event_count": len(events), "events": events, "compatibility": {"allow_new_events": True, "allow_new_optional_fields": True, "reject_removed_events": True, "reject_version_change": True, "reject_required_field_addition": True, "reject_constraint_narrowing": True}}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(events)} events)")


if __name__ == "__main__":
    main()
