use super::AppState;
use crate::{
    analytics::{EventPage, EventQuery, Overview, OverviewParams, OverviewQuery, QueryParams},
    domain::{self, Event, EventData, UpdateEvent},
    error::{Error, Result},
    storage::repository::Source,
};
use axum::{
    Json,
    extract::{
        Path, Query, State,
        rejection::{JsonRejection, QueryRejection},
    },
    http::{HeaderName, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
};
use serde::Deserialize;
use serde_json::json;
use std::{
    future::Future,
    sync::Arc,
    time::{Duration, Instant},
};

impl IntoResponse for Error {
    fn into_response(self) -> Response {
        let (status, code, message) = match self {
            Self::Invalid(message) => (StatusCode::BAD_REQUEST, "invalid_request", message),
            Self::NotFound => (
                StatusCode::NOT_FOUND,
                "not_found",
                "Event does not exist or has been deleted",
            ),
            Self::Conflict => (
                StatusCode::CONFLICT,
                "conflict",
                "ID already reserved, content differs or revision is stale",
            ),
            Self::Pending => (
                StatusCode::SERVICE_UNAVAILABLE,
                "operation_pending",
                "A durable operation is incomplete; retry it or repair this event ID",
            ),
            Self::Unavailable => (
                StatusCode::SERVICE_UNAVAILABLE,
                "storage_unavailable",
                "Storage unavailable. If this was a write, it may have completed: read the ID before retrying",
            ),
            Self::Corrupt => (
                StatusCode::SERVICE_UNAVAILABLE,
                "storage_inconsistent",
                "Stored event does not match the canonical contract",
            ),
            Self::ScanLimit => (
                StatusCode::SERVICE_UNAVAILABLE,
                "scan_limit",
                "Too many stale projections; repair before continuing this query",
            ),
            Self::Timeout => (
                StatusCode::SERVICE_UNAVAILABLE,
                "operation_timeout",
                "Operation exceeded 30 seconds; a write may have completed. Read or repair the ID",
            ),
        };
        tracing::warn!(status = status.as_u16(), code, "event_request_failed");
        (
            status,
            Json(json!({"error":{"code":code,"message":message}})),
        )
            .into_response()
    }
}

async fn bounded<T>(operation: impl Future<Output = Result<T>>) -> Result<T> {
    tokio::time::timeout(Duration::from_secs(30), operation)
        .await
        .map_err(|_| Error::Timeout)?
}

pub type Timing = [(HeaderName, HeaderValue); 1];

/// `Server-Timing: db;dur=<ms>`: monotonic time spent in the storage adapter
/// (driver, network to the container, database work and row decoding). HTTP,
/// JSON serialization and client time are excluded and measured by the client.
async fn timed<T>(operation: impl Future<Output = Result<T>>) -> Result<(Timing, T)> {
    let start = Instant::now();
    let value = bounded(operation).await?;
    let millis = start.elapsed().as_secs_f64() * 1000.0;
    let header = HeaderValue::from_str(&format!("db;dur={millis:.3}"))
        .unwrap_or_else(|_| HeaderValue::from_static("db"));
    Ok(([(HeaderName::from_static("server-timing"), header)], value))
}

pub async fn create(
    State(state): State<Arc<AppState>>,
    Path(source): Path<String>,
    body: std::result::Result<Json<EventData>, JsonRejection>,
) -> Result<(StatusCode, Json<Event>)> {
    let source = Source::parse(&source)?;
    let data = body
        .map_err(|_| Error::Invalid("invalid JSON event body or unknown fields"))?
        .0
        .validated()?;
    let (event, created) = bounded(
        state
            .repositories
            .create(source, Event { data, revision: 1 }),
    )
    .await?;
    Ok((
        if created {
            StatusCode::CREATED
        } else {
            StatusCode::OK
        },
        Json(event),
    ))
}

pub async fn get(
    State(state): State<Arc<AppState>>,
    Path((source, id)): Path<(String, String)>,
) -> Result<(Timing, Json<Event>)> {
    let (source, id) = (Source::parse(&source)?, domain::parse_id(&id)?);
    let (timing, event) = timed(state.repositories.get(source, id)).await?;
    Ok((timing, Json(event)))
}

pub async fn update(
    State(state): State<Arc<AppState>>,
    Path((source, id)): Path<(String, String)>,
    body: std::result::Result<Json<UpdateEvent>, JsonRejection>,
) -> Result<Json<Event>> {
    let source = Source::parse(&source)?;
    let id = domain::parse_id(&id)?;
    let body = body
        .map_err(|_| {
            Error::Invalid("PUT accepts only expected_revision, outcome, message and metadata")
        })?
        .0;
    body.validate()?;
    Ok(Json(
        bounded(state.repositories.update(source, id, &body)).await?,
    ))
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DeleteParams {
    expected_revision: i64,
}

pub async fn delete(
    State(state): State<Arc<AppState>>,
    Path((source, id)): Path<(String, String)>,
    params: std::result::Result<Query<DeleteParams>, QueryRejection>,
) -> Result<StatusCode> {
    let source = Source::parse(&source)?;
    let id = domain::parse_id(&id)?;
    let params = params
        .map_err(|_| Error::Invalid("DELETE requires expected_revision"))?
        .0;
    domain::validate_revision(params.expected_revision)?;
    bounded(
        state
            .repositories
            .delete(source, id, params.expected_revision),
    )
    .await?;
    Ok(StatusCode::NO_CONTENT)
}

pub async fn query(
    State(state): State<Arc<AppState>>,
    Path((source, kind)): Path<(String, String)>,
    params: std::result::Result<Query<QueryParams>, QueryRejection>,
) -> Result<(Timing, Json<EventPage>)> {
    let source = Source::parse(&source)?;
    let params = params
        .map_err(|_| Error::Invalid("invalid query parameters"))?
        .0;
    let query = EventQuery::parse(&kind, params)?;
    let (timing, events) = timed(state.repositories.query(source, &query)).await?;
    Ok((timing, Json(query.page(events)?)))
}

pub async fn overview(
    State(state): State<Arc<AppState>>,
    Path(source): Path<String>,
    params: std::result::Result<Query<OverviewParams>, QueryRejection>,
) -> Result<(Timing, Json<Overview>)> {
    let source = Source::parse(&source)?;
    let params = params
        .map_err(|_| Error::Invalid("overview accepts from, to, category and severity"))?
        .0;
    let query = OverviewQuery::parse(params)?;
    let (timing, cells) = timed(state.repositories.overview(source, &query)).await?;
    Ok((timing, Json(query.build(cells)?)))
}

pub async fn repair(
    State(state): State<Arc<AppState>>,
    Path((source, id)): Path<(String, String)>,
) -> Result<Json<serde_json::Value>> {
    let status = bounded(
        state
            .repositories
            .repair(Source::parse(&source)?, domain::parse_id(&id)?),
    )
    .await?;
    Ok(Json(json!({"state":status})))
}
