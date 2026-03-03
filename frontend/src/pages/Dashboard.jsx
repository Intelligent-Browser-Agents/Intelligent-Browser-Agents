import React, { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from 'axios'     // messenger between React and FastAPI
import "./Dashboard.css";

export default function Dashboard() {
  
  // ⬅ Stores the settings text
  const [conversations, setConversations] = useState([ { id: crypto.randomUUID(), title: "Browse 1", messages: [] }]);
  const [agentPrompt, setAgentPrompt] = useState(localStorage.getItem("agentPrompt") || "");
  const [activeChatId, setActiveChatId] = useState(conversations[0].id);
  const [showUserCredentials, setShowUserCredentials] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [firstname, setFirstname] = useState("");
  const [input, setInput] = useState("");

  const activeChat = conversations.find((c) => c.id === activeChatId);
  const chatListRef = useRef(null);
  const bottomRef = useRef(null);
  const navigate = useNavigate();

  const handleSend = async() => {
    if (!input.trim()) return;

    // handle user chat
    setConversations((prev) =>
      prev.map((chat) =>
        chat.id === activeChatId
          ? {
              ...chat,
              messages: [...chat.messages, { text: input, isUser: true }],
              title:
                chat.messages.length === 0
                  ? input.slice(0, 20) || "New Chat"
                  : chat.title,
            }
          : chat
      )
    );
    setInput("");

    // send input to server to start app.py using this prompt
    var response = await axios.post("http://localhost:8000/start_agent", {
      user_input: input
    });

    //! TEST
    console.log(response);

    // make a agent chat bubble with output  
    setConversations((prev) =>
      prev.map((chat) =>
        chat.id === activeChatId ? {
            ...chat,
            messages: [...chat.messages, { text: response.data?.STDOUT, isUser: false }],
            title:
              chat.messages.length === 0
                ? response.data?.STDOUT.slice(0, 20) || "New Chat"
                : chat.title,
        }: chat
      )
    );
  };

  const handleNewChat = () => {
    const newChat = {
      id: crypto.randomUUID(),
      title: `Browse ${conversations.length + 1}`,
      messages: [{ text: "How can I be of assistance today?", isUser: false }]
    };

    setConversations((prev) => [...prev, newChat]);
    setActiveChatId(newChat.id);

    setTimeout(() => {
      chatListRef.current?.scrollTo({
        top: chatListRef.current.scrollHeight,
        behavior: "smooth",
      });
    }, 50);
  };

  const handleKeyPress = (e) => {
    if (e.key === "Enter") handleSend();
  };

  const handleSaveSettings = () => {
    localStorage.setItem("agentPrompt", agentPrompt); // persistence
    setShowSettings(false); // close modal
  };

  const handleGetFirstname = async () => {
    const token = localStorage.getItem('token');
    const response = await fetch('http://localhost:8000/api/users/', {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
    });

    const data = await response.json();
    if (data.error === '') {
      setFirstname(data.firstname);
    } else {
      console.log(data.error);
    }
  };

  useEffect(() => {
    handleGetFirstname();
  }, []);

  const handleLogout = () => {
    localStorage.removeItem('token');
    navigate("/");
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeChat.messages]);

  return (
    <div className="dashboard-container">
      <button
        className="mobile-menu-btn"
        onClick={() => setMobileMenuOpen((prev) => !prev)}
        aria-label={mobileMenuOpen ? "Close navigation menu" : "Open navigation menu"}
      >
        <span className="mobile-menu-icon" aria-hidden="true">&#9776;</span>
      </button>
      {mobileMenuOpen && (
        <div className="mobile-drawer-overlay" onClick={() => setMobileMenuOpen(false)} />
      )}
      
      {/* Sidebar */}
      <aside className={`dashboard-sidebar ${mobileMenuOpen ? "mobile-open" : ""}`}>
        <h1 className="dashboard-title">Intelligent Browser Agents</h1>

        <button className="sidebar-btn" onClick={() => { handleNewChat(); setMobileMenuOpen(false); }}>
          ＋ New Chat
        </button>
        
        <button className="sidebar-btn" onClick={() => { setShowSettings(true); setMobileMenuOpen(false); }}>
          Settings
        </button>

        <button className="sidebar-btn" onClick={() => { setShowUserCredentials(true); setMobileMenuOpen(false); }}>User Credentials</button>
        <button onClick={() => { handleLogout(); setMobileMenuOpen(false); }} className="sidebar-btn">Logout</button>

        <div className="chat-list" ref={chatListRef}>
          {conversations.map((chat) => (
            <div
              key={chat.id}
              className={`chat-item ${
                chat.id === activeChatId ? "active-chat" : ""
              }`}
              onClick={() => {
                setActiveChatId(chat.id);
                setMobileMenuOpen(false);
              }}
            >
              {chat.title}
            </div>
          ))}
        </div>
      </aside>

      {/* Main Chat */}
      <main className="dashboard-main">
        {activeChat.messages.length === 0 && (
          <h2 className="welcome-text">Welcome {firstname}</h2>
        )}

        {activeChat.messages.map((msg, index) => (
          <div key={index} className={msg.isUser ? "chat-user" : "chat-system"}>
            {msg.text}
          </div>
        ))}
        <div ref={bottomRef}></div>

      </main>

      {/* Input Bar */}
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

      {/* ---------- SETTINGS MODAL ---------- */}
      {showSettings && (
        <div className="modal-overlay" onClick={() => setShowSettings(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={() => setShowSettings(false)} aria-label="Close settings">✖</button>
            <h2 className="modal-title">Settings</h2>

            <label className="modal-label">Agent Prompt</label>
            <textarea
              className="modal-textarea"
              placeholder="Type here..."
              value={agentPrompt}
              onChange={(e) => setAgentPrompt(e.target.value)}
            />

            <button className="save-btn" onClick={handleSaveSettings}>Save Settings</button>
          </div>
        </div>
      )}


      {/* ---------- USER CREDENTIALS MODAL ---------- */}
      {showUserCredentials && (
        <div className="modal-overlay" onClick={() => setShowUserCredentials(false)}>
          <div className="modal-content">
            <button className="modal-close" onClick={() => setShowUserCredentials(false)} aria-label="Close user credentials">✖</button>
          </div>
        </div>
      )}


    </div>
  );
}



