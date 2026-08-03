import autonomy


def test_default_policy_confirms_irreversible_only():
    policy = autonomy.default_policy()
    assert policy["level"] == "confirm_irreversible"


def test_money_movement_always_confirms_regardless_of_level():
    for level in autonomy.LEVELS:
        policy = {"level": level, "domain_overrides": {}}
        decision = autonomy.assess_action("click", {"role": "button", "name": "Place Order"}, policy=policy)
        assert decision["mode"] == "confirm"
        assert decision["category"] == "money_movement"


def test_destructive_action_always_confirms_regardless_of_level():
    policy = {"level": "autonomous", "domain_overrides": {}}
    decision = autonomy.assess_action("click", {"role": "button", "name": "Delete Account"}, policy=policy)
    assert decision["mode"] == "confirm"
    assert decision["category"] == "destructive"


def test_submission_confirms_at_default_level_but_not_autonomous():
    args = {"role": "button", "name": "Submit Application"}
    default_policy = {"level": "confirm_irreversible", "domain_overrides": {}}
    autonomous_policy = {"level": "autonomous", "domain_overrides": {}}

    assert autonomy.assess_action("click", args, policy=default_policy)["mode"] == "confirm"
    assert autonomy.assess_action("click", args, policy=autonomous_policy)["mode"] == "allow"


def test_read_only_actions_always_allowed_even_at_observe_only():
    policy = {"level": "observe_only", "domain_overrides": {}}
    decision = autonomy.assess_action("read_form", {}, policy=policy)
    assert decision["mode"] == "allow"


def test_observe_only_confirms_ordinary_state_changing_actions():
    policy = {"level": "observe_only", "domain_overrides": {}}
    decision = autonomy.assess_action("fill", {"role": "textbox", "name": "Full name"}, policy=policy)
    assert decision["mode"] == "confirm"


def test_name_substring_does_not_misfire_like_the_old_token_lists():
    """Regression pin: the executor's old _SENSITIVE_TARGET_TOKENS matched
    'submit' as a raw substring, so name='Total' contained no such token but
    plenty of similar bugs existed for 'to'/'add'. Category matching here is on
    word boundaries, so an unrelated name containing a would-be-sensitive verb
    as a substring (not a whole word) is not misclassified."""
    decision = autonomy.classify_action_category("click", {"name": "Resubmittal Instructions"})
    assert decision is None


def test_domain_override_raises_autonomy_for_a_trusted_site():
    policy = {
        "level": "confirm_irreversible",
        "domain_overrides": {"jobs.example.com": "autonomous"},
    }
    args = {"role": "button", "name": "Submit Application"}

    trusted = autonomy.assess_action("click", args, policy=policy, url="https://jobs.example.com/apply")
    other = autonomy.assess_action("click", args, policy=policy, url="https://other.example.com/apply")

    assert trusted["mode"] == "allow"
    assert other["mode"] == "confirm"


def test_domain_override_matches_subdomains_only():
    policy = {"level": "confirm_irreversible", "domain_overrides": {"example.com": "autonomous"}}
    args = {"role": "button", "name": "Submit Application"}

    assert autonomy.assess_action("click", args, policy=policy, url="https://apply.example.com")["mode"] == "allow"
    assert autonomy.assess_action("click", args, policy=policy, url="https://notexample.com")["mode"] == "confirm"


def test_load_policy_prefers_stored_over_environment_over_default():
    env_policy = autonomy.load_policy(credentials={}, environ={"AGENT_AUTONOMY_LEVEL": "autonomous"})
    assert env_policy["level"] == "autonomous"

    stored_policy = autonomy.load_policy(
        credentials={"autonomyPolicy": {"level": "observe_only"}},
        environ={"AGENT_AUTONOMY_LEVEL": "autonomous"},
    )
    assert stored_policy["level"] == "observe_only"

    default_policy = autonomy.load_policy(credentials={}, environ={})
    assert default_policy["level"] == "confirm_irreversible"
