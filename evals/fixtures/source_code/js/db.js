const sqlite3 = require('sqlite3').verbose();

class Database {
    constructor(path) {
        this.db = new sqlite3.Database(path);
        this._init();
    }

    _init() {
        this.db.run(`CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            value TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )`);
    }

    async get(key) {
        return new Promise((resolve, reject) => {
            this.db.get(
                'SELECT * FROM items WHERE key = ?',
                [key],
                (err, row) => err ? reject(err) : resolve(row)
            );
        });
    }

    async set(key, value) {
        return new Promise((resolve, reject) => {
            this.db.run(
                'INSERT OR REPLACE INTO items (key, value) VALUES (?, ?)',
                [key, value],
                function (err) { err ? reject(err) : resolve(this.lastID); }
            );
        });
    }

    async delete(key) {
        return new Promise((resolve, reject) => {
            this.db.run(
                'DELETE FROM items WHERE key = ?',
                [key],
                function (err) { err ? reject(err) : resolve(this.changes); }
            );
        });
    }

    close() {
        this.db.close();
    }
}

module.exports = { Database };
