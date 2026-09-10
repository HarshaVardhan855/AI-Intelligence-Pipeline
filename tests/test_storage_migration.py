import sqlite3
from pathlib import Path

from ai_pipeline.storage import SQLiteStore


def test_old_logical_table_schema_is_migrated(tmp_path: Path):
    database = tmp_path / "old.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE startups (source_url TEXT PRIMARY KEY, payload JSON)")
    connection.execute("INSERT INTO startups VALUES (?, ?)", ("https://example.com/old", "{}"))
    connection.commit()
    connection.close()
    store = SQLiteStore(database)
    columns = {row[1] for row in store.connection.execute("PRAGMA table_info(startups)")}
    assert "record_key" in columns
    assert store.connection.execute("SELECT COUNT(*) FROM startups").fetchone()[0] == 1
    store.close()