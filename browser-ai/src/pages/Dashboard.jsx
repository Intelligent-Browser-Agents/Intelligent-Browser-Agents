import React from "react";
import "./Dashboard.css";

export default function Dashboard() {
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
        <h2>Welcome Guest</h2>
      </main>

      {/* INPUT BAR */}
      <div className="dashboard-input-bar">
        <input className="dashboard-input" placeholder="Start browsing..." />
        <button className="dashboard-input-btn">＋</button>
        <button className="dashboard-input-btn">🎤</button>
      </div>
    </div>
  );
}