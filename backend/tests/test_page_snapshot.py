"""
Unit tests for the unified page snapshot (dom_extraction/snapshot.py).

Phase 3 of docs/IMPROVEMENT_PLAN.md replaced two unrelated snapshot pipelines
with this single producer. The offline tests here pin its parsing, merging and
rendering; the browser tests pin the acceptance criterion against the job
application fixture (every field with type, label, required flag and filled
state, including inside an iframe and a shadow root, with no unclickable
`<option>` rows).
"""

import pathlib

import pytest

from dom_extraction.snapshot import (
    SNAPSHOT_LINE,
    PageElement,
    PageSnapshot,
    _merge_form_metadata,
    capture_page_snapshot,
    parse_aria_yaml,
)


# ---------------------------------------------------------------------------
# aria_snapshot YAML parsing
# ---------------------------------------------------------------------------

ARIA_YAML = """
- heading "Login" [level=1]
- textbox "Username"
- textbox "Email": a@b.com
- textbox "Password": hunter2-secret
- textbox "Disabled field" [disabled]
- button "Sign In"
- link "Forgot password":
  - /url: "https://example.com/reset"
- combobox "Country":
  - option "Pick" [selected]
  - option "United States"
- checkbox "Terms" [checked]
- radio "Radio A"
- generic "wrapper"
- text: some stray copy
- banner:
  - img "logo"
  - button "Nested in banner"
"""


def _roles_and_names(nodes, out=None):
    out = out if out is not None else []
    for node in nodes:
        out.append((node.role, node.name))
        _roles_and_names(node.children, out)
    return out


def test_parser_reads_roles_names_attrs_and_nesting():
    nodes = parse_aria_yaml(ARIA_YAML)
    flat = _roles_and_names(nodes)
    assert ("textbox", "Username") in flat
    assert ("button", "Sign In") in flat
    assert ("heading", "Login") in flat
    assert ("button", "Nested in banner") in flat

    combobox = next(n for n in nodes if n.role == "combobox")
    assert [c.name for c in combobox.children] == ["Pick", "United States"]
    assert combobox.children[0].attrs.get("selected")

    checkbox = next(n for n in nodes if n.role == "checkbox")
    assert checkbox.attrs.get("checked") is True

    disabled = next(n for n in nodes if n.name == "Disabled field")
    assert disabled.attrs.get("disabled") is True


def test_parser_skips_property_rows_and_text_rows():
    """`- /url:` describes the row above and `- text:` is not a target."""
    flat = _roles_and_names(parse_aria_yaml(ARIA_YAML))
    assert not any("/url" in role for role, _ in flat)
    assert not any(role == "text" for role, _ in flat)
    assert not any("example.com/reset" in name for _, name in flat)


def test_parser_records_value_presence_but_never_value_text():
    """The YAML contains live field values; a typed password must not survive
    parsing in any form. Only the fact that a value exists is kept."""
    nodes = parse_aria_yaml(ARIA_YAML)
    email = next(n for n in nodes if n.name == "Email")
    username = next(n for n in nodes if n.name == "Username")
    assert email.value_present is True
    assert username.value_present is False

    for node in nodes:
        for attr_value in vars(node).values():
            assert "hunter2-secret" not in str(attr_value)


def test_parser_handles_block_scalar_values():
    yaml_text = '- textbox "Cover letter": |\n    line one\n    line two\n- button "Next"'
    nodes = parse_aria_yaml(yaml_text)
    cover = next(n for n in nodes if n.name == "Cover letter")
    assert cover.value_present is True
    assert ("button", "Next") in _roles_and_names(nodes)
    assert not any("line one" in str(vars(n)) for n in nodes)


def test_parser_unescapes_quoted_names():
    nodes = parse_aria_yaml('- button "Say \\"hello\\""')
    assert nodes[0].name == 'Say "hello"'


@pytest.mark.parametrize("name", [
    "Step 2: Continue",
    "Apt #",
    "{City}",
    "Use `preferred` name",
])
def test_parser_handles_single_quoted_yaml_keys(name):
    yaml_text = f"- 'button \"{name}\"'"
    nodes = parse_aria_yaml(yaml_text)
    assert len(nodes) == 1
    assert nodes[0].role == "button"
    assert nodes[0].name == name


def test_parser_is_safe_on_empty_input():
    assert parse_aria_yaml("") == []
    assert parse_aria_yaml(None) == []


# ---------------------------------------------------------------------------
# Flattening and rendering
# ---------------------------------------------------------------------------

