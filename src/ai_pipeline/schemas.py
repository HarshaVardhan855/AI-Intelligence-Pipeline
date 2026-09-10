from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class Source(BaseModel):
    name: str
    url: HttpUrl
    record_id: str | None = None


class BaseRecord(BaseModel):
    schemaVersion: str = "1.0"
    recordType: str
    source: Source
    collectedAt: datetime
    crawl_timestamp: datetime | None = None
    extraction_timestamp: datetime | None = None
    extraction_provider: str | None = None


class StartupRecord(BaseRecord):
    recordType: Literal["STARTUP"] = "STARTUP"
    entityName: str
    employeeCount: int | None = Field(default=None, ge=0)


class ProductRecord(BaseRecord):
    recordType: Literal["PRODUCT"] = "PRODUCT"
    startupName: str
    pricingModel: Literal["FREE", "FREEMIUM", "PAID", "ENTERPRISE"] | None = None


class ResearchPaperRecord(BaseRecord):
    recordType: Literal["RESEARCH_PAPER"] = "RESEARCH_PAPER"
    title: str
    authors: list[str]
    paper_url: HttpUrl
    published_date: datetime
    github_url: HttpUrl | None = None
    github_stars: int | None = Field(default=None, ge=0)


class JobRecord(BaseRecord):
    recordType: Literal["JOB"] = "JOB"
    company: str
    date: datetime
    is_remote: bool | None = None
    role_family: str | None = None


class NewsRecord(BaseRecord):
    recordType: Literal["NEWS"] = "NEWS"
    title: str
    publication_timestamp: datetime
    content: str
    fields: dict[str, Any] = Field(default_factory=dict)


class EntityMapping(BaseModel):
    raw_name: str
    canonical_name: str | None
    resolution_method: Literal["exact", "alias", "fuzzy", "unresolved"]
    confidence: float = Field(ge=0, le=1)
