use crate::{
    domain::{self, Event},
    error::{Error, Result},
};
use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use chrono::{DateTime, Duration, NaiveDate, Utc};
use serde::{Deserialize, Serialize};
use std::net::IpAddr;
use uuid::Uuid;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value")]
pub enum QueryKey {
    Device(String),
    Ip(IpAddr),
    Severity(i16),
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct QueryParams {
    pub from: String,
    pub to: String,
    pub device_id: Option<String>,
    pub source_ip: Option<String>,
    pub severity: Option<i16>,
    pub page_size: Option<usize>,
    pub cursor: Option<String>,
}

#[derive(Clone, Debug)]
pub struct EventQuery {
    pub key: QueryKey,
    pub from: DateTime<Utc>,
    pub to: DateTime<Utc>,
    pub page_size: usize,
    pub upper: (DateTime<Utc>, Uuid),
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Cursor {
    version: u8,
    key: QueryKey,
    from: i64,
    to: i64,
    page_size: usize,
    timestamp: i64,
    event_id: Uuid,
}

#[derive(Serialize)]
pub struct EventPage {
    pub items: Vec<Event>,
    pub next_cursor: Option<String>,
}

impl EventQuery {
    pub fn parse(kind: &str, params: QueryParams) -> Result<Self> {
        let key = match (kind, params.device_id, params.source_ip, params.severity) {
            ("device", Some(device), None, None) => {
                domain::validate_device(&device)?;
                QueryKey::Device(device)
            }
            ("ip", None, Some(ip), None) => QueryKey::Ip(domain::parse_ip(&ip)?),
            ("alerts", None, None, Some(severity)) => {
                domain::validate_severity(severity)?;
                QueryKey::Severity(severity)
            }
            _ => {
                return Err(Error::Invalid(
                    "provide exactly the filter required by device, ip or alerts",
                ));
            }
        };
        let from = domain::parse_time(&params.from)?;
        let to = domain::parse_time(&params.to)?;
        if from >= to
            || (to - Duration::milliseconds(1))
                .date_naive()
                .signed_duration_since(from.date_naive())
                .num_days()
                >= 7
        {
            return Err(Error::Invalid(
                "window must be nonempty and touch at most 7 UTC dates; interval is [from,to)",
            ));
        }
        let page_size = params.page_size.unwrap_or(50);
        if !(1..=100).contains(&page_size) {
            return Err(Error::Invalid("page_size must be 1..100"));
        }
        let mut result = Self {
            key,
            from,
            to,
            page_size,
            upper: (to, Uuid::nil()),
        };
        if let Some(raw) = params.cursor {
            if raw.len() > 2048 {
                return Err(Error::Invalid("cursor too large"));
            }
            let bytes = URL_SAFE_NO_PAD
                .decode(raw)
                .map_err(|_| Error::Invalid("invalid cursor"))?;
            let c: Cursor =
                serde_json::from_slice(&bytes).map_err(|_| Error::Invalid("invalid cursor"))?;
            if c.version != 1
                || c.key != result.key
                || c.from != from.timestamp_millis()
                || c.to != to.timestamp_millis()
                || c.page_size != page_size
                || c.timestamp < from.timestamp_millis()
                || c.timestamp >= to.timestamp_millis()
                || domain::parse_id(&c.event_id.to_string()).is_err()
            {
                return Err(Error::Invalid("cursor does not match this query"));
            }
            result.upper = (
                DateTime::from_timestamp_millis(c.timestamp)
                    .ok_or(Error::Invalid("invalid cursor time"))?,
                c.event_id,
            );
        }
        Ok(result)
    }

    pub fn days_desc(&self) -> Vec<NaiveDate> {
        let first = self.from.date_naive();
        let mut day = (self.to - Duration::milliseconds(1)).date_naive();
        let mut result = Vec::new();
        while day >= first {
            result.push(day);
            day -= Duration::days(1);
        }
        result
    }

    pub fn matches(&self, event: &Event) -> bool {
        let Ok(time) = event.data.time() else {
            return false;
        };
        let Ok(id) = event.data.id() else {
            return false;
        };
        time >= self.from
            && time < self.to
            && (time, id) < self.upper
            && match &self.key {
                QueryKey::Device(device) => event.data.device_id == *device,
                QueryKey::Ip(ip) => event.data.source_ip == ip.to_string(),
                QueryKey::Severity(severity) => {
                    event.data.category == "alert" && event.data.severity == *severity
                }
            }
    }

    pub fn page(&self, mut items: Vec<Event>) -> Result<EventPage> {
        let has_more = items.len() > self.page_size;
        items.truncate(self.page_size);
        let next_cursor = if has_more {
            let last = items.last().ok_or(Error::Corrupt)?;
            Some(
                URL_SAFE_NO_PAD.encode(
                    serde_json::to_vec(&Cursor {
                        version: 1,
                        key: self.key.clone(),
                        from: self.from.timestamp_millis(),
                        to: self.to.timestamp_millis(),
                        page_size: self.page_size,
                        timestamp: last.data.time()?.timestamp_millis(),
                        event_id: last.data.id()?,
                    })
                    .map_err(|_| Error::Corrupt)?,
                ),
            )
        } else {
            None
        };
        Ok(EventPage { items, next_cursor })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn params() -> QueryParams {
        QueryParams {
            from: "2026-11-01T00:00:00Z".into(),
            to: "2026-11-08T00:00:00Z".into(),
            device_id: Some("test-device".into()),
            source_ip: None,
            severity: None,
            page_size: Some(2),
            cursor: None,
        }
    }
    #[test]
    fn seven_dates_are_bounded_and_end_is_exclusive() {
        let query = EventQuery::parse("device", params()).unwrap();
        assert_eq!(query.days_desc().len(), 7);
        assert_eq!(query.days_desc()[0].to_string(), "2026-11-07");
        let mut p = params();
        p.to = "2026-11-08T00:00:00.001Z".into();
        assert!(EventQuery::parse("device", p).is_err());
    }
    #[test]
    fn mixed_filters_invalid_cursor_and_unbounded_pages_are_rejected() {
        let mut p = params();
        p.source_ip = Some("192.0.2.1".into());
        assert!(EventQuery::parse("device", p).is_err());
        let mut p = params();
        p.page_size = Some(101);
        assert!(EventQuery::parse("device", p).is_err());
        let mut p = params();
        p.cursor = Some("bad".into());
        assert!(EventQuery::parse("device", p).is_err());
    }
}
