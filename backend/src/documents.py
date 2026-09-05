"""
Stored documents: the contract the agents share for the user's uploaded files.

The server stores a user's files (resume, cover letter, transcript, ...) and
hands them to the agent subprocess inside the credential blob as
``user_credentials["userDocuments"]``. Everything the agents need to know about
that blob lives here, so the planner, the executor and the fallback agent read
one shape and describe the files the same way.

Blob shapes accepted:

* current: ``{slug: {"label": "Resume", "filename": "Edwin_Resume.pdf", "path": "..."}}``
* legacy (two-slot store): ``{slug: "<absolute path>"}``

Matching is deliberately simple and deterministic: a form field called
"Resume/CV" takes the document labelled Resume, a "Cover letter" field takes the
cover letter, and when nothing matches, the only document, then the resume, are
the sensible defaults for a job application. The model still chooses to call
``upload_file``; this module only decides which stored file the call gets.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class StoredDocument:
    slug: str
    label: str
    filename: str
    path: str

    def describe(self) -> str:
        """`Resume (Edwin_Resume.pdf)` for planner and fallback context."""
        return f"{self.label} ({self.filename})"


# Words that mean the same thing on application forms and in labels.
_SYNONYMS = {
    "cv": "resume",
    "curriculum": "resume",
    "vitae": "resume",
    "résumé": "resume",
    "letter": "cover_letter",
    "cover": "cover_letter",
    "coverletter": "cover_letter",
    "transcripts": "transcript",
    "certificate": "certification",
    "certifications": "certification",
    "certificates": "certification",
    "picture": "photo",
    "headshot": "photo",
    "image": "photo",
}

_WORD = re.compile(r"[a-z0-9]+")


def _humanize(slug: str) -> str:
    return (slug or "").replace("_", " ").strip().capitalize() or "Document"


def stored_documents(user_credentials: Optional[dict]) -> list[StoredDocument]:
    """The user's stored documents, normalized and sorted by label."""
    creds = user_credentials if isinstance(user_credentials, dict) else {}
    raw = creds.get("userDocuments")
    if not isinstance(raw, dict):
        return []
    out: list[StoredDocument] = []
    for slug, entry in raw.items():
        slug_s = str(slug or "").strip()
        if not slug_s:
            continue
        if isinstance(entry, str):
            path = entry.strip()
            label = _humanize(slug_s)
            filename = os.path.basename(path)
        elif isinstance(entry, dict):
            path = str(entry.get("path") or "").strip()
            label = str(entry.get("label") or "").strip() or _humanize(slug_s)
            filename = str(entry.get("filename") or "").strip() or os.path.basename(path)
        else:
            continue
        if not path:
            continue
        out.append(StoredDocument(slug=slug_s, label=label, filename=filename, path=path))
    out.sort(key=lambda d: d.label.lower())
    return out


def _tokens(text: str) -> set[str]:
    words = _WORD.findall((text or "").lower())
    out: set[str] = set()
    for word in words:
        out.add(word)
        canonical = _SYNONYMS.get(word)
        if canonical:
            out.update(canonical.split("_"))
            out.add(canonical)
    return out


def _document_tokens(document: StoredDocument) -> set[str]:
    stem = os.path.splitext(document.filename)[0]
    tokens = _tokens(document.label) | _tokens(document.slug.replace("_", " ")) | _tokens(stem)
    tokens.add(document.slug)
    return tokens


def match_document(
    documents: Iterable[StoredDocument],
    *hints: str,
    requested_path: Optional[str] = None,
) -> Optional[StoredDocument]:
    """The stored document a form field or plan step most plausibly wants.

    `hints` are free text: the field's accessible name first, then the plan
    step. Earlier hints outrank later ones. `requested_path` is what the model
    asked for; a stored path or a stored filename is honoured directly.
    """
    docs = list(documents)
    if not docs:
        return None

    if requested_path:
        wanted = os.path.normcase(os.path.abspath(requested_path.strip()))
        wanted_name = os.path.basename(requested_path.strip()).lower()
        for document in docs:
            if os.path.normcase(os.path.abspath(document.path)) == wanted:
                return document
        for document in docs:
            if wanted_name and document.filename.lower() == wanted_name:
                return document

    best: Optional[StoredDocument] = None
    best_score = 0
    for document in docs:
        doc_tokens = _document_tokens(document)
        score = 0
        for rank, hint in enumerate(hints):
            overlap = len(_tokens(hint) & doc_tokens)
            if overlap:
                # Earlier hints dominate later ones regardless of overlap size.
                score += overlap * (10 ** (len(hints) - rank))
        if score > best_score:
            best, best_score = document, score
    if best is not None:
        return best

    if len(docs) == 1:
        return docs[0]
    for document in docs:
        if "resume" in _document_tokens(document):
            return document
    return None


def describe_documents(documents: Iterable[StoredDocument]) -> str:
    """One line per document, for the planner and fallback context."""
    return "\n".join(f"- {d.describe()}" for d in documents)


def render_for_executor(documents: Iterable[StoredDocument]) -> str:
    """The executor's STORED_DOCUMENTS block body: label, path, filename."""
    return "\n".join(f"  - {d.label}: {d.path} ({d.filename})" for d in documents)
