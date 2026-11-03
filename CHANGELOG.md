# Changelog

## 1.1.0 — 2026-11

### Fixed
- **Crash on every fresh install.** `anthropic` 1.x and later reject `temperature=` on
  `messages.create()` with a `TypeError`, and the unpinned `anthropic>=0.39.0` dependency
  now resolves to 2.x. Sampling parameters are gone; the SDK is pinned to `>=2.4,<3`.
- Response text was read from `content[0]`, which is a thinking block on current models.
- Plain-text parsing used random message IDs and fell back to the wall clock, so the same
  thread produced different IDs and timestamps on every run (#2).
- Events citing message IDs that do not exist in the thread flowed into the report as
  "unknown time" (#1). They now get one corrective retry and are then dropped.

### Added
- Structured outputs on both calls; `--print-schema` and `schema/incident-report.schema.json` (#7).
- Local redaction of secrets (default) and PII (`--redact all`) before any LLM call (#4).
- Per-call input-token budget checked with the free `count_tokens` endpoint; over budget
  fails closed with exit code 3 (#5).
- `--slack-channel/--slack-ts`: pull a thread from the Slack API with a bot token (#6).
- `--tz` and `--date` for plain-text threads; midnight rollover handling.
- Server-side refusal fallback (`fallbacks: "default"`) on models that support it.
- Tests that drive the real Anthropic SDK through a mock transport, so SDK signature
  changes fail CI instead of users.

### Changed
- Default model `claude-sonnet-4-6` → `claude-sonnet-5-5`; effort is configurable
  (`INCIDENT_SCRIBE_EFFORT`, default `medium`); default `max_tokens` 16000.
- Timeline timestamps are resolved from cited message IDs instead of being copied by the model.
- Prompt version 2.0.0.

## 1.0.0

Initial release.
