import json
from pathlib import Path
from agents.orchestrator import Orchestrator

CASES_FILE = Path("eval/cases/orchestrator_planning.jsonl")
OUT_DIR = Path("eval/runs/orchestrator")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def load_jsonl(path: Path) -> list[dict]:
    cases: list[dict] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))
    return cases

def build_state(user_request: str) -> dict:
    # Minimal state for planning-mode runs
    return {
        "messages": [{"role": "user", "content": user_request}],
        "current_url": "https://google.com",
        "current_plan": [],
        "current_step_index": 0,
        "reasoning_log": [],
        "needs_fallback": False,
        "number_of_transactions": 0,
    }

def main():
    orch = Orchestrator()
    cases = load_jsonl(CASES_FILE)

    print(f"Loaded {len(cases)} cases from {CASES_FILE}")

    for case in cases:
        case_id = case["id"]
        user_request = case["user"]

        print("\n" + "=" * 70)
        print(f"CASE {case_id}: {user_request}")
        print("=" * 70)

        state = build_state(user_request)
        output = orch(state)

        record = {
            "case": case,
            "output": output,
        }

        out_path = OUT_DIR / f"{case_id}.json"
        out_path.write_text(json.dumps(record, indent=2))

        print(f"Saved: {out_path}")

if __name__ == "__main__":
    main()

