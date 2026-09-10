from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer


def build(path: str = "architecture.pdf") -> None:
    styles = getSampleStyleSheet()
    story = []
    pages = [
        ("System architecture and data flow", "Sources are accessed through official feeds/APIs, public HTML, or supplied verified CSVs. AsyncFetcher applies bounded concurrency, connection timeouts, retries, and structured logs. Raw content is cleaned, dates are normalized to UTC, and records retain source.name, source.url, collectedAt, and optional source IDs. Pydantic schemas validate the canonical output."),
        ("Scalability and correctness controls", "The crawler is restartable at page boundaries and a failed URL does not stop the run. HTTP 429 responses honor Retry-After or use exponential backoff with jitter and a finite retry limit. Content is reduced to meaningful text and paragraph-chunked before LLM use, preventing oversized 413 requests. News/jobs are accepted only when a reliable publication date is within the inclusive previous 24-hour window. Stable URLs are the deduplication keys."),
        ("Storage, resolution, and operations", "The trial includes a lightweight SQLite store and JSON/CSV exports suitable for Sheets import. Entity resolution uses normalized exact matches, explicit aliases, then conservative fuzzy matching; unresolved names remain unresolved and are logged. CAPTCHA, Cloudflare, authentication, and other access controls are not bypassed: blocked sources are deferred or replaced. Production scale can add queues, workers, object storage, Postgres, graph/vector search, and monitoring without changing crawler contracts."),
    ]
    for index, (heading, body) in enumerate(pages):
        story.extend([Paragraph(heading, styles["Title"]), Spacer(1, 18), Paragraph(body, styles["BodyText"])])
        if index < len(pages) - 1:
            story.append(PageBreak())
    SimpleDocTemplate(path, pagesize=letter, rightMargin=54, leftMargin=54, topMargin=54, bottomMargin=54).build(story)


if __name__ == "__main__":
    build()
