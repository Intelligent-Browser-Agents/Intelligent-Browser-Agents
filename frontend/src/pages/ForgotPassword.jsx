import { useState } from "react";
import { useNavigate } from "react-router-dom";
import "./ForgotPassword.css";

import { api } from "../lib/api";

export default function ForgotPassword() {
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Now a POST with the address in the body. It used to be a GET with the address
  // in the query string, which rotated the account password on a plain GET: that
  // is CSRF-able from any <img src> and puts the address in every access log.
  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting) return;

    if (!email.trim()) {
      setMessage("Enter the email address on your account.");
      return;
    }

    setSubmitting(true);
    setMessage("");
    try {
      await api.forgotPassword(email.trim());
    } catch (err) {
      if (err.status === 429) {
        setMessage("Too many reset requests. Please wait a few minutes and try again.");
        setSubmitting(false);
        return;
      }
      // Any other failure still gets the neutral message below, so this page
      // cannot be used to test whether an account exists.
    }

    setMessage(
      "If an account matches that address, a reset email is on its way. " +
        "Sign in with the temporary password to choose a new one."
    );
    setSubmitting(false);
  };

  return (
    <div className="forgot-page">
      <div className="forgot-container">
        <h1>Forgot Password</h1>

        <form onSubmit={handleSubmit} className="forgot-form">
          <label className="forgot-label" htmlFor="forgot-email">Email</label>
          <input
            id="forgot-email"
            name="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Enter your email"
            className="forgot-input"
          />
          {message && (
            <p
              className={`forgot-message ${message.includes("on its way") ? "success" : ""}`}
              role="status"
            >
              {message}
            </p>
          )}
          <button type="submit" className="forgot-button" disabled={submitting}>
            {submitting ? "Sending..." : "Send Reset Link"}
          </button>
        </form>

        <div className="back-to-login">
          <button type="button" onClick={() => navigate("/")}>Back to Login</button>
        </div>
      </div>
    </div>
  );
}
