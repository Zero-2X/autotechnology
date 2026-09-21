from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.media.local_demo_generator import generate_cover_png, generate_cover_svg, generate_demo_content

root = Path(__file__).resolve().parents[1]
out = root / '.tmp' / 'generated-content'
out.mkdir(parents=True, exist_ok=True)
content = generate_demo_content('小红书账号矩阵的内容质量管理')
(out / 'note.md').write_text('# ' + content.title + '\n\n' + content.body + '\n\n' + ' '.join(content.hashtags) + '\n', encoding='utf-8')
generate_cover_svg(content, out / 'cover.svg')
generate_cover_png(content, out / 'cover.png')
print(out / 'note.md')
print(out / 'cover.svg')
print(out / 'cover.png')
