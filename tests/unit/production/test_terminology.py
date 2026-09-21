from __future__ import annotations

import sqlite3
from uuid import uuid4

import pytest

from modules.production import ProductionError, RuleTransformPort, TerminologyService, VariantDraftService


class Versions:
    def __init__(self, source: dict) -> None:
        self.source = source

    def get_version(self, *, org_id, version_id):
        return dict(self.source)


def _service():
    connection = sqlite3.connect(":memory:")
    service = TerminologyService(connection=connection)
    tenant, actor = str(uuid4()), str(uuid4())
    return connection, service, tenant, actor


def test_glossary_is_versioned_idempotent_and_tenant_scoped() -> None:
    connection, service, tenant, actor = _service()
    args = dict(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="glossary",
                locale="fr-FR", entries=[{"source": "database", "target": "base de données"}],
                locked_product_names=["Acme Pro"])
    first = service.create_glossary(**args)
    assert first["version_no"] == 1
    assert service.create_glossary(**args) == first
    second = service.create_glossary(**{**args, "idempotency_key": "glossary-2"})
    assert second["version_no"] == 2
    with pytest.raises(ProductionError) as error:
        service.create_glossary(**{**args, "entries": [{"source": "database", "target": "DB"}]})
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
    with pytest.raises(ProductionError) as error:
        service.get_glossary(org_id=str(uuid4()), version_id=first["id"])
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("DELETE FROM production_terminology_versions")


def test_protection_reports_missing_tokens_product_names_and_terms() -> None:
    connection, service, tenant, actor = _service()
    glossary = service.create_glossary(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="terms", locale="fr-FR",
        entries=[{"source": "database", "target": "base de données"}],
        locked_product_names=["Acme Pro"],
    )
    source = "Acme Pro database takes 20 ms. See https://example.test and `x=1`."
    target = "La base prend 30 ms. Voir https://other.test et `x=2`."
    issues = service.check_translation(org_id=tenant, glossary_version_id=glossary["id"],
                                       source_text=source, target_text=target)
    codes = {issue["code"] for issue in issues}
    assert {"MISSING_NUMBER", "MISSING_URL", "MISSING_CODE", "PRODUCT_NAME_CHANGED",
            "PREFERRED_TERM_MISSING"} <= codes
    assert service.check_translation(
        org_id=tenant, glossary_version_id=glossary["id"], source_text=source,
        target_text="Acme Pro base de données prend 20 ms. Voir https://example.test et `x=1`.",
    ) == []


def test_translation_memory_uses_source_hash_and_never_leaks_tenants() -> None:
    connection, service, tenant, actor = _service()
    args = dict(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="memory",
                locale="fr-FR", source_text="Hello", target_text="Bonjour")
    first = service.add_memory(**args)
    assert first["status"] == "approved"
    assert service.add_memory(**args) == first
    assert service.add_memory(**{**args, "idempotency_key": "memory-2"}) == first
    assert service.suggestions(org_id=tenant, locale="fr-FR", source_text="Hello") == [first]
    assert service.suggestions(org_id=str(uuid4()), locale="fr-FR", source_text="Hello") == []
    assert "Hello" not in str(first)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE production_translation_memory SET target_text = 'changed'")


def test_draft_check_maps_issues_and_memory_to_source_blocks() -> None:
    connection, service, tenant, actor = _service()
    content_id, version_id = str(uuid4()), str(uuid4())
    source = {
        "id": version_id, "org_id": tenant, "canonical_content_id": content_id,
        "status": "draft", "freshness_status": "fresh", "content_hash": "a" * 64,
        "title": "Source", "abstract": "", "sections": [
            {"key": "intro", "position": 1, "content": "Acme Pro has 20 ms latency."},
        ],
    }
    versions = Versions(source)
    draft = VariantDraftService(canonical_versions=versions).generate(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="draft",
        canonical_content_version_id=version_id, locale="en-US", market="US",
        audience="engineers", tone="neutral",
    )
    glossary = service.create_glossary(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="terms", locale="en-US",
        entries=[{"source": "latency", "target": "latency"}], locked_product_names=["Acme Pro"],
    )
    memory = service.add_memory(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="memory",
        locale="en-US", source_text="Acme Pro has 20 ms latency.",
        target_text="Acme Pro has 20 ms latency.",
    )
    result = service.check_draft(org_id=tenant, glossary_version_id=glossary["id"],
                                 draft=draft, canonical_versions=versions)
    assert result["passed"] is True and result["issues"] == []
    assert result["memory_suggestions"]["intro"] == [memory]
    class DropNumber(RuleTransformPort):
        def transform(self, **kwargs):
            candidate = super().transform(**kwargs)
            candidate["blocks"][0]["localized_text"] = "Acme Pro has latency."
            return candidate

    changed = VariantDraftService(canonical_versions=versions, transform_port=DropNumber()).generate(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="draft-changed",
        canonical_content_version_id=version_id, locale="en-US", market="US",
        audience="engineers", tone="neutral",
    )
    checked = service.check_draft(org_id=tenant, glossary_version_id=glossary["id"],
                                  draft=changed, canonical_versions=versions)
    assert checked["passed"] is False
    assert checked["issues"][0]["block_id"] == "intro"
    assert checked["issues"][0]["code"] == "MISSING_NUMBER"
