import os
import argparse
from schemas.domain_finder_models import DomainFinderInput
from tools.search_providers import SerpAPIProvider, DummyProvider
from tools.domain_finder import find_domains

def get_provider(name: str):
    match name:
        case "serpapi": return SerpAPIProvider()
        case "dummy":
            # a tiny canned set for offline tryouts
            canned = [
              {"url":"https://joeslawncare.com/","title":"Joe's Lawncare – Home","snippet":"Official site for Joe's Lawncare in Orlando"},
              {"url":"https://www.facebook.com/joeslawncare","title":"Joe's Lawncare - Facebook","snippet":"Business page"},
              {"url":"https://www.yelp.com/biz/joes-lawncare-orlando","title":"Joe's Lawncare - Yelp","snippet":"Reviews"},
              {"url":"https://maps.google.com/...","title":"Joe's Lawncare on Google Maps","snippet":"Location"},
            ]
            return DummyProvider(canned)
        case _:
            raise SystemExit("Unknown provider. Use bing | serpapi | dummy")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", required=True)
    ap.add_argument("--location", default=None)
    ap.add_argument("--provider", default="dummy")
    ap.add_argument("--k", type=int, default=10)
    args = ap.parse_args()

    provider = get_provider(args.provider)
    inp = DomainFinderInput(company=args.company, location_hint=args.location, k=args.k, provider=args.provider)
    out = find_domains(inp, provider)
    for c in out.candidates:
        print(f"{c.score:>5.2f}  {c.url}  [{c.reason}]")
