"""Render model Markdown with raw HTML and remote image embedding disabled."""
from markdown_it import MarkdownIt


def render_feedback(text):
    """Format stored feedback without executing model HTML or loading external images."""
    renderer = MarkdownIt('commonmark', {'html': False, 'breaks': True})
    renderer.enable(['table', 'strikethrough']).disable('image')
    return renderer.render(text or '')
