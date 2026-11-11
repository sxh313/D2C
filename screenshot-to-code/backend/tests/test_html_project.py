"""CSP packaging regressions. Live browser evidence is recorded separately."""
import json

import pytest

from design2code.html_project import html_project
from design2code.runs import parse_files


def test_scripts_are_compiled_sources_and_markup_keeps_content() -> None:
    files = html_project('''<!doctype html><main><h1 title="A &amp; B">中文 ${title} `</h1>
<button onclick="count++; this.textContent = count; return false">Count</button></main>
<script>let count=0; document.addEventListener('DOMContentLoaded',()=>{document.querySelector('h1').dataset.ready='yes'});</script>''')
    parsed = {item['path']: item['content'] for item in parse_files(json.dumps({'files': files}))}
    app, runtime = parsed['src/App.tsx'], parsed['src/agent-runtime.js']
    assert 'script.text' not in app and 'document.createElement' not in app
    assert '<script>' not in app and 'onclick=' not in app
    assert '${title}' in app and '&amp;' in app and 'data-d2c-handler' in app
    assert 'let count=0' in runtime and 'this.textContent = count' in runtime
    assert 'new Function' not in runtime and 'eval(' not in runtime
    assert "mountAgentPage" in app and 'initialized.current' in app


def test_non_executable_script_is_preserved() -> None:
    app = html_project('<script type="application/ld+json">{"name":"中文"}</script><p>&#123; &copy;</p>')[0]['content']
    assert 'application/ld+json' in app and '&#123; &copy;' in app


@pytest.mark.parametrize('html', ['<script src="https://example.invalid/x.js"></script>',
                                  '<script type="module">import x from "x"</script>',
                                  '<script>unclosed'])
def test_unsupported_scripts_fail_explicitly(html: str) -> None:
    with pytest.raises(ValueError):
        html_project(html)
