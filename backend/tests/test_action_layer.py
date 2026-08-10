"""
Phase 2 action layer tests.

Runs against a local HTML fixture (tests/fixtures/job_application.html), so these
need a browser but no network and no model. The fixture is shaped like a real job
application: text inputs, two native selects, a radio group, checkboxes, a file
input, a readonly field, a control that appears late, and two different buttons
that share the accessible name "Save".

Each test pins a behaviour the previous action layer got wrong.
"""

import pathlib

import pytest

from execution import actions
from execution.targeting import normalize_role, resolve_target, unique_frames

pytestmark = pytest.mark.browser

FIXTURE_URL = (
    pathlib.Path(__file__).parent / "fixtures" / "job_application.html"
).resolve().as_uri()


@pytest.fixture
async def form(page):
    await page.goto(FIXTURE_URL)
    return page


# ---------------------------------------------------------------------------
# Ambiguity: the central failure of the old resolver
# ---------------------------------------------------------------------------

async def test_duplicate_names_report_ambiguity_instead_of_guessing(form):
    """Two buttons are named "Save". Taking `.first` was a coin flip on DOM order."""
    result = await actions.do_click(form, "button", "Save")
    assert result.status == "failure"
    assert result.error_type == "ambiguous_target"
    assert "nth=" in result.message


async def test_nth_disambiguates(form):
    result = await actions.do_click(form, "button", "Save", nth=1)
    assert result.status == "success"


async def test_out_of_range_nth_is_reported(form):
    result = await actions.do_click(form, "button", "Save", nth=9)
    assert result.status == "failure"
    assert result.error_type == "element_not_found"


async def test_a_miss_lists_the_targets_that_do_exist(form):
    """The emoji-name failure: the model needs to know what it could have clicked.

    A real run spent two 60s timeouts on click(link, "🔒 Log In to myUCF") and
    reported only "element not found", so it retried the same wrong target.
    """
    result = await actions.do_click(form, "button", "🔒 Submit application")
    assert result.status == "failure"
    assert "Available targets:" in result.message
    assert "Submit application" in result.message


async def test_html_tag_names_are_mapped_to_aria_roles(form):
    """The extractor and the model both emit tag names; get_by_role rejects them."""
    assert normalize_role("a") == "link"
    assert normalize_role("select") == "combobox"
    assert normalize_role("tbody") == ""
    result = await actions.do_click(form, "a", "Help")
    assert result.status == "success"


async def test_invalid_role_fails_fast_with_suggestions(form):
    result = await resolve_target(form, "tbody", "Spring 2026")
    assert result.error == "invalid_role"
    assert not result.ok


async def test_role_without_a_name_is_refused(form):
    """Role-only used to click the first element of that role, typically a nav button."""
    result = await actions.do_click(form, "button", "")
    assert result.status == "failure"
    assert result.error_type == "element_not_found"


# ---------------------------------------------------------------------------
# fill
# ---------------------------------------------------------------------------

async def test_fill_addresses_the_named_field(form):
    result = await actions.do_fill(form, "textbox", "Full name", "Ada Lovelace")
    assert result.status == "success"
    assert result.verified is True
    assert await form.locator("#full-name").input_value() == "Ada Lovelace"


async def test_fill_does_not_touch_other_fields(form):
    """The old handler picked the field by classifying the value being typed, so a
    name could land in the cover-letter textarea."""
    await actions.do_fill(form, "textbox", "Full name", "Ada Lovelace")
    assert await form.locator("#cover").input_value() == ""
    assert await form.locator("#email").input_value() == ""


async def test_fill_never_echoes_the_value(form):
    """The message reaches the model context and the run log; it may be a password."""
    secret = "Tr0ub4dor&3"
    result = await actions.do_fill(form, "textbox", "Full name", secret)
    assert secret not in result.message
    assert "character(s)" in result.message


async def test_fill_press_enter_commits_on_the_field_itself(form):
    """press_enter presses Enter on the just-filled element, not the page keyboard,
    so a focus-stealing overlay cannot eat the keystroke the way press_key can
    (the Apple-careers run typed a search twice and never committed it)."""
    result = await actions.do_fill(form, "textbox", "Full name", "Ada Lovelace", press_enter=True)
    assert result.status == "success"
    assert result.verified is True
    assert "Pressed Enter" in result.message
    assert await form.locator("#status").inner_text() == "Application received"


async def test_fill_without_press_enter_does_not_submit(form):
    result = await actions.do_fill(form, "textbox", "Full name", "Ada Lovelace")
    assert result.status == "success"
    assert "Pressed Enter" not in result.message
    assert await form.locator("#status").inner_text() == ""


