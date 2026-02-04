from agents.orchestrator import Orchestrator

def run_planning():
    orch = Orchestrator()

    state = {
        "messages": [
            {"role": "user", "content": "Find the refund policy for Spotify Premium"}
        ],
        "current_url": "https://google.com",
        "current_plan": [],
        "current_step_index": 0,
        "reasoning_log": [],
        "needs_fallback": False,
        "number_of_transactions": 0
    }

    result = orch(state)

    print("\n=== ORCHESTRATOR PLANNING OUTPUT ===")
    for k, v in result.items():
        print(f"\n{k}:")
        print(v)


if __name__ == "__main__":
    run_planning()

