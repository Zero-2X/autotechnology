"""Deterministic local content and cover generator used while model access is absent."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
import re


@dataclass(frozen=True)
class DemoContent:
    title: str
    body: str
    hashtags: tuple[str, ...]


def generate_demo_content(topic: str, *, audience: str = "AI 工程团队") -> DemoContent:
    topic = re.sub(r"\s+", " ", topic.strip())
    if not topic:
        raise ValueError("topic is required")
    title = f"{topic}：一份可执行的实践清单"
    body = (f"给{audience}的一个小结：围绕“{topic}”，先把目标、素材、审核和发布回查拆开。\n\n"
            "建议先做单账号、小批量、人工确认；每次发布都保存内容版本、素材来源和平台回执。\n\n"
            "这样可以先验证内容质量，再逐步增加账号和自动化动作。")
    return DemoContent(title, body, ("#AI工程", "#内容运营", "#工作流"))


def generate_cover_svg(content: DemoContent, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    title = escape(content.title[:26])
    lines = [title[i:i + 13] for i in range(0, len(title), 13)][:3]
    text = "".join(f'<text x="90" y="{280 + i * 92}" fill="#112033" font-size="56" font-weight="700">{escape(line)}</text>' for i, line in enumerate(lines))
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="1200" viewBox="0 0 900 1200">
<rect width="900" height="1200" rx="48" fill="#f7efe3"/><circle cx="760" cy="150" r="130" fill="#f4b183" opacity=".8"/>
<rect x="70" y="72" width="160" height="44" rx="22" fill="#112033"/><text x="96" y="103" fill="white" font-size="22">运营中枢</text>{text}
<text x="90" y="1030" fill="#536171" font-size="26">单账号试点 · 人工审核 · 可回查</text>
</svg>'''
    output.write_text(svg, encoding="utf-8")
    return output


def generate_cover_png(content: DemoContent, output: Path) -> Path:
    """Render the deterministic cover to a normal PNG for platform upload."""
    from PIL import Image, ImageDraw, ImageFont

    output.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (900, 1200), '#f7efe3')
    draw = ImageDraw.Draw(image)
    draw.ellipse((630, 20, 890, 280), fill='#f4b183')
    font_paths = [Path('C:/Windows/Fonts/msyh.ttc'), Path('C:/Windows/Fonts/simhei.ttf')]
    font_path = next((p for p in font_paths if p.exists()), None)
    title_font = ImageFont.truetype(str(font_path), 56) if font_path else ImageFont.load_default()
    small_font = ImageFont.truetype(str(font_path), 26) if font_path else ImageFont.load_default()
    draw.rounded_rectangle((70, 72, 230, 116), radius=22, fill='#112033')
    draw.text((96, 82), '运营中枢', fill='white', font=small_font)
    title = content.title[:26]
    for index in range(0, len(title), 13):
        draw.text((90, 250 + (index // 13) * 92), title[index:index + 13], fill='#112033', font=title_font)
    draw.text((90, 1030), '单账号试点 · 人工审核 · 可回查', fill='#536171', font=small_font)
    image.save(output, format='PNG')
    return output
