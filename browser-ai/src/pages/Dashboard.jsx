import React, { useState } from "react";
import "./Dashboard.css";

export default function Dashboard() {
  const [message, setMessage] = useState("");
  const [chat, setChat] = useState([]);

  const handleSend = () => {
    if (!message.trim()) return;

    setChat((prev) => [...prev, message]);
    setMessage("");
  };

  const handleKeyPress = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="dashboard-container">
      {/* LEFT SIDEBAR */}
      <aside className="dashboard-sidebar">
        <h1 className="dashboard-title">Browser AI</h1>
        <button className="sidebar-btn">＋ New Browse</button>
        <button className="sidebar-btn">⚙️ Settings</button>
        <button className="sidebar-btn">👤 User Credentials</button>
        <button className="sidebar-btn">↪ Logout</button>
      </aside>

      {/* MAIN CONTENT AREA */}
      <main className="dashboard-main">
        {chat.map((msg, index) => (
          <div key={index} className="chat-bubble">
            {msg}
          </div>
        ))}

        {chat.length === 0 && <h2>Welcome Guest</h2>}
      </main>

      {/* INPUT BAR */}
      <div className="dashboard-input-bar">
        <input
          className="dashboard-input"
          placeholder="Start browsing..."
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyPress}
        />
        <button className="dashboard-input-btn" onClick={handleSend}>＋</button>
      </div>
    </div>
  );
}
