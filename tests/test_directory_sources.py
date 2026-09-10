import asyncio

from ai_pipeline.directory_sources import PublicDirectoryCrawler


def test_directory_parser_preserves_explicit_startup_urls():
    crawler = PublicDirectoryCrawler("Directory", "https://example.com/startups", "startup")
    html = '<a class="company-link" href="/companies/verified">Verified Startup</a><a rel="next" href="/startups?page=2">Next</a>'
    records, next_url = crawler._parse_page(html, crawler.start_url, set())
    assert len(records) == 1
    assert records[0].entityName == "Verified Startup"
    assert str(records[0].source.url) == "https://example.com/companies/verified"
    assert next_url == "https://example.com/startups?page=2"


def test_directory_parser_keeps_unverified_fields_null():
    crawler = PublicDirectoryCrawler("Directory", "https://example.com/products", "product")
    records, _ = crawler._parse_page('<a class="product-link" href="/products/tool">Tool</a>', crawler.start_url, set())
    assert records[0].pricingModel is None


def test_directory_parser_accepts_explicit_structured_fields():
    startup = PublicDirectoryCrawler("Directory", "https://example.com/startups", "startup")
    startup_records, _ = startup._parse_page('<a class="company-link" data-employee-count="42" href="/companies/a">A</a>', startup.start_url, set())
    assert startup_records[0].employeeCount == 42
    product = PublicDirectoryCrawler("Directory", "https://example.com/products", "product")
    product_records, _ = product._parse_page('<a class="product-link" data-pricing-model="FREEMIUM" href="/products/a">A</a>', product.start_url, set())
    assert product_records[0].pricingModel == "FREEMIUM"


def test_directory_parser_accepts_json_ld_records():
    crawler = PublicDirectoryCrawler("Directory", "https://example.com/startups", "startup")
    html = '<script type="application/ld+json">{"@type":"ItemList","itemListElement":[{"item":{"@type":"Organization","name":"Structured Startup","url":"/companies/structured","numberOfEmployees":{"value":12}}}]}</script>'
    records, _ = crawler._parse_page(html, crawler.start_url, set())
    assert records[0].entityName == "Structured Startup"
    assert records[0].employeeCount == 12


def test_directory_parser_accepts_explicit_json_api_records():
    crawler = PublicDirectoryCrawler("API", "https://example.com/api/startups", "startup")
    payload = {"data": [{"name": "API Startup", "url": "https://startup.example", "team_size": 8}], "next": "/api/startups?page=2"}
    records, next_url = crawler._parse_page(__import__("json").dumps(payload), crawler.start_url, set())
    assert records[0].entityName == "API Startup"
    assert records[0].employeeCount == 8
    assert next_url == "https://example.com/api/startups?page=2"