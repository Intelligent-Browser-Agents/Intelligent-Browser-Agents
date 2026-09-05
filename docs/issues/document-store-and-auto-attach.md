# Issue: A documents section the agent attaches from, without asking

Status: **closed** (implemented 2026-09-05)
Branch: `Edwin-after-grad`
Opened: 2026-09-05

Closed with: all seven items under "What" below.
Verification: offline suite 349 passed / 3 xfailed (from 325: 15 new API tests in `backend/tests/test_documents_api.py`, 15 new agent and matching tests in `backend/tests/test_documents.py`, the 6 old two-slot tests retired), eslint and `npm run build` clean.
The Documents tab was checked visually against the real Modal and stylesheets through a throwaway harness page with the API mocked in-page (Claude in Chrome was not connected, so the signed-in dashboard itself could not be driven): list with label, filename, size and date; Remove updates the list and shows the notice; "Other..." reveals the custom-label field; Upload stays disabled and dimmed until both a label and a file are chosen.
Two polish items came out of that pass and were fixed: `.setting-btn` had no disabled style, and the add form used a bare native file input where the rest of the app uses a styled button.
Not exercised live: a browser-driven upload through the real dashboard. The upload path itself is covered by the API tests, and the agent-side attach by the existing `do_upload_file` browser tests plus the new path-resolution tests.

## Why

The request: a section of the app where the user uploads the files an application may need (resume, cover letter, transcript, anything else), named so the agent can tell them apart, and an agent that picks the right stored file when a form asks for one instead of asking the user to supply it.

Phase 7 built part of this and then stopped short.
What exists today:

- A server-side store with exactly two fixed slots, `resume` and `cover_letter` (`server.py`, `DOCUMENT_TYPES`), managed from the Settings modal, where most users will never look for it.
  The Apple run on 2026-09-05 started with no `userDocuments` key in the credential blob at all: nothing had been uploaded.
- The stored file is renamed to `resume.pdf`; the original filename is lost, and that renamed file is what an employer receives.
- Document paths ride the credential blob, but only the executor reads them, and only on steps whose text matches the form keywords (`fill`, `enter`, `submit`, `apply`, ...).
  A step worded "Attach your resume" or "Upload a CV" shows the model no documents, and a form step whose page has a file input but whose text does not match shows none either.
- The planner's credentials summary never mentions documents, so plans say "leave document uploads unresolved" or "prompt the user to upload", as the Apple run's plan did.
- The fallback agent has no view of stored documents, so a failed upload step turns into `request_context` and a question to the user.
- `upload_file` accepts any path on the agent host.
  A hallucinated path fails with "File not found", and nothing steers the model back to the stored files.
  A page that asks the agent to upload `.env` would also be obeyed.

## What

1. **Labeled store.** `POST /api/documents` takes a label and a file; the label is slugified server-side and becomes the document's identity (`Cover letter` -> `cover_letter`, so existing slots keep their names).
   Any label is allowed; the UI suggests Resume, Cover letter, Transcript, Portfolio, Certification, Photo.
   Files are stored one per slug directory under their sanitized original filename, so the employer sees `Edwin_Villanueva_Resume.pdf`.
   Labels live in a per-user `manifest.json`; the listing is derived from the directories so a manually removed file cannot leave a ghost entry.
   Legacy `<slug>.<ext>` files from the two-slot store are still listed and are replaced cleanly.
   Extensions widen to include `.odt` and images; the size limit rises to 10 MB.
2. **One contract for the agents.** `backend/src/documents.py` normalizes the `userDocuments` blob (old and new shapes), renders it for prompts, and matches a form field or step to a document by label, slug, filename, and common synonyms (CV = resume, letter = cover letter).
3. **Planner** lists stored documents in `AVAILABLE USER CREDENTIALS` and is told to plan uploads as automated steps.
4. **Executor** gets a `STORED_DOCUMENTS` block whenever documents exist and the step mentions a file or the page shows a file input, independent of the form-keyword classifier.
   Every `upload_file` path is resolved against the store: a stored path passes, anything else is remapped to the best-matching document (field name, then step text, then the only document, then the resume), and when nothing fits the action fails with the list of stored files instead of a bare "File not found".
   Only stored documents can be attached.
5. **Fallback** sees a `STORED_DOCUMENTS` block and is told to revise a failed upload step toward the stored file rather than asking the user.
6. **Frontend.** A Documents tab in Your Details, beside Services, Payment Info, and Experience: the stored files with label, filename, size, and date, replace and remove per file, and an add form with a label picker (suggested labels plus a custom label) and a file picker.
   The Settings modal's two-slot section is removed so there is one place for documents.
7. **Tests and docs.** API tests for labels, sanitized filenames, the legacy layout, and per-user isolation; unit tests for the matching and the three agents' context blocks; prompt contract allowlists; README.

## Non-goals

- Generating or tailoring documents (a cover letter per posting). The agent attaches what the user uploaded.
- Virus scanning or content inspection of uploads.
- Per-document visibility rules (which sites may receive which file).

## Acceptance

- Uploading `Edwin_Resume.pdf` under the label Resume stores it as `user_documents/<user>/resume/Edwin_Resume.pdf` and lists it with that label and filename.
- A plan for "apply to this job" with a stored resume contains an attach step and no "prompt the user to upload" step.
- On a page with a file input named "Resume/CV", the executor's `upload_file` receives the stored resume's path even when the model proposed a made-up path.
- A failed upload with a stored cover letter and a "Cover letter" field is revised by the fallback toward the stored file, not `request_context`.
- Offline suite green; frontend lint and build clean.
