-- Additive. The laboratory datacenter has one replica, not fault tolerance.
CREATE KEYSPACE IF NOT EXISTS cyberguard WITH replication = {'class': 'NetworkTopologyStrategy', 'datacenter1': 1} AND durable_writes = true;

-- Canonical JSON is validated by Rust. Revision/state use conditional writes.
-- A deleted row keeps only its UUID, revision and lifecycle; payload becomes null.
CREATE TABLE IF NOT EXISTS cyberguard.events_by_id (
    event_id uuid PRIMARY KEY,
    payload text,
    revision bigint,
    lifecycle text
);

-- Query projections deliberately contain immutable keys only.
CREATE TABLE IF NOT EXISTS cyberguard.events_by_device_day (
    device_id text,
    event_date date,
    occurred_at timestamp,
    event_id uuid,
    PRIMARY KEY ((device_id, event_date), occurred_at, event_id)
) WITH CLUSTERING ORDER BY (occurred_at DESC, event_id DESC);

CREATE TABLE IF NOT EXISTS cyberguard.events_by_ip_day (
    source_ip inet,
    event_date date,
    occurred_at timestamp,
    event_id uuid,
    PRIMARY KEY ((source_ip, event_date), occurred_at, event_id)
) WITH CLUSTERING ORDER BY (occurred_at DESC, event_id DESC);

CREATE TABLE IF NOT EXISTS cyberguard.alerts_by_severity_day (
    severity smallint,
    event_date date,
    occurred_at timestamp,
    event_id uuid,
    PRIMARY KEY ((severity, event_date), occurred_at, event_id)
) WITH CLUSTERING ORDER BY (occurred_at DESC, event_id DESC);
