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
        .allow_headers([header::ACCEPT, header::CONTENT_TYPE]);
    let state = Arc::new(AppState {
        repositories: Repositories::new(config.clone()),
        config,
    });
    Router::new()
        .route("/api/health", get(health))
        .route("/api/health/storage", get(storage_health))
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
        }),
    )
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
