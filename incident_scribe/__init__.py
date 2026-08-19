"""incident-scribe — Slack thread → structured incident report, powered by Claude."""

from importlib.metadata import PackageNotFoundError, version

# Single source of truth is pyproject.toml. Hardcoding the number here and in
# cli.py meant three copies that had to be remembered together on every release.
try:
    __version__ = version("incident-scribe")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0.dev0"
