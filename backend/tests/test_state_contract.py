"""`ProjectState` key-coverage contract tests.

LangGraph merges a node's returned dict into the state by key. A key the
`ProjectState` TypedDict does not declare is dropped on the floor: no exception,
no warning, and the write simply does not happen. The agent that wrote it goes
on believing the value is there, and the bug surfaces later as an unrelated
symptom somewhere downstream.

`TypedDict` is not enforced at runtime, so nothing catches this. These tests do,
by reading the agent modules and checking every state update they construct.

Identifying a state update
--------------------------
A dict literal in an agent module counts as a state update when it is not nested
inside another dict literal and at least two of its keys are declared
`ProjectState` fields. Two rather than one, because a nested payload occasionally
shares a single name with a state field: `_build_recovery_screenshot_meta`
returns a `screenshot_meta` value whose own `step_attempts` key collides with the
state field of that name, and the payload under `pending_sensitive_action`
carries a `current_task`. Neither is a state update, and both are excluded by the
threshold.

Subscript writes onto a dict the function returns (`out["stall_cycles"] = ...` in
the verifier's stall cap) are collected too, since those never appear as literal
keys.

The floor assertions at the bottom exist because this analysis is static: if a
refactor moves state construction into a shape the walk does not recognise, the
tests above would keep passing while covering nothing. A drop in what the walk
finds is itself a failure.
"""

from __future__ import annotations

import ast
import pathlib
import typing

import pytest

from state import ProjectState

AGENTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "src" / "agents"

DECLARED = set(typing.get_type_hints(ProjectState).keys())

# Every module holding a graph node. Named explicitly so a new agent has to be
# added here deliberately rather than silently escaping the contract.
AGENT_MODULES = ["executor.py", "fallback.py", "interaction.py", "orchestrator.py", "verifier.py"]

# A dict literal needs this many recognised state fields before it is treated as
# a state update. See the module docstring.
_MIN_DECLARED_KEYS = 2


def _string_keys(node: ast.Dict) -> set[str]:
    return {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def _state_updates(source: str) -> list[tuple[int, set[str]]]:
    """Every state-update dict in a module, as (line number, keys)."""
    tree = ast.parse(source)

    nested = {
        id(value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        for value in node.values
        if isinstance(value, ast.Dict)
    }

    updates = [
        (node.lineno, keys)
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        and id(node) not in nested
        and len((keys := _string_keys(node)) & DECLARED) >= _MIN_DECLARED_KEYS
    ]

    # Subscript writes onto a dict the function hands back. Grouped per
    # returned name and held to the same threshold as a dict literal: the
    # executor has several helpers that build and return a non-state dict this
    # way (a redacted copy of an action's output, a normalised argument set),
    # and those must not be mistaken for state.
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        returned = {
            n.value.id
            for n in ast.walk(fn)
            if isinstance(n, ast.Return) and isinstance(n.value, ast.Name)
        }
        if not returned:
            continue

        groups: dict[str, list[tuple[int, str]]] = {}
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id in returned
                    and isinstance(target.slice, ast.Constant)
                    and isinstance(target.slice.value, str)
                ):
                    groups.setdefault(target.value.id, []).append((node.lineno, target.slice.value))

        for writes in groups.values():
            keys = {key for _, key in writes}
            if len(keys & DECLARED) >= _MIN_DECLARED_KEYS:
                updates.extend((line, {key}) for line, key in writes)

    return updates


def _module_source(name: str) -> str:
    return (AGENTS_DIR / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module", AGENT_MODULES)
def test_every_key_an_agent_writes_is_declared_in_project_state(module):
    undeclared = [
        (line, sorted(keys - DECLARED))
        for line, keys in _state_updates(_module_source(module))
        if keys - DECLARED
    ]

    assert not undeclared, (
        f"{module} writes state keys that ProjectState does not declare: {undeclared}. "
        "LangGraph drops undeclared keys silently, so the write never lands. Declare "
        "them in backend/src/state.py, or correct the spelling."
    )


@pytest.mark.parametrize("module", AGENT_MODULES)
def test_every_agent_module_exists(module):
    """A renamed or deleted agent must not quietly leave the contract."""
    assert (AGENTS_DIR / module).is_file()


def test_reducer_backed_fields_are_declared_with_an_annotation():
    """`Annotated[..., reducer]` is what makes a list field append rather than
    replace. Losing the annotation turns an accumulating field into a
    last-writer-wins one, which is silent and destroys history."""
    hints = typing.get_type_hints(ProjectState, include_extras=True)

    for field in ("reasoning_log", "extracted_content", "dom_cache", "plan_history", "item_results"):
        assert typing.get_origin(hints[field]) is typing.Annotated, (
            f"{field} lost its reducer annotation; it will now overwrite instead of append"
        )


# ---------------------------------------------------------------------------
# Floors: the static walk must keep finding what it found
# ---------------------------------------------------------------------------

# Recorded when this contract was written (Phase 8). Raise them when real state
# updates are added. A drop means the walk stopped recognising state
# construction, not that the agents stopped writing state.
_MIN_UPDATES_PER_MODULE = {
    "executor.py": 4,
    "fallback.py": 8,
    "interaction.py": 8,
    "orchestrator.py": 24,
    "verifier.py": 4,
}


@pytest.mark.parametrize("module", AGENT_MODULES)
def test_the_walk_still_finds_this_module_s_state_updates(module):
    found = len(_state_updates(_module_source(module)))
    floor = _MIN_UPDATES_PER_MODULE[module]

    assert found >= floor, (
        f"Found {found} state updates in {module}, down from {floor}. The contract above "
        "only checks what this walk can see, so a drop means state construction moved into "
        "a shape it does not recognise and is now unchecked. Teach _state_updates the new "
        "shape rather than lowering this number."
    )


def test_the_walk_covers_most_of_the_declared_state():
    """A sanity floor on the whole contract rather than one module at a time."""
    written = set()
    for module in AGENT_MODULES:
        for _, keys in _state_updates(_module_source(module)):
            written |= keys

    assert len(written & DECLARED) >= 29, (
        f"The walk accounts for only {len(written & DECLARED)} of {len(DECLARED)} declared "
        "state fields, down from 29."
    )
