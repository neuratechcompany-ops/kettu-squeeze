//! Simple key-value store
use std::collections::HashMap;
use std::sync::{Arc, RwLock};

/// A thread-safe key-value store.
pub struct KvStore {
    data: Arc<RwLock<HashMap<String, String>>>,
}

impl KvStore {
    /// Create a new empty store.
    pub fn new() -> Self {
        KvStore {
            data: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    /// Insert a key-value pair.
    pub fn insert(&self, key: String, value: String) -> Option<String> {
        self.data.write().unwrap().insert(key, value)
    }

    /// Get a value by key.
    pub fn get(&self, key: &str) -> Option<String> {
        self.data.read().unwrap().get(key).cloned()
    }

    /// Remove a key.
    pub fn remove(&self, key: &str) -> Option<String> {
        self.data.write().unwrap().remove(key)
    }

    /// Number of entries.
    pub fn len(&self) -> usize {
        self.data.read().unwrap().len()
    }
}

impl Default for KvStore {
    fn default() -> Self {
        KvStore::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_insert_get() {
        let store = KvStore::new();
        store.insert("hello".into(), "world".into());
        assert_eq!(store.get("hello"), Some("world".into()));
    }

    #[test]
    fn test_remove() {
        let store = KvStore::new();
        store.insert("key".into(), "val".into());
        store.remove("key");
        assert_eq!(store.get("key"), None);
    }
}
