-- Additive. Dashboard rollup modelled for the overview query (query-first design):
-- one partition per UTC date, one counter cell per (hour, category, severity).
-- A day partition holds at most 24 x 15 cells, so the overview reads at most
-- 7 small partitions instead of scanning events. Only immutable fields are
-- dimensions (outcome is mutable and therefore excluded).
-- Maintained by the API at the winning LWT transitions (pending->active: +1,
-- deleting->deleted: -1). Counters are not idempotent; drift after partial
-- failures is detected and corrected by scripts/loading/reconcile_rollup.py.
CREATE TABLE IF NOT EXISTS cyberguard.event_counts_by_day (
    event_date date,
    hour tinyint,
    category text,
    severity smallint,
    events counter,
    PRIMARY KEY ((event_date), hour, category, severity)
);
