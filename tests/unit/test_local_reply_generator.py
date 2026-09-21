from modules.support.local_reply_generator import generate_local_reply


def test_low_risk_question_gets_reviewable_reply():
    result = generate_local_reply('怎么开始？', intent='question', risk='low')
    assert result['requires_human'] is False
    assert '主题' in result['reply']


def test_high_risk_is_escalated_without_reply():
    result = generate_local_reply('这是版权申诉', intent='copyright', risk='high')
    assert result == {'reply': None, 'requires_human': True, 'source': 'local-policy'}
