import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SQLiteStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("CREATE TABLE IF NOT EXISTS records (record_type TEXT, source_url TEXT, payload JSON, PRIMARY KEY(record_type, source_url))")
        for table in ("startups", "products", "research_papers", "jobs", "news", "entity_mapping", "crawl_runs"):
            self._migrate_table(table)
            self.connection.execute(f"CREATE TABLE IF NOT EXISTS {table} (record_key TEXT PRIMARY KEY, source_url TEXT, payload JSON)")
        self.connection.commit()

    def _migrate_table(self, table: str) -> None:
        existing = {row[1] for row in self.connection.execute(f"PRAGMA table_info({table})")}
        if existing and "record_key" not in existing:
            legacy = f"{table}_legacy"
            self.connection.execute(f"ALTER TABLE {table} RENAME TO {legacy}")
            self.connection.execute(f"CREATE TABLE {table} (record_key TEXT PRIMARY KEY, source_url TEXT, payload JSON)")
            if {"source_url", "payload"} <= existing:
                self.connection.execute(f"INSERT OR IGNORE INTO {table} (record_key, source_url, payload) SELECT source_url, source_url, payload FROM {legacy}")

    def upsert(self, record_type: str, source_url: str, payload: dict[str, Any]) -> None:
        self.connection.execute("INSERT OR REPLACE INTO records VALUES (?, ?, ?)", (record_type, source_url, json.dumps(payload)))
        self.connection.commit()

    def upsert_record(self, table: str, record_key: str, payload: dict[str, Any], source_url: str | None = None) -> None:
        self._validate_table(table)
        self.connection.execute(f"INSERT OR REPLACE INTO {table} (record_key, source_url, payload) VALUES (?, ?, ?)", (record_key, source_url, json.dumps(payload)))
        self.connection.commit()

    def upsert_records(self, table: str, records: list[tuple[str, dict[str, Any], str | None]]) -> None:
        self._validate_table(table)
        values = [(record_key, source_url, json.dumps(payload)) for record_key, payload, source_url in records]
        self.connection.executemany(f"INSERT OR REPLACE INTO {table} (record_key, source_url, payload) VALUES (?, ?, ?)", values)
        self.connection.commit()

    @staticmethod
    def _validate_table(table: str) -> None:
        allowed = {"startups", "products", "research_papers", "jobs", "news", "entity_mapping", "crawl_runs"}
        if table not in allowed:
            raise ValueError(f"Unsupported table: {table}")

    def record_run(self, counts: dict[str, int], events: list[dict] | None = None) -> None:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.upsert_record("crawl_runs", run_id, {"run_id": run_id, "counts": counts, "source_events": events or [], "completed_at": datetime.now(timezone.utc).isoformat()})

    def close(self) -> None:
        self.connection.close()
