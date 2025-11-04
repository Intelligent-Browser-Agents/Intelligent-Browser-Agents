import React from "react";
import "./Login.css";

export default function Login() {
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

        <div className="forgot-password-container">
          <span className="forgot-text">Forgot your password?</span>
          <button className="forgot-password">Forgot password</button>
        </div>

        <div className="register-container">
          <span className="register-text">New here?<br /></span>
          <button type="button" className="register-button">
            Register
          </button>
        </div>
      </div>
    </div>
  );
}



