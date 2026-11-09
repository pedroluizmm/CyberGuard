use crate::{
    analytics::EventQuery,
    config::Config,
    domain::{Event, UpdateEvent},
    error::{Error, Result},
    storage::{cassandra::CassandraStore, postgresql::PostgresStore},
};
use sqlx::postgres::PgPoolOptions;
use tokio::sync::{Mutex, MutexGuard, OnceCell};
use uuid::Uuid;

#[derive(Clone, Copy)]
pub enum Source {
    Postgresql,
    Cassandra,
}

impl Source {
    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "postgresql" => Ok(Self::Postgresql),
            "cassandra" => Ok(Self::Cassandra),
            _ => Err(Error::Invalid("source must be postgresql or cassandra")),
        }
    }
}

pub struct Repositories {
    postgres: PostgresStore,
    cassandra: OnceCell<CassandraStore>,
    config: Config,
    locks: Vec<Mutex<()>>,
}

impl Repositories {
    pub fn new(config: Config) -> Self {
        let options = config
            .postgres
            .clone()
            .options([("statement_timeout", "15000"), ("lock_timeout", "5000")]);
        let pool = PgPoolOptions::new()
            .max_connections(5)
            .acquire_timeout(config.storage_timeout)
            .connect_lazy_with(options);
        Self {
            postgres: PostgresStore { pool },
            cassandra: OnceCell::new(),
            config,
            locks: (0..128).map(|_| Mutex::new(())).collect(),
        }
    }

    async fn cql(&self) -> Result<&CassandraStore> {
        self.cassandra
            .get_or_try_init(|| CassandraStore::connect(&self.config))
            .await
    }

    // Fixed-size striping avoids unbounded per-ID lock allocation. It supplements,
    // but never replaces, SQL transactions and Cassandra conditional writes.
    pub async fn lock(&self, source: Source, id: Uuid) -> MutexGuard<'_, ()> {
        let offset = match source {
            Source::Postgresql => 0,
            Source::Cassandra => 64,
        };
        self.locks[offset + (id.as_u128() % 64) as usize]
            .lock()
            .await
    }

    pub async fn get(&self, source: Source, id: Uuid) -> Result<Event> {
        match source {
            Source::Postgresql => self.postgres.get(id).await,
            Source::Cassandra => self.cql().await?.get(id).await,
        }
    }
    pub async fn create(&self, source: Source, event: Event) -> Result<(Event, bool)> {
        let _guard = self.lock(source, event.data.id()?).await;
        match source {
            Source::Postgresql => self.postgres.create(event).await,
            Source::Cassandra => self.cql().await?.create(event).await,
        }
    }
    pub async fn update(&self, source: Source, id: Uuid, update: &UpdateEvent) -> Result<Event> {
        let _guard = self.lock(source, id).await;
        match source {
            Source::Postgresql => self.postgres.update(id, update).await,
            Source::Cassandra => self.cql().await?.update(id, update).await,
        }
    }
    pub async fn delete(&self, source: Source, id: Uuid, revision: i64) -> Result<()> {
        let _guard = self.lock(source, id).await;
        match source {
            Source::Postgresql => self.postgres.delete(id, revision).await,
            Source::Cassandra => self.cql().await?.delete(id, revision).await,
        }
    }
    pub async fn query(&self, source: Source, q: &EventQuery) -> Result<Vec<Event>> {
        match source {
            Source::Postgresql => self.postgres.query(q).await,
            Source::Cassandra => self.cql().await?.query(q).await,
        }
    }
    pub async fn repair(&self, source: Source, id: Uuid) -> Result<&'static str> {
        let _guard = self.lock(source, id).await;
        match source {
            Source::Postgresql => self.postgres.repair(id).await,
            Source::Cassandra => self.cql().await?.repair(id).await,
        }
    }
}
