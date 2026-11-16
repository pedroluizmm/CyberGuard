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

pub const CATEGORIES: [&str; 3] = ["authentication", "network", "alert"];
const HOUR_MS: i64 = 3_600_000;

/// Dashboard aggregate over whole UTC hours: `[from,to)`, at most 7 UTC dates.
/// Optional exact filters by category and severity. Both sources return the
/// same `Overview`, built from (hour, category, severity, count) cells.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OverviewParams {
    pub from: String,
    pub to: String,
    pub category: Option<String>,
    pub severity: Option<i16>,
}

#[derive(Clone, Debug)]
pub struct OverviewQuery {
    pub from: DateTime<Utc>,
    pub to: DateTime<Utc>,
    pub category: Option<String>,
    pub severity: Option<i16>,
}

/// One aggregated cell read from storage.
pub struct Cell {
    pub hour: DateTime<Utc>,
    pub category: String,
    pub severity: i16,
    pub count: i64,
}

#[derive(Serialize)]
pub struct OverviewFilters {
    category: Option<String>,
    severity: Option<i16>,
}

#[derive(Serialize)]
pub struct Point {
    t: String,
    total: i64,
    /// Order: authentication, network, alert.
    by_category: [i64; 3],
    /// Order: severity 1..5.
    by_severity: [i64; 5],
}

#[derive(Serialize)]
pub struct Overview {
    from: String,
    to: String,
    bucket: &'static str,
    filters: OverviewFilters,
    total: i64,
    alerts: i64,
    by_category: [i64; 3],
    by_severity: [i64; 5],
    series: Vec<Point>,
}

impl OverviewQuery {
    pub fn parse(params: OverviewParams) -> Result<Self> {
        let from = domain::parse_time(&params.from)?;
        let to = domain::parse_time(&params.to)?;
        if from.timestamp_millis() % HOUR_MS != 0 || to.timestamp_millis() % HOUR_MS != 0 {
            return Err(Error::Invalid("overview from/to must be whole UTC hours"));
        }
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
        if let Some(category) = &params.category {
            if !CATEGORIES.contains(&category.as_str()) {
                return Err(Error::Invalid(
                    "category must be authentication, network or alert",
                ));
            }
        }
        if let Some(severity) = params.severity {
            domain::validate_severity(severity)?;
        }
        Ok(Self {
            from,
            to,
            category: params.category,
            severity: params.severity,
        })
    }

    /// Ascending UTC dates with the hour range `[lo,hi)` touched on each date.
    pub fn days(&self) -> Vec<(NaiveDate, i8, i8)> {
        let first = self.from.date_naive();
        let last = (self.to - Duration::milliseconds(1)).date_naive();
        let mut result = Vec::new();
        let mut day = first;
        while day <= last {
            let lo = if day == first {
                self.from.hour_of_day()
            } else {
                0
            };
            let hi = if day == self.to.date_naive() {
                self.to.hour_of_day()
            } else {
                24
            };
            result.push((day, lo, hi));
            day += Duration::days(1);
        }
        result
    }

    pub fn accepts(&self, category: &str, severity: i16) -> bool {
        self.category.as_deref().is_none_or(|c| c == category)
            && self.severity.is_none_or(|s| s == severity)
    }

    pub fn build(&self, cells: Vec<Cell>) -> Result<Overview> {
        let hours = ((self.to - self.from).num_milliseconds() / HOUR_MS) as usize;
        let mut series: Vec<Point> = (0..hours)
            .map(|i| Point {
                t: (self.from + Duration::hours(i as i64))
                    .to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
                total: 0,
                by_category: [0; 3],
                by_severity: [0; 5],
            })
            .collect();
        let (mut by_category, mut by_severity) = ([0i64; 3], [0i64; 5]);
        for cell in cells {
            if cell.count == 0 || !self.accepts(&cell.category, cell.severity) {
                continue;
            }
            if cell.hour < self.from || cell.hour >= self.to {
                continue;
            }
            let c = CATEGORIES
                .iter()
                .position(|known| *known == cell.category)
                .ok_or(Error::Corrupt)?;
            if !(1..=5).contains(&cell.severity) {
                return Err(Error::Corrupt);
            }
            let s = (cell.severity - 1) as usize;
            let point =
                &mut series[((cell.hour - self.from).num_milliseconds() / HOUR_MS) as usize];
            point.total += cell.count;
            point.by_category[c] += cell.count;
            point.by_severity[s] += cell.count;
            by_category[c] += cell.count;
            by_severity[s] += cell.count;
        }
        Ok(Overview {
            from: self
                .from
                .to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
            to: self.to.to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
            bucket: "hour",
            filters: OverviewFilters {
                category: self.category.clone(),
                severity: self.severity,
            },
            total: by_category.iter().sum(),
            alerts: by_category[2],
            by_category,
            by_severity,
            series,
        })
    }
}

