import React from "react";
import "./Login.css";

export default function Login() {
  return (
    <div className="login-page">
      <div className="login-container">
        <h1 className="login-title">Login</h1>
        <form className="login-form">
          <input type="email" placeholder="Email" className="login-input" />
          <input type="password" placeholder="Password" className="login-input" />
          <button type="submit" className="login-button">Sign In</button>
        </form>
      </div>
    </div>
  );
}
