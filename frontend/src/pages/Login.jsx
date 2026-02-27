import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import "./Login.css";

export default function Login() {
  const navigate = useNavigate(); // allows navigation between pages

  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [message, setMessage] = React.useState("");

  useEffect(() => {
      // This runs exactly ONCE when the page loads
      setMessage(''); 
    }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();

    const token = localStorage.getItem('token');
    const headers = {
      'Content-Type': 'application/json' // Include the token in the Authorization header
    };

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch('http://localhost:8000/api/users/login/', {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({ username, password }), // Sending raw JSON
    });

    const data = await response.json();
    if (data.error === '') {
      localStorage.setItem('token', data.token);
      navigate("/dashboard");
    } else {
      setMessage('Username or password is incorrect. Please try again.');
    }
  };

  return (
    <div className="login-page">
      <div className="login-container">
        <h1 className="login-title">
          Intelligent Browser Agents
          <br/> 

        </h1>

        <form onSubmit={handleSubmit} className="login-form">
          <input
            type="text"
            placeholder="Username"
            className="login-input"
            onChange={(e) => setUsername(e.target.value)}
          />
          <input
            type="password"
            placeholder="Password"
            className="login-input"
            onChange={(e) => setPassword(e.target.value)}
          />
          {message && (
            <p style={{ color: 'red', fontSize: '14px', marginTop: '10px' }}>
              {message}
            </p>
          )}
        {/* Login Button */}
        <div className="login-button-container">
          <button
            type="submit"
            className="login-button"
          >
            Login
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
