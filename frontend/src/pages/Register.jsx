import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import "./Register.css"; // optional, you can style separately

export default function Register() {
  const navigate = useNavigate();

  const [Username, setUsername] = useState("");
  const [Password, setPassword] = useState("");
  const [Email, setEmail] = useState("");
  const [FirstName, setFirstName] = useState("");
  const [LastName, setLastName] = useState("");
  const [message, setMessage] = useState("");

  useEffect (() => {
    setMessage('');
  })


  const handleRegister = async (e) => {
    e.preventDefault();
    const headers = {
      'Content-Type': 'application/json' // Include the token in the Authorization header
    };

    const response = await fetch('http://localhost:8000/api/users/insert/', {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({ username: Username, firstname: FirstName, lastname: LastName, email: Email, password: Password }), // Sending raw JSON
    });
    
    const data = await response.json();
    if (data.userId) {
      return navigate('/');
    }
    setMessage('Registration failed. ' + (data.error || 'Unknown error') + '. Please try again.');
    return navigate("/register");
  };

  return (
    <div className="register-page">
      <div className="registe-container">
        <h1>Create an Account</h1>

        <form onSubmit={handleRegister} className="register-form">
          <input type="text" placeholder="First Name" className="register-input" onChange={(e) => setFirstName(e.target.value)} />
          <input type="text" placeholder="Last Name" className="register-input" onChange={(e) => setLastName(e.target.value)} />
          <input type="text" placeholder="Username" className="register-input" onChange={(e) => setUsername(e.target.value)} />
          <input type="email" placeholder="Email" className="register-input" onChange={(e) => setEmail(e.target.value)} />
          <input type="password" placeholder="Password" className="register-input" onChange={(e) => setPassword(e.target.value)} />
          {message && (
            <p style={{ color: 'red', fontSize: '14px', marginTop: '10px' }}>
              {message}
            </p>
          )}
          <button type="submit" className="register-button"  >Register</button>
        </form>

        <div className="back-to-login">
          <button onClick={() => navigate("/")}>Back to Login</button>
        </div>
      </div>
    </div>
  );
}
