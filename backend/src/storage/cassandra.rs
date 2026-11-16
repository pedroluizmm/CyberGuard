use crate::{
    analytics::{Cell, EventQuery, OverviewQuery, QueryKey},
    config::Config,
    domain::{Event, UpdateEvent},
    error::{Error, Result},
};
use chrono::{DateTime, Timelike, Utc};
use futures::{StreamExt, TryFutureExt, future::try_join_all, stream};
use scylla::{
    client::{caching_session::CachingSession, session_builder::SessionBuilder},
    response::query_result::QueryResult,
    statement::{
        Consistency, SerialConsistency,
        batch::{Batch, BatchType},
        unprepared::Statement,
    },
    value::{Counter, Row},
};
use uuid::Uuid;

pub struct CassandraStore {
    session: CachingSession,
    read_concurrency: usize,
}

struct Record {
    event: Option<Event>,
    revision: i64,
    lifecycle: String,
}

fn statement(query: &str) -> Statement {
    let mut s = Statement::new(query);
    s.set_consistency(Consistency::LocalQuorum);
    s.set_serial_consistency(Some(SerialConsistency::LocalSerial));
    s
}

fn applied(result: QueryResult) -> Result<bool> {
    let rows = result.into_rows_result().map_err(|_| Error::Corrupt)?;
    let row: Row = rows.single_row().map_err(|_| Error::Corrupt)?;
    row.columns
        .first()
        .and_then(Option::as_ref)
        .and_then(|v| v.as_boolean())
        .ok_or(Error::Corrupt)
}

impl CassandraStore {
    pub async fn connect(config: &Config) -> Result<Self> {
        let session = SessionBuilder::new()
            .known_node(&config.cassandra_contact_point)
            .connection_timeout(config.storage_timeout)
            .build()
            .await
            .map_err(|_| Error::Unavailable)?;
        Ok(Self {
            session: CachingSession::from(session, 32),
            read_concurrency: config.cassandra_read_concurrency,
        })
    }

    /// Write-time rollup (`event_counts_by_day`). Called only by the request that
    /// won the LWT lifecycle transition, so each activation/deletion is counted
    /// once. Counters are not idempotent: a failure here is logged and corrected
    /// by `scripts/loading/reconcile_rollup.py`; the event write itself stands.
    async fn count(&self, event: &Event, delta: i64) {
        let d = &event.data;
        let (Ok(time), Ok(day), Ok(id)) = (d.time(), d.day(), d.id()) else {
            return;
        };
        let result = self
            .session
            .execute_unpaged(
                statement("UPDATE cyberguard.event_counts_by_day SET events = events + ? WHERE event_date=? AND hour=? AND category=? AND severity=?"),
                (Counter(delta), day, time.hour() as i8, &d.category, d.severity),
            )
            .await;
        if result.is_err() {
            tracing::warn!(event_id = %id, delta, "rollup_update_failed");
        }
    }

    /// Reads one rollup partition per UTC date (at most 7, concurrently). Category
    /// and severity are filtered in the application: each partition holds at most
    /// 24 x 15 cells, so no ALLOW FILTERING or scan is needed.
    pub async fn overview(&self, q: &OverviewQuery) -> Result<Vec<Cell>> {
        let reads = q.days().into_iter().map(|(day, lo, hi)| {
            self.session
                .execute_unpaged(
                    statement("SELECT hour,category,severity,events FROM cyberguard.event_counts_by_day WHERE event_date=? AND hour>=? AND hour<?"),
                    (day, lo, hi),
                )
                .map_err(|_| Error::Unavailable)
                .and_then(move |result| async move {
                    let rows = result.into_rows_result().map_err(|_| Error::Corrupt)?;
                    let mut cells = Vec::new();
                    for row in rows
                        .rows::<(i8, String, i16, Option<Counter>)>()
                        .map_err(|_| Error::Corrupt)?
                    {
                        let (hour, category, severity, count) = row.map_err(|_| Error::Corrupt)?;
                        if !(0..24).contains(&hour) {
                            return Err(Error::Corrupt);
                        }
                        cells.push(Cell {
                            hour: day
                                .and_hms_opt(hour as u32, 0, 0)
                                .ok_or(Error::Corrupt)?
                                .and_utc(),
                            category,
                            severity,
                            count: count.map_or(0, |c| c.0),
                        });
                    }
                    Ok(cells)
                })
        });
        Ok(try_join_all(reads).await?.into_iter().flatten().collect())
    }

