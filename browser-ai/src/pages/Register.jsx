import React from "react";
import { useNavigate } from "react-router-dom";
import "./Register.css"; // optional, you can style separately

export default function Register() {
  const navigate = useNavigate();

  return (
    <div className="register-page">
      <div className="registe-container">
        <h1>Create an Account</h1>

        <form className="register-form">
          <input type="text" placeholder="Username" className="register-input" />
          <input type="email" placeholder="Email" className="register-input" />
          <input type="password" placeholder="Password" className="register-input" />
          <button type="submit" className="register-button">Register</button>
        </form>

        <div className="back-to-login">
          <button onClick={() => navigate("/")}>Back to Login</button>
        </div>
      </div>
    </div>
  );
}