async def test_fill_refuses_a_readonly_field(form):
    result = await actions.do_fill(form, "textbox", "Requisition", "TAMPERED")
    assert result.status == "failure"
    assert result.error_type == "not_interactable"
    assert await form.locator("#req-id").input_value() == "REQ-4417"


async def test_fill_rejects_a_non_editable_role(form):
    result = await actions.do_fill(form, "button", "Save", "text")
    assert result.status == "failure"


async def test_fill_replaces_an_existing_value(form):
    assert await form.locator("#phone").input_value() == "000"
    result = await actions.do_fill(form, "textbox", "Phone", "555-0100")
    assert result.status == "success"
    assert await form.locator("#phone").input_value() == "555-0100"


# ---------------------------------------------------------------------------
# select_option
# ---------------------------------------------------------------------------

async def test_select_option_by_label(form):
    result = await actions.do_select_option(form, "combobox", "Country", label="Canada")
    assert result.status == "success"
    assert result.verified is True
    assert await form.locator("#country").input_value() == "ca"


async def test_select_option_by_value(form):
    result = await actions.do_select_option(form, "combobox", "Country", value="us")
    assert result.status == "success"
    assert await form.locator("#country").input_value() == "us"


async def test_absent_option_fails_fast_and_lists_the_real_ones(form):
    """Handing an absent option to select_option burned the whole 8s timeout and
    reported only "Timeout exceeded", telling the model nothing."""
    import time

    started = time.perf_counter()
    result = await actions.do_select_option(form, "combobox", "Country", label="Atlantis")
    elapsed = time.perf_counter() - started

    assert result.status == "failure"
    assert "Available options" in result.message
    assert "United States" in result.message
    assert elapsed < 3.0, f"should fail fast, took {elapsed:.1f}s"


async def test_two_selects_are_addressed_independently(form):
    await actions.do_select_option(form, "combobox", "Country", label="Canada")
    await actions.do_select_option(form, "combobox", "Highest degree", label="Masters")
    assert await form.locator("#country").input_value() == "ca"
    assert await form.locator("#degree").input_value() == "ms"


# ---------------------------------------------------------------------------
# set_checkbox
# ---------------------------------------------------------------------------

async def test_set_checkbox_checks(form):
    result = await actions.do_set_checkbox(form, "checkbox", "I accept the terms", True)
    assert result.status == "success"
    assert result.verified is True
    assert await form.locator("#terms").is_checked()


async def test_set_checkbox_is_idempotent(form):
    """A bare click toggles, so a retry after a click that actually worked but was
    reported as failed silently turned the box back off."""
    await actions.do_set_checkbox(form, "checkbox", "I accept the terms", True)
    result = await actions.do_set_checkbox(form, "checkbox", "I accept the terms", True)
    assert result.status == "success"
    assert await form.locator("#terms").is_checked() is True


async def test_set_checkbox_unchecks(form):
    assert await form.locator("#subscribe").is_checked() is True
    result = await actions.do_set_checkbox(form, "checkbox", "Send me job alerts", False)
    assert result.status == "success"
    assert await form.locator("#subscribe").is_checked() is False


async def test_radio_selects_the_named_option(form):
    """Radio labels repeat across questions, so `.first` answered the wrong one."""
    result = await actions.do_set_checkbox(form, "radio", "Authorized to work", True)
    assert result.status == "success"
    assert await form.locator("#auth-yes").is_checked() is True
    assert await form.locator("#auth-no").is_checked() is False


async def test_set_checkbox_rejects_a_non_checkable_role(form):
    result = await actions.do_set_checkbox(form, "button", "Save", True)
    assert result.status == "failure"


# ---------------------------------------------------------------------------
# upload_file
# ---------------------------------------------------------------------------

async def test_upload_attaches_a_real_file(form):
    """Nothing could do this before, which made any application requiring a resume
    unfinishable."""
    target = str(pathlib.Path(__file__).resolve())
    result = await actions.do_upload_file(form, "textbox", "Resume", target)
    assert result.status == "success"
    assert result.verified is True
    attached = await form.locator("#resume").evaluate("el => el.files[0].name")
    assert attached == pathlib.Path(target).name


async def test_upload_rejects_a_missing_file(form):
    result = await actions.do_upload_file(form, "textbox", "Resume", "/no/such/file.pdf")
    assert result.status == "failure"
    assert "not found" in result.message.lower()


async def test_upload_finds_the_input_without_a_name(form):
    target = str(pathlib.Path(__file__).resolve())
    result = await actions.do_upload_file(form, None, None, target)
    assert result.status == "success"


