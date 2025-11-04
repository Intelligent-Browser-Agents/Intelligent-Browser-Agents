import React from "react";
import { useNavigate } from "react-router-dom";
import "./Login.css";

export default function Login() {
  const navigate = useNavigate(); // allows navigation between pages

  return (
    <div className="login-page">
      <div className="login-container">
        <h1 className="login-title">
          Browser
          <br />AI
        </h1>

        <form className="login-form">
          <input
            type="text"
            placeholder="Username"
            className="login-input"
          />
          <input
            type="password"
            placeholder="Password"
            className="login-input"
          />
          <button type="submit" className="login-button">
            Sign In
          </button>
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
