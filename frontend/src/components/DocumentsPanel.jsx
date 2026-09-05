import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

// Mirrors DOCUMENT_EXTENSIONS on the server; the server is the authority.
const ACCEPTED_EXTENSIONS = ".pdf,.docx,.doc,.txt,.rtf,.odt,.png,.jpg,.jpeg";
const CUSTOM_LABEL = "__custom__";

function formatFileSize(bytes) {
  if (!bytes && bytes !== 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString();
}

/**
 * The user's stored documents: the files the agent attaches when a form asks
 * for one. The label is what the agent matches a field against ("Resume/CV"
 * takes the resume), so the panel is organised around labels rather than
 * filenames. Self-contained: it loads and mutates its own data, so it can sit in
 * the Your Details tabs without threading more state through Dashboard.
 */
export default function DocumentsPanel() {
  const [documents, setDocuments] = useState({});
  const [suggestedLabels, setSuggestedLabels] = useState([]);
  const [labelChoice, setLabelChoice] = useState("");
  const [customLabel, setCustomLabel] = useState("");
  const [pendingFile, setPendingFile] = useState(null);
  const [busy, setBusy] = useState(""); // slug being replaced or removed, or "new"
  const [notice, setNotice] = useState(null);
  const addFileRef = useRef(null);
  const replaceInputsRef = useRef({});

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const payload = await api.getDocuments();
        if (cancelled) return;
        const labels = payload.suggested_labels || [];
        setDocuments(payload.documents || {});
        setSuggestedLabels(labels);
        setLabelChoice((current) => current || labels[0] || CUSTOM_LABEL);
      } catch (err) {
        if (!cancelled) {
          setNotice({ kind: "error", text: err.detail || "Could not load your documents." });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const applyListing = (payload) => {
    setDocuments(payload?.documents || {});
    if (payload?.suggested_labels) setSuggestedLabels(payload.suggested_labels);
  };

  const newLabel = labelChoice === CUSTOM_LABEL ? customLabel.trim() : labelChoice;
  const canUpload = Boolean(newLabel && pendingFile) && busy !== "new";

  const uploadNew = async () => {
    if (!canUpload) return;
    setBusy("new");
    try {
      applyListing(await api.uploadDocument(newLabel, pendingFile));
      setPendingFile(null);
      if (addFileRef.current) addFileRef.current.value = "";
      if (labelChoice === CUSTOM_LABEL) setCustomLabel("");
      setNotice({ kind: "ok", text: `${newLabel} uploaded. The agent attaches it when a form asks for it.` });
    } catch (err) {
      setNotice({ kind: "error", text: err.detail || "Upload failed." });
    } finally {
      setBusy("");
    }
  };

  const replaceExisting = async (slug, label, file) => {
    if (!file) return;
    setBusy(slug);
    try {
      applyListing(await api.uploadDocument(label, file));
      setNotice({ kind: "ok", text: `${label} replaced.` });
    } catch (err) {
      setNotice({ kind: "error", text: err.detail || "Could not replace the file." });
    } finally {
      setBusy("");
      const input = replaceInputsRef.current[slug];
      if (input) input.value = "";
    }
  };

  const remove = async (slug, label) => {
    setBusy(slug);
    try {
      applyListing(await api.deleteDocument(slug));
      setNotice({ kind: "ok", text: `${label} removed.` });
    } catch (err) {
      setNotice({ kind: "error", text: err.detail || "Could not remove the file." });
    } finally {
      setBusy("");
    }
  };

  const entries = Object.entries(documents).sort(([, a], [, b]) =>
    (a.label || "").localeCompare(b.label || "")
  );

  return (
    <div className="documents-panel cards-scroll">
      <p className="settings-hint">
        Files the agent attaches when an application asks for one. Label each file so the
        agent can tell them apart: a &quot;Resume/CV&quot; field gets the resume, a
        &quot;Cover letter&quot; field gets the cover letter.
      </p>

      {notice && (
        <p className={`settings-notice ${notice.kind}`} role="status">
          {notice.text}
        </p>
      )}

      {entries.length === 0 ? (
        <p className="services-empty-state">No documents uploaded yet.</p>
      ) : (
        <div className="document-list">
          {entries.map(([slug, doc]) => (
            <div key={slug} className="document-row">
              <div className="document-info">
                <strong>{doc.label}</strong>
                <small>
                  {doc.filename} ({formatFileSize(doc.size)}
                  {formatDate(doc.updated_at) ? `, ${formatDate(doc.updated_at)}` : ""})
                </small>
              </div>
              <div className="document-actions">
                <input
                  ref={(el) => (replaceInputsRef.current[slug] = el)}
                  type="file"
                  accept={ACCEPTED_EXTENSIONS}
                  className="document-file-input"
                  aria-label={`Replace ${doc.label}`}
                  onChange={(e) => replaceExisting(slug, doc.label, e.target.files?.[0])}
                />
                <button
                  type="button"
                  className="setting-btn"
                  disabled={busy === slug}
                  onClick={() => replaceInputsRef.current[slug]?.click()}
                >
                  {busy === slug ? "Working..." : "Replace"}
                </button>
                <button
                  type="button"
                  className="setting-btn delete-service-btn"
                  disabled={busy === slug}
                  onClick={() => remove(slug, doc.label)}
                >
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="document-add">
        <h4>Add a document</h4>
        <div className="document-add-row">
          <div className="creds-field">
            <label htmlFor="document-label">Label</label>
            <select
              id="document-label"
              value={labelChoice}
              onChange={(e) => setLabelChoice(e.target.value)}
            >
              {suggestedLabels.map((label) => (
                <option key={label} value={label}>
                  {label}
                </option>
              ))}
              <option value={CUSTOM_LABEL}>Other...</option>
            </select>
          </div>
          {labelChoice === CUSTOM_LABEL && (
            <div className="creds-field">
              <label htmlFor="document-custom-label">Custom label</label>
              <input
                id="document-custom-label"
                type="text"
                placeholder="Reference letter"
                value={customLabel}
                onChange={(e) => setCustomLabel(e.target.value)}
              />
            </div>
          )}
          <div className="creds-field">
            <label htmlFor="document-file">File</label>
            <div className="document-file-picker">
              <input
                ref={addFileRef}
                id="document-file"
                type="file"
                accept={ACCEPTED_EXTENSIONS}
                className="document-file-input"
                onChange={(e) => setPendingFile(e.target.files?.[0] || null)}
              />
              <button type="button" className="setting-btn" onClick={() => addFileRef.current?.click()}>
                Choose file
              </button>
              <span className="document-file-name">{pendingFile ? pendingFile.name : "No file chosen"}</span>
            </div>
          </div>
        </div>
        <button type="button" className="setting-btn" disabled={!canUpload} onClick={uploadNew}>
          {busy === "new" ? "Uploading..." : "Upload"}
        </button>
        <p className="settings-hint document-add-hint">
          PDF, Word, text, OpenDocument, or image files up to 10 MB. Uploading under an
          existing label replaces that file.
        </p>
      </div>
    </div>
  );
}