    async fn record(&self, id: Uuid) -> Result<Record> {
        let result=self.session.execute_unpaged(statement("SELECT payload,revision,lifecycle FROM cyberguard.events_by_id WHERE event_id=?"),(id,))
            .await.map_err(|_| Error::Unavailable)?.into_rows_result().map_err(|_| Error::Corrupt)?;
        let row = result
            .rows::<(Option<String>, i64, String)>()
            .map_err(|_| Error::Corrupt)?
            .next()
            .transpose()
            .map_err(|_| Error::Corrupt)?
            .ok_or(Error::NotFound)?;
        let (payload, revision, lifecycle) = row;
        if !matches!(
            lifecycle.as_str(),
            "pending" | "active" | "deleting" | "deleted"
        ) {
            return Err(Error::Corrupt);
        }
        let event = if lifecycle == "deleted" {
            None
        } else {
            let mut event: Event = serde_json::from_str(&payload.ok_or(Error::Corrupt)?)
                .map_err(|_| Error::Corrupt)?;
            event.data = event.data.validated().map_err(|_| Error::Corrupt)?;
            if event.revision != revision || event.revision < 1 || event.data.id()? != id {
                return Err(Error::Corrupt);
            }
            Some(event)
        };
        Ok(Record {
            event,
            revision,
            lifecycle,
        })
    }

    pub async fn get(&self, id: Uuid) -> Result<Event> {
        let record = self.record(id).await?;
        match record.lifecycle.as_str() {
            "active" => record.event.ok_or(Error::Corrupt),
            "deleted" => Err(Error::NotFound),
            _ => Err(Error::Pending),
        }
    }

    pub async fn create(&self, event: Event) -> Result<(Event, bool)> {
        let id = event.data.id()?;
        let payload = serde_json::to_string(&event).map_err(|_| Error::Corrupt)?;
        let created=applied(self.session.execute_unpaged(statement("INSERT INTO cyberguard.events_by_id(event_id,payload,revision,lifecycle) VALUES(?,?,?,'pending') IF NOT EXISTS"),(id,payload,event.revision)).await.map_err(|_| Error::Unavailable)?)?;
        let record = self.record(id).await?;
        if !matches!(record.lifecycle.as_str(), "pending" | "active")
            || record.event.as_ref() != Some(&event)
        {
            return Err(Error::Conflict);
        }
        if record.lifecycle == "pending" {
            self.finish_create(&event).await?;
        }
        Ok((self.get(id).await?, created))
    }

    async fn projections(&self, event: &Event, delete: bool) -> Result<()> {
        let d = &event.data;
        let mut batch = Batch::new(BatchType::Logged);
        batch.set_consistency(Consistency::LocalQuorum);
        for (table, key) in [
            ("events_by_device_day", "device_id"),
            ("events_by_ip_day", "source_ip"),
        ] {
            let sql = if delete {
                format!(
                    "DELETE FROM cyberguard.{table} WHERE {key}=? AND event_date=? AND occurred_at=? AND event_id=?"
                )
            } else {
                format!(
                    "INSERT INTO cyberguard.{table}({key},event_date,occurred_at,event_id) VALUES(?,?,?,?)"
                )
            };
            batch.append_statement(statement(&sql));
        }
        let device = (&d.device_id, d.day()?, d.time()?, d.id()?);
        let ip = (d.ip()?, d.day()?, d.time()?, d.id()?);
        if d.category == "alert" {
            batch.append_statement(statement(if delete { "DELETE FROM cyberguard.alerts_by_severity_day WHERE severity=? AND event_date=? AND occurred_at=? AND event_id=?" } else { "INSERT INTO cyberguard.alerts_by_severity_day(severity,event_date,occurred_at,event_id) VALUES(?,?,?,?)" }));
            self.session
                .batch(
                    &batch,
                    (device, ip, (d.severity, d.day()?, d.time()?, d.id()?)),
                )
                .await
                .map_err(|_| Error::Unavailable)?;
        } else {
            self.session
                .batch(&batch, (device, ip))
                .await
                .map_err(|_| Error::Unavailable)?;
        }
        Ok(())
    }

    async fn finish_create(&self, event: &Event) -> Result<()> {
        self.projections(event, false).await?;
        let ok=applied(self.session.execute_unpaged(statement("UPDATE cyberguard.events_by_id SET lifecycle='active' WHERE event_id=? IF lifecycle='pending'"),(event.data.id()?,)).await.map_err(|_| Error::Unavailable)?)?;
        if ok {
            self.count(event, 1).await;
        } else if self.record(event.data.id()?).await?.lifecycle != "active" {
            return Err(Error::Conflict);
        }
        Ok(())
    }

    pub async fn update(&self, id: Uuid, update: &UpdateEvent) -> Result<Event> {
        let current = self.get(id).await?;
        let next = update.apply(&current)?;
        if next.revision == current.revision {
            return Ok(next);
        }
        let payload = serde_json::to_string(&next).map_err(|_| Error::Corrupt)?;
        let ok=applied(self.session.execute_unpaged(statement("UPDATE cyberguard.events_by_id SET payload=?,revision=? WHERE event_id=? IF revision=? AND lifecycle='active'"),(payload,next.revision,id,current.revision)).await.map_err(|_| Error::Unavailable)?)?;
        if !ok {
            return Err(Error::Conflict);
        }
        Ok(next)
    }

