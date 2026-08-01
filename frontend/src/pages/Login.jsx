import { useState } from "react";
import { useNavigate } from "react-router-dom";
import "./Login.css";

import { api, clearToken, setToken } from "../lib/api";

export default function Login() {
  const navigate = useNavigate(); // allows navigation between pages

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // The Authorization header is deliberately NOT sent. This page used to attach
  // any stored token to the login request, and the backend short-circuited on a
  // valid header and returned that token without checking the submitted
  // credentials. On a shared browser, the next person could type anything and be
  // logged in as the previous user.
  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting) return;

    setSubmitting(true);
    setMessage("");
    clearToken();

    try {
      const data = await api.login(username, password);

      if (data.resetRequired) {
        // Carry the scoped reset token to the change-password page. Previously the
        // frontend discarded the response here, so a user whose password had been
        // reset could never log in again.
        navigate("/change-password", { state: { resetToken: data.resetToken } });
        return;
      }

      if (data.token) {
        setToken(data.token);
        navigate("/dashboard");
        return;
      }

      setMessage(data.error || "Username or password is incorrect. Please try again.");
    } catch (err) {
      setMessage(err.detail || "Could not sign in. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-page">
      <button
        type="button"
        className="about-link-button"
        onClick={() => navigate("/about")}
      >
        About
      </button>

      <div className="login-container">
        <h1 className="login-title">
          Intelligent Browser Agents
          <br/> 

        </h1>

        <form onSubmit={handleSubmit} className="login-form">
          <label className="login-label" htmlFor="login-username">Username</label>
          <input
            id="login-username"
            name="username"
            type="text"
            autoComplete="username"
            placeholder="Username"
            className="login-input"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <label className="login-label" htmlFor="login-password">Password</label>
          <input
            id="login-password"
            name="password"
            type="password"
            autoComplete="current-password"
            placeholder="Password"
            className="login-input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {message && (
            <p className="login-message" role="alert">
              {message}
            </p>
          )}
        {/* Login Button */}
        <div className="login-button-container">
          <button
            type="submit"
            className="login-button"
            disabled={submitting}
          >
            {submitting ? "Signing in..." : "Login"}
          </button>
        </div>
        </form>

        {/* Forgot Password Section */}
        <div className="forgot-password-container">
          <span className="forgot-text">Forgot your password?</span>
          <button
            type="button"
            className="forgot-password"
            onClick={() => navigate("/forgot-password")} // <-- navigate here
          >
            Forgot password
          </button>
        </div>

        {/* Register Section */}
        <div className="register-container">
          <span className="register-text">New here?</span>
          <button
            type="button"
            className="register-button"
            onClick={() => navigate("/register")} // <-- navigate here
          >
            Register
          </button>
        </div>
      </div>
    </div>
  );
}
