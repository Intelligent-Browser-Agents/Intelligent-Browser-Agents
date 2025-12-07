import React from "react";
import { useNavigate } from "react-router-dom";
import "./ForgotPassword.css";

export default function ForgotPassword() {
  const navigate = useNavigate();

  return (
    <div className="forgot-page">
      <div className="forgot-container">
        <h1>Forgot Password</h1>

        <form className="forgot-form">
          <input type="email" placeholder="Enter your email" className="forgot-input" />
          <button type="submit" className="forgot-button">Send Reset Link</button>
        </form>

        <div className="back-to-login">
          <button onClick={() => navigate("/")}>Back to Login</button>
        </div>
      </div>
    </div>
  );
}
