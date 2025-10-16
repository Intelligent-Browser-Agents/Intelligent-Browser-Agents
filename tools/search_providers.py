import os
import json
import time
import urllib.parse
import http.client
from dotenv import load_dotenv
from typing import List, Protocol
from pydantic import HttpUrl
from schemas.domain_finder_models import SearchResult

load_dotenv()

# ---------- Provider interface ----------
class SearchProvider(Protocol):
    def search_web(self, query: str, k: int = 10) -> List[SearchResult]: ...

# ---------- Helpers ----------
def _normalize_result(url: str, title: str | None, snippet: str | None, source: str) -> SearchResult:
    return SearchResult(url=HttpUrl(url), title=title, snippet=snippet, source=source)

# ---------- SerpAPI ----------
class SerpAPIProvider:
    """
    Requires env: SERPAPI_KEY
    """
    def __init__(self, api_key: str | None = None):
        self.key = api_key or os.getenv("SERPAPI_KEY")
        if not self.key:
            raise RuntimeError("SERPAPI_KEY not set")

    def search_web(self, query: str, k: int = 10) -> List[SearchResult]:
        # Simple GET using serpapi.com/search.json?engine=google&q=...
        params = urllib.parse.urlencode({"engine": "google", "q": query, "num": k, "api_key": self.key})
        conn = http.client.HTTPSConnection("serpapi.com", timeout=15)
        conn.request("GET", f"/search.json?{params}")
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()

        results: List[SearchResult] = []
        for item in (data.get("organic_results") or [])[:k]:
            url = item.get("link")
            title = item.get("title")
            snippet = item.get("snippet")
            if url:
                results.append(_normalize_result(url, title, snippet, "serpapi"))
        return results

# ---------- Dummy (for tests / offline dev) ----------
class DummyProvider:
    def __init__(self, canned: List[dict]):
        self.canned = canned

    def search_web(self, query: str, k: int = 10) -> List[SearchResult]:
        out: List[SearchResult] = []
        for item in self.canned[:k]:
            out.append(_normalize_result(item["url"], item.get("title"), item.get("snippet"), "dummy"))
        return out
