"""CLI entry point for incident-scribe."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .integrations.markdown_writer import render_markdown
from .patterns.compensating import save_draft, save_draft_json
from .scribe import generate_report


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="incident-scribe",
        description="Slack thread → structured incident report, powered by Claude",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--thread", metavar="FILE", help="Path to Slack thread file (JSON or text)")
    group.add_argument("--stdin", action="store_true", help="Read Slack thread from stdin")
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "--save-draft",
        action="store_true",
        help="Also save output to .incident-scribe/drafts/",
    )
    parser.add_argument("--version", action="version", version="incident-scribe 1.0.0")
    args = parser.parse_args()

    # Load input
    if args.stdin:
        thread_data = sys.stdin.read()
    else:
        path = Path(args.thread)
        if not path.exists():
            print(f"Error: file not found: {path}", file=sys.stderr)
            sys.exit(1)
        thread_data = path.read_text()

    if not thread_data.strip():
        print("Error: empty input", file=sys.stderr)
        sys.exit(1)

    # Generate report
    try:
        report = generate_report(thread_data)
    except Exception as e:
        print(f"Error generating report: {e}", file=sys.stderr)
        sys.exit(1)

    # Output
    if args.format == "markdown":
        output = render_markdown(report)
    else:
        output = json.dumps(report.model_dump(), indent=2)

    print(output)

    # Save draft if requested
    if args.save_draft:
        if args.format == "markdown":
            draft_path = save_draft(output)
        else:
            draft_path = save_draft_json(report.model_dump())
        print(f"\nDraft saved to: {draft_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
