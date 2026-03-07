import React, { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
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

  // verify user values
  const [password, setPassword] = useState("");
  const [didUserVerifyIdentity, setDidUserVerifyIdentity] = useState(false);

  const activeChat = conversations.find((c) => c.id === activeChatId);
  const chatListRef = useRef(null);
  const bottomRef = useRef(null);
  const navigate = useNavigate();
  const activeChatIdRef = useRef(activeChatId);

  //Store llive frames
  const [liveFrame, setLiveFrame] = useState(null);
  const socketRef = useRef(null);

  const [isAgentRunning, setIsAgentRunning] = useState(false);
  const isAgentRunningRef = useRef(false);
  const chatSocketRef = useRef(null);
  const [agentSessionsByChat, setAgentSessionsByChat] = useState({});
  const [currentRunSessionId, setCurrentRunSessionId] = useState(null);
  const currentRunSessionIdRef = useRef(null);

  useEffect(() => {
    activeChatIdRef.current = activeChatId;
  }, [activeChatId]);

  useEffect(() => {
    isAgentRunningRef.current = isAgentRunning;
  }, [isAgentRunning]);

  useEffect(() => {
    currentRunSessionIdRef.current = currentRunSessionId;
  }, [currentRunSessionId]);

  const createTextMessage = (text, isUser, channel = "main") => ({
    id: crypto.randomUUID(),
    type: "text",
    text,
    isUser,
    channel,
  });

  const appendMessageToChat = (chatId, text, isUser, channel = "main") => {
    setConversations((prev) =>
      prev.map((chat) =>
        chat.id === chatId
          ? {
              ...chat,
              messages: [...chat.messages, createTextMessage(text, isUser, channel)],
              title: chat.messages.length === 0 && isUser ? text.slice(0, 20) : chat.title,
            }
          : chat
      )
    );
  };

  const startAgentSession = (chatId, prompt) => {
    const sessionId = crypto.randomUUID();
    setAgentSessionsByChat((prev) => ({
      ...prev,
      [chatId]: [
        ...(prev[chatId] || []),
        {
          id: sessionId,
          prompt,
          logs: [],
          chatMessages: [],
          status: "running",
        },
      ],
    }));
    return sessionId;
  };

  const appendAgentLogLine = (chatId, sessionId, line) => {
    setAgentSessionsByChat((prev) => ({
      ...prev,
      [chatId]: (prev[chatId] || []).map((session) =>
        session.id === sessionId
          ? { ...session, logs: [...session.logs, line] }
          : session
      ),
    }));
  };

  const appendSessionChatMessage = (chatId, sessionId, text, isUser) => {
    setAgentSessionsByChat((prev) => ({
      ...prev,
      [chatId]: (prev[chatId] || []).map((session) =>
        session.id === sessionId
          ? {
              ...session,
              chatMessages: [...session.chatMessages, createTextMessage(text, isUser, "chat-socket")],
            }
          : session
      ),
    }));
  };

  const markSessionFinished = (chatId, sessionId) => {
    setAgentSessionsByChat((prev) => ({
      ...prev,
      [chatId]: (prev[chatId] || []).map((session) =>
        session.id === sessionId
          ? { ...session, status: "finished" }
          : session
      ),
    }));
  };

  const sendThroughChatSocket = (text) => {
    const socket = chatSocketRef.current;
    if (!socket || !text.trim()) return;

    if (socket.readyState === WebSocket.OPEN) {
      socket.send(text);
      return;
    }

    if (socket.readyState === WebSocket.CONNECTING) {
      socket.addEventListener(
        "open",
        () => {
          socket.send(text);
        },
        { once: true }
      );
    }
  };

  {/*}
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
    var response = await axios.post("/api/start_agent", {
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
  */}
  const handleSend = async () => {
    if (!input.trim()) return;

    const currentInput = input;
    setInput("");
    const selectedChatId = activeChatIdRef.current;

    // 1. While agent is running, route future chats to current run session
    if (isAgentRunning) {
      const runningSessionId = currentRunSessionIdRef.current;
      if (runningSessionId) {
        appendSessionChatMessage(selectedChatId, runningSessionId, currentInput, true);
      }
      sendThroughChatSocket(currentInput);
      return;
    }

    // 2. Agent is not running: start a new run session
    const sessionId = startAgentSession(selectedChatId, currentInput);

    // 3. Start a read-only live video run
    if (socketRef.current) socketRef.current.close();

    const encodedPrompt = encodeURIComponent(currentInput);
    const wsVideoUrl = `ws://localhost:8000/ws/stream/${selectedChatId}?prompt=${encodedPrompt}`;
    socketRef.current = new WebSocket(wsVideoUrl);
    
    setIsAgentRunning(true);
    setCurrentRunSessionId(sessionId);

    socketRef.current.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      
      if (msg.type === "FRAME") {
        setLiveFrame(`data:image/jpeg;base64,${msg.data}`);
      } else if (msg.type === "STATUS") {
        appendAgentLogLine(selectedChatId, sessionId, `STATUS: ${msg.content}`);
      } else if (msg.type === "LOG") {
        appendAgentLogLine(selectedChatId, sessionId, `${msg.source}: ${msg.content}`);
      }
    };

    socketRef.current.onclose = () => {
      setLiveFrame(null); // Clear video when finished
      appendAgentLogLine(selectedChatId, sessionId, "STATUS: Agent finished task.");
      markSessionFinished(selectedChatId, sessionId);
      setIsAgentRunning(false);
      setCurrentRunSessionId(null);
      console.log("Agent finished task.");
    };
  };

  const handleNewChat = () => {
    const newChat = {
      id: crypto.randomUUID(),
      title: `Browse ${conversations.length + 1}`,
      messages: [createTextMessage("How can I be of assistance today?", false)]
    };

    setConversations((prev) => [...prev, newChat]);
    setAgentSessionsByChat((prev) => ({ ...prev, [newChat.id]: [] }));
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

  const handleGetUserInfo = async () => {
    const token = localStorage.getItem('token');
    const response = await fetch('/api/users/', {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      }
    });

    const data = await response.json();
    console.log(data);
    if (data.error === '') {
      setFirstname(data.firstname);
    } else {
      console.log(data.error);
    }
  };

  useEffect(() => {
    handleGetUserInfo();
  }, []);

  useEffect(() => {
    const token = localStorage.getItem('token') || '';
    const wsChatUrl = `ws://localhost:8000/ws/chat/1?token=${encodeURIComponent(token)}`;
    const chatSocket = new WebSocket(wsChatUrl);
    chatSocketRef.current = chatSocket;

    chatSocket.onmessage = (event) => {
      const chatId = activeChatIdRef.current;
      const runningSessionId = currentRunSessionIdRef.current;

      if (isAgentRunningRef.current && runningSessionId) {
        appendSessionChatMessage(chatId, runningSessionId, event.data, false);
        return;
      }

      appendMessageToChat(chatId, event.data, false, "chat-socket");
    };

    chatSocket.onerror = (error) => {
      console.error('Chat socket error:', error);
    };

    chatSocket.onclose = () => {
      console.log('Chat socket closed.');
    };

    return () => {
      if (chatSocketRef.current) {
        chatSocketRef.current.close();
        chatSocketRef.current = null;
      }

      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }
    };
  }, []);

  const handleLogout = () => {
    localStorage.removeItem('token');
    navigate("/");
  }

  // verify user identity to show credentials
  const verifyUser = async () => {
    try {
      const token = localStorage.getItem('token');
      if (!token || token === 'undefined' || token === 'null') {
        alert('Your session expired. Please log in again.');
        navigate('/');
        return;
      }
      const response = await fetch('/api/users/verify/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ password }),
      });
      const data = await response.json();

      if (data.verified === true && data.error === '') {
        // show user credentials on page
        setDidUserVerifyIdentity(true);
        console.log(didUserVerifyIdentity);
      } else {
        // unsuccessful - try again
        setDidUserVerifyIdentity(false);
        alert(data.error || 'Verification failed.');

      }
    } catch (err) {
      console.error(err);
      alert('Verification failed. Try again.');       
    }
  };

  // add credentials function
  const addUserCredentials = () => {
    alert("This needds to be implemented!!");
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeChat.messages]);

  const mainLaneMessages = activeChat.messages.filter((msg) => msg.channel !== "chat-socket");
  const activeChatSessions = agentSessionsByChat[activeChatId] || [];

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
          <h2 className="welcome-text">Welcome, {firstname}!</h2>
        )}

        {mainLaneMessages.map((msg, index) => (
          <div key={msg.id || index} className={msg.isUser ? "chat-user" : "chat-system"}>
            {msg.text}
          </div>
        ))}

        {activeChatSessions.map((session) => (
          <div key={session.id} className="agent-session-block">
            <div className="chat-user">{session.prompt}</div>

            {session.logs.length > 0 && (
              <div className="chat-system agent-log-bundle">
                <details className="agent-log-details">
                  <summary>Agent Status Logs ({session.logs.length})</summary>
                  <div className="agent-log-content">
                    {session.logs.map((line, lineIndex) => (
                      <div key={`${session.id}-line-${lineIndex}`} className="agent-log-line">
                        {line}
                      </div>
                    ))}
                  </div>
                </details>
              </div>
            )}

            {session.status === "running" ? (
              <div className="agent-running-badge">● Agent running...</div>
            ) : (
              <div className="agent-finished-badge">✓ Agent finished running</div>
            )}

            {session.status === "running" && liveFrame && session.id === currentRunSessionId && (
              <div className="live-browser-container">
                <div className="browser-header">Live Agent View</div>
                <img src={liveFrame} alt="Browser Stream" className="browser-frame" />
              </div>
            )}

            {session.chatMessages.length > 0 && (
              <div className="chat-socket-lane">
                {session.chatMessages.map((msg, index) => (
                  <div key={msg.id || index} className={msg.isUser ? "chat-user" : "chat-system"}>
                    {msg.text}
                  </div>
                ))}
              </div>
            )}
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
        <div className="modal-overlay" >
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

            {/* Account Options */}
            <h3>Account Settings</h3>
            <button className="setting-btn">Reset Password</button>
            <br/>
            <button className="setting-btn">Delete Account</button>
            <br/><br/>

            <button className="save-btn" onClick={handleSaveSettings}>Save Settings</button>
          </div>
        </div>
      )}


      {/* ---------- USER CREDENTIALS MODAL ---------- */}
      {showUserCredentials && (
        <div className="modal-overlay">
          <div className="modal-content user-credentials-modal">
            <button className="modal-close" onClick={() => setShowUserCredentials(false)} aria-label="Close user credentials">✖</button>
            <h2 className="modal-title">User Credentials</h2>
            <hr className="modal-title-divider"/>

            {/* VERIFY USER'S IDENTITY BEFORE REVELAING CREDENTIALS */}
            {didUserVerifyIdentity ? (
              // TRUE - show the previously defined user credentials
              <div>
                <h2>SHOW USER CREDENTIALS</h2>
              </div>
            ) : (
              // FALSE - prompt user to verify their identity first
              <div className="password-verification-group">
                <h3 className="password-prompt">Please enter your password.</h3>
                <input 
                  className="small-input password-input" 
                  placeholder="Your Password" 
                  type="password" 
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}  
                ></input>
                <button className="setting-btn verify-identity-btn" type="submit" onClick={verifyUser}>Verify Identity</button>
              </div>
            )}

            <br/>

            {/* Add user credentials button - should be available either way */}
            <button className="setting-btn" onClick={addUserCredentials}>Add New Credentials</button>
          </div>
        </div>
      )}


    </div>
  );
}


