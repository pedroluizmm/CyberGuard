use crate::{
    analytics::{Cell, EventQuery, OverviewQuery, QueryKey},
    domain::{Event, EventData, UpdateEvent},
    error::{Error, Result},
};
use chrono::{DateTime, NaiveDate, Utc};
use sqlx::{PgPool, Postgres, Row, Transaction, postgres::PgRow};
use uuid::Uuid;

const COLUMNS: &str = "event_id, occurred_at, event_date, device_id, host(source_ip) AS source_ip, category, event_type, severity, outcome, message, metadata, revision";

pub struct PostgresStore {
    pub pool: PgPool,
}

fn decode(row: PgRow) -> Result<Event> {
    let read = || -> std::result::Result<Event, sqlx::Error> {
        Ok(Event {
            data: EventData {
                event_id: row.try_get::<Uuid, _>("event_id")?.to_string(),
                occurred_at: row
                    .try_get::<DateTime<Utc>, _>("occurred_at")?
                    .to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
                event_date: row.try_get::<NaiveDate, _>("event_date")?.to_string(),
                device_id: row.try_get("device_id")?,
                source_ip: row.try_get("source_ip")?,
                category: row.try_get("category")?,
                event_type: row.try_get("event_type")?,
                severity: row.try_get("severity")?,
                outcome: row.try_get("outcome")?,
                message: row.try_get("message")?,
                metadata: row.try_get("metadata")?,
            },
            revision: row.try_get("revision")?,
        })
    };
    let mut event = read().map_err(|_| Error::Corrupt)?;
    event.data = event.data.validated().map_err(|_| Error::Corrupt)?;
    Ok(event)
}

impl PostgresStore {
    pub async fn get(&self, id: Uuid) -> Result<Event> {
        let sql = format!("SELECT {COLUMNS} FROM events WHERE event_id=$1");
        let row = sqlx::query(&sql)
            .bind(id)
            .fetch_optional(&self.pool)
            .await
            .map_err(|_| Error::Unavailable)?;
        decode(row.ok_or(Error::NotFound)?)
    }

