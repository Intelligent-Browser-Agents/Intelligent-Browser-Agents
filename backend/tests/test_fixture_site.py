"""
Action-layer tests against the offline fixture site.

Everything here runs against `tests/fixtures/`, served over local HTTP by the
`site` fixture in conftest.py, so these need a browser but never the network.
They cover the ground `test_action_layer.py` does not:

* the three silent-success failure modes Phase 8 names (an element behind an
  overlay, a value that does not survive `fill`, an upload rejected by type),
* a multi-page application with client-side validation, a same-origin iframe, a
  shadow root, and a confirmation page,
* a login form with a second factor,
* a listing page where every row's link is named "Apply".

Each assertion is on an observable post-condition, never on the action's own
status alone. That distinction is the whole point: every bug in this file's
scope was a case where the action reported success and the page had not moved.
"""

import pathlib

import pytest

from execution import actions

pytestmark = pytest.mark.browser


@pytest.fixture
async def hazards(page, site):
    await page.goto(f"{site}/hazards.html")
    return page


@pytest.fixture
async def step_one(page, site):
    await page.goto(f"{site}/apply_step1.html")
    return page


@pytest.fixture
async def step_two(page, site):
    await page.goto(f"{site}/apply_step2.html")
    return page


@pytest.fixture
async def sign_in(page, site):
    await page.goto(f"{site}/login.html")
    return page


@pytest.fixture
async def listings(page, site):
    await page.goto(f"{site}/listings.html")
    return page


def _write(tmp_path: pathlib.Path, name: str, body: bytes = b"fixture") -> str:
    target = tmp_path / name
    target.write_bytes(body)
    return str(target)


# ---------------------------------------------------------------------------
# Silent success: an element behind an overlay
# ---------------------------------------------------------------------------

async def test_click_refuses_a_button_under_an_overlay(hazards):
    """A consent banner covers the button. `click(force=True)` used to fire at its
    coordinates anyway and report "Clicked"."""
    result = await actions.do_click(hazards, "button", "Save and continue")

    assert result.status == "failure"
    assert result.error_type == "not_interactable"
    # The click handler never ran, which is the part that actually matters.
    assert await hazards.locator("#hazard-status").inner_text() == ""


async def test_overlay_failure_says_the_element_may_be_covered(hazards):
    """The message has to point at the cause, or the fallback agent cannot act on it."""
    result = await actions.do_click(hazards, "button", "Save and continue")

    assert "covered" in result.message.lower()


async def test_click_refuses_a_disabled_control(hazards):
    await hazards.evaluate("document.getElementById('consent-banner').remove()")

    result = await actions.do_click(hazards, "button", "Archive")

    assert result.status == "failure"
    assert result.error_type == "not_interactable"


async def test_click_succeeds_once_the_overlay_is_gone(hazards):
    """The negative cases above must not be passing for the wrong reason."""
    await hazards.evaluate("document.getElementById('consent-banner').remove()")

    result = await actions.do_click(hazards, "button", "Save and continue")

    assert result.status == "success"
    assert await hazards.locator("#hazard-status").inner_text() == "Saved"


# ---------------------------------------------------------------------------
# Silent success: a value that does not survive the fill
# ---------------------------------------------------------------------------

async def test_fill_reports_a_value_the_mask_rejected(hazards):
    """The field drops anything that is not an uppercase letter, so nothing of
    what was written remains. Reporting success here left the model believing a
    required field was answered."""
    result = await actions.do_fill(hazards, "textbox", "Office code", "abc123")

    assert result.status == "failure"
    assert result.error_type == "verification_failed"
    assert await hazards.locator("#masked").input_value() == ""


async def test_fill_reports_a_truncated_value(hazards):
    """`maxlength` keeps a prefix. A partial phone or extension number is worse
    than an empty one, because the form accepts it."""
    result = await actions.do_fill(hazards, "textbox", "Extension", "1234567")

    assert result.status == "failure"
    assert result.error_type == "verification_failed"
    assert await hazards.locator("#truncating").input_value() == "1234"


async def test_fill_failure_never_echoes_the_value(hazards):
    """The failure path reaches the model context and the run log like any other.

    Only the message is checked. `args["text"]` deliberately carries the value
    through to the executor, which redacts it against the credential vault on
    the way to the log (see test_secret_redaction.py); the action layer's own
    contract is that the human-readable message never contains it.
    """
    result = await actions.do_fill(hazards, "textbox", "Office code", "hunter2")

    assert "hunter2" not in result.message
    assert "7 character" in result.message


