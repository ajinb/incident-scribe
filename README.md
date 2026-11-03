# incident-scribe

[![CI](https://github.com/ajinb/incident-scribe/actions/workflows/ci.yml/badge.svg)](https://github.com/ajinb/incident-scribe/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)

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
pip install "git+https://github.com/ajinb/incident-scribe@main"
```

(PyPI release pending.) Or from source:

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

# Pull the thread straight from Slack (bot token with channels:history)
export SLACK_BOT_TOKEN=xoxb-...
incident-scribe --slack-channel C0123456789 --slack-ts 1713451260.000100

# Pasted text with local times and no dates
incident-scribe --thread examples/sample_thread.txt --tz America/Denver --date 2026-04-18

# Redact PII as well as secrets before anything leaves the machine
incident-scribe --thread examples/sample_thread.json --redact all

# The JSON Schema that --format json output conforms to
incident-scribe --print-schema
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
Slack thread → parse → redact → extract → validate IDs → synthesize → resolve times → report
```

1. **Parse** — Slack export JSON, the Slack API, or pasted text is normalized into a timestamped message stream. Pure Python, no LLM, and deterministic: message IDs are `msg-<ts>` (Slack) or `msg-0001…` (text), naive times are read in `--tz`, and nothing ever falls back to the wall clock.
2. **Redact** — secrets (cloud keys, tokens, JWTs, private keys, connection-string passwords) are replaced with stable placeholders such as `[AWS_ACCESS_KEY_1]` before any text leaves the machine. `--redact all` adds emails, IPs, phone and card numbers; `--redact off` opts out.
3. **Extract** — Claude identifies discrete events and cites message IDs, never timestamps. Every cited ID is checked against the parsed thread; unknown IDs get one corrective retry, then are dropped.
4. **Synthesize** — a second call drafts the report. Timeline rows cite message IDs too, and the time on each row is looked up from the parsed message. The model cannot invent or mistype a time.
5. **Validate** — both calls use [structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs): the API returns JSON that matches the pydantic schema in `schema.py`. The published contract for `--format json` is [`schema/incident-report.schema.json`](schema/incident-report.schema.json).

Thread contents (after redaction) are sent to Anthropic's servers. Review their [privacy policy](https://www.anthropic.com/privacy) before using with sensitive production data.

---

## Reliability Patterns

| Pattern | Where | Why |
|---|---|---|
| Event Sourcing | `patterns/event_sourcing.py` | Every API call + input/output hash is logged immutably for audit |
| Compensating Transaction | `patterns/compensating.py` | If downstream posting fails, original draft is preserved locally |
| Retry + Throttling | `claude.py` | Rate-limit, 5xx and connection errors retry with exponential backoff + jitter; 4xx fails fast |
| Structured Output | `schema.py` | Responses are schema-constrained by the API, then validated again before use |
| Budget Gate | `claude.py` | Input tokens are counted (free endpoint) before every paid call; an over-budget prompt fails closed (exit 3) |
| Refusal Fallback | `claude.py` | `fallbacks: "default"` re-runs a declined request on Anthropic's recommended model; a refusal that survives is an error, never parsed |
| Data Minimization | `redact.py` | Secrets (and optionally PII) never reach the model or the audit log |

See the [blog post](https://cloudandsre.com/blog/building-incident-scribe/) for the design rationale.

---

## Configuration

```bash
# Required
export ANTHROPIC_API_KEY=sk-ant-...

# Optional
export INCIDENT_SCRIBE_MODEL=claude-sonnet-5-5      # default
export INCIDENT_SCRIBE_EFFORT=medium                # low | medium | high | xhigh | max
export INCIDENT_SCRIBE_MAX_TOKENS=16000             # output cap per call (includes thinking)
export INCIDENT_SCRIBE_MAX_INPUT_TOKENS=100000      # per-call input budget; over it, no call is made
export SLACK_BOT_TOKEN=xoxb-...                     # only for --slack-channel
```

Exit codes: `0` success · `1` input error · `2` usage · `3` refused by the token budget (nothing billed) · `4` Claude API or model failure.

---

## Roadmap

- [x] Pull threads directly from the Slack API (`--slack-channel`)
- [x] Local secret/PII redaction before LLM calls
- [x] Structured outputs + published JSON Schema
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
