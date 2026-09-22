from fastapi.testclient import TestClient
from pathlib import Path

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

    def fake_launch(account_key, *, target, content=None, auto_publish=False):
        launched.update(account_key=account_key, target=target, content=content, auto_publish=auto_publish)
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
        'auto_publish': False,
    }


def test_xhs_browser_endpoint_rejects_invalid_target(monkeypatch):
    def fake_launch(account_key, *, target, content=None, auto_publish=False):
        raise ValueError('target must be home, inbox, or publish')

    monkeypatch.setattr('apps.api.main.launch_operator_session', fake_launch)
    response = TestClient(create_app()).post(
        '/internal/xhs/accounts/xhs-9653254890/browser:open', json={'target': 'unknown'}
    )
    assert response.status_code == 400
    assert response.json()['detail']['code'] == 'XHS_BROWSER_LAUNCH_FAILED'


def test_console_state_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr('apps.api.main.CONSOLE_STATE_PATH', Path(tmp_path) / '.local' / 'workflow-state.json')
    client = TestClient(create_app())
    assert client.get('/internal/console/state').json()['data']['state'] is None
    state = {'tasks': [{'id': 'TASK-TEST', 'status': 'todo'}], 'settings': {'runMode': 'browser_preview'}}
    response = client.put('/internal/console/state', json={'state': state})
    assert response.status_code == 200
    assert response.json()['data']['state'] == state
    assert client.get('/internal/console/state').json()['data']['state'] == state
    assert (Path(tmp_path) / '.local' / 'workflow-state.json').exists()


def test_platform_route_prefers_browser_for_xhs_without_api_scope():
    client = TestClient(create_app())
    response = client.get('/internal/platforms/%E5%B0%8F%E7%BA%A2%E4%B9%A6/route?action=publish&browser_session_ready=true')
    assert response.status_code == 200
    assert response.json()['data']['mode'] == 'browser_automation'


def test_platform_route_uses_approved_api_when_explicitly_authorized():
    client = TestClient(create_app())
    response = client.get('/internal/platforms/YouTube/route?action=publish&api_authorized=true&browser_session_ready=true')
    assert response.status_code == 200
    assert response.json()['data']['mode'] == 'authorized_api'
