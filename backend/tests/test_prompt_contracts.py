"""Prompt-to-code contract tests.

A prompt that names an output field the schema does not have, an enum value
the Literal does not accept, an input block the code never supplies, or a
tool that is not registered ships misinformation straight into the model.
These tests fail when either side drifts, in both directions:

- every field/enum/tool the prompt names must exist in the code, and
- every field/enum/tool the code defines must be documented in the prompt.

The input-block direction is pinned with explicit per-prompt allowlists.
Each allowlist entry names the code that supplies the block; when a context
label is added or removed in an agent, update the allowlist here in the same
change.
"""

import re
import typing

import pytest

from execution.models import ACTION_NAMES
from prompt_loader import load_prompt
from schema import (
    ExecutionArgs,
    ExecutionResult,
    FallbackStrategy,
    InteractionResponse,
    OrchestratorDecision,
    OrchestratorPlan,
    VerificationResult,
    WorkItem,
)

PROMPT_NAMES = [
    "orchestration",
    "orchestration_reasoning",
    "execution",
    "execution_tools",
    "verification",
    "fallback",
    "interaction",
]

# The response model each prompt's JSON output example must match.
# execution_tools has no JSON output (tool-call mode), so it is absent.
OUTPUT_MODELS = {
    "orchestration": OrchestratorPlan,
    "orchestration_reasoning": OrchestratorDecision,
    "execution": ExecutionResult,
    "verification": VerificationResult,
    "fallback": FallbackStrategy,
    "interaction": InteractionResponse,
}

# Nested models whose fields may legitimately appear inside a prompt's JSON
# example (e.g. the args template inside the execution output example).
NESTED_MODELS = {
    "execution": [ExecutionArgs],
    "orchestration": [WorkItem],
}

# Context labels each prompt may promise as inputs. Every entry is supplied by
# the consuming agent; the reference says where. A prompt naming a label not
# in its allowlist fails: either the prompt promises an input nothing sends
# (the old BEFORE_STATE / ALLOWED_TOOLS defect), or a new context block needs
# to be added here alongside the code that sends it.
_EXECUTOR_CONTEXT = {
    "MAIN_GOAL",              # executor.py context f-string
    "STEP_OBJECTIVE",         # executor.py context f-string
    "PLAN_STEP",              # executor.py context f-string
    "PLAN_STEP_URL_HINT",     # executor.py context f-string
    "DOM_SNAPSHOT",           # executor.py context f-string
    "PAGE_SECTION_JUST_READ", # executor._build_read_section_context
    "DOM_TEXT_CONTEXT",       # executor._build_dom_cache_context
    "FIELD_PRIORITY_CONTEXT", # executor._build_field_priority_context
    "USER_CREDENTIALS",       # executor._build_credentials_context
    "STORED_DOCUMENTS",       # executor._build_documents_context
    "SERVICE_CREDENTIALS",    # inside the credentials block
    "PERSONAL_INFO",          # inside the credentials block
    "PAYMENT_INFO",           # inside the credentials block
    "PREVIOUS_ACTIONS",       # executor._build_recent_actions
    "ADAPTIVE_GUIDANCE",      # executor._build_adaptive_guidance
    "EXECUTION_STATUS_SIGNALS",  # executor._build_execution_status_context
    "MISSION_STATUS_EXCERPT", # inside the status signals block
    "SITE_NOTES",             # executor._build_site_notes_context
}

