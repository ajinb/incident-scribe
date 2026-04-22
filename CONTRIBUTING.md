# Contributing to incident-scribe

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/ajinb/incident-scribe
cd incident-scribe
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest
```

## Linting

```bash
ruff check .
ruff format --check .
```

## Pull Requests

1. Fork the repo and create a feature branch
2. Make your changes with tests
3. Run `ruff check .` and `pytest` before submitting
4. Open a PR with a clear description of the change

## Areas Where Help Is Welcome

- New output exporters (Confluence, Notion, Jira)
- Additional report templates
- Better plain-text parsing heuristics
- Documentation improvements

## Code of Conduct

Be respectful and constructive. We follow the [Contributor Covenant](https://www.contributor-covenant.org/).
