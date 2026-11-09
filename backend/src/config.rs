use axum::http::HeaderValue;
use sqlx::postgres::{PgConnectOptions, PgSslMode};
use std::{env, net::SocketAddr, time::Duration};

// Deliberately no Debug: configuration contains credentials.
#[derive(Clone)]
pub struct Config {
    pub bind: SocketAddr,
    pub frontend_origin: HeaderValue,
    pub postgres: PgConnectOptions,
    pub cassandra_contact_point: String,
    pub storage_timeout: Duration,
}

impl Config {
    pub fn from_env() -> Result<Self, String> {
        let bind: SocketAddr = value("API_BIND", "127.0.0.1:3000")
            .parse()
            .map_err(|_| "API_BIND must be an IP:port")?;
        let origin = value("FRONTEND_ORIGIN", "http://localhost:5173");
        validate_origin(&origin)?;
        let frontend_origin = origin.parse().map_err(|_| "Invalid FRONTEND_ORIGIN")?;
        let timeout_ms: u64 = value("STORAGE_TIMEOUT_MS", "5000")
            .parse()
            .map_err(|_| "STORAGE_TIMEOUT_MS must be an integer")?;
        if !(100..=10000).contains(&timeout_ms) {
            return Err("STORAGE_TIMEOUT_MS must be between 100 and 10000".into());
        }
        let password = env::var("POSTGRES_PASSWORD")
            .map_err(|_| "POSTGRES_PASSWORD is required; run scripts/setup_env.py")?;
        if password.is_empty() || password == "replace_with_generated_local_password" {
            return Err("Generate a local POSTGRES_PASSWORD before starting".into());
        }
        let port: u16 = value("POSTGRES_PORT", "5432")
            .parse()
            .map_err(|_| "Invalid POSTGRES_PORT")?;
        let postgres = PgConnectOptions::new()
            .host(&value("POSTGRES_HOST", "127.0.0.1"))
            .port(port)
            .username(&value("POSTGRES_USER", "cyberguard"))
            .password(&password)
            .database(&value("POSTGRES_DB", "cyberguard"))
            .ssl_mode(PgSslMode::Disable);
        Ok(Self {
            bind,
            frontend_origin,
            postgres,
            cassandra_contact_point: value("CASSANDRA_CONTACT_POINT", "127.0.0.1:9042"),
            storage_timeout: Duration::from_millis(timeout_ms),
        })
    }
}

fn value(key: &str, fallback: &str) -> String {
    env::var(key).unwrap_or_else(|_| fallback.to_owned())
}

fn validate_origin(origin: &str) -> Result<(), String> {
    let uri: axum::http::Uri = origin.parse().map_err(|_| "Invalid FRONTEND_ORIGIN")?;
    if uri.scheme_str() != Some("http")
        || !matches!(uri.host(), Some("localhost" | "127.0.0.1"))
        || uri.port_u16().is_none()
        || uri.path() != "/"
        || uri.query().is_some()
        || origin.contains('@')
        || origin.ends_with('/')
    {
        return Err("FRONTEND_ORIGIN must be http://localhost:PORT or http://127.0.0.1:PORT, without trailing slash".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::validate_origin;

    #[test]
    fn cors_only_accepts_explicit_local_origins() {
        for origin in ["http://localhost:5173", "http://127.0.0.1:5173"] {
            assert!(validate_origin(origin).is_ok());
        }
        for origin in [
            "*",
            "https://example.com",
            "http://localhost:5173/path",
            "http://localhost:5173/",
            "http://user@localhost:5173",
        ] {
            assert!(validate_origin(origin).is_err());
        }
    }
}