INPUT_ALLOWLISTS = {
    "orchestration": set(),  # planner labels are space-separated (PAGE STATE etc.)
    "orchestration_reasoning": {
        "MISSION_STATUS",     # orchestrator._make_decision context
    },
    "execution": _EXECUTOR_CONTEXT,
    "execution_tools": _EXECUTOR_CONTEXT,
    "verification": {
        "MAIN_GOAL",              # verifier context f-string
        "PLAN_POSITION",          # verifier context f-string
        "PLAN_STEP",              # verifier context f-string
        "STRUCTURAL_SIGNALS",     # verifier context f-string
        "EXECUTION_OUTPUT",       # verifier context f-string
        "AFTER_STATE",            # appended from state["last_page_snapshot"]
        "RECENT_EXECUTION_HISTORY",  # verifier context f-string
        "CURRENT_URL",            # verifier context f-string
        "MISSION_STATUS",         # verifier context f-string
        "SITE_NOTES",             # verifier site_notes_block
    },
    "fallback": {
        "MAIN_GOAL",              # fallback context f-string
        "PLAN_STEP",              # fallback context f-string
        "VERIFICATION_OUTPUT",    # fallback context f-string
        "EXECUTION_OUTPUT",       # fallback context f-string
        "CURRENT_URL",            # fallback context f-string
        "AFTER_STATE",            # fallback context f-string
        "LAST_DOM_SNAPSHOT",      # fallback context f-string
        "PREVIOUS_DOM_SNAPSHOT",  # fallback context f-string
        "MISSION_STATUS",         # fallback context f-string
        "SCREENSHOT_SIGNAL",      # fallback._build_screenshot_context_block
        "LOOP_ANALYSIS",          # fallback loop_analysis_block
        "STORED_DOCUMENTS",       # fallback documents_block
        "SITE_NOTES",             # fallback site_notes_block
    },
    "interaction": {
        "MAIN_GOAL",              # interaction context f-string
        "VERIFIED_RESULT",        # interaction context f-string
        "EXTRACTED_CONTENT",      # interaction context f-string
        "SYSTEM_STATUS",          # interaction context f-string
        "WORK_ITEM_RESULTS",      # interaction context f-string
        "MISSION_STATUS",         # interaction context f-string
    },
}

# Tools the executor actually offers: the dispatchable action set plus the
# two discovery helpers registered only as LangChain tools.
REGISTERED_TOOLS = set(ACTION_NAMES) | {"dom_search", "list_links"}


def _prompt(name: str) -> str:
    return load_prompt(name)


def _json_blocks(text: str) -> list[str]:
    return re.findall(r"```json\s*\n(.*?)```", text, flags=re.DOTALL)


def _json_block_keys(text: str) -> set[str]:
    """Every `"key":` occurrence in the prompt's json blocks, including keys of
    objects written inline on one line."""
    keys: set[str] = set()
    for block in _json_blocks(text):
        keys.update(re.findall(r'"([a-zA-Z_]+)":', block))
    return keys


def _json_block_fields(text: str) -> dict[str, str]:
    """Map of key -> raw value text for every `"key": value` line in json blocks."""
    fields: dict[str, str] = {}
    for block in _json_blocks(text):
        for line in block.splitlines():
            match = re.match(r'\s*"([a-zA-Z_]+)":\s*(.*?),?\s*$', line)
            if match:
                fields.setdefault(match.group(1), match.group(2))
    return fields


def _literal_fields(model) -> dict[str, set[str]]:
    """String-valued Literal fields of a Pydantic model."""
    out: dict[str, set[str]] = {}
    for field_name, field in model.model_fields.items():
        annotation = field.annotation
        if typing.get_origin(annotation) is typing.Union:
            args = [a for a in typing.get_args(annotation) if a is not type(None)]
            if len(args) == 1:
                annotation = args[0]
        if typing.get_origin(annotation) is typing.Literal:
            values = typing.get_args(annotation)
            if all(isinstance(v, str) for v in values):
                out[field_name] = set(values)
    return out


# ---------------------------------------------------------------------------
# Structural hygiene
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", PROMPT_NAMES)
def test_code_fences_are_balanced(name):
    """An unterminated fence means the system prompt ends inside a code block."""
    text = _prompt(name)
    assert text.count("```") % 2 == 0, f"{name}.prompt.md has an unclosed code fence"


@pytest.mark.parametrize("name", PROMPT_NAMES)
def test_no_scaffolding_shipped_as_prompt_text(name):
    """The old fallback prompt began with '---' and a heading quoting its own
    repo path, and ended mid-fence; all of it reached the model verbatim."""
    text = _prompt(name)
    assert not text.lstrip().startswith("---"), f"{name}.prompt.md starts with scaffolding"
    assert f"`prompts/{name}.prompt.md`" not in text, f"{name}.prompt.md quotes its own path"
    assert "</output>" not in text, f"{name}.prompt.md contains a stray closing tag"