async def test_fill_accepts_a_value_the_mask_keeps(hazards):
    result = await actions.do_fill(hazards, "textbox", "Office code", "ORL")

    assert result.status == "success"
    assert result.verified is True
    assert await hazards.locator("#masked").input_value() == "ORL"


async def test_fill_accepts_a_value_the_phone_mask_reformats(step_one):
    """Digits survive the mask, so this one is a real success and must not be
    reported as a failure."""
    result = await actions.do_fill(step_one, "textbox", "Phone number", "4075550143")

    assert result.status == "success"
    assert await step_one.locator("#phone").input_value() == "4075550143"


# ---------------------------------------------------------------------------
# Silent success: an upload the page rejects by type
# ---------------------------------------------------------------------------

async def test_upload_rejected_by_type_is_not_reported_as_verified(hazards, tmp_path):
    """`set_input_files` does not honour `accept`, so the attach itself succeeds
    and the page's own handler clears the field. The readback is the only signal
    that the document is not attached."""
    result = await actions.do_upload_file(
        hazards, "textbox", "Signed offer (PDF only)", _write(tmp_path, "offer.txt")
    )

    assert result.verified is False
    assert "readback" in result.message.lower()
    assert await hazards.locator("#strict-upload").evaluate("el => el.files.length") == 0


async def test_upload_rejected_by_type_surfaces_the_page_error(hazards, tmp_path):
    await actions.do_upload_file(
        hazards, "textbox", "Signed offer (PDF only)", _write(tmp_path, "offer.txt")
    )

    assert "only pdf" in (await hazards.locator("#hazard-status").inner_text()).lower()


async def test_upload_of_an_accepted_type_is_verified(hazards, tmp_path):
    result = await actions.do_upload_file(
        hazards, "textbox", "Signed offer (PDF only)", _write(tmp_path, "offer.pdf")
    )

    assert result.status == "success"
    assert result.verified is True
    assert await hazards.locator("#strict-upload").evaluate("el => el.files[0].name") == "offer.pdf"


# ---------------------------------------------------------------------------
# Multi-page application: client-side validation
# ---------------------------------------------------------------------------

async def test_client_side_validation_blocks_the_continue_click(step_one, site):
    """The click lands and the handler runs, so the click itself is a success.
    What must not happen is the page being reported as advanced."""
    await actions.do_click(step_one, "button", "Continue")

    assert step_one.url.endswith("apply_step1.html")
    assert "required" in (await step_one.locator("#errors").inner_text()).lower()


async def test_a_malformed_email_is_rejected_too(step_one):
    await actions.do_fill(step_one, "textbox", "Full name", "Dana Reyes")
    await actions.do_fill(step_one, "textbox", "Email address", "dana.example.test")

    await actions.do_click(step_one, "button", "Continue")

    assert step_one.url.endswith("apply_step1.html")
    assert "not valid" in (await step_one.locator("#errors").inner_text()).lower()


async def test_completing_step_one_advances_to_step_two(step_one):
    await actions.do_fill(step_one, "textbox", "Full name", "Dana Reyes")
    await actions.do_fill(step_one, "textbox", "Email address", "dana@example.test")

    result = await actions.do_click(step_one, "button", "Continue")

    assert result.status == "success"
    await step_one.wait_for_url("**/apply_step2.html*")


# ---------------------------------------------------------------------------
# Multi-page application: iframe and shadow root
# ---------------------------------------------------------------------------

async def test_read_form_sees_the_fields_inside_the_iframe(step_two):
    """The EEO block is in a same-origin frame. A document-only extractor reports
    the application complete while these are unanswered."""
    result = await actions.do_read_form(step_two)

    assert "gender" in result.extracted_text.lower()
    assert "veteran" in result.extracted_text.lower()


async def test_iframe_fields_are_labelled_as_belonging_to_a_frame(step_two):
    result = await actions.do_read_form(step_two)

    assert "frame1" in result.extracted_text


async def test_a_select_inside_the_iframe_is_addressable(step_two):
    result = await actions.do_select_option(step_two, "combobox", "Veteran status", label="I am not a protected veteran")

    assert result.status == "success"
    selected = await step_two.frame_locator("#eeo").locator("#veteran").input_value()
    assert selected == "not-veteran"


async def test_read_form_sees_the_field_inside_the_shadow_root(step_two):
    result = await actions.do_read_form(step_two)

    assert "referral" in result.extracted_text.lower()


