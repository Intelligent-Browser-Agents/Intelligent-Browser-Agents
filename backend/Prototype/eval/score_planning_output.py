import json
import csv
from pathlib import Path

RUN_DIR = Path("eval/runs/orchestrator")
CSV_OUT = Path("eval/results_orchestrator_planning.csv")

def score(output: dict, expected: dict) -> dict:
    plan = output.get("current_plan", [])
    plan_status = output.get("plan_status")
    current_task = output.get("current_task")
    is_complete = output.get("is_complete", None)

    # Infer mode based on your orchestrator implementation
    needs_clarification_actual = (plan_status == "NEEDS_CLARIFICATION")

    scores = {}
    scores["mode_correct"] = (needs_clarification_actual == expected.get("needs_clarification", False))

    if not needs_clarification_actual:
        scores["has_plan"] = (len(plan) > 0)
        scores["step_count_ok"] = expected.get("min_steps", 3) <= len(plan) <= expected.get("max_steps", 8)
        scores["current_task_matches_step0"] = (len(plan) > 0 and current_task == plan[0])
        scores["not_complete_after_planning"] = (is_complete is False)
        scores["plan_status_ok"] = (plan_status == "MAINTAIN")
    else:
        scores["has_no_plan_on_clarify"] = (len(plan) == 0)
        scores["not_complete_on_clarify"] = (is_complete is False)
        scores["plan_status_ok"] = (plan_status == "NEEDS_CLARIFICATION")

    scores["total_pass_fraction"] = sum(bool(v) for v in scores.values()) / len(scores)
    return scores

def main():
    rows = []
    for path in sorted(RUN_DIR.glob("*.json")):
        record = json.loads(path.read_text())
        case = record["case"]
        output = record["output"]
        expected = case.get("expected", {})

        scores = score(output, expected)

        rows.append({
            "id": case.get("id", path.stem),
            "user": case.get("user", ""),
            "expected_needs_clarification": expected.get("needs_clarification", False),
            "actual_plan_status": output.get("plan_status"),
            "steps": len(output.get("current_plan", [])),
            **scores,
        })

    if not rows:
        raise SystemExit(f"No run files found in {RUN_DIR}. Run: python -m eval.run_orchestrator")

    # Write CSV
    # Write CSV (union of all keys, because clarify-mode has different fields)
    all_keys = set()
    for r in rows:
        all_keys.update(r.keys())

    preferred_order = [
        "id", "user", "expected_needs_clarification", "actual_plan_status", "steps",
        "mode_correct", "has_plan", "step_count_ok", "current_task_matches_step0",
        "not_complete_after_planning", "has_no_plan_on_clarify", "not_complete_on_clarify",
        "plan_status_ok", "total_pass_fraction",
    ]
    fieldnames = [k for k in preferred_order if k in all_keys] + sorted(all_keys - set(preferred_order))

    with CSV_OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"Wrote {len(rows)} rows to {CSV_OUT}")

    # Print quick summary
    avg = sum(r["total_pass_fraction"] for r in rows) / len(rows)
    print(f"Average pass fraction: {avg:.3f}")

    failed = [r for r in rows if r["total_pass_fraction"] < 1.0]
    print(f"Perfect passes: {len(rows) - len(failed)}/{len(rows)}")
    if failed:
        print("Failures:")
        for r in failed:
            print(f"  {r['id']} | plan_status={r['actual_plan_status']} | steps={r['steps']} | total={r['total_pass_fraction']:.2f}")

if __name__ == "__main__":
    main()

