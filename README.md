# incident-scribe

**Slack thread → incident report, powered by Claude.**

Drop in a messy Slack incident channel thread. Get back a blameless, structured incident report in under 30 seconds — timeline, impact, root cause, remediation, and open questions. Markdown or JSON.

> Built by [Ajin Baby](https://github.com/ajinb) · Part of the [cloudandsre.com](https://cloudandsre.com) open-source toolkit for AI-native SRE.

---

## Why

Most incidents are documented twice: once in the Slack thread as it happens, once (badly, days later) in a postmortem doc nobody wants to write. incident-scribe closes that gap.

It's not a replacement for human review. It's a first draft that respects blameless culture and gets 80% of the structure right so the on-call engineer can focus on the 20% that actually requires judgment.

---

## Install

```bash
pip install incident-scribe
```

Or from source:

```bash
git clone https://github.com/ajinb/incident-scribe
cd incident-scribe
pip install -e .
```

---

## Quickstart

```bash
export ANTHROPIC_API_KEY=sk-ant-...

# From a Slack export JSON
incident-scribe --thread examples/sample_thread.json --format markdown

# From plain text (copy-paste from Slack)
incident-scribe --thread examples/sample_thread.txt --format markdown

# Structured JSON for downstream tools
incident-scribe --thread examples/sample_thread.json --format json

# Save a draft locally
incident-scribe --thread examples/sample_thread.json --save-draft
```

---

## Example Output

Input: an 11-message Slack thread spanning 11 minutes.

Output:

```markdown
# Incident Report

## Summary
At 14:21 UTC, report-generation job R-8821 triggered a full table scan on
the events table (200M rows), exhausting the postgres-primary connection pool.
For 8 minutes, roughly 42% of /api/v1/reports requests returned 503.

## Impact
Users affected: ~3,200 (estimated from upstream request volume).
Duration: 14:21 — 14:29 UTC (8 minutes).

## Timeline
- 14:21 — Report job R-8821 starts
- 14:22 — postgres-primary connections spike to pool limit (200)
- 14:23 — PagerDuty alert fires
- 14:24 — On-call engineer acknowledges
- 14:27 — R-8821 manually killed
- 14:29 — Error rates return to baseline

## Root Cause
Missing index on events.tenant_id column. The report query plan
fell back to sequential scan after recent data growth.

## Remediation
- Immediate: Kill job R-8821 (done)
- Short term: Add composite index on (tenant_id, created_at)
- Long term: Query review checklist for scheduled jobs

## Open Questions
- Why didn't the slow-query alert fire?
- Should scheduled jobs run against a read replica?
```

Full structured output: see [`examples/example_output.md`](examples/example_output.md).

---

## How It Works

```
Slack thread  →  parse  →  extract  →  synthesize  →  validate  →  report
```

1. **Parse** — Slack export JSON or raw text is normalized into a timestamped message stream. Pure Python, no LLM. Timestamps stay exact.
2. **Extract** — Claude identifies discrete events and returns message IDs (not timestamps). The LLM never touches a clock.
3. **Synthesize** — A second Claude call drafts the report. Timestamps are resolved deterministically from message IDs.
4. **Validate** — Output is validated against a pydantic schema. Malformed responses retry with narrowed prompts. Three retries, then fail loudly.

All processing uses the [Anthropic API](https://www.anthropic.com). Thread contents are sent to Anthropic's servers — review their [privacy policy](https://www.anthropic.com/privacy) before using with sensitive production data.

---

## Reliability Patterns

| Pattern | Where | Why |
|---|---|---|
| Event Sourcing | `patterns/event_sourcing.py` | Every API call + input/output hash is logged immutably for audit |
| Compensating Transaction | `patterns/compensating.py` | If downstream posting fails, original draft is preserved locally |
| Retry + Throttling | `scribe.py` | All Claude calls wrapped with exponential backoff + jitter |
| Structured Output | `schema.py` | Every LLM response validated against pydantic schema before use |

See the [blog post](https://cloudandsre.com/blog/building-incident-scribe/) for the design rationale.

---

## Configuration

```bash
# Required
export ANTHROPIC_API_KEY=sk-ant-...

# Optional
export INCIDENT_SCRIBE_MODEL=claude-sonnet-4-6   # default
export INCIDENT_SCRIBE_MAX_TOKENS=4096
```

---

## Roadmap

- [ ] Slack bot mode (listen to `/incident report` slash command)
- [ ] Confluence + Notion exporters
- [ ] PagerDuty and Opsgenie metadata enrichment
- [ ] Multi-language support

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PRs welcome — especially new exporters and template formats.

## License

Apache 2.0 — see [LICENSE](LICENSE).

---

*Part of the [cloudandsre.com](https://cloudandsre.com) open-source toolkit for AI-native SRE.*
