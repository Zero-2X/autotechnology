from uuid import uuid4

import pytest

from modules.topic import TopicError, TopicTaxonomyService


def test_taxonomy_and_idempotent_result_survive_restart(tmp_path) -> None:
    database = tmp_path / "topics.db"
    org_id = uuid4()
    first = TopicTaxonomyService(database)
    created = first.create(org_id=org_id, key="llm.rag", label="RAG", technical_versions=["v1"],
                           audiences=["engineer"], tags=["retrieval"], idempotency_key="create")
    first.close()

    reopened = TopicTaxonomyService(database)
    assert reopened.get(org_id=org_id, taxonomy_id=created.id) == created
    assert reopened.create(org_id=org_id, key="llm.rag", label="RAG", technical_versions=["v1"],
                           audiences=["engineer"], tags=["retrieval"], idempotency_key="create") == created
    updated = reopened.update(org_id=org_id, taxonomy_id=created.id, expected_version=0,
                              idempotency_key="update", label="Retrieval")
    reopened.close()

    third = TopicTaxonomyService(database)
    assert third.get(org_id=org_id, taxonomy_id=created.id) == updated
    assert third.update(org_id=org_id, taxonomy_id=created.id, expected_version=0,
                        idempotency_key="update", label="Retrieval") == updated
    with pytest.raises(TopicError) as error:
        third.update(org_id=org_id, taxonomy_id=created.id, expected_version=0,
                     idempotency_key="other", label="Changed")
    assert error.value.code == "VERSION_CONFLICT"
    third.close()
