"""
Release helpers for CI. pyproject.toml is the single version source; CHANGELOG.md
must carry a matching "## [x.y.z] - YYYY-MM-DD" section before a version ships.

  release.py version [GIT_REF]   print the project version (at GIT_REF if given)
  release.py notes VERSION       print that version's changelog section; exit 1 if absent
"""

import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def project_version(ref: str | None = None) -> str:
    if ref:
        text = subprocess.run(
            ["git", "show", f"{ref}:pyproject.toml"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        ).stdout
    else:
        text = (ROOT / "pyproject.toml").read_text()
    return tomllib.loads(text)["project"]["version"]


def changelog_section(version: str) -> str | None:
    text = (ROOT / "CHANGELOG.md").read_text()
    header = re.compile(rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", re.M)
    match = header.search(text)
    if not match:
        return None
    rest = text[match.end():]
    end = re.search(r"^## \[", rest, re.M)
    return rest[: end.start() if end else len(rest)].strip()


def main(argv: list[str]) -> int:
    match argv:
        case ["version"]:
            print(project_version())
        case ["version", ref]:
            print(project_version(ref))
        case ["notes", version]:
            section = changelog_section(version)
            if section is None:
                print(f"CHANGELOG.md has no '## [{version}] - YYYY-MM-DD' section", file=sys.stderr)
                return 1
            print(section)
        case _:
            print(__doc__, file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
