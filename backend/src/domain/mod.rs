use crate::error::{Error, Result};
use chrono::{DateTime, NaiveDate, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::net::IpAddr;
use uuid::Uuid;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct EventData {
    pub event_id: String,
    pub occurred_at: String,
    pub event_date: String,
    pub device_id: String,
    pub source_ip: String,
    pub category: String,
    pub event_type: String,
    pub severity: i16,
    pub outcome: String,
    pub message: String,
    pub metadata: Value,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Event {
    pub data: EventData,
    pub revision: i64,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct UpdateEvent {
    pub expected_revision: i64,
    pub outcome: String,
    pub message: String,
    pub metadata: Value,
}

impl EventData {
    pub fn validated(mut self) -> Result<Self> {
        self.event_id = parse_id(&self.event_id)?.to_string();
        let time = parse_time(&self.occurred_at)?;
        self.occurred_at = time.to_rfc3339_opts(SecondsFormat::Millis, true);
        if self.event_date != time.date_naive().to_string() {
            return Err(Error::Invalid(
                "event_date must equal the UTC date of occurred_at",
            ));
        }
        validate_device(&self.device_id)?;
        self.source_ip = parse_ip(&self.source_ip)?.to_string();
        let valid_type = match self.category.as_str() {
            "authentication" => matches!(self.event_type.as_str(), "login" | "suspicious_access"),
            "network" => matches!(self.event_type.as_str(), "connection" | "traffic_anomaly"),
            "alert" => self.event_type == "potential_threat",
            _ => false,
        };
        if !valid_type {
            return Err(Error::Invalid("invalid category/event_type combination"));
        }
        validate_severity(self.severity)?;
        validate_mutable(&self.outcome, &self.message, &self.metadata)?;
        Ok(self)
    }

    pub fn id(&self) -> Result<Uuid> {
        parse_id(&self.event_id)
    }
    pub fn time(&self) -> Result<DateTime<Utc>> {
        parse_time(&self.occurred_at)
    }
    pub fn day(&self) -> Result<NaiveDate> {
        Ok(self.time()?.date_naive())
    }
    pub fn ip(&self) -> Result<IpAddr> {
        parse_ip(&self.source_ip)
    }
}

impl UpdateEvent {
    pub fn validate(&self) -> Result<()> {
        validate_revision(self.expected_revision)?;
        if self.expected_revision == i64::MAX {
            return Err(Error::Invalid(
                "revision exhausted; UPDATE cannot increment it",
            ));
        }
        validate_mutable(&self.outcome, &self.message, &self.metadata)
    }

    pub fn apply(&self, current: &Event) -> Result<Event> {
        self.validate()?;
        // A retry of an already accepted PUT is successful without incrementing twice.
        if current.revision == self.expected_revision + 1
            && current.data.outcome == self.outcome
            && current.data.message == self.message
            && current.data.metadata == self.metadata
        {
            return Ok(current.clone());
        }
        if current.revision != self.expected_revision {
            return Err(Error::Conflict);
        }
        let mut next = current.clone();
        next.revision += 1;
        next.data.outcome.clone_from(&self.outcome);
        next.data.message.clone_from(&self.message);
        next.data.metadata.clone_from(&self.metadata);
        Ok(next)
    }
}

pub fn validate_revision(revision: i64) -> Result<()> {
    if revision < 1 {
        return Err(Error::Invalid("expected_revision must be positive"));
    }
    Ok(())
}

pub fn parse_id(value: &str) -> Result<Uuid> {
    let id = Uuid::parse_str(value).map_err(|_| Error::Invalid("event_id must be a UUID v4"))?;
    if value.len() != 36 || id.get_version_num() != 4 || id.get_variant() != uuid::Variant::RFC4122
    {
        return Err(Error::Invalid(
            "event_id must be a hyphenated RFC 4122 UUID v4",
        ));
    }
    Ok(id)
}

pub fn parse_time(value: &str) -> Result<DateTime<Utc>> {
    let time = DateTime::parse_from_rfc3339(value)
        .map_err(|_| Error::Invalid("timestamp must be RFC3339 UTC"))?;
    if time.offset().local_minus_utc() != 0
        || time.timestamp_subsec_nanos() >= 1_000_000_000
        || time.timestamp_subsec_nanos() % 1_000_000 != 0
    {
        return Err(Error::Invalid(
            "timestamp must use UTC and at most millisecond precision",
        ));
    }
    let utc = time.with_timezone(&Utc);
    if utc < DateTime::from_timestamp(946684800, 0).unwrap()
        || utc >= DateTime::from_timestamp(4102444800, 0).unwrap()
    {
        return Err(Error::Invalid(
            "timestamp must be in [2000-01-01, 2100-01-01)",
        ));
    }
    Ok(utc)
}

pub fn parse_ip(value: &str) -> Result<IpAddr> {
    value
        .parse::<IpAddr>()
        .map(|ip| ip.to_canonical())
        .map_err(|_| Error::Invalid("source_ip must be an IPv4 or IPv6 host address"))
}

pub fn validate_device(value: &str) -> Result<()> {
    if value.is_empty()
        || value.len() > 64
        || !value.as_bytes()[0].is_ascii_alphanumeric()
        || !value
            .bytes()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || b"._-".contains(&c))
    {
        return Err(Error::Invalid(
            "device_id must match [a-z0-9][a-z0-9._-]{0,63}",
        ));
    }
    Ok(())
}

pub fn validate_severity(value: i16) -> Result<()> {
    if !(1..=5).contains(&value) {
        return Err(Error::Invalid("severity must be 1..5"));
    }
    Ok(())
}

fn validate_mutable(outcome: &str, message: &str, metadata: &Value) -> Result<()> {
    if !matches!(outcome, "success" | "failure" | "blocked" | "unknown") {
        return Err(Error::Invalid(
            "outcome must be success, failure, blocked or unknown",
        ));
    }
    if message.trim().is_empty() || message.len() > 2048 || message.contains('\0') {
        return Err(Error::Invalid(
            "message must contain 1..2048 UTF-8 bytes without NUL",
        ));
    }
    if !metadata.is_object() || metadata.to_string().len() > 4096 || !valid_json(metadata, 0) {
        return Err(Error::Invalid(
            "metadata must be a JSON object <=4096 bytes, depth <=8, with integer numbers and no NUL",
        ));
    }
    Ok(())
}

fn valid_json(value: &Value, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    match value {
        Value::Null | Value::Bool(_) => true,
        Value::Number(n) => n.as_i64().is_some(),
        Value::String(s) => !s.contains('\0'),
        Value::Array(a) => a.iter().all(|v| valid_json(v, depth + 1)),
        Value::Object(o) => o
            .iter()
            .all(|(k, v)| !k.contains('\0') && k.len() <= 64 && valid_json(v, depth + 1)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn timestamps_preserve_milliseconds_and_reject_precision_loss() {
        assert!(parse_time("2026-11-09T12:30:00.123Z").is_ok());
        for input in [
            "2016-12-31T23:59:60Z",
            "2026-11-09",
            "2026-11-09T12:30:00.1234Z",
            "2026-11-09T12:30:00-03:00",
            "1999-12-31T23:59:59Z",
            "2026-02-30T00:00:00Z",
        ] {
            assert!(parse_time(input).is_err(), "{input}");
        }
    }

    #[test]
    fn metadata_rejects_lossy_numbers_and_nul() {
        for bad in [
            serde_json::json!([]),
            serde_json::json!({"n": 1.5}),
            serde_json::json!({"n": "\u{0}"}),
        ] {
            assert!(validate_mutable("success", "message", &bad).is_err());
        }
        assert!(
            validate_mutable(
                "success",
                "message",
                &serde_json::json!({"n": 9223372036854775807_i64})
            )
            .is_ok()
        );
    }

    #[test]
    fn identifiers_and_filters_are_strict() {
        assert!(parse_id("04a51d3e-b1c0-4bd6-a0fb-fac6cf4d9759").is_ok());
        assert!(parse_id("00000000-0000-0000-0000-000000000000").is_err());
        assert!(validate_device("server-01.example").is_ok());
        for value in ["", "UPPER", "a' OR 1=1", "-bad"] {
            assert!(validate_device(value).is_err());
        }
        assert!(parse_ip("2001:db8::1").is_ok());
        assert!(parse_ip("192.0.2.1/24").is_err());
        assert_eq!(
            parse_ip("::ffff:192.0.2.1").unwrap().to_string(),
            "192.0.2.1"
        );
        assert!(validate_severity(0).is_err());
        assert!(validate_severity(6).is_err());
        // An exhausted revision may still be deleted, but never incremented.
        assert!(validate_revision(i64::MAX).is_ok());
        assert!(
            UpdateEvent {
                expected_revision: i64::MAX,
                outcome: "success".into(),
                message: "test".into(),
                metadata: serde_json::json!({})
            }
            .validate()
            .is_err()
        );
    }
}
