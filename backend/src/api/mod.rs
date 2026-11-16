use crate::{
    config::Config,
    storage::{self, StorageCheck},
};
mod events;
use crate::storage::repository::Repositories;
use axum::{
    Json, Router,
    extract::State,
    http::{HeaderValue, Method, StatusCode, header},
    response::{IntoResponse, Response},
    routing::get,
};
use serde::Serialize;
use std::sync::Arc;
use tower_http::{cors::CorsLayer, trace::TraceLayer};

pub struct AppState {
    config: Config,
    repositories: Repositories,
}

#[derive(Serialize)]
pub struct Health {
    status: &'static str,
    service: &'static str,
    version: &'static str,
    /// Compilation profile; benchmarks must record it (debug is not comparable).
    build: &'static str,
}

const BUILD: &str = if cfg!(debug_assertions) {
    "debug"
} else {
    "release"
};

#[derive(Serialize)]
struct Runtime {
    build: &'static str,
    cassandra_read_concurrency: usize,
    postgres_synchronous_commit: &'static str,
    postgres_pool_size: u32,
}

#[derive(Serialize)]
struct StorageHealth {
    status: &'static str,
    cassandra: StorageCheck,
    postgresql: StorageCheck,
}

pub fn router(config: Config) -> Router {
    let cors = CorsLayer::new()
        .allow_origin(config.frontend_origin.clone())
        .allow_methods([Method::GET, Method::POST, Method::PUT, Method::DELETE])
        .allow_headers([header::ACCEPT, header::CONTENT_TYPE])
        .expose_headers([header::HeaderName::from_static("server-timing")]);
    let state = Arc::new(AppState {
        repositories: Repositories::new(config.clone()),
        config,
    });
    Router::new()
        .route("/api/health", get(health))
        .route("/api/health/storage", get(storage_health))
        .route("/api/runtime", get(runtime))
        .route("/api/benchmarks/summary", get(benchmark_summary))
        .route("/api/{source}/stats/overview", get(events::overview))
        .route("/api/{source}/events", axum::routing::post(events::create))
        .route(
            "/api/{source}/events/{id}",
            get(events::get).put(events::update).delete(events::delete),
        )
        .route(
            "/api/{source}/events/{id}/repair",
            axum::routing::post(events::repair),
        )
        .route("/api/{source}/queries/{kind}", get(events::query))
        .layer(axum::extract::DefaultBodyLimit::max(16 * 1024))
        .layer(axum::middleware::map_response(
            |mut response: axum::response::Response| async {
                response
                    .headers_mut()
                    .insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
                response
            },
        ))
        .layer(cors)
        .layer(TraceLayer::new_for_http())
        .with_state(state)
}

async fn health() -> ([(header::HeaderName, HeaderValue); 1], Json<Health>) {
    (
        no_cache(),
        Json(Health {
            status: "ok",
            service: "cyberguard-api",
            version: env!("CARGO_PKG_VERSION"),
            build: BUILD,
        }),
    )
}

async fn runtime(State(state): State<Arc<AppState>>) -> Json<Runtime> {
    Json(Runtime {
        build: BUILD,
        cassandra_read_concurrency: state.config.cassandra_read_concurrency,
        postgres_synchronous_commit: state.config.postgres_synchronous_commit,
        postgres_pool_size: state.config.postgres_pool_size,
    })
}

/// Serves the summary written by `benchmarks/run_benchmarks.py`. The file holds
/// measured results only; absence is reported as 404, never replaced by mocks.
async fn benchmark_summary(State(state): State<Arc<AppState>>) -> Response {
    let configured = &state.config.benchmark_summary;
    let mut candidates = vec![configured.clone()];
    if configured.is_relative() {
        // `cargo run` from backend/ resolves the repository root as the parent.
        candidates.push(std::path::Path::new("..").join(configured));
    }
    for path in candidates {
        match tokio::fs::read(&path).await {
            Ok(bytes) if bytes.len() <= 8 * 1024 * 1024 => {
                return match serde_json::from_slice::<serde_json::Value>(&bytes) {
                    Ok(value) => Json(value).into_response(),
                    Err(_) => error(StatusCode::SERVICE_UNAVAILABLE, "benchmark_summary_invalid"),
                };
            }
            Ok(_) => {
                return error(
                    StatusCode::SERVICE_UNAVAILABLE,
                    "benchmark_summary_too_large",
                );
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => continue,
            Err(_) => {
                return error(
                    StatusCode::SERVICE_UNAVAILABLE,
                    "benchmark_summary_unreadable",
                );
            }
        }
    }
    error(StatusCode::NOT_FOUND, "benchmark_summary_missing")
}

fn error(status: StatusCode, code: &'static str) -> Response {
    (
        status,
        Json(serde_json::json!({"error": {"code": code, "message": "Run benchmarks/run_benchmarks.py to produce measured results"}})),
    )
        .into_response()
}

async fn storage_health(
    State(state): State<Arc<AppState>>,
) -> (
    StatusCode,
    [(header::HeaderName, HeaderValue); 1],
    Json<StorageHealth>,
) {
    let (cassandra, postgresql) = tokio::join!(
        storage::cassandra(&state.config),
        storage::postgres(&state.config)
    );
    let ready = cassandra.status == "up" && postgresql.status == "up";
    (
        if ready {
            StatusCode::OK
        } else {
            StatusCode::SERVICE_UNAVAILABLE
        },
        no_cache(),
        Json(StorageHealth {
            status: if ready { "ok" } else { "degraded" },
            cassandra,
            postgresql,
        }),
    )
}

fn no_cache() -> [(header::HeaderName, HeaderValue); 1] {
    [(header::CACHE_CONTROL, HeaderValue::from_static("no-store"))]
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{
        body::{Body, to_bytes},
        http::Request,
    };
    use tower::ServiceExt;

    #[tokio::test]
    async fn liveness_does_not_require_storage() {
        let app = Router::new().route("/api/health", get(health));
        let response = app
            .oneshot(
                Request::builder()
                    .uri("/api/health")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(response.headers()[header::CACHE_CONTROL], "no-store");
        let bytes = to_bytes(response.into_body(), 1024).await.unwrap();
        let body: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(body["status"], "ok");
        assert_eq!(body["service"], "cyberguard-api");
    }
}
