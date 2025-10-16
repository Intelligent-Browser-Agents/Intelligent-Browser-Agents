import re
from urllib.parse import urlparse
from typing import List, Tuple
from schemas.domain_finder_models import (
    DomainFinderInput, DomainFinderOutput, DomainCandidate, SearchResult
)
from tools.search_providers import SearchProvider

# Directories we generally deprioritize as "not official site"
DIRECTORY_HINTS = [
    "yelp.com", "facebook.com", "instagram.com", "x.com", "twitter.com",
    "linkedin.com", "yellowpages.com", "angi.com", "thumbtack.com",
    "mapquest.com", "google.com/maps", "tripadvisor.com", "bloomberg.com/profile"
]

def extract_domain(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc

def is_directory(url: str) -> bool:
    host = extract_domain(url)
    return any(host.endswith(h) or host == h for h in DIRECTORY_HINTS)

def token_overlap(a: str, b: str) -> float:
    """
    Simple Jaccard overlap on alphanumeric tokens
    """
    ta = set(re.findall(r"[a-z0-9]+", a.lower()))
    tb = set(re.findall(r"[a-z0-9]+", b.lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)

def location_hits(text: str, location_hint: str | None) -> int:
    if not location_hint:
        return 0
    # loose containment check on tokens
    loc_tokens = [t for t in re.findall(r"[a-z]+", location_hint.lower()) if len(t) > 2]
    text_low = text.lower()
    return sum(1 for t in loc_tokens if t in text_low)

def compute_score(result: SearchResult, company: str, location_hint: str | None) -> Tuple[float, str]:
    """
    Score rationale:
    + title/url token overlap with company name
    + url contains company tokens
    + location hint in snippet/title
    - directory/social hosts
    """
    title = result.title or ""
    snippet = result.snippet or ""
    url = str(result.url)

    overlap_title = token_overlap(company, title)
    overlap_url = token_overlap(company, extract_domain(url))

    s = 0.0
    reasons = []

    # Base overlaps
    if overlap_title > 0:
        s += 2.0 * overlap_title
        reasons.append(f"title_overlap={overlap_title:.2f}")
    if overlap_url > 0:
        s += 2.0 * overlap_url
        reasons.append(f"url_overlap={overlap_url:.2f}")

    # URL contains exact company tokens (boost)
    company_main = re.sub(r"[^a-z0-9]+", "", company.lower())
    if company_main and company_main in url.lower():
        s += 1.0
        reasons.append("company_token_in_url")

    # Location hint matches
    hits = location_hits(f"{title} {snippet}", location_hint)
    if hits > 0:
        s += 0.5 * hits
        reasons.append(f"location_hits={hits}")

    # Penalize directories or socials
    if is_directory(url):
        s -= 1.8
        reasons.append("directory_penalty")

    # prefer simpler hostnames (e.g., not /maps/place or .business.site)
    path = urlparse(url).path
    if "/maps" in path or len(path) > 80:
        s -= 0.3
        reasons.append("path_penalty")

    return s, ", ".join(reasons) if reasons else "heuristic score"

def rank_candidates(results: List[SearchResult], company: str, location_hint: str | None, topn: int = 5) -> List[DomainCandidate]:
    scored: List[DomainCandidate] = []
    seen_hosts = set()

    for r in results:
        score, reason = compute_score(r, company, location_hint)
        host = extract_domain(str(r.url))
        # Keep only one result per host (highest score)
        if host in seen_hosts:
            continue
        seen_hosts.add(host)
        scored.append(DomainCandidate(url=r.url, title=r.title, reason=reason, score=score))

    # sort desc by score and take topn
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:topn]

def find_domains(inp: DomainFinderInput, provider: SearchProvider) -> DomainFinderOutput:
    # Build search queries (try a couple patterns for better recall)
    queries = [
        f'{inp.company} {inp.location_hint}' if inp.location_hint else f'{inp.company}',
        f'{inp.company} {inp.location_hint} official site' if inp.location_hint else f'{inp.company} official site',
        f'{inp.company} {inp.location_hint} contact' if inp.location_hint else f'{inp.company} contact',
    ]
    results: List[SearchResult] = []
    for q in queries:
        results.extend(provider.search_web(q, k=max(5, inp.k // 2)))

    candidates = rank_candidates(results, company=inp.company, location_hint=inp.location_hint, topn=5)
    return DomainFinderOutput(query=inp, candidates=candidates)
