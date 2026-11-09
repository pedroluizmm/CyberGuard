-- Additive and repeatable. Never recreate the database or existing volumes.
BEGIN;

CREATE TABLE IF NOT EXISTS devices (
    device_id text PRIMARY KEY CHECK (device_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$')
);

-- UUIDs remain reserved after DELETE; an old request cannot recreate an event.
CREATE TABLE IF NOT EXISTS event_registry (
    event_id uuid PRIMARY KEY,
    deleted boolean NOT NULL DEFAULT false,
    CHECK (substring(event_id::text, 15, 1) = '4'),
    CHECK (substring(event_id::text, 20, 1) IN ('8','9','a','b'))
);

CREATE TABLE IF NOT EXISTS events (
    event_id uuid PRIMARY KEY REFERENCES event_registry(event_id) ON DELETE RESTRICT,
    occurred_at timestamptz NOT NULL,
    event_date date NOT NULL,
    device_id text NOT NULL REFERENCES devices(device_id) ON DELETE RESTRICT,
    source_ip inet NOT NULL,
    category text NOT NULL,
    event_type text NOT NULL,
    severity smallint NOT NULL CHECK (severity BETWEEN 1 AND 5),
    outcome text NOT NULL CHECK (outcome IN ('success','failure','blocked','unknown')),
    message text NOT NULL CHECK (octet_length(message) BETWEEN 1 AND 2048 AND length(btrim(message)) > 0),
    metadata jsonb NOT NULL CHECK (jsonb_typeof(metadata) = 'object'),
    revision bigint NOT NULL CHECK (revision >= 1),
    CHECK (occurred_at >= '2000-01-01T00:00:00Z'::timestamptz AND occurred_at < '2100-01-01T00:00:00Z'::timestamptz),
    CHECK (date_trunc('milliseconds', occurred_at) = occurred_at),
    CHECK (event_date = (occurred_at AT TIME ZONE 'UTC')::date),
    CHECK ((family(source_ip) = 4 AND masklen(source_ip) = 32) OR (family(source_ip) = 6 AND masklen(source_ip) = 128)),
    CHECK ((category = 'authentication' AND event_type IN ('login','suspicious_access'))
        OR (category = 'network' AND event_type IN ('connection','traffic_anomaly'))
        OR (category = 'alert' AND event_type = 'potential_threat'))
);

-- Equality first, followed by the time range and deterministic tie breaker.
CREATE INDEX IF NOT EXISTS events_device_time_idx ON events (device_id, occurred_at DESC, event_id DESC);
CREATE INDEX IF NOT EXISTS events_ip_time_idx ON events (source_ip, occurred_at DESC, event_id DESC);
-- Only alerts participate in Q3. Non-alert high severity events are excluded.
CREATE INDEX IF NOT EXISTS events_alert_severity_time_idx ON events (severity, occurred_at DESC, event_id DESC) WHERE category = 'alert';

COMMIT;
