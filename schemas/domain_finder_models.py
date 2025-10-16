from pydantic import BaseModel, HttpUrl, Field
from typing import Optional, List

class SearchResult(BaseModel):
    title: Optional[str] = None
    url: HttpUrl
    snippet: Optional[str] = None
    source: Optional[str] = None   # e.g., "bing" | "serpapi" | "dummy"

class DomainCandidate(BaseModel):
    url: HttpUrl
    title: Optional[str] = None
    reason: Optional[str] = None
    score: float = Field(0.0, ge=-1000, le=1000)

class DomainFinderInput(BaseModel):
    company: str
    location_hint: Optional[str] = None
    k: int = 10                     # how many search results to pull
    provider: Optional[str] = None  # "bing", "serpapi", "dummy"

class DomainFinderOutput(BaseModel):
    query: DomainFinderInput
    candidates: List[DomainCandidate]
