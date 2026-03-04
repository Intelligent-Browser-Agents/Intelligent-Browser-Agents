import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import "./ForgotPassword.css";

export default function ForgotPassword() {
  const navigate = useNavigate();

  const [email, setEmail] = React.useState("");
  const [message, setMessage] = React.useState("");

  useEffect(() => {
    // This runs exactly ONCE when the page loads
    setMessage(''); 
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();

    const url = '/api/users/forgot-password/?email=' + encodeURIComponent(email);

    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json'
      },
    });

    const data = await response.json();
    if (data.error === '') {
      setMessage('Password reset link sent to your email!');
    } else {
      setMessage('Please check email provided and try again.');
    }
  }



  return (
    <div className="forgot-page">
      <div className="forgot-container">
        <h1>Forgot Password</h1>

        <form onSubmit={handleSubmit} className="forgot-form">
          <input type="email" onChange={(e) => setEmail(e.target.value)}placeholder="Enter your email" className="forgot-input" />
          {message && (
            <p className={`forgot-message ${message.includes("sent") ? "success" : ""}`}>
              {message}
            </p>
          )}
          <button type="submit"  className="forgot-button">Send Reset Link</button>
          
        </form>

        <div className="back-to-login">
          <button onClick={() => navigate("/")}>Back to Login</button>
        </div>
      </div>
    </div>
  );
}