    async fn lock(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<bool> {
        sqlx::query_scalar("SELECT deleted FROM event_registry WHERE event_id=$1 FOR UPDATE")
            .bind(id)
            .fetch_optional(&mut **tx)
            .await
            .map_err(|_| Error::Unavailable)?
            .ok_or(Error::NotFound)
    }

    async fn get_locked(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<Option<Event>> {
        let sql = format!("SELECT {COLUMNS} FROM events WHERE event_id=$1");
        sqlx::query(&sql)
            .bind(id)
            .fetch_optional(&mut **tx)
            .await
            .map_err(|_| Error::Unavailable)?
            .map(decode)
            .transpose()
    }

    pub async fn create(&self, event: Event) -> Result<(Event, bool)> {
        let d = &event.data;
        let id = d.id()?;
        let mut tx = self.pool.begin().await.map_err(|_| Error::Unavailable)?;
        sqlx::query("INSERT INTO event_registry(event_id) VALUES($1) ON CONFLICT DO NOTHING")
            .bind(id)
            .execute(&mut *tx)
            .await
            .map_err(|_| Error::Unavailable)?;
        if Self::lock(&mut tx, id).await? {
            return Err(Error::Conflict);
        }
        if let Some(current) = Self::get_locked(&mut tx, id).await? {
            if current != event {
                return Err(Error::Conflict);
            }
            tx.commit().await.map_err(|_| Error::Unavailable)?;
            return Ok((current, false));
        }
        sqlx::query("INSERT INTO devices(device_id) VALUES($1) ON CONFLICT DO NOTHING")
            .bind(&d.device_id)
            .execute(&mut *tx)
            .await
            .map_err(|_| Error::Unavailable)?;
        sqlx::query("INSERT INTO events(event_id,occurred_at,event_date,device_id,source_ip,category,event_type,severity,outcome,message,metadata,revision) VALUES($1,$2,$3,$4,$5::inet,$6,$7,$8,$9,$10,$11,$12)")
            .bind(id).bind(d.time()?).bind(d.day()?).bind(&d.device_id).bind(&d.source_ip)
            .bind(&d.category).bind(&d.event_type).bind(d.severity).bind(&d.outcome).bind(&d.message).bind(&d.metadata).bind(event.revision)
            .execute(&mut *tx).await.map_err(|_| Error::Unavailable)?;
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok((event, true))
    }

    pub async fn update(&self, id: Uuid, update: &UpdateEvent) -> Result<Event> {
        let mut tx = self.pool.begin().await.map_err(|_| Error::Unavailable)?;
        if Self::lock(&mut tx, id).await? {
            return Err(Error::NotFound);
        }
        let current = Self::get_locked(&mut tx, id).await?.ok_or(Error::Corrupt)?;
        let next = update.apply(&current)?;
        if next.revision != current.revision {
            sqlx::query(
                "UPDATE events SET outcome=$1,message=$2,metadata=$3,revision=$4 WHERE event_id=$5",
            )
            .bind(&next.data.outcome)
            .bind(&next.data.message)
            .bind(&next.data.metadata)
            .bind(next.revision)
            .bind(id)
            .execute(&mut *tx)
            .await
            .map_err(|_| Error::Unavailable)?;
        }
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(next)
    }

    pub async fn delete(&self, id: Uuid, revision: i64) -> Result<()> {
        let mut tx = self.pool.begin().await.map_err(|_| Error::Unavailable)?;
        if !Self::lock(&mut tx, id).await? {
            let current = Self::get_locked(&mut tx, id).await?.ok_or(Error::Corrupt)?;
            if current.revision != revision {
                return Err(Error::Conflict);
            }
            sqlx::query("DELETE FROM events WHERE event_id=$1")
                .bind(id)
                .execute(&mut *tx)
                .await
                .map_err(|_| Error::Unavailable)?;
            sqlx::query("UPDATE event_registry SET deleted=true WHERE event_id=$1")
                .bind(id)
                .execute(&mut *tx)
                .await
                .map_err(|_| Error::Unavailable)?;
        }
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(())
    }

    pub async fn repair(&self, id: Uuid) -> Result<&'static str> {
        let deleted: bool =
            sqlx::query_scalar("SELECT deleted FROM event_registry WHERE event_id=$1")
                .bind(id)
                .fetch_optional(&self.pool)
                .await
                .map_err(|_| Error::Unavailable)?
                .ok_or(Error::NotFound)?;
        Ok(if deleted { "deleted" } else { "active" })
    }

    /// Aggregates on read from the normalized `events` table. The covering index
    /// `events_time_cover_idx (occurred_at) INCLUDE (category, severity)` allows an
    /// index-only range scan; filters are fixed SQL fragments with bound values.
    pub async fn overview(&self, q: &OverviewQuery) -> Result<Vec<Cell>> {
        let filter = match (&q.category, q.severity) {
            (None, None) => "",
            (Some(_), None) => " AND category=$3",
            (None, Some(_)) => " AND severity=$3",
            (Some(_), Some(_)) => " AND category=$3 AND severity=$4",
        };
        let sql = format!(
            // date_bin is timezone independent (UTC-aligned origin) and was the
            // cheapest equivalent bucketing expression measured (vs date_trunc).
            "SELECT date_bin('1 hour', occurred_at, TIMESTAMPTZ '2000-01-01 00:00:00+00') AS hour, category, severity, count(*) AS n FROM events WHERE occurred_at >= $1 AND occurred_at < $2{filter} GROUP BY 1, 2, 3"
        );
        let mut statement = sqlx::query(&sql).bind(q.from).bind(q.to);
        if let Some(category) = &q.category {
            statement = statement.bind(category);
        }
        if let Some(severity) = q.severity {
            statement = statement.bind(severity);
        }
        statement
            .fetch_all(&self.pool)
            .await
            .map_err(|_| Error::Unavailable)?
            .into_iter()
            .map(|row| {
                Ok(Cell {
                    hour: row.try_get("hour").map_err(|_| Error::Corrupt)?,
                    category: row.try_get("category").map_err(|_| Error::Corrupt)?,
                    severity: row.try_get("severity").map_err(|_| Error::Corrupt)?,
                    count: row.try_get("n").map_err(|_| Error::Corrupt)?,
                })
            })
            .collect()
    }

    pub async fn query(&self, q: &EventQuery) -> Result<Vec<Event>> {
        let filter = match q.key {
            QueryKey::Device(_) => "device_id=$1",
            QueryKey::Ip(_) => "source_ip=$1::inet",
            QueryKey::Severity(_) => "category='alert' AND severity=$1",
        };
        let sql = format!(
            "SELECT {COLUMNS} FROM events WHERE {filter} AND occurred_at >= $2 AND occurred_at < $3 AND (occurred_at,event_id) < ($4,$5) ORDER BY occurred_at DESC,event_id DESC LIMIT $6"
        );
        let statement = sqlx::query(&sql);
        let statement = match &q.key {
            QueryKey::Device(v) => statement.bind(v),
            QueryKey::Ip(v) => statement.bind(v.to_string()),
            QueryKey::Severity(v) => statement.bind(v),
        };
        statement
            .bind(q.from)
            .bind(q.to)
            .bind(q.upper.0)
            .bind(q.upper.1)
            .bind((q.page_size + 1) as i64)
            .fetch_all(&self.pool)
            .await
            .map_err(|_| Error::Unavailable)?
            .into_iter()
            .map(decode)
            .collect()
    }
}
