import React, { useState, useRef, useEffect } from "react";
import "./Dashboard.css";

export default function Dashboard() {
  const [input, setInput] = useState("");

  const [showSettings, setShowSettings] = useState(false);

  // ⬅ Stores the settings text
  const [agentPrompt, setAgentPrompt] = useState(
    localStorage.getItem("agentPrompt") || ""
  );

  const [conversations, setConversations] = useState([
    { id: crypto.randomUUID(), title: "Browse 1", messages: [] }
  ]);

  const [activeChatId, setActiveChatId] = useState(conversations[0].id);

  const bottomRef = useRef(null);
  const chatListRef = useRef(null);

  const activeChat = conversations.find((c) => c.id === activeChatId);

  const handleSend = () => {
    if (!input.trim()) return;

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
  };

  const handleNewChat = () => {
    const newChat = {
      id: crypto.randomUUID(),
      title: `Browse ${conversations.length + 1}`,
      messages: [{ text: "New chat started.", isUser: false }]
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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeChat.messages]);

  return (
    <div className="dashboard-container">
      
      {/* Sidebar */}
      <aside className="dashboard-sidebar">
        <h1 className="dashboard-title">Browser AI</h1>

        <button className="sidebar-btn" onClick={handleNewChat}>
          ＋ New Browse
        </button>
        
        <button className="sidebar-btn" onClick={() => setShowSettings(true)}>
          ⚙️ Settings
        </button>

        <button className="sidebar-btn">👤 User Credentials</button>
        <button className="sidebar-btn">↪ Logout</button>

        <div className="chat-list" ref={chatListRef}>
          {conversations.map((chat) => (
            <div
              key={chat.id}
              className={`chat-item ${
                chat.id === activeChatId ? "active-chat" : ""
              }`}
              onClick={() => setActiveChatId(chat.id)}
            >
              {chat.title}
            </div>
          ))}
        </div>
      </aside>

      {/* Main Chat */}
      <main className="dashboard-main">
        {activeChat.messages.length === 0 && (
          <h2 className="welcome-text">Welcome Guest</h2>
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
            <button className="modal-close" onClick={() => setShowSettings(false)}>✖</button>
            <h2>Settings</h2>

            <label>Agent’s Prompt</label>
            <textarea
              placeholder="Type here..."
              value={agentPrompt}
              onChange={(e) => setAgentPrompt(e.target.value)}
            />

            <button className="save-btn" onClick={handleSaveSettings}>
              Save
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
