mod analytics;
mod api;
mod config;
mod domain;
mod error;
mod storage;

use std::error::Error;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    // dotenvy searches the working directory and its parents; process env wins.
    if let Err(error) = dotenvy::dotenv() {
        if !error.not_found() {
            return Err("Could not load .env; check its format and permissions".into());
        }
    }
    tracing_subscriber::fmt()
        .json()
        .with_env_filter(
            EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "cyberguard_api=info,tower_http=info".into()),
        )
        .init();
    let config = config::Config::from_env().map_err(std::io::Error::other)?;
    let listener = tokio::net::TcpListener::bind(config.bind).await?;
    tracing::info!(address = %config.bind, "api_started");
    axum::serve(listener, api::router(config))
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await?;
    Ok(())
}
