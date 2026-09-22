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


def test_xhs_browser_endpoint_launches_requested_local_session(monkeypatch):
    launched = {}

    def fake_launch(account_key, *, target, content=None):
        launched.update(account_key=account_key, target=target, content=content)
        return {'account_key': account_key, 'target': target, 'status': 'browser_starting'}

    monkeypatch.setattr('apps.api.main.launch_operator_session', fake_launch)
    client = TestClient(create_app())
    response = client.post(
        '/internal/xhs/accounts/xhs-9653254890/browser:open',
        json={'target': 'publish', 'content': {'title': '标题', 'body': '正文'}},
    )
    assert response.status_code == 200
    assert response.json()['data']['status'] == 'browser_starting'
    assert launched == {
        'account_key': 'xhs-9653254890',
        'target': 'publish',
        'content': {'title': '标题', 'body': '正文'},
    }


def test_xhs_browser_endpoint_rejects_invalid_target(monkeypatch):
    def fake_launch(account_key, *, target, content=None):
        raise ValueError('target must be home, inbox, or publish')

    monkeypatch.setattr('apps.api.main.launch_operator_session', fake_launch)
    response = TestClient(create_app()).post(
        '/internal/xhs/accounts/xhs-9653254890/browser:open', json={'target': 'unknown'}
    )
    assert response.status_code == 400
    assert response.json()['detail']['code'] == 'XHS_BROWSER_LAUNCH_FAILED'
