use std::time::Duration;
use std::thread;

/// Retry configuration.
pub struct RetryConfig {
    pub max_attempts: u32,
    pub initial_delay: Duration,
    pub max_delay: Duration,
    pub backoff_multiplier: f64,
}

impl Default for RetryConfig {
    fn default() -> Self {
        RetryConfig {
            max_attempts: 3,
            initial_delay: Duration::from_millis(100),
            max_delay: Duration::from_secs(10),
            backoff_multiplier: 2.0,
        }
    }
}

/// Execute a fallible operation with retries.
pub fn retry<F, T, E>(config: &RetryConfig, mut f: F) -> Result<T, E>
where
    F: FnMut() -> Result<T, E>,
{
    let mut delay = config.initial_delay;

    for attempt in 0..config.max_attempts {
        match f() {
            Ok(value) => return Ok(value),
            Err(e) => {
                if attempt == config.max_attempts - 1 {
                    return Err(e);
                }
                thread::sleep(delay);
                delay = Duration::from_secs_f64(
                    delay.as_secs_f64() * config.backoff_multiplier
                );
                if delay > config.max_delay {
                    delay = config.max_delay;
                }
            }
        }
    }

    unreachable!()
}
