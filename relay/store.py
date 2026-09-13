"""SQLite journal and simulator storage. One connection per transaction."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS documents (
                    kind TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS records (key TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, plan_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (
                    key TEXT PRIMARY KEY, payload TEXT NOT NULL, run_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL, data TEXT NOT NULL);
            """)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def save(self, kind, identity, data):
        with self.transaction() as db:
            db.execute("INSERT OR REPLACE INTO documents VALUES(?,?,?)", (kind, identity, json.dumps(data)))

    def get(self, kind, identity):
        with self.transaction() as db:
            row = db.execute("SELECT data FROM documents WHERE kind=? AND id=?", (kind, identity)).fetchone()
        if row is None:
            raise KeyError(identity)
        return json.loads(row["data"])

    def put_record(self, record):
        with self.transaction() as db:
            db.execute("INSERT OR REPLACE INTO records VALUES(?,?)", (record["key"], json.dumps(record)))

    def records(self):
        with self.transaction() as db:
            rows = db.execute("SELECT key,data FROM records ORDER BY key").fetchall()
        return {row["key"]: json.loads(row["data"]) for row in rows}

    def get_run(self, identity):
        with self.transaction() as db:
            row = db.execute("SELECT data FROM runs WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise KeyError(identity)
        return json.loads(row["data"])

    def save_run(self, run):
        with self.transaction() as db:
            db.execute("UPDATE runs SET status=?,data=? WHERE id=?", (run["status"], json.dumps(run), run["id"]))

    def runs(self):
        with self.transaction() as db:
            rows = db.execute("SELECT data FROM runs ORDER BY rowid DESC LIMIT 30").fetchall()
        return [json.loads(row["data"]) for row in rows]

    def attempt(self, run_id, operation_id, evidence):
        with self.transaction() as db:
            db.execute("INSERT INTO attempts(run_id,operation_id,data) VALUES(?,?,?)",
                       (run_id, operation_id, json.dumps(evidence)))
