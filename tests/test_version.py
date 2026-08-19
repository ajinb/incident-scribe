"""The reported version must track pyproject.toml, not a copy of it."""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import incident_scribe


def _pyproject_version() -> str:
    text = (pathlib.Path(__file__).parent.parent / "pyproject.toml").read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert match, "no version in pyproject.toml"
    return match.group(1)


def test_package_version_matches_pyproject():
    assert incident_scribe.__version__ == _pyproject_version()


def test_cli_version_flag_matches_pyproject():
    out = subprocess.run(
        [sys.executable, "-m", "incident_scribe.cli", "--version"],
        capture_output=True,
        text=True,
    )
    printed = (out.stdout + out.stderr).strip()
    assert printed == f"incident-scribe {_pyproject_version()}", printed