# ---------------------------------------------------------------------------
# Output contract: JSON example keys and enum values match the schema
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(OUTPUT_MODELS))
def test_output_example_keys_match_schema(name):
    model = OUTPUT_MODELS[name]
    prompt_keys = _json_block_keys(_prompt(name))
    allowed = set(model.model_fields)
    for nested in NESTED_MODELS.get(name, []):
        allowed |= set(nested.model_fields)

    phantom = prompt_keys - allowed
    assert not phantom, (
        f"{name}.prompt.md documents output fields the schema does not have: {sorted(phantom)}"
    )

    undocumented = set(model.model_fields) - prompt_keys
    assert not undocumented, (
        f"{model.__name__} has fields {sorted(undocumented)} that "
        f"{name}.prompt.md never documents; the model cannot emit what it was "
        f"never told about"
    )

    for nested in NESTED_MODELS.get(name, []):
        missing_nested = set(nested.model_fields) - prompt_keys
        assert not missing_nested, (
            f"{nested.__name__} fields {sorted(missing_nested)} are missing from "
            f"{name}.prompt.md's example"
        )


@pytest.mark.parametrize("name", sorted(OUTPUT_MODELS))
def test_enum_values_in_examples_exist_in_schema(name):
    """Every pipe-separated enum token in a JSON example line must be a value
    its Literal accepts. Catches phantom values like the verifier's old
    'tool_limit'."""
    model = OUTPUT_MODELS[name]
    literals = _literal_fields(model)
    for nested in NESTED_MODELS.get(name, []):
        literals.update(_literal_fields(nested))

    for key, value_text in _json_block_fields(_prompt(name)).items():
        if key not in literals or "|" not in value_text:
            continue
        for part in value_text.split("|"):
            token = part.strip().strip('"<>').strip()
            if not re.fullmatch(r"[a-z_]+", token) or token == "null":
                continue
            assert token in literals[key], (
                f"{name}.prompt.md offers '{token}' for '{key}', which "
                f"{model.__name__} does not accept"
            )


@pytest.mark.parametrize("name", sorted(OUTPUT_MODELS))
def test_every_schema_enum_value_is_documented(name):
    model = OUTPUT_MODELS[name]
    text = _prompt(name)
    for key, values in _literal_fields(model).items():
        for value in values:
            assert re.search(rf"\b{re.escape(value)}\b", text), (
                f"{model.__name__}.{key} accepts '{value}' but "
                f"{name}.prompt.md never mentions it"
            )


# ---------------------------------------------------------------------------
# Input contract: promised context labels are actually supplied
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", PROMPT_NAMES)
def test_promised_inputs_are_supplied_by_code(name):
    """Underscore-joined ALL-CAPS tokens are the context-block labels. Each one
    a prompt names must be in its allowlist of labels the agent actually
    sends. BEFORE_STATE and ALLOWED_TOOLS both failed this once."""
    text = _prompt(name)
    tokens = set(re.findall(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b", text))
    phantom = tokens - INPUT_ALLOWLISTS[name]
    assert not phantom, (
        f"{name}.prompt.md promises context blocks nothing supplies: {sorted(phantom)}"
    )


# ---------------------------------------------------------------------------
# Tool contract: execution prompts describe the real action set
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["execution", "execution_tools"])
def test_every_tool_the_prompt_names_is_registered(name):
    """Backticked call syntax like `fill(role, name, text)` must reference a
    registered tool."""
    text = _prompt(name)
    named = set(re.findall(r"`([a-z_]+)\(", text))
    phantom = named - REGISTERED_TOOLS
    assert not phantom, (
        f"{name}.prompt.md documents tools that are not registered: {sorted(phantom)}"
    )


@pytest.mark.parametrize("name", ["execution", "execution_tools"])
def test_every_registered_action_is_documented(name):
    """The old prompts described 8 of 20 actions; the model cannot use what it
    was never told exists."""
    text = _prompt(name)
    missing = [
        action for action in ACTION_NAMES
        if not re.search(rf"\b{re.escape(action)}\b", text)
    ]
    assert not missing, (
        f"{name}.prompt.md never mentions registered actions: {missing}"
    )
