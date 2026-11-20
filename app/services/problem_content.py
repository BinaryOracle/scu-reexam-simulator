"""Safe Markdown and structured public samples for imported problem statements."""
import json

from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin


def render_statement(text):
    """Render Markdown with inert raw HTML and escaped math for local KaTeX rendering."""
    renderer = MarkdownIt('commonmark', {'html': False, 'breaks': True})
    renderer.enable(['table', 'strikethrough'])
    renderer.use(dollarmath_plugin, allow_digits=True, allow_space=True)
    return renderer.render(text or '')


def public_problem(row):
    """Expose statement and public examples without leaking hidden judge test cases."""
    result = {key: row[key] for key in ('id', 'title', 'statement', 'sample_input', 'sample_output', 'remote_problem_id')}
    result['samples'] = json.loads(row['samples'])
    if not result['samples'] and (row['sample_input'] or row['sample_output']):
        result['samples'] = [{'input': row['sample_input'], 'output': row['sample_output']}]
    result['statement_html'] = render_statement(row['statement'])
    return result
