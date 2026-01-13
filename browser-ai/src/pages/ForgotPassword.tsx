import React, { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import "./ForgotPassword.css";

export default function ForgotPassword() {
  // TypeScript automatically knows useNavigate returns a NavigateFunction
  const navigate = useNavigate();

  // Adding a handler for the form to prevent page refresh
  const handleSubmit = (e: FormEvent<HTMLFormElement>): void => {
    e.preventDefault();
    // Logic for sending reset link would go here
    console.log("Reset link requested");
  };

  return (
    <div className="forgot-page">
      <div className="forgot-container">
        <h1>Forgot Password</h1>

        <form className="forgot-form" onSubmit={handleSubmit}>
          <input 
            type="email" 
            placeholder="Enter your email" 
            className="forgot-input" 
            required 
          />
          <button type="submit" className="forgot-button">
            Send Reset Link
          </button>
        </form>

        <div className="back-to-login">
          {/* navigate() expects a string path, which TS validates */}
          <button onClick={() => navigate("/")}>Back to Login</button>
        </div>
      </div>
    </div>
  );
}