# ---------------------------------------------------------------------------
# wait_for
# ---------------------------------------------------------------------------

async def test_wait_for_an_element_that_appears_late(form):
    """`wait(seconds)` was a blind sleep, so async transitions were guesswork."""
    result = await actions.do_wait_for(form, "button", "Continue to review", seconds=5)
    assert result.status == "success"
    assert result.verified is True


async def test_wait_for_times_out_on_something_absent(form):
    result = await actions.do_wait_for(form, "button", "Nonexistent control", seconds=1)
    assert result.status == "failure"
    assert result.error_type == "timeout"


async def test_wait_for_visible_text(form):
    await actions.do_click(form, "button", "Submit application")
    result = await actions.do_wait_for(form, text_contains="Application received", seconds=5)
    assert result.status == "success"


async def test_wait_for_requires_a_condition(form):
    result = await actions.do_wait_for(form, seconds=1)
    assert result.status == "failure"
    assert result.error_type == "ambiguous_step"


async def test_wait_for_says_when_the_url_condition_was_already_true(form):
    """A tautological wait must say so, or a login-wall step can 'succeed'
    instantly every cycle and burn the transaction budget without waiting."""
    result = await actions.do_wait_for(form, url_contains="job_application", seconds=5)
    assert result.status == "success"
    assert "already contained" in result.message


# ---------------------------------------------------------------------------
# read_form
# ---------------------------------------------------------------------------

async def test_read_form_reports_what_is_still_empty(form):
    """Answers "which fields are still missing?", which nothing could do before."""
    result = await actions.do_read_form(form)
    assert result.status == "success"
    body = result.extracted_text or ""
    assert 'Email' in body
    assert "empty" in body
    assert "no file" in body


async def test_read_form_tracks_state_changes(form):
    await actions.do_fill(form, "textbox", "Email", "ada@example.com")
    await actions.do_set_checkbox(form, "checkbox", "I accept the terms", True)
    body = (await actions.do_read_form(form)).extracted_text or ""
    assert "filled (15 chars)" in body
    assert 'checkbox "I accept the terms": checked' in body


async def test_read_form_flags_readonly_and_required(form):
    body = (await actions.do_read_form(form)).extracted_text or ""
    assert "readonly" in body


# ---------------------------------------------------------------------------
# Verification semantics
# ---------------------------------------------------------------------------

async def test_click_with_an_observable_effect_is_verified(form):
    result = await actions.do_click(form, "button", "Submit application")
    assert result.status == "success"
    assert result.verified is True
    assert await form.locator("#status").inner_text() == "Application received"


async def test_click_with_no_observable_effect_is_unverified(form):
    """An inert button reports success but not verified, rather than implying it worked."""
    result = await actions.do_click(form, "button", "Save", nth=1)
    assert result.status == "success"
    assert result.verified is False


# ---------------------------------------------------------------------------
# Frame handling
# ---------------------------------------------------------------------------

async def test_frames_are_not_processed_twice(form):
    """`[page.main_frame] + list(page.frames)` doubled the work on every lookup."""
    frames = unique_frames(form)
    assert len(frames) == len(set(id(f) for f in frames))
    assert form.main_frame in frames


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------

async def test_complete_the_whole_application(form):
    """The target use case: fill every field type and submit, all verified."""
    steps = [
        await actions.do_fill(form, "textbox", "Full name", "Ada Lovelace"),
        await actions.do_fill(form, "textbox", "Email", "ada@example.com"),
        await actions.do_fill(form, "textbox", "Phone", "555-0100"),
        await actions.do_select_option(form, "combobox", "Country", label="United States"),
        await actions.do_select_option(form, "combobox", "Highest degree", label="Masters"),
        await actions.do_set_checkbox(form, "radio", "Authorized to work", True),
        await actions.do_set_checkbox(form, "checkbox", "I accept the terms", True),
        await actions.do_upload_file(form, "textbox", "Resume", str(pathlib.Path(__file__).resolve())),
        await actions.do_fill(form, "textbox", "Cover letter", "I would like to apply."),
    ]
    for i, step in enumerate(steps):
        assert step.status == "success", f"step {i} failed: {step.message}"
        assert step.verified is True, f"step {i} unverified: {step.message}"

    # Nothing required is left empty apart from the intentionally readonly field.
    body = (await actions.do_read_form(form)).extracted_text or ""
    assert "no file" not in body

    submit = await actions.do_click(form, "button", "Submit application")
    assert submit.status == "success"
    assert submit.verified is True
    assert await form.locator("#status").inner_text() == "Application received"
