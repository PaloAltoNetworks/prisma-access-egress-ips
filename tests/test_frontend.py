"""
Guards for the frontend, which has no build step or JS test runner.
"""

from pathlib import Path

WEB = Path(__file__).parent.parent / "web"


def test_no_innerhtml():
    # API data must reach the page through textContent / createElement only.
    for path in WEB.glob("*.js"):
        assert "innerHTML" not in path.read_text(), f"{path.name} uses innerHTML"
