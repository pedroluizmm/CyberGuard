-- Additive and repeatable. Supports the dashboard overview, which aggregates on
-- read: count(*) per hour/category/severity over an occurred_at range.
-- INCLUDE makes it a covering index, so PostgreSQL can answer with an
-- index-only range scan instead of reading the heap. This is the appropriate
-- relational index for the query; no existing index is removed or altered.
BEGIN;

CREATE INDEX IF NOT EXISTS events_time_cover_idx ON events (occurred_at) INCLUDE (category, severity);

COMMIT;

-- Refresh planner statistics after adding the index (non-destructive).
ANALYZE events;
