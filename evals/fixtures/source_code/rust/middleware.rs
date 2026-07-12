use std::fmt;

/// Log level.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Level {
    Debug,
    Info,
    Warn,
    Error,
}

impl fmt::Display for Level {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Level::Debug => write!(f, "DEBUG"),
            Level::Info => write!(f, "INFO"),
            Level::Warn => write!(f, "WARN"),
            Level::Error => write!(f, "ERROR"),
        }
    }
}

/// Middleware pipeline for request processing.
pub struct Pipeline {
    middlewares: Vec<Box<dyn Middleware>>,
}

pub trait Middleware: Send + Sync {
    fn process(&self, request: &mut Request) -> Result<(), String>;
}

pub struct Request {
    pub path: String,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

impl Pipeline {
    pub fn new() -> Self {
        Pipeline {
            middlewares: Vec::new(),
        }
    }

    pub fn add<M: Middleware + 'static>(&mut self, mw: M) {
        self.middlewares.push(Box::new(mw));
    }

    pub fn execute(&self, request: &mut Request) -> Result<(), String> {
        for mw in &self.middlewares {
            mw.process(request)?;
        }
        Ok(())
    }
}

pub struct LoggingMiddleware {
    pub level: Level,
}

impl Middleware for LoggingMiddleware {
    fn process(&self, request: &mut Request) -> Result<(), String> {
        println!("[{}] {}", self.level, request.path);
        Ok(())
    }
}

pub struct AuthMiddleware {
    pub required_header: String,
}

impl Middleware for AuthMiddleware {
    fn process(&self, request: &mut Request) -> Result<(), String> {
        let found = request.headers.iter().any(|(k, _)| k == &self.required_header);
        if !found {
            return Err(format!("Missing header: {}", self.required_header));
        }
        Ok(())
    }
}