def _snapshot_from_yaml(yaml_text: str) -> PageSnapshot:
    from dom_extraction.snapshot import _assign_refs_and_nth, _flatten_aria_nodes

    elements: list[PageElement] = []
    _flatten_aria_nodes(parse_aria_yaml(yaml_text), elements, 400)
    _assign_refs_and_nth(elements)
    return PageSnapshot(url="https://example.com", elements=elements, frame_urls=[""])


def test_option_rows_are_folded_into_their_combobox():
    """Chromium does not accept clicks on native options; advertising them as
    standalone targets sent the model into guaranteed-failure actions."""
    snapshot = _snapshot_from_yaml(ARIA_YAML)
    rendered = snapshot.render(max_chars=8000)
    assert '[role="option"]' not in rendered
    country_line = next(l for l in rendered.splitlines() if '"Country"' in l)
    assert "Pick*" in country_line and "United States" in country_line


def test_grouped_listbox_options_are_folded_into_the_listbox():
    yaml_text = """
- listbox "Locations":
  - group "Popular cities":
    - option "Orlando" [selected]
    - option "Tampa"
"""
    rendered = _snapshot_from_yaml(yaml_text).render(max_chars=8000)
    line = next(l for l in rendered.splitlines() if '"Locations"' in l)
    assert "Orlando*" in line
    assert "Tampa" in line
    assert '[role="option"] "Orlando"' not in rendered
    assert '[role="group"]' not in rendered


def test_uninteresting_and_unnamed_rows_are_dropped_but_children_kept():
    snapshot = _snapshot_from_yaml(ARIA_YAML)
    rendered = snapshot.render(max_chars=8000)
    assert '[role="generic"]' not in rendered
    assert '[role="banner"]' not in rendered
    assert '"Nested in banner"' in rendered


def test_duplicate_role_name_pairs_get_nth_markers():
    yaml_text = '- button "Save"\n- textbox "Email"\n- button "Save"'
    rendered = _snapshot_from_yaml(yaml_text).render(max_chars=8000)
    lines = [l for l in rendered.splitlines() if '"Save"' in l]
    assert "[nth=0]" in lines[0]
    assert "[nth=1]" in lines[1]
    assert "[nth=" not in next(l for l in rendered.splitlines() if "Email" in l)


def test_checkable_roles_report_unchecked_when_the_attr_is_absent():
    rendered = _snapshot_from_yaml(ARIA_YAML).render(max_chars=8000)
    assert '"Radio A" [unchecked]' in rendered
    assert '"Terms" [checked]' in rendered


def test_refs_are_stable_and_sequential():
    snapshot = _snapshot_from_yaml(ARIA_YAML)
    refs = [e.ref for e in snapshot.elements]
    assert refs == [f"e{i}" for i in range(1, len(refs) + 1)]


def test_rendered_lines_match_the_published_contract():
    """Consumers (field ranking, click-target checks, the verifier's credential
    markers) parse `[role="x"] "name"` as a contiguous substring."""
    rendered = _snapshot_from_yaml(ARIA_YAML).render(max_chars=8000)
    element_lines = [l for l in rendered.splitlines() if l.startswith("[ref=")]
    assert element_lines
    for line in element_lines:
        assert SNAPSHOT_LINE.search(line), f"unparseable line: {line!r}"


def test_absurdly_long_names_keep_their_closing_quote():
    """Truncation must land inside the name, never on the quote that closes it,
    or every downstream parser silently drops the line."""
    long_name = "Please describe " + "in great detail " * 30 + "your experience"
    rendered = _snapshot_from_yaml(f'- textbox "{long_name}"').render(max_chars=8000)
    line = rendered.splitlines()[0]
    match = SNAPSHOT_LINE.search(line)
    assert match, f"unparseable line: {line!r}"
    assert match.group("name").endswith("...")


def test_verifier_credential_marker_still_matches():
    rendered = _snapshot_from_yaml('- textbox "Password"').render()
    assert '[role="textbox"] "password"' in rendered.lower()


# ---------------------------------------------------------------------------
# Metadata merge
# ---------------------------------------------------------------------------

def _element(role, name, **kwargs):
    return PageElement(ref="", role=role, name=name, **kwargs)


def test_merge_attaches_metadata_by_role_and_name():
    elements = [_element("textbox", "Email"), _element("button", "Resume")]
    js_fields = [
        {"role": "textbox", "name": "Email", "type": "email", "required": True,
         "filled": False, "visible": True},
        {"role": "button", "name": "Resume", "type": "file", "filled": False, "visible": True},
    ]
    _merge_form_metadata(elements, js_fields)
    assert elements[0].required is True
    assert elements[0].input_type == "email"
    assert elements[1].input_type == "file"
    assert "[file input]" in elements[1].render_line()
    assert "[no file]" in elements[1].render_line()


