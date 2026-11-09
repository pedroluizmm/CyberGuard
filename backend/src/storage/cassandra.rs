use crate::{
    analytics::{EventQuery, QueryKey},
    config::Config,
    domain::{Event, UpdateEvent},
    error::{Error, Result},
};
use chrono::{DateTime, Utc};
use scylla::{
    client::{caching_session::CachingSession, session_builder::SessionBuilder},
    response::query_result::QueryResult,
    statement::{
        Consistency, SerialConsistency,
        batch::{Batch, BatchType},
        unprepared::Statement,
    },
    value::Row,
};
use uuid::Uuid;

pub struct CassandraStore {
    session: CachingSession,
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
        })
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
        if !ok && self.record(event.data.id()?).await?.lifecycle != "active" {
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
        if !ok && self.record(event.data.id()?).await?.lifecycle != "deleted" {
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
                for position in candidates {
                    scanned += 1;
                    if scanned > 1000 {
                        return Err(Error::ScanLimit);
                    }
                    upper = position;
                    match self.get(position.1).await {
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
