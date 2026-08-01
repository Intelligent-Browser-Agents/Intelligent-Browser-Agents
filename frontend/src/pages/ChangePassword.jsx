import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import "./Login.css";

import { api, setToken } from "../lib/api";

/**
 * Completes a required password change.
 *
 * This page closes a dead end: a forgot-password reset set `chng_pass` on the
 * account, after which login returned a valid token alongside the error
 * "Password Change Required". The login page required `error === ''`, so it threw
 * the token away and reported "incorrect password" - and there was no
 * change-password UI anywhere. Users who reset their password could never get
 * back in.
 *
 * Reached from Login with a scoped reset token in router state. That token
 * authorises only this operation.
 */
export default function ChangePassword() {
  const navigate = useNavigate();
  const location = useLocation();
  const resetToken = location.state?.resetToken;

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting) return;

    if (password.length < 8) {
      setMessage("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setMessage("Passwords do not match.");
      return;
    }

    setSubmitting(true);
    setMessage("");
    try {
      const data = await api.changePassword(resetToken, password);
      setToken(data.token);
      navigate("/dashboard");
    } catch (err) {
      setMessage(err.detail || "Could not change the password. Request a new reset email.");
    } finally {
      setSubmitting(false);
    }
  };

  if (!resetToken) {
    return (
      <div className="login-page">
        <div className="login-container">
          <h1 className="login-title">Set a new password</h1>
          <p className="login-message" role="alert">
            This page needs a valid password-reset link. Please sign in again to restart the process.
          </p>
          <div className="login-button-container">
            <button type="button" className="login-button" onClick={() => navigate("/")}>
              Back to sign in
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="login-page">
      <div className="login-container">
        <h1 className="login-title">Set a new password</h1>
        <p className="login-subtitle">
          Your password was reset. Choose a new one to finish signing in.
        </p>

        <form onSubmit={handleSubmit} className="login-form">
          <label className="login-label" htmlFor="new-password">New password</label>
          <input
            id="new-password"
            name="new-password"
            type="password"
            autoComplete="new-password"
            placeholder="New password"
            className="login-input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <label className="login-label" htmlFor="confirm-password">Confirm password</label>
          <input
            id="confirm-password"
            name="confirm-password"
            type="password"
            autoComplete="new-password"
            placeholder="Confirm password"
            className="login-input"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
          {message && (
            <p className="login-message" role="alert">
              {message}
            </p>
          )}
          <div className="login-button-container">
            <button type="submit" className="login-button" disabled={submitting}>
              {submitting ? "Saving..." : "Save password"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
