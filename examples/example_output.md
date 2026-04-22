# Incident Report

## Summary
At 14:21 UTC, report-generation job R-8821 triggered a full table scan on the `events` table (200M rows), exhausting the `postgres-primary` connection pool. For 8 minutes, roughly 42% of `/api/v1/reports` requests returned 503.

## Impact
Users affected: ~3,200 (estimated from upstream request volume). Duration: 14:21 — 14:29 UTC (8 minutes). Revenue impact: Not yet quantified.

## Timeline
- **2024-04-18 14:21:00 UTC** — Report job R-8821 starts, triggering full table scan on events table
- **2024-04-18 14:22:00 UTC** — postgres-primary connection pool reaches capacity (200/200)
- **2024-04-18 14:22:00 UTC** — PagerDuty alert fires for high error rate on report-generation-service
- **2024-04-18 14:23:00 UTC** — On-call engineer acknowledges and begins investigation
- **2024-04-18 14:24:00 UTC** — Root cause identified: missing index on events.tenant_id
- **2024-04-18 14:26:00 UTC** — R-8821 manually killed
- **2024-04-18 14:29:00 UTC** — Error rates return to baseline; incident resolved

## Root Cause
Missing index on `events.tenant_id` column. The report query plan fell back to sequential scan after recent data growth pushed the table past the planner's heuristic threshold.

## Remediation
Immediate: Kill job R-8821 (done). Short term: Add composite index on (tenant_id, created_at). Long term: Query review checklist for scheduled jobs; evaluate moving scheduled jobs to a read replica.

## Open Questions
- Why didn't the slow-query alert fire? Threshold review needed.
- Should scheduled jobs run against a read replica by default?
- What is the confirmed revenue impact?

## Lessons Learned
- Large table growth can silently change query plans from index scan to sequential scan
- Connection pool exhaustion by a single job can cascade to unrelated API endpoints
- Scheduled jobs should be isolated from primary database traffic
