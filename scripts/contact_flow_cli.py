import argparse
from schemas.contact_lookup_task import ContactLookupTask
from schemas.domain_finder_models import DomainFinderInput
from tools.search_providers import SerpAPIProvider, DummyProvider
from tools.domain_finder import find_domains

def get_provider(name: str):
    if name == "serpapi": return SerpAPIProvider()
    if name == "dummy":
        return DummyProvider([
            {"url":"https://joeslawncare.com/","title":"Joe's Lawncare – Home","snippet":"Official site"},
            {"url":"https://www.facebook.com/joeslawncare","title":"Facebook","snippet":"Business page"},
        ])
    raise SystemExit("Unknown provider. Use serpapi|dummy")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True, help='e.g. "find 2025 contact info for Joe\'s Lawncare in Orlando"')
    ap.add_argument("--provider", default="serpapi")
    ap.add_argument("--k", type=int, default=10)
    args = ap.parse_args()

    # Step 1: normalize
    task = ContactLookupTask.from_raw(args.query)

    # Step 2: domain finder
    provider = get_provider(args.provider)
    df_in = DomainFinderInput(company=task.company, location_hint=task.location_hint, k=args.k, provider=args.provider)
    df_out = find_domains(df_in, provider)

    print("TASK:", task.model_dump())
    print("CANDIDATES:")
    for c in df_out.candidates:
        print(f"{c.score:>5.2f}  {c.url}  [{c.reason}]")
