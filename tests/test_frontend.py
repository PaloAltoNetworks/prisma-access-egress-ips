"""
Guards for the frontend, which has no build step or JS test runner.
"""

import re
from pathlib import Path

import pytest

WEB = Path(__file__).parent.parent / "web"


@pytest.mark.parametrize("sink", ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"])
def test_no_html_sinks(sink):
    # API data must reach the page through textContent / createElement only.
    for path in WEB.glob("*.js"):
        assert sink not in path.read_text(), f"{path.name} uses {sink}"


def test_page_needs_no_unsafe_inline():
    # The CSP allows only same-origin scripts and styles: no inline handlers or style attributes.
    html = (WEB / "index.html").read_text()
    assert not re.search(r"\son[a-z]+\s*=", html), "inline event handler in index.html"
    assert not re.search(r"\sstyle\s*=", html), "inline style attribute in index.html"
    assert "<script>" not in html and "<style" not in html


def test_every_wired_element_exists():
    # app.js wires handlers by id; a missing id would throw on load and break the whole page.
    ids = set(re.findall(r'\sid="([^"]+)"', (WEB / "index.html").read_text()))
    wired = re.findall(r"\bon\('([^']+)'", (WEB / "app.js").read_text())
    assert wired and set(wired) <= ids
