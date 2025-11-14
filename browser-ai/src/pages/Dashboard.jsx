import React, { useState, useRef, useEffect } from "react";
import "./Dashboard.css";

export default function Dashboard() {
  const [input, setInput] = useState("");
  const [chat, setChat] = useState([]);

  const bottomRef = useRef(null);

  const handleSend = () => {
    if (!input.trim()) return;

    setChat((prev) => [...prev, { text: input, isUser: true }]);
    setInput("");
  };

  const handleKeyPress = (e) => {
    if (e.key === "Enter") {
      handleSend();
    }
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat]);

  return (
    <div className="dashboard-container">
      
      <aside className="dashboard-sidebar">
        <h1 className="dashboard-title">Browser AI</h1>
        <button className="sidebar-btn">＋ New Browse</button>
        <button className="sidebar-btn">⚙️ Settings</button>
        <button className="sidebar-btn">👤 User Credentials</button>
        <button className="sidebar-btn">↪ Logout</button>
      </aside>

      <main className="dashboard-main">
        {chat.length === 0 && (
          <h2 className="welcome-text">Welcome Guest</h2>
        )}
        
        {chat.map((msg, index) => (
          <div 
            key={index} 
            className={msg.isUser ? "chat-user" : "chat-system"}
          >
            {msg.text}
          </div>
        ))}
        <div ref={bottomRef}></div>
      </main>

      <div className="dashboard-input-bar">
        <input
          className="dashboard-input"
          placeholder="Start browsing..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyPress}
        />
        <button className="dashboard-bar-btn" onClick={handleSend}>➤</button>
      </div>
    </div>
  );
}