def test_merge_matches_duplicates_by_occurrence_order():
    elements = [_element("radio", "Yes"), _element("radio", "Yes")]
    js_fields = [
        {"role": "radio", "name": "Yes", "type": "radio", "checked": True, "visible": True},
        {"role": "radio", "name": "Yes", "type": "radio", "checked": False, "visible": True},
    ]
    _merge_form_metadata(elements, js_fields)
    assert elements[0].checked is True
    assert elements[1].checked is False


def test_merge_falls_back_to_a_unique_name_when_the_role_drifted():
    """A date input's computed role differs across engines; a unique name still
    lets its metadata land rather than being lost."""
    elements = [_element("textbox", "Start date")]
    js_fields = [{"role": "combobox", "name": "Start date", "type": "date",
                  "required": True, "visible": True}]
    _merge_form_metadata(elements, js_fields)
    assert elements[0].required is True
    assert elements[0].input_type == "date"


def test_merge_never_invents_elements_from_js_only_records():
    """A JS record whose name matches nothing must not become a snapshot line:
    its name is not guaranteed to resolve through get_by_role."""
    elements = [_element("textbox", "Email")]
    js_fields = [
        {"role": "textbox", "name": "Email", "type": "email", "visible": True},
        {"role": "textbox", "name": "Ghost field", "type": "text", "visible": True},
    ]
    _merge_form_metadata(elements, js_fields)
    assert len(elements) == 1


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def _many_buttons(count: int) -> PageSnapshot:
    yaml_text = "\n".join(f'- button "Button number {i:03d}"' for i in range(count))
    return _snapshot_from_yaml(yaml_text)


def test_small_pages_render_as_a_single_unmarked_section():
    snapshot = _many_buttons(5)
    rendered = snapshot.render(max_chars=3500)
    assert snapshot.section_count(3500) == 1
    assert "section" not in rendered
    assert "read_page" not in rendered


def test_long_pages_paginate_instead_of_truncating():
    """The old pipeline cut at the budget in DOM order with a bare marker, so
    the unfilled fields at the bottom of a long form were silently invisible."""
    snapshot = _many_buttons(120)
    total = snapshot.section_count(2000)
    assert total > 1

    first = snapshot.render(max_chars=2000, section=1)
    assert f"section 1 of {total}" in first
    assert "read_page(section=2)" in first
    assert "[DOM truncated]" not in first

    # Every element is reachable through some section.
    seen = set()
    for section in range(1, total + 1):
        body = snapshot.render(max_chars=2000, section=section)
        for line in body.splitlines():
            match = SNAPSHOT_LINE.search(line)
            if match:
                seen.add(match.group("name"))
    assert len(seen) == 120

    last = snapshot.render(max_chars=2000, section=total)
    assert "read_page" not in last


def test_out_of_range_sections_clamp_to_the_nearest_real_one():
    snapshot = _many_buttons(120)
    total = snapshot.section_count(2000)
    assert snapshot.render(max_chars=2000, section=99) == snapshot.render(max_chars=2000, section=total)
    assert snapshot.render(max_chars=2000, section=0) == snapshot.render(max_chars=2000, section=1)


def test_empty_snapshot_is_explicit():
    snapshot = PageSnapshot(url="https://example.com", elements=[], frame_urls=[""])
    assert snapshot.render() == "[No interactive elements in snapshot]"


# ---------------------------------------------------------------------------
# Browser: the Phase 3 acceptance criterion on the fixture
# ---------------------------------------------------------------------------

FIXTURE_URL = (
    pathlib.Path(__file__).parent / "fixtures" / "job_application.html"
).resolve().as_uri()

IFRAME_SURVEY = (
    "<label for='hear'>How did you hear about us</label>"
    "<input id='hear' type='text'>"
    "<input type='button' value='Submit survey' id='survey-submit'>"
)


