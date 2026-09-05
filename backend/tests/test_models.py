"""Model factory configuration.

The split between gpt-5.4 and gpt-6-astra in AGENT_MODELS is a cost decision as
much as a quality one, and the temperature handling is a correctness one: an
OpenAI reasoning model rejects any non-default temperature with HTTP 400, which
would fail every call the affected agent makes. Both are pinned here so a casual
edit cannot silently multiply the cost of a run or break the planner.

`get_llm` itself is stubbed by conftest for the offline suite, so the tests
exercise `_llm_kwargs`, the helper that decides what the provider class is
constructed with.
"""

from models import AGENT_MODELS, MODELS, TEMPERATURES, ModelConfig, _llm_kwargs


PREMIUM_MODEL_KEY = "gpt-6-astra"

# Agents that run once per browser action. Roughly 40 calls per run, so a
# price multiplier on any of them is a price multiplier on the whole run.
PER_ACTION_AGENTS = ("executor", "verifier", "decision")


def test_every_agent_maps_to_a_defined_model():
    assert set(AGENT_MODELS) == set(TEMPERATURES)
    for agent, key in AGENT_MODELS.items():
        assert key in MODELS, f"{agent} is assigned {key!r}, which MODELS does not define"


def test_premium_model_is_reserved_for_the_planner_and_fallback():
    """gpt-6-astra costs 4x per input token and 3.3x per output token.

    The planner and the fallback agent run a few times per run and their
    output shapes everything downstream, which is what justifies the premium.
    The per-action agents run ~40 times per run; putting one of them on the
    premium tier adds more to a run's cost than the two strategic agents put
    together. Changing this is a deliberate decision: update the cost note in
    models.py and docs/issues/gpt-6-astra-for-planner-and-fallback.md with it.
    """
    assert AGENT_MODELS["planner"] == PREMIUM_MODEL_KEY
    assert AGENT_MODELS["fallback"] == PREMIUM_MODEL_KEY
    for agent in PER_ACTION_AGENTS:
        assert AGENT_MODELS[agent] != PREMIUM_MODEL_KEY, (
            f"{agent} runs once per browser action; the premium tier there "
            "multiplies the cost of every run"
        )


def test_openai_reasoning_models_are_flagged_as_rejecting_temperature():
    """Verified live: gpt-6-astra answers temperature=0.2 with HTTP 400
    'Only the default (1) value is supported', the same as gpt-5.x."""
    for key in ("gpt-5.4", "gpt-5.4-mini", PREMIUM_MODEL_KEY):
        assert MODELS[key].supports_temperature is False, key


def test_temperature_is_omitted_for_models_that_reject_it():
    config = ModelConfig(
        name="gpt-6-astra",
        provider="openai",
        api_key_env="OPENAI_API_KEY",
        supports_temperature=False,
    )

    kwargs = _llm_kwargs(config, temperature=0.2)

    assert "temperature" not in kwargs
    # The OpenAI-specific bounds still apply.
    assert kwargs["request_timeout"] > 0
    assert kwargs["max_retries"] >= 0


def test_temperature_is_forwarded_for_models_that_accept_it():
    config = ModelConfig(
        name="gemini-2.5-pro",
        provider="google",
        api_key_env="GOOGLE_API_KEY",
    )

    assert _llm_kwargs(config, temperature=0.2) == {"temperature": 0.2}


def test_every_assigned_openai_model_omits_temperature():
    """The assignment table and the flag must agree: any OpenAI entry an agent
    actually uses would fail at call time if the flag were wrong."""
    for agent, key in AGENT_MODELS.items():
        config = MODELS[key]
        if config.provider != "openai":
            continue
        kwargs = _llm_kwargs(config, TEMPERATURES[agent])
        assert "temperature" not in kwargs, f"{agent} ({key}) would send a temperature"
