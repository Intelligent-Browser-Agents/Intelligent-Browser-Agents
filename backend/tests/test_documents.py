"""Stored documents: the contract shared by the planner, executor and fallback.

The user uploads files under labels; the agents must (1) know they exist,
(2) attach the right one to a file field without asking, and (3) never attach
anything that is not in the store.
"""

from agents.executor import Executor
from agents.fallback import Fallback
from agents.orchestrator import Orchestrator
from documents import StoredDocument, match_document, stored_documents


BLOB = {
    "resume": {
        "label": "Resume",
        "filename": "Edwin_Resume.pdf",
        "path": "/store/1/resume/Edwin_Resume.pdf",
    },
    "cover_letter": {
        "label": "Cover letter",
        "filename": "Letter.pdf",
        "path": "/store/1/cover_letter/Letter.pdf",
    },
    "transcript": {
        "label": "Transcript (Fall 2025)",
        "filename": "ucf.pdf",
        "path": "/store/1/transcript/ucf.pdf",
    },
}


def _state(blob=BLOB, **extra):
    state = {"user_credentials": {"fullName": "Edwin", "userDocuments": blob}}
    state.update(extra)
    return state


def _docs(blob=BLOB):
    return stored_documents({"userDocuments": blob})


# ── contract module ─────────────────────────────────────────────────────

def test_stored_documents_normalizes_both_blob_shapes():
    new_shape = _docs()
    assert [d.slug for d in new_shape] == ["cover_letter", "resume", "transcript"]
    assert new_shape[1] == StoredDocument("resume", "Resume", "Edwin_Resume.pdf", BLOB["resume"]["path"])

    legacy = stored_documents({"userDocuments": {"resume": "/old/resume.pdf"}})
    assert legacy == [StoredDocument("resume", "Resume", "resume.pdf", "/old/resume.pdf")]

    assert stored_documents({}) == []
    assert stored_documents(None) == []
    assert stored_documents({"userDocuments": {"broken": {"label": "x"}}}) == []


def test_match_prefers_the_field_name_over_the_step_text():
    # The step is about the resume, the field asks for the cover letter: the field wins.
    chosen = match_document(_docs(), "Cover letter", "Upload your resume and cover letter")
    assert chosen.slug == "cover_letter"


def test_match_understands_form_synonyms():
    docs = _docs()
    assert match_document(docs, "Resume/CV").slug == "resume"
    assert match_document(docs, "Upload CV").slug == "resume"
    assert match_document(docs, "Curriculum vitae").slug == "resume"
    assert match_document(docs, "Letter of interest").slug == "cover_letter"
    assert match_document(docs, "Unofficial transcripts").slug == "transcript"


def test_match_honours_a_stored_path_or_filename_the_model_asked_for():
    docs = _docs()
    assert match_document(docs, "Attachment", requested_path=BLOB["transcript"]["path"]).slug == "transcript"
    assert match_document(docs, "Attachment", requested_path="/somewhere/else/Letter.pdf").slug == "cover_letter"


def test_match_falls_back_to_the_only_document_then_the_resume():
    only = _docs({"portfolio": {**BLOB["transcript"], "label": "Portfolio"}})
    assert match_document(only, "Attachment").slug == "portfolio"

    assert match_document(_docs(), "Attachment", "Add a file").slug == "resume"

    without_resume = _docs({k: v for k, v in BLOB.items() if k != "resume"})
    assert match_document(without_resume, "Attachment", "Add a file") is None


# ── executor ────────────────────────────────────────────────────────────

SNAPSHOT_WITH_FILE_INPUT = (
    '[ref=e1] [role="textbox"] "Full name" [required] [empty]\n'
    '[ref=e2] [role="button"] "Resume/CV" [file input] [no file]\n'
)
SNAPSHOT_WITHOUT_FILE_INPUT = '[ref=e1] [role="textbox"] "City" [empty]'