@pytest.mark.browser
async def test_fixture_snapshot_meets_the_acceptance_criterion(page):
    """Every field with its type, label, required flag and filled state,
    including inside the iframe and the shadow root, and no option rows."""
    await page.goto(FIXTURE_URL)
    await page.evaluate(
        "html => { const f = document.createElement('iframe'); f.srcdoc = html;"
        " document.body.appendChild(f); }",
        IFRAME_SURVEY,
    )
    await page.wait_for_timeout(900)

    snapshot = await capture_page_snapshot(page)
    rendered = snapshot.render(max_chars=20000)

    # Labels, types and state for the main-frame fields.
    assert '[role="textbox"] "Full name"' in rendered
    assert '"Email" [empty]' in rendered
    assert '"Phone" [filled]' in rendered
    assert '"Requisition" [readonly] [filled]' in rendered
    assert '"Resume" [file input] [no file]' in rendered
    assert '[role="textbox"] "Message to hiring manager"' in rendered
    assert '"I accept the terms" [unchecked]' in rendered
    assert '"Send me job alerts" [checked]' in rendered
    assert '"Authorized to work" [unchecked]' in rendered

    # Selects carry their options inline; no standalone option rows anywhere.
    country = next(l for l in rendered.splitlines() if '"Country"' in l)
    assert "United States" in country and "Canada" in country
    assert '[role="option"]' not in rendered

    # aria-labelledby is how Workday and most React form libraries label inputs.
    assert '[role="textbox"] "Expected salary"' in rendered

    # The shadow root: invisible to the old pipeline, required flag included.
    referral = next(l for l in rendered.splitlines() if '"Referral code"' in l)
    assert "[required]" in referral
    assert '"Verify referral"' in rendered

    # The iframe, behind its frame header.
    assert "[iframe:" in rendered
    assert '"How did you hear about us"' in rendered
    assert '"Submit survey"' in rendered

    # type=hidden never appears.
    assert "csrf" not in rendered.lower()

    # Duplicate "Save" buttons carry their nth markers.
    save_lines = [l for l in rendered.splitlines() if '"Save"' in l]
    assert len(save_lines) == 2
    assert "[nth=0]" in save_lines[0] and "[nth=1]" in save_lines[1]


@pytest.mark.browser
async def test_every_advertised_target_resolves(page):
    """The snapshot must never advertise a target the action layer cannot find:
    that mismatch is what made the model retry the same failing action."""
    from execution.targeting import resolve_target

    await page.goto(FIXTURE_URL)
    await page.wait_for_timeout(900)

    snapshot = await capture_page_snapshot(page)
    actionable = {"button", "link", "textbox", "checkbox", "radio", "combobox"}
    checked = 0
    for element in snapshot.elements:
        if element.role not in actionable or not element.name:
            continue
        resolution = await resolve_target(page, element.role, element.name, nth=element.nth)
        assert resolution.ok, (
            f"snapshot advertised {element.role} '{element.name}' (nth={element.nth}) "
            f"but resolution failed: {resolution.error}"
        )
        checked += 1
    assert checked >= 15


@pytest.mark.browser
async def test_typed_secrets_do_not_enter_the_snapshot(page):
    """aria_snapshot YAML carries live field values; the snapshot must not."""
    await page.goto(FIXTURE_URL)
    secret = "correct-horse-battery-staple"
    await page.fill("#full-name", secret)

    snapshot = await capture_page_snapshot(page)
    rendered = snapshot.render(max_chars=20000)
    assert secret not in rendered
    assert '"Full name" [filled]' in rendered


@pytest.mark.browser
async def test_read_page_action_serves_later_sections(page):
    from execution.actions import do_read_page

    await page.goto(FIXTURE_URL)
    await page.evaluate(
        "() => { for (let i = 0; i < 150; i++) { const b = document.createElement('button');"
        " b.textContent = 'Filler button number ' + i; document.body.appendChild(b); } }"
    )

    first = await do_read_page(page, section=1)
    assert first.status == "success"
    assert "read_page(section=2)" in (first.extracted_text or "")

    second = await do_read_page(page, section=2)
    assert second.status == "success"
    assert "section 2" in (second.extracted_text or "")

    beyond = await do_read_page(page, section=99)
    assert beyond.status == "success"
    assert "does not exist" in beyond.message


@pytest.mark.browser
async def test_read_page_uses_the_same_section_boundaries_the_snapshot_advertises(page):
    from execution.actions import do_read_page

    await page.goto(FIXTURE_URL)
    await page.evaluate(
        "() => { for (let i = 0; i < 120; i++) { const input = document.createElement('input');"
        " input.type = 'text'; input.setAttribute('aria-label', 'Extra field ' + i);"
        " document.body.appendChild(input); } }"
    )

    snapshot = await capture_page_snapshot(page)
    advertised_first = snapshot.render(max_chars=3500, section=1)
    advertised_second = snapshot.render(max_chars=3500, section=2)
    action_second = await do_read_page(page, section=2)

    assert action_second.status == "success"
    assert advertised_first.endswith("read_page(section=2) to see them.]")
    assert (action_second.extracted_text or "") == advertised_second


@pytest.mark.browser
async def test_read_form_sees_shadow_and_labelledby_fields(page):
    """read_form uses the same collector as the snapshot, so the inventory now
    covers the composed tree instead of stopping at shadow boundaries."""
    from execution.actions import do_read_form

    await page.goto(FIXTURE_URL)
    body = (await do_read_form(page)).extracted_text or ""
    assert "Referral code" in body
    assert "Expected salary" in body
    assert "Message to hiring manager" in body
    assert "csrf" not in body.lower()