    pub async fn delete(&self, id: Uuid, revision: i64) -> Result<()> {
        let record = self.record(id).await?;
        if record.lifecycle == "deleted" {
            return Ok(());
        }
        if record.lifecycle == "pending" {
            return Err(Error::Pending);
        }
        if record.revision != revision {
            return Err(Error::Conflict);
        }
        if record.lifecycle == "active" {
            let ok=applied(self.session.execute_unpaged(statement("UPDATE cyberguard.events_by_id SET lifecycle='deleting' WHERE event_id=? IF revision=? AND lifecycle='active'"),(id,revision)).await.map_err(|_| Error::Unavailable)?)?;
            if !ok {
                return Err(Error::Conflict);
            }
        }
        self.finish_delete(&record.event.ok_or(Error::Corrupt)?)
            .await
    }

    async fn finish_delete(&self, event: &Event) -> Result<()> {
        self.projections(event, true).await?;
        let ok=applied(self.session.execute_unpaged(statement("UPDATE cyberguard.events_by_id SET lifecycle='deleted',payload=null WHERE event_id=? IF lifecycle='deleting'"),(event.data.id()?,)).await.map_err(|_| Error::Unavailable)?)?;
        if ok {
            self.count(event, -1).await;
        } else if self.record(event.data.id()?).await?.lifecycle != "deleted" {
            return Err(Error::Conflict);
        }
        Ok(())
    }

    pub async fn repair(&self, id: Uuid) -> Result<&'static str> {
        let record = self.record(id).await?;
        match record.lifecycle.as_str() {
            "pending" => {
                self.finish_create(&record.event.ok_or(Error::Corrupt)?)
                    .await?;
                Ok("active")
            }
            "deleting" => {
                self.finish_delete(&record.event.ok_or(Error::Corrupt)?)
                    .await?;
                Ok("deleted")
            }
            "active" => {
                self.projections(&record.event.ok_or(Error::Corrupt)?, false)
                    .await?;
                Ok("active")
            }
            "deleted" => Ok("deleted"),
            _ => Err(Error::Corrupt),
        }
    }

    pub async fn query(&self, q: &EventQuery) -> Result<Vec<Event>> {
        let (table, key) = match q.key {
            QueryKey::Device(_) => ("events_by_device_day", "device_id"),
            QueryKey::Ip(_) => ("events_by_ip_day", "source_ip"),
            QueryKey::Severity(_) => ("alerts_by_severity_day", "severity"),
        };
        let sql = format!(
            "SELECT occurred_at,event_id FROM cyberguard.{table} WHERE {key}=? AND event_date=? AND (occurred_at,event_id) >= (?,?) AND (occurred_at,event_id) < (?,?) LIMIT ?"
        );
        let mut items = Vec::new();
        let mut scanned = 0;
        for day in q.days_desc() {
            let mut upper = q.upper;
            loop {
                let limit = (q.page_size + 1 - items.len()) as i32;
                let s = statement(&sql);
                let result = match &q.key {
                    QueryKey::Device(value) => {
                        self.session
                            .execute_unpaged(
                                s,
                                (value, day, q.from, Uuid::nil(), upper.0, upper.1, limit),
                            )
                            .await
                    }
                    QueryKey::Ip(value) => {
                        self.session
                            .execute_unpaged(
                                s,
                                (*value, day, q.from, Uuid::nil(), upper.0, upper.1, limit),
                            )
                            .await
                    }
                    QueryKey::Severity(value) => {
                        self.session
                            .execute_unpaged(
                                s,
                                (*value, day, q.from, Uuid::nil(), upper.0, upper.1, limit),
                            )
                            .await
                    }
                }
                .map_err(|_| Error::Unavailable)?
                .into_rows_result()
                .map_err(|_| Error::Corrupt)?;
                let candidates = result
                    .rows::<(DateTime<Utc>, Uuid)>()
                    .map_err(|_| Error::Corrupt)?
                    .collect::<std::result::Result<Vec<_>, _>>()
                    .map_err(|_| Error::Corrupt)?;
                let count = candidates.len();
                // Canonical reads are independent single-partition lookups. They run
                // with bounded concurrency; `buffered` yields them in candidate order,
                // so ordering, filtering and the scan limit keep the sequential
                // semantics. At most `limit` (<= page_size + 1) reads per slice, i.e.
                // never more than the candidates the page can still use.
                let ids: Vec<Uuid> = candidates.iter().map(|position| position.1).collect();
                let fetched: Vec<Result<Event>> = stream::iter(ids)
                    .map(|id| self.get(id))
                    .buffered(self.read_concurrency)
                    .collect()
                    .await;
                for (position, fetched) in candidates.into_iter().zip(fetched) {
                    scanned += 1;
                    if scanned > 1000 {
                        return Err(Error::ScanLimit);
                    }
                    upper = position;
                    match fetched {
                        Ok(event) if q.matches(&event) => items.push(event),
                        Ok(_) | Err(Error::NotFound) | Err(Error::Pending) => {}
                        Err(error) => return Err(error),
                    }
                    if items.len() > q.page_size {
                        return Ok(items);
                    }
                }
                if count < limit as usize {
                    break;
                }
            }
        }
        Ok(items)
    }
}
