"""CLI entry point for incident-scribe."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import anthropic
from pydantic import ValidationError

from . import __version__
from .claude import ClaudeCallError, TokenBudgetExceeded
from .integrations.markdown_writer import render_markdown
from .integrations.slack_api import SlackAPIError, fetch_thread
from .parser import parse_thread
from .patterns.compensating import save_draft, save_draft_json
from .schema import IncidentReport
from .scribe import generate_report_from_stream

# Exit codes: 0 ok · 1 input error · 2 usage (argparse) · 3 budget refused · 4 API/model failure
EXIT_INPUT, EXIT_BUDGET, EXIT_API = 1, 3, 4


def _fail(message: str, code: int) -> None:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(code)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="incident-scribe",
        description="Slack thread → structured incident report, powered by Claude",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--thread", metavar="FILE", help="Path to Slack thread file (JSON or text)")
    group.add_argument("--stdin", action="store_true", help="Read Slack thread from stdin")
    group.add_argument(
        "--slack-channel",
        metavar="CHANNEL_ID",
        help="Pull the thread from Slack (needs SLACK_BOT_TOKEN and --slack-ts)",
    )
    group.add_argument(
        "--print-schema",
        action="store_true",
        help="Print the JSON Schema of the --format json output and exit",
    )
    parser.add_argument("--slack-ts", metavar="TS", help="Parent message ts of the Slack thread")
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "--redact",
        choices=["off", "secrets", "all"],
        default="secrets",
        help="Redact before sending to the model: secrets (default), all (secrets + PII), off",
    )
    parser.add_argument(
        "--tz",
        default="UTC",
        help="IANA timezone for plain-text times without an offset (default: UTC)",
    )
    parser.add_argument(
        "--date",
        dest="reference_date",
        metavar="YYYY-MM-DD",
        help="Date for plain-text times that carry no date (default: first dated line)",
    )
    parser.add_argument(
        "--save-draft", action="store_true", help="Also save output to .incident-scribe/drafts/"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Log redaction and warnings")
    parser.add_argument("--version", action="version", version=f"incident-scribe {__version__}")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s"
    )

    if args.print_schema:
        print(json.dumps(IncidentReport.model_json_schema(), indent=2))
        return

    try:
        if args.slack_channel:
            if not args.slack_ts:
                parser.error("--slack-channel requires --slack-ts")
            stream = fetch_thread(args.slack_channel, args.slack_ts)
        else:
            if args.stdin:
                thread_data = sys.stdin.read()
            else:
                path = Path(args.thread)
                if not path.exists():
                    _fail(f"file not found: {path}", EXIT_INPUT)
                thread_data = path.read_text()
            if not thread_data.strip():
                _fail("empty input", EXIT_INPUT)
            stream = parse_thread(thread_data, tz=args.tz, reference_date=args.reference_date)
    except (SlackAPIError, ValueError, OSError) as e:
        _fail(str(e), EXIT_INPUT)

    try:
        report = generate_report_from_stream(stream, redact=args.redact)
    except TokenBudgetExceeded as e:
        _fail(str(e), EXIT_BUDGET)
    except (ClaudeCallError, ValidationError) as e:
        _fail(f"could not generate a report: {e}", EXIT_API)
    except anthropic.AuthenticationError:
        _fail("Anthropic authentication failed; set ANTHROPIC_API_KEY.", EXIT_API)
    except anthropic.APIError as e:
        _fail(f"Claude API error: {e}", EXIT_API)

    if args.format == "markdown":
        output = render_markdown(report)
    else:
        output = json.dumps(report.model_dump(), indent=2)
    print(output)

    if args.save_draft:
        if args.format == "markdown":
            draft_path = save_draft(output)
        else:
            draft_path = save_draft_json(report.model_dump())
        print(f"\nDraft saved to: {draft_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
