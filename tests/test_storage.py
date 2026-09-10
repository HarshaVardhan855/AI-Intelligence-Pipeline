from pathlib import Path
from ai_pipeline.storage import SQLiteStore


def test_storage_creates_logical_tables(tmp_path: Path):
    database = tmp_path / "pipeline.db"
    store = SQLiteStore(database)
    tables = {row[0] for row in store.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"startups", "products", "research_papers", "jobs", "news", "entity_mapping", "crawl_runs"} <= tables
    store.upsert_record("startups", "https://example.com/startup", {"name": "Verified"}, "https://example.com/startup")
    store.upsert_records("products", [("https://example.com/product", {"name": "Product"}, "https://example.com/product")])
    store.record_run({"startups": 1})
    assert store.connection.execute("SELECT COUNT(*) FROM startups").fetchone()[0] == 1
    assert store.connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1
    assert store.connection.execute("SELECT COUNT(*) FROM crawl_runs").fetchone()[0] == 1
    store.close()