from fastapi.testclient import TestClient

from apps.api.main import create_app


def test_local_draft_endpoint_returns_text_tags_and_cover():
    client = TestClient(create_app())
    response = client.post('/internal/content/drafts:generate', json={'topic': 'RAG 评测清单'})
    assert response.status_code == 200
    data = response.json()['data']
    assert data['source'] == 'local-template'
    assert data['model_used'] is False
    assert data['title'].startswith('RAG 评测清单')
    assert data['hashtags'] == ['#AI工程', '#内容运营', '#工作流']
    assert data['cover_svg'].startswith('<svg')


def test_local_draft_endpoint_rejects_empty_topic():
    client = TestClient(create_app())
    response = client.post('/internal/content/drafts:generate', json={'topic': ''})
    assert response.status_code == 400
    assert response.json()['detail']['code'] == 'INVALID_DRAFT_TOPIC'
