# AI Intelligence Pipeline

A small, provenance-first implementation of the GraphOne / FrontierAtlas demo task: messy public data is collected, cleaned, validated, resolved, and exported without inventing unavailable facts.

## Scope and honest status

The runnable trial currently includes an asynchronous arXiv crawler, optional GitHub verification hook boundary, verified CSV ingestion for startups/products, five news feeds, five job feeds, UTC freshness checks, safe HTML cleaning, bounded retries, semantic chunking, typed schemas, deterministic entity resolution, SQLite storage, and JSON/CSV export. Feed failures are isolated and logged; blocked or invalid feeds produce no records. It does **not** claim that 1,000 startups/products or fresh jobs exist locally until genuine source inputs are supplied and a live run produces them. The default paper command is intentionally small; use `--paper-limit 1000` for the requested acquisition target.

## Setup

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Set API keys and runtime settings only in `.env`; it is ignored by Git. Model names are configurable with `GEMINI_MODEL`, `GROQ_MODEL`, and `DEEPSEEK_MODEL`; provider order is Gemini, Groq, DeepSeek. `HTTP_CONCURRENCY` (default: 20) and `REQUEST_TIMEOUT_SECONDS` (default: 30) control bounded crawler throughput and timeouts for every HTTP source. HTTPS clients use the operating system trust store while retaining certificate validation. The orchestrator sends source text only, requests JSON, chunks content at `LLM_MAX_CHARS`, retries bounded 429/5xx responses, and falls back to the next configured provider. With no API key, extraction fails clearly rather than fabricating fields.

## Run

```powershell
$env:PYTHONPATH = "src"
python -m ai_pipeline --paper-limit 10 --output data/output
python -m ai_pipeline --paper-limit 10 --github --output data/output
python architecture.py
```

Add `--validate-targets` to fail the run unless at least 1,000 startups, 1,000 products, and 1,000 research papers pass provenance, uniqueness, and required-field checks. The CLI preflights startup/product counts before expensive paper/GitHub work, reports missing targets as one concise error, and exits with status 2 without a traceback. This is an acceptance check, not a record generator.

The CLI fetches the configured news and job feeds on every run and writes `news.json`/`news.csv` and `jobs.json`/`jobs.csv`. Only records with a reliable publication date within the previous 24 hours are exported. Use `--paper-limit 0` to exercise feeds without collecting papers.

Add `--extract-news` to run the LLM extraction stage on fresh news content. It requires at least one provider API key in `.env`; without one, the command exits clearly rather than inventing extracted fields. The original cleaned article text remains in the exported record, and `extraction_provider` records the provider that actually succeeded after fallback.

For startups/products, pass CSVs with `name,source_url,source_name,source_record_id` and either `employee_count` or `pricing_model`. Before crawling feeds, CSVs are validated for HTTP(S) provenance URLs, duplicate URLs, numeric employee counts, and the allowed pricing values. Invalid input exits clearly with status 2; it is not silently converted into fabricated data.

The CSV files are user/source inputs and are not generated automatically. If a referenced file does not exist, the CLI exits with a concise instruction to create it first.

Alternatively, pass a legitimate public paginated directory with explicit record links: `--startup-source https://source.example/startups` or `--product-source https://source.example/products`. The YC Startup Directory is supported through Playwright because its company list is JavaScript-rendered: `--startup-source https://www.ycombinator.com/companies`. If it yields no records, the crawler falls back to the public YC company index and retains each company’s official YC URL and structured team size. Product Hunt first uses its GraphQL API when `PRODUCT_HUNT_TOKEN` is configured, then falls back to its public `/products?page=N` directory; without a token it uses that public directory directly. When Product Hunt does not meet the requested limit, the pipeline adds explicit AI software repositories from GitHub’s official search API; each record retains its GitHub URL and leaves pricing null. The Product Hunt fallback runs in bounded concurrent batches, deduplicates canonical `/products/<slug>` URLs, stops at the requested limit, and is bounded by `PRODUCT_HUNT_MAX_PAGES` (default: 30) and `PRODUCT_HUNT_PAGE_CONCURRENCY` (default: 5). It accepts only anchors that contain both an explicit product URL and visible product name; an empty or blocked listing returns no products, so `--validate-targets` fails honestly. The adapters accept JSON-LD `ItemList`/`Organization`/`Product` records and JSON APIs with explicit `name` and `url` fields. They accept employee counts and pricing only when explicitly structured and valid; otherwise fields remain null.

## Architecture and data flow

`official/API/feed or verified CSV -> AsyncFetcher -> clean HTML/XML -> layered UTC date validation -> chunked LLM extraction -> Pydantic validation -> deterministic entity resolution -> SQLite/JSON/CSV`

See [architecture.pdf](architecture.pdf) for the three-page technical design. The `data/seed_entities.json` file is a small canonical mapping seed, not a fabricated company dataset.

## Freshness and provenance

`parse_date` handles ISO dates, timezone offsets, Unix timestamps, common relative phrases, and `Yesterday`. Undated records are rejected. A record is fresh only when its parsed UTC age is between 0 and 24 hours inclusive. Production HTML extraction should inspect JSON-LD, meta/OpenGraph fields, visible dates, then a source-specific parser; the RSS adapters use feed publication fields conservatively.

All schemas require `source.name`, `source.url`, and `collectedAt`. Optional crawl and extraction timestamps/provider fields are available. With `--github`, research paper pages are scanned only for explicit GitHub links, and each candidate is verified through the GitHub API before `github_url` and `github_stars` are populated. Missing or unverified repositories remain null; they are never inferred by an LLM.

## Reliability

Requests use a semaphore, pooled `aiohttp` sessions, timeouts, finite retries, exponential backoff, jitter, and `Retry-After` for HTTP 429. ArXiv pages are checkpointed to `CHECKPOINT_FILE` after each completed page and resume after interruption. Clean text is split on paragraph boundaries with overlap before LLM submission, avoiding repeated 413 failures. Protected sources are not bypassed; blocked pages should be logged and deferred to an official API/feed or a later run.

## Entity resolution and deduplication

Names are normalized for case, punctuation, whitespace, and corporate suffixes. Resolution order is exact normalized name, explicit alias, conservative fuzzy score, then unresolved. The mapping retains raw name, canonical name, method, and confidence. URL/source IDs are stable deduplication keys; arXiv IDs and DOI can be added as source IDs.

## Storage and export

`SQLiteStore` provides a local restart-friendly store for the trial. Every CLI run writes the logical tables plus a `crawl_runs` summary containing counts and structured blocked/failed source events in `pipeline.db`. `export_records` writes one JSON and one CSV per record group, and every CLI run also writes `ai_intelligence_pipeline.xlsx` with the six tabs `Startups`, `Products`, `Research Papers`, `Jobs`, `News`, and `Entity Mapping Log`; the workbook is ready for manual Google Sheets import and is never published automatically. A production deployment can swap in PostgreSQL/Supabase without changing record schemas.

Each run also writes `run_report.json`. Its `status` is `complete` only when startups, products, and research papers each contain at least 1,000 records; otherwise it reports `incomplete_targets` without pretending the acquisition succeeded.

## Testing

```powershell
python -m pytest -q
```

Tests cover relative/UTC dates, the inclusive freshness rule, paragraph chunking, normalization, exact/alias resolution, and unresolved-name preservation. Live source counts depend on network availability, source freshness, quotas, and the supplied verified startup/product files; they must be reported from the generated output rather than claimed in advance.