trait HourOfDay {
    fn hour_of_day(&self) -> i8;
}

impl HourOfDay for DateTime<Utc> {
    fn hour_of_day(&self) -> i8 {
        use chrono::Timelike;
        self.hour() as i8
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

    fn overview(from: &str, to: &str) -> OverviewParams {
        OverviewParams {
            from: from.into(),
            to: to.into(),
            category: None,
            severity: None,
        }
    }

    #[test]
    fn overview_requires_whole_hours_seven_dates_and_known_filters() {
        assert!(
            OverviewQuery::parse(overview("2026-10-05T00:00:00Z", "2026-10-12T00:00:00Z")).is_ok()
        );
        assert!(
            OverviewQuery::parse(overview("2026-10-05T00:00:00Z", "2026-10-12T01:00:00Z")).is_err()
        );
        assert!(
            OverviewQuery::parse(overview("2026-10-05T00:30:00Z", "2026-10-06T00:00:00Z")).is_err()
        );
        assert!(
            OverviewQuery::parse(overview("2026-10-06T00:00:00Z", "2026-10-06T00:00:00Z")).is_err()
        );
        let mut p = overview("2026-10-05T00:00:00Z", "2026-10-06T00:00:00Z");
        p.category = Some("malware".into());
        assert!(OverviewQuery::parse(p).is_err());
        let mut p = overview("2026-10-05T00:00:00Z", "2026-10-06T00:00:00Z");
        p.severity = Some(6);
        assert!(OverviewQuery::parse(p).is_err());
    }

    #[test]
    fn overview_days_cover_partial_hours_and_build_fills_every_hour() {
        let q =
            OverviewQuery::parse(overview("2026-10-05T22:00:00Z", "2026-10-07T03:00:00Z")).unwrap();
        let days: Vec<_> = q
            .days()
            .into_iter()
            .map(|(d, lo, hi)| (d.to_string(), lo, hi))
            .collect();
        assert_eq!(
            days,
            vec![
                ("2026-10-05".to_string(), 22, 24),
                ("2026-10-06".to_string(), 0, 24),
                ("2026-10-07".to_string(), 0, 3)
            ]
        );
        let hour = |h: &str| DateTime::parse_from_rfc3339(h).unwrap().with_timezone(&Utc);
        let cells = vec![
            Cell {
                hour: hour("2026-10-05T22:00:00Z"),
                category: "alert".into(),
                severity: 5,
                count: 2,
            },
            Cell {
                hour: hour("2026-10-06T10:00:00Z"),
                category: "network".into(),
                severity: 1,
                count: 7,
            },
            // Outside the window: ignored.
            Cell {
                hour: hour("2026-10-07T03:00:00Z"),
                category: "network".into(),
                severity: 1,
                count: 9,
            },
        ];
        let o = q.build(cells).unwrap();
        assert_eq!(o.series.len(), 29);
        assert_eq!((o.total, o.alerts), (9, 2));
        assert_eq!(o.by_category, [0, 7, 2]);
        assert_eq!(o.by_severity, [7, 0, 0, 0, 2]);
        assert_eq!(o.series[0].by_category, [0, 0, 2]);
        let mut filtered = q.clone();
        filtered.category = Some("alert".into());
        let cells = vec![Cell {
            hour: hour("2026-10-06T10:00:00Z"),
            category: "network".into(),
            severity: 1,
            count: 7,
        }];
        assert_eq!(filtered.build(cells).unwrap().total, 0);
    }
}
