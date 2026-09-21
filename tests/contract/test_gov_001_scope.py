from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / "docs/governance/vertical-scope.yaml"
SCHEMA = ROOT / "packages/contracts/jsonschema/vertical-scope.schema.json"


def test_gov_001_scope_is_locked_and_account_free() -> None:
    scope = yaml.safe_load(SCOPE.read_text(encoding="utf-8"))
    schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))

    required = set(schema["required"])
    assert required <= set(scope)
    assert scope["status"] == "locked"
    assert scope["scope_version"] == 1
    assert scope["vertical_name"] == "AI 技术与应用工程"
    assert scope["languages"] == ["zh-CN", "en-US"]
    assert scope["content_types"] == ["text"]
    assert scope["knowledge_site"] == "first_party"
    assert scope["distribution_modes"] == ["manual_export", "simulation"]
    assert scope["account_strategy"] == "deferred_to_M2"
    assert len(scope["product_capabilities"]) == 8
    assert "真实平台账号、OAuth、Token 和平台 API 副作用" in scope["initial_out_of_scope"]
    datetime.fromisoformat(scope["locked_at"])


def test_gov_001_scope_has_no_credential_or_placeholder_text() -> None:
    text = SCOPE.read_text(encoding="utf-8")
    assert "[VERTICAL_REQUIRED]" not in text
    for forbidden in ("access_token", "refresh_token", "client_secret", "cookie", "BEGIN PRIVATE KEY"):
        assert forbidden not in text
