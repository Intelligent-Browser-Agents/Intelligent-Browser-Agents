import { useEffect, useRef, useState } from "react";
import Modal from "./Modal";
import { api, clearToken } from "../lib/api";

const AUTONOMY_LEVELS = [
  {
    value: "confirm_irreversible",
    label: "Ask before irreversible actions",
    hint: "The agent pauses for your approval before submitting, purchasing, sending, or deleting. Recommended.",
  },
  {
    value: "autonomous",
    label: "Fully autonomous",
    hint: "The agent submits applications and finishes tasks without pausing. Money movement and account deletion still require approval.",
  },
  {
    value: "observe_only",
    label: "Observe only",
    hint: "The agent navigates and reads but asks before changing anything on a page.",
  },
];

const DOCUMENT_SLOTS = [
  { type: "resume", label: "Resume" },
  { type: "cover_letter", label: "Cover letter" },
];

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Settings that actually do something: agent autonomy (stored with the
 * encrypted vault and honored by the run's autonomy policy), the document
 * store the agent attaches from, password change, and account deletion.
 * The old free-text "Agent Prompt" box that nothing read is gone.
 */
export default function SettingsModal({ onClose, onLogout }) {
  const [autonomy, setAutonomy] = useState("");
  const [autonomyBusy, setAutonomyBusy] = useState(false);
  const [documents, setDocuments] = useState({});
  const [docBusy, setDocBusy] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [deleteArmed, setDeleteArmed] = useState(false);
  const [notice, setNotice] = useState(null);
  const fileInputsRef = useRef({});

  useEffect(() => {
    (async () => {
      try {
        const { documents: docs } = await api.getDocuments();
        setDocuments(docs || {});
      } catch {
        setDocuments({});
      }
      try {
        const { credentials } = await api.readCredentials();
        setAutonomy(credentials?.autonomyPolicy?.level || "confirm_irreversible");
      } catch {
        setAutonomy("confirm_irreversible");
      }
    })();
  }, []);

  const flash = (kind, text) => setNotice({ kind, text });

  const saveAutonomy = async (level) => {
    const previous = autonomy;
    setAutonomy(level);
    setAutonomyBusy(true);
    try {
      // The autonomy level lives inside the encrypted vault blob, so merge it
      // into whatever is stored rather than replacing the vault.
      const { credentials } = await api.readCredentials();
      await api.storeCredentials({ ...(credentials || {}), autonomyPolicy: { level } });
      flash("ok", "Autonomy preference saved. It applies from the next run.");
    } catch (err) {
      setAutonomy(previous);
      flash("error", err.detail || "Could not save the autonomy preference.");
    } finally {
      setAutonomyBusy(false);
    }
  };

  const uploadDocument = async (docType, file) => {
    if (!file) return;
    setDocBusy(docType);
    try {
      const { documents: docs } = await api.uploadDocument(docType, file);
      setDocuments(docs || {});
      flash("ok", `${docType === "resume" ? "Resume" : "Cover letter"} uploaded.`);
    } catch (err) {
      flash("error", err.detail || "Upload failed.");
    } finally {
      setDocBusy("");
      const input = fileInputsRef.current[docType];
      if (input) input.value = "";
    }
  };

  const removeDocument = async (docType) => {
    setDocBusy(docType);
    try {
      const { documents: docs } = await api.deleteDocument(docType);
      setDocuments(docs || {});
    } catch (err) {
      flash("error", err.detail || "Could not remove the file.");
    } finally {
      setDocBusy("");
    }
  };

  const changePassword = async (e) => {
    e.preventDefault();
    if (newPassword.length < 8) {
      flash("error", "The new password must be at least 8 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      flash("error", "The new passwords do not match.");
      return;
    }
    setPasswordBusy(true);
    try {
      const verified = await api.verifyPassword(currentPassword);
      if (verified?.verified !== true) {
        flash("error", "Current password is incorrect.");
        return;
      }
      await api.updateUser({ password: newPassword });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      flash("ok", "Password changed.");
    } catch (err) {
      flash("error", err.detail || "Could not change the password.");
    } finally {
      setPasswordBusy(false);
    }
  };

  const deleteAccount = async () => {
    try {
      await api.deleteAccount();
      clearToken();
      onLogout();
    } catch (err) {
      flash("error", err.detail || "Could not delete the account.");
    }
  };

  return (
    <Modal title="Settings" onClose={onClose}>
      {notice && (
        <p className={`settings-notice ${notice.kind}`} role="status">
          {notice.text}
        </p>
      )}

      <section className="settings-section">
        <h3>Agent autonomy</h3>
        <p className="settings-hint">How much the agent may do without checking in.</p>
        <div className="autonomy-options" role="radiogroup" aria-label="Agent autonomy">
          {AUTONOMY_LEVELS.map((option) => (
            <label
              key={option.value}
              className={`autonomy-option${autonomy === option.value ? " selected" : ""}`}
            >
              <input
                type="radio"
                name="autonomy"
                value={option.value}
                checked={autonomy === option.value}
                disabled={autonomyBusy || !autonomy}
                onChange={() => saveAutonomy(option.value)}
              />
              <span>
                <strong>{option.label}</strong>
                <small>{option.hint}</small>
              </span>
            </label>
          ))}
        </div>
      </section>

      <section className="settings-section">
        <h3>Documents</h3>
        <p className="settings-hint">
          Stored securely on the server; the agent attaches them when an application asks.
        </p>
        {DOCUMENT_SLOTS.map(({ type, label }) => {
          const doc = documents[type];
          return (
            <div key={type} className="document-row">
              <div className="document-info">
                <strong>{label}</strong>
                {doc ? (
                  <small>
                    {doc.filename} ({formatSize(doc.size)})
                  </small>
                ) : (
                  <small>Nothing uploaded yet.</small>
                )}
              </div>
              <div className="document-actions">
                <input
                  ref={(el) => (fileInputsRef.current[type] = el)}
                  id={`doc-${type}`}
                  type="file"
                  accept=".pdf,.docx,.doc,.txt,.rtf"
                  className="document-file-input"
                  onChange={(e) => uploadDocument(type, e.target.files?.[0])}
                />
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={docBusy === type}
                  onClick={() => fileInputsRef.current[type]?.click()}
                >
                  {docBusy === type ? "Working..." : doc ? "Replace" : "Upload"}
                </button>
                {doc && (
                  <button
                    type="button"
                    className="btn btn-ghost"
                    disabled={docBusy === type}
                    onClick={() => removeDocument(type)}
                  >
                    Remove
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </section>

      <section className="settings-section">
        <h3>Change password</h3>
        <form className="settings-password-form" onSubmit={changePassword}>
          <label className="field-label" htmlFor="current-password">Current password</label>
          <input
            id="current-password"
            className="text-input"
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            required
          />
          <label className="field-label" htmlFor="new-password">New password</label>
          <input
            id="new-password"
            className="text-input"
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
          />
          <label className="field-label" htmlFor="confirm-password">Confirm new password</label>
          <input
            id="confirm-password"
            className="text-input"
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
          />
          <button type="submit" className="btn btn-primary" disabled={passwordBusy}>
            {passwordBusy ? "Changing..." : "Change password"}
          </button>
        </form>
      </section>

      <section className="settings-section settings-danger">
        <h3>Danger zone</h3>
        {deleteArmed ? (
          <div className="danger-confirm">
            <p>This permanently deletes your account, saved details, and run history.</p>
            <div className="danger-confirm-actions">
              <button type="button" className="btn btn-danger" onClick={deleteAccount}>
                Yes, delete my account
              </button>
              <button type="button" className="btn btn-secondary" onClick={() => setDeleteArmed(false)}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button type="button" className="btn btn-danger" onClick={() => setDeleteArmed(true)}>
            Delete account
          </button>
        )}
      </section>
    </Modal>
  );
}
