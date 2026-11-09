use crate::config::Config;
pub mod cassandra;
pub mod postgresql;
pub mod repository;
use scylla::client::session_builder::SessionBuilder;
use serde::Serialize;
use sqlx::{Connection, PgConnection};
use std::{
    future::Future,
    time::{Duration, Instant},
};
use tokio::time::timeout;

#[derive(Debug, Serialize)]
pub struct StorageCheck {
    pub status: &'static str,
    pub duration_ms: u128,
    pub error: Option<&'static str>,
}

pub async fn postgres(config: &Config) -> StorageCheck {
    measure("postgresql", config.storage_timeout, async {
        let mut connection = PgConnection::connect_with(&config.postgres)
            .await
            .map_err(|_| "connection_failed")?;
        let value: i32 = sqlx::query_scalar("SELECT 1")
            .fetch_one(&mut connection)
            .await
            .map_err(|_| "query_failed")?;
        if value != 1 {
            return Err("unexpected_response");
        }
        connection
            .close()
            .await
            .map_err(|_| "connection_close_failed")?;
        Ok(())
    })
    .await
}

pub async fn cassandra(config: &Config) -> StorageCheck {
    measure("cassandra", config.storage_timeout, async {
        let session = SessionBuilder::new()
            .known_node(&config.cassandra_contact_point)
            .connection_timeout(config.storage_timeout)
            .build()
            .await
            .map_err(|_| "connection_failed")?;
        let result = session
            .query_unpaged("SELECT cluster_name FROM system.local", &[])
            .await
            .map_err(|_| "query_failed")?;
        let rows = result
            .into_rows_result()
            .map_err(|_| "unexpected_response")?;
        let (name,): (String,) = rows.single_row().map_err(|_| "unexpected_response")?;
        if name.is_empty() {
            return Err("unexpected_response");
        }
        Ok(())
    })
    .await
}

async fn measure(
    database: &'static str,
    limit: Duration,
    operation: impl Future<Output = Result<(), &'static str>>,
) -> StorageCheck {
    let start = Instant::now();
    let error = match timeout(limit, operation).await {
        Ok(Ok(())) => None,
        Ok(Err(code)) => Some(code),
        Err(_) => Some("timeout"),
    };
    let result = StorageCheck {
        status: if error.is_none() { "up" } else { "down" },
        duration_ms: start.elapsed().as_millis(),
        error,
    };
    // Never log driver errors or connection options: they can contain credentials.
    tracing::info!(database, status = result.status, duration_ms = %result.duration_ms, error = result.error, "storage_probe");
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn probe_reports_failure_and_timeout_without_false_success() {
        let failed = measure("test", Duration::from_secs(1), async {
            Err("query_failed")
        })
        .await;
        assert_eq!(failed.status, "down");
        assert_eq!(failed.error, Some("query_failed"));
        let expired = measure("test", Duration::from_millis(1), std::future::pending()).await;
        assert_eq!(expired.status, "down");
        assert_eq!(expired.error, Some("timeout"));
    }
}
