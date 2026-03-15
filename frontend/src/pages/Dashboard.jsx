import React, { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import "./Dashboard.css";

// === COMPONENTS ===
function UserCredentials({ 
  fullName, setFullName,
  address, setAddress,
  phoneNumber, setPhoneNumber,
  email, setEmail,
  serviceCredentials,
  serviceForm,
  serviceView,
  onOpenService,
  onCreateService,
  onServiceFormChange,
  onSaveService,
  onDeleteService,
  onBackToServices,
  paymentMethods,
  paymentView,
  paymentForm,
  onCreatePayment,
  onOpenPayment,
  onPaymentFormChange,
  onSavePayment,
  onDeletePayment,
  onBackToPayments,
}) {
  const [activeCredentialsTab, setActiveCredentialsTab] = useState("services");
  const isDetailView = serviceView.mode === "edit" || serviceView.mode === "create";
  const isCreateMode = serviceView.mode === "create";
  const isPaymentDetailView = paymentView.mode === "edit" || paymentView.mode === "create";
  const isPaymentCreateMode = paymentView.mode === "create";
  const showingServices = activeCredentialsTab === "services";

  return (
    <div className="user-creds-container">
      <div className="general-creds-container">
        <h3>General User Data</h3>
        <div className="creds-field">
          <label htmlFor="fullName">Name</label>
        <input
            id="fullName"
            type="text"
            placeholder="John Doe"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          />
        </div>

        <div className="creds-field">
          <label htmlFor="address">Address</label>
        <input 
            id="address"
            type="text"
            placeholder="123 Main St, Orlando, FL 32816"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          />
        </div>

        <div className="creds-field">
          <label htmlFor="phoneNumber">Phone Number</label>
        <input 
            id="phoneNumber"
            type="tel"
            placeholder="(407) 555-0123"
            value={phoneNumber}
            onChange={(e) => setPhoneNumber(e.target.value)}
          />
        </div>

        <div className="creds-field">
          <label htmlFor="email">Email</label>
        <input 
            id="email"
            type="email"
            placeholder="name@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          />
        </div>
      </div>

      <div className="services-container">
        <div className="credentials-tabs">
          <button type="button" className={`credentials-tab ${showingServices ? "active" : ""}`} onClick={() => setActiveCredentialsTab("services")}>Services</button>
          <button type="button" className={`credentials-tab ${!showingServices ? "active" : ""}`} onClick={() => setActiveCredentialsTab("payments")}>Payment Info</button>
        </div>
        <div className="credentials-tab-body">
          {showingServices ? (
            !isDetailView ? (
              <div className="services-grid cards-scroll">
                {serviceCredentials.length === 0 ? (
                  <p className="services-empty-state">No credentials saved yet.</p>
                ) : (
                  serviceCredentials.map((service) => (
                    <button type="button" key={service.id} className="service-card" onClick={() => onOpenService(service.id)}>
                      <span className="service-card-name">{service.serviceName || "Unnamed Service"}</span>
                      <span className="service-card-username">@{service.username || "no-username"}</span>
                    </button>
                  ))
                )}
              </div>
            ) : (
              <div className="cards-scroll">
                <div className="service-detail-header">
                  <h3>{isCreateMode ? "Create Service Credential" : "Edit Service Credential"}</h3>
                  <button type="button" className="setting-btn back-services-btn" onClick={onBackToServices}>Back</button>
                </div>
                <div className="creds-field"><label htmlFor="serviceName">Service Name</label><input id="serviceName" type="text" value={serviceForm.serviceName} onChange={(e) => onServiceFormChange("serviceName", e.target.value)} placeholder="Google, Facebook, Github..." /></div>
                <div className="creds-field"><label htmlFor="serviceEmail">Email</label><input id="serviceEmail" type="email" value={serviceForm.email} onChange={(e) => onServiceFormChange("email", e.target.value)} placeholder="name@example.com" /></div>
                <div className="creds-field"><label htmlFor="serviceUsername">Username</label><input id="serviceUsername" type="text" value={serviceForm.username} onChange={(e) => onServiceFormChange("username", e.target.value)} placeholder="username" /></div>
                <div className="creds-field"><label htmlFor="servicePassword">Password</label><input id="servicePassword" type="password" value={serviceForm.password} onChange={(e) => onServiceFormChange("password", e.target.value)} placeholder="password" /></div>
                <div className="creds-field"><label htmlFor="serviceNotes">Notes</label><input id="serviceNotes" type="text" value={serviceForm.notes} onChange={(e) => onServiceFormChange("notes", e.target.value)} placeholder="Security question hints, recovery notes..." /></div>
                <div className="service-detail-actions">
                  <button className="setting-btn" onClick={onSaveService}>{isCreateMode ? "Create Credential" : "Save Changes"}</button>
                  {!isCreateMode && (<button className="setting-btn delete-service-btn" onClick={onDeleteService}>Delete</button>)}
                </div>
              </div>
            )
          ) : !isPaymentDetailView ? (
            <div className="services-grid cards-scroll">
              {paymentMethods.length === 0 ? (
                <p className="services-empty-state">No payment methods saved yet.</p>
              ) : (
                paymentMethods.map((payment) => (
                  <button type="button" key={payment.id} className="service-card" onClick={() => onOpenPayment(payment.id)}>
                    <span className="service-card-name">{payment.cardNickname || "Card"}</span>
                    <span className="service-card-username">{payment.cardholderName || "No cardholder name"}</span>
                    <span className="service-card-username">{payment.maskedCardNumber || "No number"}</span>
                  </button>
                ))
              )}
            </div>
          ) : (
            <div className="cards-scroll">
              <div className="service-detail-header">
                <h3>{isPaymentCreateMode ? "Add Payment Method" : "Edit Payment Method"}</h3>
                <button type="button" className="setting-btn back-services-btn" onClick={onBackToPayments}>Back</button>
              </div>
              <div className="creds-field"><label htmlFor="cardNickname">Card Name</label><input id="cardNickname" type="text" placeholder="Personal Visa" value={paymentForm.cardNickname} onChange={(e) => onPaymentFormChange("cardNickname", e.target.value)} /></div>
              <div className="creds-field"><label htmlFor="cardholderName">Cardholder Name</label><input id="cardholderName" type="text" placeholder="John Doe" value={paymentForm.cardholderName} onChange={(e) => onPaymentFormChange("cardholderName", e.target.value)} /></div>
              <div className="creds-field"><label htmlFor="cardNumber">Card Number</label><input id="cardNumber" type="text" inputMode="numeric" placeholder="4111111111111111" value={paymentForm.cardNumber} onChange={(e) => onPaymentFormChange("cardNumber", e.target.value)} /></div>
              <div className="creds-field"><label htmlFor="expiryMonth">Expiry Month</label><input id="expiryMonth" type="text" inputMode="numeric" placeholder="MM" value={paymentForm.expiryMonth} onChange={(e) => onPaymentFormChange("expiryMonth", e.target.value)} /></div>
              <div className="creds-field"><label htmlFor="expiryYear">Expiry Year</label><input id="expiryYear" type="text" inputMode="numeric" placeholder="YYYY" value={paymentForm.expiryYear} onChange={(e) => onPaymentFormChange("expiryYear", e.target.value)} /></div>
              <div className="creds-field"><label htmlFor="cvv">CVV</label><input id="cvv" type="password" inputMode="numeric" placeholder="123" value={paymentForm.cvv} onChange={(e) => onPaymentFormChange("cvv", e.target.value)} /></div>
              <div className="creds-field"><label htmlFor="billingZip">Billing ZIP</label><input id="billingZip" type="text" placeholder="32816" value={paymentForm.billingZip} onChange={(e) => onPaymentFormChange("billingZip", e.target.value)} /></div>
              <div className="service-detail-actions">
                <button className="setting-btn" onClick={onSavePayment}>{isPaymentCreateMode ? "Add Card" : "Save Card"}</button>
                {!isPaymentCreateMode && (<button className="setting-btn delete-service-btn" onClick={onDeletePayment}>Delete</button>)}
              </div>
            </div>
          )}
        </div>
        {showingServices && !isDetailView && (
          <button className="setting-btn credentials-add-btn" onClick={onCreateService}>Add New Credentials</button>
        )}
        {!showingServices && !isPaymentDetailView && (
          <button className="setting-btn credentials-add-btn" onClick={onCreatePayment}>Add Payment Method</button>
        )}
      </div>
    </div>
  );
}

export default function Dashboard() {
  const defaultServiceForm = {
    id: null,
    serviceName: "",
    email: "",
    username: "",
    password: "",
    notes: "",
  };
  const defaultPaymentForm = {
    id: null,
    cardNickname: "",
    cardholderName: "",
    cardNumber: "",
    expiryMonth: "",
    expiryYear: "",
    cvv: "",
    billingZip: "",
  };
  
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

  const validatePhoneNumber = (value) => {
    // Accepts (407) 555-0123, 407-555-0123, 4075550123, +1 formats
    const phoneRegex = /^(\+1\s?)?(\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}$/;
    return phoneRegex.test(value.trim());
  }

  const validateEmail = (value) => {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(value.trim());
  };

  // add credentials function
  const addUserCredentials = () => {
    setServiceView({ mode: "create", selectedId: null });
    setServiceForm({ ...defaultServiceForm });
  }

  const openServiceCard = (serviceId) => {
    const credential = userCredentialsList.find((service) => service.id === serviceId);
    if (!credential) return;
    setServiceForm({
      id: credential.id,
      serviceName: credential.serviceName || "",
      email: credential.email || "",
      username: credential.username || "",
      password: credential.password || "",
      notes: credential.notes || "",
    });
    setServiceView({ mode: "edit", selectedId: serviceId });
  };

  const handleServiceFormChange = (field, value) => {
    setServiceForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleBackToServices = () => {
    setServiceView({ mode: "list", selectedId: null });
    setServiceForm({ ...defaultServiceForm });
  };

  const saveServiceCredential = () => {
    if (!serviceForm.serviceName.trim()) {
      alert("Service name is required.");
      return;
    }
    if (serviceForm.email && !validateEmail(serviceForm.email)) {
      alert("Please enter a valid email address.");
      return;
    }

    const payload = {
      id: serviceForm.id || crypto.randomUUID(),
      serviceName: serviceForm.serviceName.trim(),
      email: serviceForm.email.trim(),
      username: serviceForm.username.trim(),
      password: serviceForm.password,
      notes: serviceForm.notes.trim(),
      updatedAt: new Date().toISOString(),
    };

    setUserCredentialsList((prev) => {
      if (serviceView.mode === "create") return [...prev, payload];
      return prev.map((service) => (service.id === payload.id ? payload : service));
    });
    handleBackToServices();
  };

  const deleteServiceCredential = () => {
    if (!serviceView.selectedId) return;
    setUserCredentialsList((prev) => prev.filter((service) => service.id !== serviceView.selectedId));
    handleBackToServices();
  };

  const createPaymentMethod = () => {
    setPaymentView({ mode: "create", selectedId: null });
    setPaymentForm({ ...defaultPaymentForm });
  };

  const openPaymentCard = (paymentId) => {
    const payment = paymentMethods.find((method) => method.id === paymentId);
    if (!payment) return;
    setPaymentForm({
      id: payment.id,
      cardNickname: payment.cardNickname || "",
      cardholderName: payment.cardholderName || "",
      cardNumber: payment.cardNumber || "",
      expiryMonth: payment.expiryMonth || "",
      expiryYear: payment.expiryYear || "",
      cvv: payment.cvv || "",
      billingZip: payment.billingZip || "",
    });
    setPaymentView({ mode: "edit", selectedId: paymentId });
  };

  const handlePaymentFormChange = (field, value) => {
    setPaymentForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleBackToPayments = () => {
    setPaymentView({ mode: "list", selectedId: null });
    setPaymentForm({ ...defaultPaymentForm });
  };

  const savePaymentMethod = () => {
    const cardDigits = paymentForm.cardNumber.replace(/\D/g, "");
    if (!paymentForm.cardNickname.trim()) {
      alert("Card name is required.");
      return;
    }
    if (!paymentForm.cardholderName.trim()) {
      alert("Cardholder name is required.");
      return;
    }
    if (cardDigits.length < 12 || cardDigits.length > 19) {
      alert("Please enter a valid card number.");
      return;
    }

    const payload = {
      id: paymentForm.id || crypto.randomUUID(),
      cardNickname: paymentForm.cardNickname.trim(),
      cardholderName: paymentForm.cardholderName.trim(),
      cardNumber: cardDigits,
      maskedCardNumber: `**** **** **** ${cardDigits.slice(-4)}`,
      expiryMonth: paymentForm.expiryMonth.trim(),
      expiryYear: paymentForm.expiryYear.trim(),
      cvv: paymentForm.cvv.trim(),
      billingZip: paymentForm.billingZip.trim(),
      updatedAt: new Date().toISOString(),
    };

    setPaymentMethods((prev) => {
      if (paymentView.mode === "create") return [...prev, payload];
      return prev.map((method) => (method.id === payload.id ? payload : method));
    });
    handleBackToPayments();
  };

  const deletePaymentMethod = () => {
    if (!paymentView.selectedId) return;
    setPaymentMethods((prev) => prev.filter((method) => method.id !== paymentView.selectedId));
    handleBackToPayments();
  };

  const handleSaveGeneralUserData = () => {
    localStorage.setItem("fullName", fullName); // persistence
    localStorage.setItem("address", address); // persistence
    localStorage.setItem("phoneNumber", phoneNumber); // persistence
    localStorage.setItem("email", email); // persistence
    localStorage.setItem("userCredentialsList", JSON.stringify(userCredentialsList)); // persistence
    localStorage.setItem("userPaymentMethods", JSON.stringify(paymentMethods)); // persistence

    setShowUserCredentials(false)
  };

  useEffect(() => {
    localStorage.setItem("userCredentialsList", JSON.stringify(userCredentialsList));
  }, [userCredentialsList]);

  useEffect(() => {
    localStorage.setItem("userPaymentMethods", JSON.stringify(paymentMethods));
  }, [paymentMethods]);

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
            <button className="modal-close" onClick={handleSaveGeneralUserData} aria-label="Close settings">✖</button>
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
              <div className="user-credentials-body">
                <UserCredentials 
                fullName={fullName} setFullName={setFullName} 
                address={address} setAddress={setAddress}
                phoneNumber={phoneNumber} setPhoneNumber={setPhoneNumber}
                email={email} setEmail={setEmail}
                serviceCredentials={userCredentialsList}
                serviceForm={serviceForm}
                serviceView={serviceView}
                onOpenService={openServiceCard}
                onCreateService={addUserCredentials}
                onServiceFormChange={handleServiceFormChange}
                onSaveService={saveServiceCredential}
                onDeleteService={deleteServiceCredential}
                onBackToServices={handleBackToServices}
                paymentMethods={paymentMethods}
                paymentView={paymentView}
                paymentForm={paymentForm}
                onCreatePayment={createPaymentMethod}
                onOpenPayment={openPaymentCard}
                onPaymentFormChange={handlePaymentFormChange}
                onSavePayment={savePaymentMethod}
                onDeletePayment={deletePaymentMethod}
                onBackToPayments={handleBackToPayments}
              />
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

          </div>
        </div>
      )}

    </div>
  );
}


