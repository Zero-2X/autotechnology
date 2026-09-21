from uuid import uuid4

import pytest

from modules.topic import TopicError, TopicTaxonomyService, validate_topic_taxonomy


def test_taxonomy_contract_contains_versions_audiences_and_tags_are_local_metadata() -> None:
    service = TopicTaxonomyService()
    org_id = uuid4()
    taxonomy = service.create(org_id=org_id, key="llm.agents", label="LLM Agents",
                              technical_versions=["v1", "v2"], audiences=["engineer", "editor"],
                              tags=["llm", "agents"], idempotency_key="topic-1")
    validate_topic_taxonomy(taxonomy.as_contract())
    assert taxonomy.tags == ("llm", "agents")
    assert service.create(org_id=org_id, key="llm.agents", label="LLM Agents",
                          technical_versions=["v1", "v2"], audiences=["engineer", "editor"],
                          tags=["llm", "agents"], idempotency_key="topic-1") == taxonomy


def test_taxonomy_updates_and_status_transitions_use_expected_versions() -> None:
    service = TopicTaxonomyService()
    org_id = uuid4()
    taxonomy = service.create(org_id=org_id, key="rag", label="RAG", technical_versions=["v1"],
                              audiences=["engineer"], idempotency_key="topic-2")
    updated = service.update(org_id=org_id, taxonomy_id=taxonomy.id, expected_version=0,
                             idempotency_key="topic-update", label="Retrieval Augmented Generation")
    assert service.update(org_id=org_id, taxonomy_id=taxonomy.id, expected_version=0,
                          idempotency_key="topic-update", label="Retrieval Augmented Generation") == updated
    active = service.activate(org_id=org_id, taxonomy_id=updated.id, expected_version=updated.version,
                              idempotency_key="topic-activate")
    assert service.activate(org_id=org_id, taxonomy_id=updated.id, expected_version=updated.version,
                            idempotency_key="topic-activate") == active
    retired = service.retire(org_id=org_id, taxonomy_id=active.id, expected_version=active.version,
                             idempotency_key="topic-retire")
    assert retired.status == "retired"
    with pytest.raises(TopicError) as error:
        service.activate(org_id=org_id, taxonomy_id=retired.id, expected_version=retired.version,
                         idempotency_key="topic-invalid")
    assert error.value.code == "INVALID_TOPIC_STATE"


def test_taxonomy_is_tenant_scoped_and_conflicts_are_rejected() -> None:
    service = TopicTaxonomyService()
    org_id = uuid4()
    taxonomy = service.create(org_id=org_id, key="security", label="Security", technical_versions=["v1"],
                              audiences=["all"], idempotency_key="topic-3")
    with pytest.raises(TopicError) as error:
        service.get(org_id=uuid4(), taxonomy_id=taxonomy.id)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(TopicError) as error:
        service.update(org_id=org_id, taxonomy_id=taxonomy.id, expected_version=9,
                       idempotency_key="topic-conflict", label="other")
    assert error.value.code == "VERSION_CONFLICT"


def test_taxonomy_key_is_unique_per_tenant_and_collections_are_not_strings() -> None:
    service = TopicTaxonomyService()
    org_id = uuid4()
    service.create(org_id=org_id, key="rag", label="RAG", technical_versions=["v1"],
                   audiences=["engineer"], idempotency_key="unique-1")
    with pytest.raises(TopicError) as error:
        service.create(org_id=org_id, key="rag", label="Other", technical_versions=["v2"],
                       audiences=["editor"], idempotency_key="unique-2")
    assert error.value.code == "TOPIC_KEY_CONFLICT"
    with pytest.raises(TopicError) as error:
        service.create(org_id=org_id, key="llm", label="LLM", technical_versions="v2",
                       audiences=["engineer"], idempotency_key="invalid")
    assert error.value.code == "INVALID_TOPIC_TAXONOMY"
