-- E5 control (benchmark only, not part of the application schema).
-- "What if PostgreSQL also pre-aggregated?" A materialized view with the same
-- hourly cells as the Cassandra rollup. Reads become as cheap as reading the
-- rollup, but the view is only as fresh as its last full REFRESH, whose cost is
-- measured by run_benchmarks.py. Additive and repeatable; no data is removed.
CREATE SCHEMA IF NOT EXISTS bench;

CREATE MATERIALIZED VIEW IF NOT EXISTS bench.overview_hourly AS
SELECT date_bin('1 hour', occurred_at, TIMESTAMPTZ '2000-01-01 00:00:00+00') AS hour,
       category, severity, count(*)::bigint AS n
FROM events
GROUP BY 1, 2, 3
WITH DATA;

CREATE INDEX IF NOT EXISTS overview_hourly_hour_idx ON bench.overview_hourly (hour);
