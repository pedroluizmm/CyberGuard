#[derive(Debug)]
pub enum Error {
    Invalid(&'static str),
    NotFound,
    Conflict,
    Pending,
    Unavailable,
    Corrupt,
    ScanLimit,
    Timeout,
}

pub type Result<T> = std::result::Result<T, Error>;
