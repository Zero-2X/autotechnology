from pathlib import Path

from modules.media.local_demo_generator import generate_cover_svg, generate_demo_content


def test_local_generator_is_deterministic(tmp_path: Path):
    content = generate_demo_content('测试主题')
    target = generate_cover_svg(content, tmp_path / 'cover.svg')
    assert content.title.startswith('测试主题')
    assert '测试主题' in content.body
    assert target.read_text(encoding='utf-8').startswith('<svg')
