"""Site-notes loading: per-domain guidance that must never leak across sites.

The generic prompts carry no site-specific rules (Phase 5); anything genuinely
site-shaped lives in prompts/site_notes/<host>.md and is injected only when
the current host matches. These tests pin the matching rules: a Gmail note
must load for mail.google.com and must NOT load for a Workday host.
"""

from prompt_loader import load_site_notes


def test_exact_host_match_loads_the_note():
    notes = load_site_notes("mail.google.com")
    assert "compose" in notes.lower()


def test_full_url_is_accepted():
    notes = load_site_notes("https://mail.google.com/mail/u/0/#inbox")
    assert "compose" in notes.lower()


def test_subdomain_walks_up_to_the_note_domain():
    # No file named u.mail.google.com.md exists; the walk must reach
    # mail.google.com.md.
    assert load_site_notes("u.mail.google.com") == load_site_notes("mail.google.com")


def test_unrelated_host_gets_nothing():
    assert load_site_notes("workday.com") == ""
    assert load_site_notes("myworkdayjobs.com") == ""


def test_a_note_never_applies_by_tld_alone(monkeypatch, tmp_path):
    """If the parent-domain walk regressed to include the bare TLD, a com.md
    note would apply to every .com site. Pin the guard with a com.md fixture
    that must never load."""
    import prompt_loader

    notes_dir = tmp_path / "site_notes"
    notes_dir.mkdir()
    (notes_dir / "com.md").write_text("must never load", encoding="utf-8")
    (notes_dir / "example.com.md").write_text("example note", encoding="utf-8")
    monkeypatch.setattr(prompt_loader, "_SITE_NOTES_DIR", notes_dir)

    assert load_site_notes("deep.sub.example.com") == "example note"
    assert load_site_notes("other-site.com") == ""


def test_garbage_input_is_safe():
    assert load_site_notes("") == ""
    assert load_site_notes(None) == ""
    assert load_site_notes("about:blank") == ""
    assert load_site_notes("localhost") == ""


def test_outlook_hosts_have_notes():
    assert "compose" in load_site_notes("outlook.office.com").lower()
    assert "compose" in load_site_notes("outlook.live.com").lower()
