# Issue: Put the planner and the fallback agent on gpt-6-astra

Status: **closed** (implemented 2026-09-05)
Branch: `Edwin-after-grad`
Opened: 2026-09-05

Closed with: the five items under "What" below.
Verification: offline suite 325 passed / 3 xfailed (from 319; the six new tests are in `backend/tests/test_models.py`).

Live check through the real `get_llm` path, identical inputs on both models, four calls, $0.08 in total:

| Call | Model | Latency | Input / output tokens (reasoning) | Cost |
| --- | --- | --- | --- | --- |
| planner | gpt-5.4 | 3.5s | 1,922 / 165 (0) | $0.0073 |
| planner | gpt-6-astra | 4.6s | 1,922 / 187 (81) | $0.0286 |
| fallback | gpt-5.4 | 3.0s | 2,974 / 119 (0) | $0.0092 |
| fallback | gpt-6-astra | 3.1s | 2,974 / 117 (0) | $0.0356 |

Both models sit far inside the 40s request timeout, so no per-agent timeout change was needed.
Measured delta for a run with 2 planner and 6 fallback calls: about +$0.20, below the +$0.50 estimated further down (the sample contexts were realistic in size; the estimate assumed heavier reasoning output).

What the two models did with the same inputs:

- Planner, "apply to apple as a software engineer" with saved Apple credentials: gpt-5.4 produced a seven-step plan immediately, with two hedged steps ("log in ... if prompted", "submit it if the role and details match").
  gpt-6-astra asked two clarifying questions first (city or country; a specific opening or one matching the saved experience), which the planner prompt permits for a missing location.
  If unattended runs should never pause for this, tighten the clarification rules in `orchestration.prompt.md`; the model follows them.
- Fallback, the Apple run's real failure (query typed but never submitted, unfiltered results, nav-heavy snapshot): both diagnosed it correctly and neither invented an overlay.
  gpt-5.4 revised the step to "click Submit Search, then select a posting", bundling a prerequisite into the objective.
  gpt-6-astra inserted "click Submit Search and wait for the results" as a prerequisite step and left the original selection step intact, which is what the prompt's objective-preservation rule asks for.

One sample each; this is a wiring and cost check, not an evaluation.

## Why

Every agent runs on `gpt-5.4` today.
All six `AGENT_MODELS` entries in `backend/src/models.py` point at it, and no code outside that module constructs a model, so the assignment table is the whole story.

OpenAI's `gpt-6-astra` is built for long end-to-end reasoning, but it costs 4x per input token and 3.3x per output token ($10 / $50 per million against $2.50 / $15).
Reasoning tokens bill as output, so the output multiplier is the one that hurts on a model that thinks before it answers.
Putting every agent on it would roughly quadruple the cost of a run.

The agents differ by two orders of magnitude in how often they run, so the upgrade should follow call frequency and leverage.

| Agent | Calls per ~40-action run | Input per call (approx.) | What a wrong answer costs |
| --- | --- | --- | --- |
| executor | 40 (every action) | 7-9k tokens: a 12k-char snapshot plus 20 tool schemas | one wasted action; the repeat guard and readback catch most of them |
| verifier | ~35 (every action not already judged structurally) | ~4k | one misrouted step; structural signals carry most of the verdict since Phase 3 |
| decision | ~15-20 (only on partial progress; completion is rule-based) | ~2k | advance or retry chosen wrongly for one step |
| planner | 1-3 (initial plan, replans, next work item) | ~3.5k | the whole run: a bad plan is repaired downstream one failure at a time |
| fallback | ~5-8 (only after a failed verification) | ~5k, plus a screenshot when escalated | the transaction budget: a bad diagnosis is written into the plan and retried |
| interaction | 1 (finish) | ~5.5k | a badly formatted report; no control-flow effect |

The two agents worth the premium are the ones that reason about strategy: the planner and the fallback agent.
Both run a handful of times per run, and both have documented judgement failures that structural guards cannot fix:

- In the Apple careers run (`docs/issues/executor-page-visibility-loop.md`) the fallback and verifier diagnosed a nonexistent "expanded global navigation overlay" from a nav-heavy snapshot and spent several plans trying to close it.
  The snapshot pipeline has since been fixed, but the diagnosis itself was a reasoning failure on evidence a stronger model should read correctly.
- Plan quality decides step granularity, whether a bulk request becomes `work_items`, and whether to ask for clarification.
  The planner prompt asks for all three at once and gets one shot.

The executor is the tempting one and the wrong one.
It is the run's main cost driver (the largest context of any agent, on every action), and its documented failures were plumbing: discarded `read_page` output, a fragile search commit, no repeat guard.
Those are fixed structurally, and a stronger model cannot see more than the harness shows it.

Estimated cost per ~40-action run at the price sheet above (token counts from the context budgets in the agents; treat as order-of-magnitude):

| Assignment | Cost per run | Delta |
| --- | --- | --- |
| all six on gpt-5.4 (today) | ~$1.80 | - |
| planner + fallback on gpt-6-astra | ~$2.00-2.30 | +$0.20 measured to +$0.50 estimated (+10-28%) |
| planner + fallback + verifier on gpt-6-astra | ~$3.60 | +$1.80 |
| all six on gpt-6-astra | ~$6.80 | +$5.00 |

### A hazard found on the way

`gpt-6-astra` rejects any `temperature` other than the default with HTTP 400, exactly like the gpt-5 family.
Verified live against the API: `Unsupported value: 'temperature' does not support 0.2 with this model. Only the default (1) value is supported.`
langchain-openai 1.1.12 silently strips the parameter for model names starting with `gpt-5`, which is the only reason `TEMPERATURES` has been harmless so far, and it does not recognise `gpt-6-astra`.
Changing `AGENT_MODELS` alone would therefore fail every planner call (the run would ask for clarification instead of planning) and every fallback call (the run would retry the same step blind).

## What

1. `ModelConfig.supports_temperature`: an explicit flag, false for the OpenAI reasoning models.
   `get_llm` omits `temperature` when it is false instead of relying on a provider-library name pattern.
2. `AGENT_MODELS`: planner and fallback on `gpt-6-astra`; executor, verifier, decision and interaction stay on `gpt-5.4`.
3. Tests in `backend/tests/test_models.py`: every agent maps to a defined model, the per-action agents are not on the premium tier, and temperature is omitted for models that reject it and forwarded for models that accept it.
4. Documentation: the assignment policy and its cost model in `models.py` and the README.
5. A live check of one planner call and one fallback call through the real `get_llm` path against both models, to confirm the wiring and record latency and token usage.

## Non-goals

- Tuning `reasoning_effort`, which is a separate cost lever.
- An evaluation harness for plan quality; the plan doc parks that under "Model and prompt evaluation harness".
- Upgrading the verifier.
  Revisit if verifier misjudgements persist in live runs once the planner and fallback are on the stronger model.

## Acceptance

- Offline suite green, with the new tests.
- A planner call and a fallback call on `gpt-6-astra` succeed through `Models.planner` and `Models.fallback` with no temperature error, and their latency stays inside the request timeout.
- README and `models.py` describe the split and the reason for it.
