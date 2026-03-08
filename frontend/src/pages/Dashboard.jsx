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

  //Store llive frames
  const [liveFrame, setLiveFrame] = useState(null);
  const socketRef = useRef(null);

  // User Credentials Values
  const [fullName, setFullName] = useState("");
  const [address, setAddress] = useState("");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [email, setEmail] = useState("");
  const [userCredentialsList, setUserCredentialsList] = useState([])

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

    // 🛑 STOP: Close any existing ghost connections first
    if (socketRef.current) {
      console.log("Closing existing socket...");
      socketRef.current.close();
    }

    const currentInput = input;
    setInput("");

    // 1. Add user message to UI
    setConversations((prev) =>
      prev.map((chat) =>
        chat.id === activeChatId
          ? {
              ...chat,
              messages: [...chat.messages, { text: currentInput, isUser: true }],
              title: chat.messages.length === 0 ? currentInput.slice(0, 20) : chat.title,
            }
          : chat
      )
    );

    // 2. Open WebSocket for the Live Stream
    // If there's an existing socket, close it
    if (socketRef.current) socketRef.current.close();

    const encodedPrompt = encodeURIComponent(currentInput);
    const token = localStorage.getItem('token'); // Use your existing token for ID
    
    // Connect to the new backend endpoint we discussed
    const wsUrl = `ws://localhost:8000/ws/stream/${activeChatId}?prompt=${encodedPrompt}`;
    socketRef.current = new WebSocket(wsUrl);

    socketRef.current.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      
      if (msg.type === "FRAME") {
        setLiveFrame(`data:image/jpeg;base64,${msg.data}`);
      } else if (msg.type === "STATUS") {
        setConversations((prev) =>
        prev.map((chat) =>
          chat.id === activeChatId
            ? {
                ...chat,
                messages: [
                  ...chat.messages, 
                  { 
                    text: msg.content, 
                    isUser: false,
                  }
                ],
              }
            : chat
        )
      );
      } else if (msg.type === "LOG") {
        setConversations((prev) =>
        prev.map((chat) =>
          chat.id === activeChatId
            ? {
                ...chat,
                messages: [
                  ...chat.messages, 
                  { 
                    text: msg.source + ": " + msg.content, 
                    isUser: false,
                  }
                ],
              }
            : chat
        )
      );
      }
    };

    socketRef.current.onclose = () => {
      setLiveFrame(null); // Clear video when finished
      console.log("Agent finished task.");
    };
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
    alert("This needds to be implemented!! (It's ANOTHER modal :D)");
  }

  // User Credentials
  const UserCredentials = () => {

    return (
      <div className="user-creds-container">
        <div className="general-creds-container">
          <h3>General User Data</h3>
          <p>Name</p>
          <input placeholder="Your Full Name"></input>

          <p>Address</p>
          <input placeholder="Your Address"></input>

          <p>Phone Number</p>
          <input placeholder="Your Phone Number"></input>

          <p>Email</p>
          <input placeholder="Your Email"></input>
        </div>

        <div className="services-container">
          <h3>Services</h3>
          {/* 
            todo: a list of credentials which the user has provided so far 
            (by service associated with them.) 
            Username: _______
            Password:________
          */}
        </div>
      </div>
    );
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
          <h2 className="welcome-text">Welcome, {firstname}!</h2>
        )}

        {activeChat.messages.map((msg, index) => (
          <div key={index} className={msg.isUser ? "chat-user" : "chat-system"}>
            {msg.text}
          </div>
        ))}

        {/* 📺 NEW: Live Browser Feed */}
        {liveFrame && (
          <div className="live-browser-container">
            <div className="browser-header">Live Agent View</div>
            <img src={liveFrame} alt="Browser Stream" className="browser-frame" />
          </div>
        )}
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
                <UserCredentials/>
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