async def test_a_field_inside_the_shadow_root_is_fillable(step_two):
    result = await actions.do_fill(step_two, "textbox", "Referral code", "REF-9931")

    assert result.status == "success"
    assert result.verified is True


# ---------------------------------------------------------------------------
# Multi-page application: the whole flow
# ---------------------------------------------------------------------------

async def test_the_application_reaches_the_confirmation_page(page, site, tmp_path):
    """The end-to-end post-condition. Every intermediate step is verified by the
    page it produces, not by the action that requested it."""
    await page.goto(f"{site}/apply_step1.html")

    await actions.do_fill(page, "textbox", "Full name", "Dana Reyes")
    await actions.do_fill(page, "textbox", "Email address", "dana@example.test")
    await actions.do_fill(page, "textbox", "Phone number", "4075550143")
    await actions.do_click(page, "button", "Continue")
    await page.wait_for_url("**/apply_step2.html*")

    await actions.do_set_checkbox(page, "radio", "I am authorized to work in this country", checked=True)
    await actions.do_select_option(page, "combobox", "Earliest start date", label="Within two weeks")
    await actions.do_upload_file(page, "textbox", "Resume (PDF or Word only)", _write(tmp_path, "resume.pdf"))
    await actions.do_select_option(page, "combobox", "Gender", label="I decline to self-identify")

    await actions.do_click(page, "button", "Submit application")
    await page.wait_for_url("**/apply_confirm.html*")

    assert "has been received" in await page.locator("#confirmation").inner_text()
    assert await page.locator("#reference").inner_text() == "PE-2026-0184"


# ---------------------------------------------------------------------------
# Login with a second factor
# ---------------------------------------------------------------------------

async def test_a_wrong_password_keeps_the_page_on_the_login_form(sign_in):
    """The guard the verifier relies on: a failed sign-in leaves a password field
    on screen, and the run must not be reported as authenticated."""
    await actions.do_fill(sign_in, "textbox", "Email or username", "candidate@example.test")
    await actions.do_fill(sign_in, "textbox", "Password", "wrong-password")

    await actions.do_click(sign_in, "button", "Sign in")

    assert sign_in.url.endswith("login.html")
    assert "incorrect" in (await sign_in.locator("#login-error").inner_text()).lower()
    assert await sign_in.locator("#password").count() == 1


async def test_correct_credentials_reach_the_second_factor(sign_in):
    await actions.do_fill(sign_in, "textbox", "Email or username", "candidate@example.test")
    await actions.do_fill(sign_in, "textbox", "Password", "correct-horse")

    await actions.do_click(sign_in, "button", "Sign in")

    await sign_in.wait_for_url("**/mfa.html*")
    assert "6-digit" in await sign_in.locator("#prompt").inner_text()


async def test_a_wrong_second_factor_code_is_rejected(page, site):
    await page.goto(f"{site}/mfa.html")

    await actions.do_fill(page, "textbox", "Verification code", "000000")
    await actions.do_click(page, "button", "Verify")

    assert page.url.endswith("mfa.html")
    assert "not correct" in (await page.locator("#mfa-error").inner_text()).lower()


async def test_completing_both_factors_signs_in(sign_in):
    await actions.do_fill(sign_in, "textbox", "Email or username", "candidate@example.test")
    await actions.do_fill(sign_in, "textbox", "Password", "correct-horse")
    await actions.do_click(sign_in, "button", "Sign in")
    await sign_in.wait_for_url("**/mfa.html*")

    await actions.do_fill(sign_in, "textbox", "Verification code", "314159")
    await actions.do_click(sign_in, "button", "Verify")

    await sign_in.wait_for_url("**/account.html*")
    assert "candidate@example.test" in await sign_in.locator("#signed-in").inner_text()


# ---------------------------------------------------------------------------
# Duplicate link text
# ---------------------------------------------------------------------------

async def test_duplicate_apply_links_are_reported_as_ambiguous(listings):
    """Three rows, three links named "Apply". Taking `.first` applied to whichever
    role happened to sort to the top."""
    result = await actions.do_click(listings, "link", "Apply")

    assert result.status == "failure"
    assert result.error_type == "ambiguous_target"
    assert listings.url.endswith("listings.html")


async def test_the_ambiguity_report_counts_every_match(listings):
    result = await actions.do_click(listings, "link", "Apply")

    assert "3" in result.message


async def test_nth_picks_the_intended_row(listings):
    result = await actions.do_click(listings, "link", "Apply", nth=2)

    assert result.status == "success"
    await listings.wait_for_url("**/apply_step1.html?role=security")