def test_executor_shows_documents_when_the_step_mentions_a_file():
    block = Executor._build_documents_context(
        _state(), "Attach your resume to the application", SNAPSHOT_WITHOUT_FILE_INPUT
    )
    assert "STORED_DOCUMENTS" in block
    assert BLOB["resume"]["path"] in block
    assert "Edwin_Resume.pdf" in block


def test_executor_shows_documents_when_the_page_has_a_file_input():
    block = Executor._build_documents_context(
        _state(), "Complete the personal details section", SNAPSHOT_WITH_FILE_INPUT
    )
    assert "STORED_DOCUMENTS" in block


def test_executor_hides_documents_when_neither_step_nor_page_involves_a_file():
    assert Executor._build_documents_context(
        _state(), "Complete the personal details section", SNAPSHOT_WITHOUT_FILE_INPUT
    ) == ""
    assert Executor._build_documents_context(
        {"user_credentials": {}}, "Attach your resume", SNAPSHOT_WITH_FILE_INPUT
    ) == ""


def test_executor_remaps_a_made_up_path_to_the_stored_file_the_field_wants():
    path, problem = Executor._resolve_upload_path(_state(), "/tmp/resume.pdf", "Cover letter", "Upload documents")
    assert problem == ""
    assert path == BLOB["cover_letter"]["path"]


def test_executor_keeps_a_stored_path_as_is():
    path, _ = Executor._resolve_upload_path(_state(), BLOB["transcript"]["path"], "Attachment", "Upload documents")
    assert path == BLOB["transcript"]["path"]


def test_executor_refuses_uploads_when_nothing_is_stored():
    path, problem = Executor._resolve_upload_path({"user_credentials": {}}, "/etc/passwd", "Resume", "Upload your resume")
    assert path is None
    assert "Documents" in problem


def test_executor_names_the_options_when_no_document_fits():
    state = _state({k: v for k, v in BLOB.items() if k != "resume"})
    path, problem = Executor._resolve_upload_path(state, None, "Attachment", "Add a file")
    assert path is None
    assert "Cover letter (Letter.pdf)" in problem


# ── planner ─────────────────────────────────────────────────────────────

def test_planner_summary_lists_stored_documents():
    summary = Orchestrator._build_credentials_summary(_state())
    assert "Stored documents" in summary
    assert "Resume (Edwin_Resume.pdf)" in summary
    assert "Cover letter (Letter.pdf)" in summary


def test_planner_summary_without_documents_is_unchanged():
    summary = Orchestrator._build_credentials_summary({"user_credentials": {"fullName": "Edwin"}})
    assert "Personal info on file" in summary
    assert "Stored documents" not in summary


# ── fallback ────────────────────────────────────────────────────────────

def test_fallback_context_lists_stored_documents():
    fallback = Fallback()
    state = _state(
        current_task="Attach the resume to the application",
        current_plan=["Attach the resume to the application"],
        current_step_index=0,
        current_url="https://jobs.example.com/apply",
        dom_cache=["URL: https://jobs.example.com/apply\n\nResume/CV Upload a file"],
        reasoning_log=[
            "[Executor] Action: upload_file\n"
            "[Executor] Args: file_path=/tmp/made-up.pdf\n"
            "[Executor] Status: failure\n"
            "[Executor] Message: File not found on the agent host: /tmp/made-up.pdf\n"
            "[Executor] Error Type: ambiguous_step",
            "[Verifier] Verdict: failure\n"
            "[Verifier] Step Complete: False\n"
            "[Verifier] Goal Complete: False\n"
            "[Verifier] Message: Executor reported a failed action; retry/fallback required.\n"
            "[Verifier] Handoff: fallback",
        ],
        number_of_transactions=6,
        step_attempts=1,
    )

    fallback(state)

    prompt_text = fallback.llm.calls[-1][-1].content
    assert "STORED_DOCUMENTS" in prompt_text
    assert "Resume (Edwin_Resume.pdf)" in prompt_text
