import React, { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import userNotificationSound from "../../assets/audio/user-notification.mp3";
import agentLogIcon from "../../assets/icons/agent.png";
import executionAgentIcon from "../../assets/icons/agents/execution.png";
import fallbackAgentIcon from "../../assets/icons/agents/fallback.png";
import interactionAgentIcon from "../../assets/icons/agents/interaction.png";
import stdoutLogIcon from "../../assets/icons/log.png";
import orchestrationAgentIcon from "../../assets/icons/agents/orchestration.png";
import statusLogIcon from "../../assets/icons/status.png";
import userLogIcon from "../../assets/icons/agents/user.png";
import verificationAgentIcon from "../../assets/icons/agents/verification.png";
import "./Dashboard.css";

import ThinkingStream, { ThinkingChatBlock } from "../components/ThinkingStream";
import LiveView from "../components/LiveView";
import Brand from "../components/Brand";
import Modal from "../components/Modal";
import SettingsModal from "../components/SettingsModal";
import RunHistory from "../components/RunHistory";
import HitlForm from "../components/HitlForm";
import DocumentsPanel from "../components/DocumentsPanel";
import { api, buildWebSocketUrl, clearToken, getToken } from "../lib/api";

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
  experienceEntries,
  experienceView,
  experienceForm,
  onCreateExperience,
  onOpenExperience,
  onExperienceFormChange,
  onSaveExperience,
  onDeleteExperience,
  onBackToExperience,
}) {
  const [activeCredentialsTab, setActiveCredentialsTab] = useState("services");
  const isDetailView = serviceView.mode === "edit" || serviceView.mode === "create";
  const isCreateMode = serviceView.mode === "create";
  const isPaymentDetailView = paymentView.mode === "edit" || paymentView.mode === "create";
  const isPaymentCreateMode = paymentView.mode === "create";
  const isExperienceDetailView = experienceView.mode === "edit" || experienceView.mode === "create";
  const isExperienceCreateMode = experienceView.mode === "create";
  const showingServices = activeCredentialsTab === "services";
  const showingPayments = activeCredentialsTab === "payments";
  const safeServiceCredentials = Array.isArray(serviceCredentials) ? serviceCredentials : [];
  const safePaymentMethods = Array.isArray(paymentMethods) ? paymentMethods : [];
  const safeExperienceEntries = Array.isArray(experienceEntries) ? experienceEntries : [];

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
          <button type="button" className={`credentials-tab ${showingPayments ? "active" : ""}`} onClick={() => setActiveCredentialsTab("payments")}>Payment Info</button>
          <button type="button" className={`credentials-tab ${activeCredentialsTab === "experience" ? "active" : ""}`} onClick={() => setActiveCredentialsTab("experience")}>Experience</button>
          <button type="button" className={`credentials-tab ${activeCredentialsTab === "documents" ? "active" : ""}`} onClick={() => setActiveCredentialsTab("documents")}>Documents</button>
        </div>
        <div className="credentials-tab-body">
          {showingServices ? (
            !isDetailView ? (
              <div className="services-grid cards-scroll">
                {safeServiceCredentials.length === 0 ? (
                  <p className="services-empty-state">No credentials saved yet.</p>
                ) : (
                  safeServiceCredentials.map((service) => (
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
          ) : showingPayments ? (
            !isPaymentDetailView ? (
            <div className="services-grid cards-scroll">
                {safePaymentMethods.length === 0 ? (
                  <p className="services-empty-state">No payment methods saved yet.</p>
                ) : (
                  safePaymentMethods.map((payment) => (
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
              <div className="creds-field"><label htmlFor="billingZip">Billing ZIP</label><input id="billingZip" type="text" placeholder="32816" value={paymentForm.billingZip} onChange={(e) => onPaymentFormChange("billingZip", e.target.value)} /></div>
              {/* No CVV field. Retaining a card verification value is prohibited by
                  PCI-DSS regardless of storage medium, so the server strips it and
                  nothing here can persist it. The input that used to sit here was
                  dead: it was never saved and never reached the agent. */}
              <p className="creds-note">
                For security, the CVV is never saved. You will be asked for it at the moment
                a payment is made.
              </p>
              <div className="service-detail-actions">
                <button className="setting-btn" onClick={onSavePayment}>{isPaymentCreateMode ? "Add Card" : "Save Card"}</button>
                {!isPaymentCreateMode && (<button className="setting-btn delete-service-btn" onClick={onDeletePayment}>Delete</button>)}
                </div>
              </div>
            )
          ) : activeCredentialsTab === "documents" ? (
            <DocumentsPanel />
          ) : !isExperienceDetailView ? (
            <div className="services-grid cards-scroll">
              {safeExperienceEntries.length === 0 ? (
                <p className="services-empty-state">No experience entries saved yet.</p>
              ) : (
                safeExperienceEntries.map((entry) => (
                  <button type="button" key={entry.id} className="service-card" onClick={() => onOpenExperience(entry.id)}>
                    <span className="service-card-name">{entry.title || "Untitled Experience"}</span>
                    <span className="service-card-username">{entry.organization || "No organization"}</span>
                    <span className="service-card-username">{entry.entryType === "education" ? "Education" : "Work"}</span>
                  </button>
                ))
              )}
            </div>
          ) : (
            <div className="cards-scroll">
              <div className="service-detail-header">
                <h3>{isExperienceCreateMode ? "Add Experience Entry" : "Edit Experience Entry"}</h3>
                <button type="button" className="setting-btn back-services-btn" onClick={onBackToExperience}>Back</button>
              </div>
              <div className="creds-field"><label htmlFor="experienceType">Entry Type</label><select id="experienceType" value={experienceForm.entryType} onChange={(e) => onExperienceFormChange("entryType", e.target.value)}><option value="work">Work</option><option value="education">Education</option></select></div>
              <div className="creds-field"><label htmlFor="experienceTitle">{experienceForm.entryType === "education" ? "Degree / Program" : "Job Title"}</label><input id="experienceTitle" type="text" placeholder={experienceForm.entryType === "education" ? "B.S. Computer Science" : "Software Engineer"} value={experienceForm.title} onChange={(e) => onExperienceFormChange("title", e.target.value)} /></div>
              <div className="creds-field"><label htmlFor="experienceOrg">{experienceForm.entryType === "education" ? "School / Institution" : "Company"}</label><input id="experienceOrg" type="text" placeholder={experienceForm.entryType === "education" ? "University of Central Florida" : "Google"} value={experienceForm.organization} onChange={(e) => onExperienceFormChange("organization", e.target.value)} /></div>
              <div className="creds-field"><label htmlFor="experienceLocation">Location</label><input id="experienceLocation" type="text" placeholder="Orlando, FL" value={experienceForm.location} onChange={(e) => onExperienceFormChange("location", e.target.value)} /></div>
              <div className="creds-field"><label htmlFor="experienceStartDate">Start Date</label><input id="experienceStartDate" type="month" value={experienceForm.startDate} onChange={(e) => onExperienceFormChange("startDate", e.target.value)} /></div>
              <div className="creds-field"><label htmlFor="experienceEndDate">End Date</label><input id="experienceEndDate" type="month" value={experienceForm.endDate} disabled={experienceForm.isCurrent} onChange={(e) => onExperienceFormChange("endDate", e.target.value)} /></div>
              <div className="creds-field creds-checkbox-row"><label htmlFor="experienceCurrent">Current</label><input id="experienceCurrent" type="checkbox" checked={experienceForm.isCurrent} onChange={(e) => onExperienceFormChange("isCurrent", e.target.checked)} /></div>
              <div className="creds-field"><label htmlFor="experienceDescription">Description</label><textarea id="experienceDescription" className="creds-textarea" placeholder="Responsibilities, achievements, or relevant coursework..." value={experienceForm.description} onChange={(e) => onExperienceFormChange("description", e.target.value)} /></div>
              <div className="service-detail-actions">
                <button className="setting-btn" onClick={onSaveExperience}>{isExperienceCreateMode ? "Add Experience" : "Save Experience"}</button>
                {!isExperienceCreateMode && (<button className="setting-btn delete-service-btn" onClick={onDeleteExperience}>Delete</button>)}
              </div>
            </div>
          )}
        </div>
        {showingServices && !isDetailView && (
          <button className="setting-btn credentials-add-btn" onClick={onCreateService}>Add New Credentials</button>
        )}
        {showingPayments && !isPaymentDetailView && (
          <button className="setting-btn credentials-add-btn" onClick={onCreatePayment}>Add Payment Method</button>
        )}
        {activeCredentialsTab === "experience" && !isExperienceDetailView && (
          <button className="setting-btn credentials-add-btn" onClick={onCreateExperience}>Add Experience Entry</button>
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
    // No `cvv`: it is never stored, so there is no form state to hold it.
    billingZip: "",
  };
  const defaultExperienceForm = {
    id: null,
    entryType: "work",
    title: "",
    organization: "",
    location: "",
    startDate: "",
    endDate: "",
    isCurrent: false,
    description: "",
  };
  
  const [conversations, setConversations] = useState([ { id: crypto.randomUUID(), title: "Browse 1", messages: [] }]);
  const [activeChatId, setActiveChatId] = useState(conversations[0].id);
  const [showUserCredentials, setShowUserCredentials] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [thoughtsTab, setThoughtsTab] = useState("thinking");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [firstname, setFirstname] = useState("");

  // Credential-vault state is loaded from the server, not localStorage. Storing
  // third-party passwords, full card numbers, and CVVs in localStorage put them
  // within reach of any script on the page; the CVV in particular must never be
  // persisted at all.
  const [fullName, setFullName] = useState("");

  const [input, setInput] = useState("");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [address, setAddress] = useState("");
  const [email, setEmail] = useState("");
  const [credentialsError, setCredentialsError] = useState("");

  // verify user values
  const [password, setPassword] = useState("");
  const [didUserVerifyIdentity, setDidUserVerifyIdentity] = useState(false);

  const activeChat = conversations.find((c) => c.id === activeChatId) || conversations[0];
  const chatListRef = useRef(null);
  const bottomRef = useRef(null);
  const thoughtsStreamRef = useRef(null);
  const navigate = useNavigate();
  const activeChatIdRef = useRef(activeChatId);

  //Store live frames
  // Whether the current/last run produced a live stream. Frames themselves
  // never touch state: LiveView paints binary frames into a canvas via refs,
  // so streaming does not re-render the Dashboard.
  const [hasStream, setHasStream] = useState(false);
  // One socket per run session, so several chats can run concurrently.
  // Each entry is a {current: WebSocket} holder, shaped like a ref so
  // LiveView can consume it directly.
  const runSocketsRef = useRef(new Map());
  const notificationAudioRef = useRef(null);

  const chatSocketRef = useRef(null);
  const [agentSessionsByChat, setAgentSessionsByChat] = useState({});
  const agentSessionsByChatRef = useRef({});
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  const [showBatchComposer, setShowBatchComposer] = useState(false);

  const [userCredentialsList, setUserCredentialsList] = useState([]);
  const [paymentMethods, setPaymentMethods] = useState([]);
  const [serviceForm, setServiceForm] = useState({ ...defaultServiceForm });
  const [serviceView, setServiceView] = useState({ mode: "list", selectedId: null });
  const [paymentForm, setPaymentForm] = useState({ ...defaultPaymentForm });
  const [paymentView, setPaymentView] = useState({ mode: "list", selectedId: null });
  const [experienceEntries, setExperienceEntries] = useState([]);
  const [experienceView, setExperienceView] = useState({ mode: "list", selectedId: null });
  const [experienceForm, setExperienceForm] = useState(defaultExperienceForm);


  // buildWebSocketUrl now lives in lib/api.js. `chatIdToStableInt` is gone with
  // it: hashing a browser-generated chat UUID into a fake "user_id" for the
  // backend's HITL map collided across users and reset on every page reload. The
  // server keys HITL by the authenticated user id from the token instead.


  useEffect(() => {
    activeChatIdRef.current = activeChatId;
  }, [activeChatId]);

  useEffect(() => {
    agentSessionsByChatRef.current = agentSessionsByChat;
  }, [agentSessionsByChat]);

  const findRunningSession = (chatId) =>
    (agentSessionsByChatRef.current[chatId] || []).find(
      (session) => session.status === "running"
    ) || null;

  useEffect(() => {
    const audio = new Audio(userNotificationSound);
    audio.preload = "auto";
    notificationAudioRef.current = audio;

    return () => {
      audio.pause();
      notificationAudioRef.current = null;
    };
  }, []);

  const createTextMessage = (text, isUser, channel = "main") => ({
    id: crypto.randomUUID(),
    type: "text",
    text,
    isUser,
    channel,
  });

  // Logs pass through untouched apart from trimming. The old sanitizer
  // collapsed whitespace and rewrote around colons, which mangled tracebacks
  // and JSON in the one panel meant for debugging.
  const sanitizeAgentLogLine = (line) => String(line ?? "").trim();

  // Keep sessions bounded so a very long run cannot grow state without limit.
  const MAX_SESSION_LOG_LINES = 1500;

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

  const buildAgentCredentialsPayload = () => ({
    fullName: fullName || "",
    address: address || "",
    phoneNumber: phoneNumber || "",
    email: email || "",
    userCredentialsList: Array.isArray(userCredentialsList) ? userCredentialsList : [],
    userPaymentMethods: Array.isArray(paymentMethods) ? paymentMethods : [],
    userExperienceEntries: Array.isArray(experienceEntries) ? experienceEntries : [],
  });

  /** Hydrate the credential form from the server-side encrypted vault. */
  const loadCredentialsFromServer = async () => {
    setCredentialsError("");
    try {
      const { credentials } = await api.readCredentials();
      const vault = credentials || {};
      setFullName(vault.fullName || "");
      setAddress(vault.address || "");
      setPhoneNumber(vault.phoneNumber || "");
      setEmail(vault.email || "");
      setUserCredentialsList(Array.isArray(vault.userCredentialsList) ? vault.userCredentialsList : []);
      setPaymentMethods(Array.isArray(vault.userPaymentMethods) ? vault.userPaymentMethods : []);
      setExperienceEntries(Array.isArray(vault.userExperienceEntries) ? vault.userExperienceEntries : []);
    } catch (err) {
      setCredentialsError(
        err.status === 503
          ? "Credential storage is not configured on the server (CREDENTIALS_KEY is unset)."
          : err.detail || "Could not load your saved details."
      );
    }
  };

  const startAgentSession = (chatId, prompt) => {
    const sessionId = crypto.randomUUID();
    // The credential blob is deliberately not kept on the session object. It was
    // held in React state for the life of the page, which put saved passwords and
    // card numbers where any component (and React DevTools) could read them.
    setAgentSessionsByChat((prev) => ({
      ...prev,
      [chatId]: [
        ...(prev[chatId] || []),
        {
          id: sessionId,
          runId: null,
          prompt,
          logs: [],
          chatMessages: [],
          status: "running",
          exitReason: "",
          hitl: null,
          itemResults: [],
          startedAt: Date.now(),
          finishedAt: null,
        },
      ],
    }));
    return sessionId;
  };

  const updateSession = (chatId, sessionId, updater) => {
    setAgentSessionsByChat((prev) => ({
      ...prev,
      [chatId]: (prev[chatId] || []).map((session) =>
        session.id === sessionId ? { ...session, ...updater(session) } : session
      ),
    }));
  };

  const appendAgentLogLine = (chatId, sessionId, line) => {
    const sanitizedLine = sanitizeAgentLogLine(line);
    if (!sanitizedLine) {
      return;
    }

    updateSession(chatId, sessionId, (session) => ({
      logs: [...session.logs.slice(-(MAX_SESSION_LOG_LINES - 1)), sanitizedLine],
    }));
  };

  const getAgentLogPresentation = (line) => {
    const prefixes = {
      AGENT: { key: "agent", icon: agentLogIcon, alt: "Agent" },
      STATUS: { key: "status", icon: statusLogIcon, alt: "Status" },
      STDOUT: { key: "stdout", icon: stdoutLogIcon, alt: "Stdout" },
    };
    const iconGroups = [
      { pattern: /^User Request:/i, key: "user", icon: userLogIcon, alt: "User" },
      { pattern: /\[NODE\]:\s*ORCHESTRATOR\b|\[Decision\]/i, key: "orchestration", icon: orchestrationAgentIcon, alt: "Orchestration" },
      { pattern: /\[NODE\]:\s*EXECUTION\b|\[executor\b|\[Executor\b/i, key: "execution", icon: executionAgentIcon, alt: "Execution" },
      { pattern: /\[NODE\]:\s*VERIFICATION\b|\[Verifier\]/i, key: "verification", icon: verificationAgentIcon, alt: "Verification" },
      { pattern: /\[NODE\]:\s*FALLBACK\b|\[Fallback\]/i, key: "fallback", icon: fallbackAgentIcon, alt: "Fallback" },
      { pattern: /\[NODE\]:\s*INTERACTION\b|\[Interaction\]/i, key: "interaction", icon: interactionAgentIcon, alt: "Interaction" },
    ];

    const rawLine = String(line ?? "");
    const match = rawLine.match(/^(AGENT|STATUS|STDOUT):\s*(.*)$/);
    if (!match) {
      return {
        groupKey: null,
        content: rawLine,
        icon: null,
        alt: null,
      };
    }

    const [, source, content] = match;
    const matchedGroup = iconGroups.find(({ pattern }) => pattern.test(content));
    const presentation = matchedGroup ?? prefixes[source];

    return {
      groupKey: presentation.key,
      content,
      icon: presentation.icon,
      alt: presentation.alt,
    };
  };

  const trimRepeatedGroupLabel = (groupKey, content, itemIndex) => {
    if (itemIndex === 0) {
      return content;
    }

    const labelPatterns = {
      orchestration: [/^\[NODE\]:\s*ORCHESTRATOR\s*/i, /^\[Decision\]\s*/i],
      execution: [/^\[NODE\]:\s*EXECUTION\s*/i, /^\[executor\]\s*/i, /^\[Executor\]\s*/],
      verification: [/^\[NODE\]:\s*VERIFICATION\s*/i, /^\[Verifier\]\s*/i],
      fallback: [/^\[NODE\]:\s*FALLBACK\s*/i, /^\[Fallback\]\s*/i],
      interaction: [/^\[NODE\]:\s*INTERACTION\s*/i, /^\[Interaction\]\s*/i],
    };

    const patterns = labelPatterns[groupKey];
    if (!patterns) {
      return content;
    }

    const trimmed = patterns.reduce((value, pattern) => value.replace(pattern, ""), content).trim();
    return trimmed || content;
  };

  const groupAgentLogs = (logs) => logs.reduce((groups, line, lineIndex) => {
    const presentation = getAgentLogPresentation(line);
    const previousGroup = groups[groups.length - 1];

    if (presentation.groupKey && previousGroup?.groupKey === presentation.groupKey) {
      previousGroup.items.push(
        trimRepeatedGroupLabel(
          presentation.groupKey,
          presentation.content,
          previousGroup.items.length
        )
      );
      previousGroup.endLineIndex = lineIndex;
      return groups;
    }

    groups.push({
      groupKey: presentation.groupKey,
      icon: presentation.icon,
      alt: presentation.alt,
      items: [
        presentation.groupKey
          ? trimRepeatedGroupLabel(presentation.groupKey, presentation.content, 0)
          : presentation.content
      ],
      startLineIndex: lineIndex,
      endLineIndex: lineIndex,
    });

    return groups;
  }, []);

  const appendSessionChatMessage = (chatId, sessionId, text, isUser) => {
    updateSession(chatId, sessionId, (session) => ({
      chatMessages: [...session.chatMessages, createTextMessage(text, isUser, "chat-socket")],
    }));
  };

  /**
   * Socket closed. If a structured `run_finished` already set the real status
   * (succeeded / failed / aborted), keep it; a close with no verdict means the
   * run died on us, which is a failure, not "Complete".
   */
  const markSessionClosed = (chatId, sessionId) => {
    updateSession(chatId, sessionId, (session) => ({
      status: session.status === "running" ? "failed" : session.status,
      exitReason:
        session.status === "running"
          ? session.exitReason || "connection closed before the run finished"
          : session.exitReason,
      hitl: null,
      finishedAt: session.finishedAt || Date.now(),
    }));
  };

  const playUserNotification = () => {
    const audio = notificationAudioRef.current;
    if (!audio) return;

    audio.pause();
    audio.currentTime = 0;

    const playPromise = audio.play();
    if (playPromise?.catch) {
      playPromise.catch((err) => {
        console.warn("Unable to play notification sound:", err);
      });
    }
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

  /** Send a HITL reply to a specific running session's socket. */
  const sendReplyToSession = (chatId, session, text) => {
    appendSessionChatMessage(chatId, session.id, text, true);
    const holder = runSocketsRef.current.get(session.id);
    const streamSocket = holder?.current;
    if (streamSocket && streamSocket.readyState === WebSocket.OPEN) {
      streamSocket.send(JSON.stringify({ type: "user_hitl_reply", content: text }));
    } else {
      sendThroughChatSocket(JSON.stringify({ content: text, run_id: session.runId || undefined }));
    }
  };

  /** The Stop button: ask the server to halt this session's run. */
  const stopSession = (chatId, session) => {
    const holder = runSocketsRef.current.get(session.id);
    const streamSocket = holder?.current;
    if (streamSocket && streamSocket.readyState === WebSocket.OPEN) {
      streamSocket.send(JSON.stringify({ type: "abort_run", content: "stop" }));
      appendAgentLogLine(chatId, session.id, "STATUS: Stop requested.");
    }
  };

  const launchRun = (prompt) => {
    const selectedChatId = activeChatIdRef.current;
    const sessionId = startAgentSession(selectedChatId, prompt);

    // Credentials are NOT pushed here. The agent reads them from the caller's
    // own encrypted vault row on the server, so there is nothing to send.
    //
    // The prompt and the bearer token used to travel as query parameters, which
    // put the task text and the credential into every access log on the path. Both
    // now go in the first frame, and the run is keyed to the authenticated user.
    const socket = new WebSocket(buildWebSocketUrl("/ws/stream"));
    // Frames arrive as binary JPEG; LiveView consumes them straight from the
    // socket without base64 or JSON.
    socket.binaryType = "arraybuffer";
    const holder = { current: socket };
    runSocketsRef.current.set(sessionId, holder);

    socket.onopen = () => {
      socket.send(JSON.stringify({
        type: "start",
        token: getToken(),
        prompt,
      }));
    };

    socket.onerror = () => {
      appendAgentLogLine(selectedChatId, sessionId, "STDERR: Connection to the agent failed.");
    };

    socket.onmessage = (event) => {
      // Binary messages are video frames; LiveView has its own listener.
      if (typeof event.data !== "string") return;
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        // A partial or non-JSON frame must not take down the handler.
        return;
      }

      if (msg.type === "run_started") {
        updateSession(selectedChatId, sessionId, () => ({ runId: msg.run_id }));
      } else if (msg.type === "STATUS") {
        appendAgentLogLine(selectedChatId, sessionId, `STATUS: ${msg.content}`);
      } else if (msg.type === "LOG") {
        appendAgentLogLine(selectedChatId, sessionId, `${msg.source}: ${msg.content}`);
      } else if (msg.type === "CLARIFICATION") {
        // Structured HITL: the message plus the labeled fields the agent
        // needs. No log-substring sniffing.
        playUserNotification();
        updateSession(selectedChatId, sessionId, () => ({
          hitl: {
            message: msg.message || "",
            requestedFields: Array.isArray(msg.requested_fields) ? msg.requested_fields : [],
          },
        }));
        appendSessionChatMessage(selectedChatId, sessionId, msg.message, false);
      } else if (msg.type === "HITL_CLOSED") {
        updateSession(selectedChatId, sessionId, () => ({ hitl: null }));
      } else if (msg.type === "RESPONSE") {
        updateSession(selectedChatId, sessionId, () => ({
          hitl: null,
          itemResults: Array.isArray(msg.item_results) ? msg.item_results : [],
        }));
        appendSessionChatMessage(selectedChatId, sessionId, msg.content, false);
      } else if (msg.type === "run_finished") {
        updateSession(selectedChatId, sessionId, () => ({
          status: msg.status || "failed",
          exitReason: msg.exit_reason || "",
          hitl: null,
          finishedAt: Date.now(),
        }));
        setHistoryRefreshKey((key) => key + 1);
      }
    };

    socket.onclose = () => {
      markSessionClosed(selectedChatId, sessionId);
      runSocketsRef.current.delete(sessionId);
    };
  };

  const handleSend = async () => {
    if (!input.trim()) return;

    const currentInput = input;
    setInput("");
    const selectedChatId = activeChatIdRef.current;

    // While this chat has a live run, the input box replies to it.
    const running = findRunningSession(selectedChatId);
    if (running) {
      sendReplyToSession(selectedChatId, running, currentInput);
      return;
    }

    launchRun(currentInput);
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

  // Enter submits; Shift+Enter makes a newline; a composing IME keydown is
  // neither (submitting mid-composition is how CJK input used to fire early).
  const handleKeyPress = (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleGetUserInfo = async () => {
    try {
      const data = await api.me();
      setFirstname(data.firstname);
    } catch {
      // apiFetch redirects to the login page on a 401; nothing to do here.
    }
  };

  useEffect(() => {
    handleGetUserInfo();
  }, []);

  useEffect(() => {
    // The chat socket is a HITL fallback. It authenticates with a first frame; the
    // `token` query parameter it used to send was never validated by the server.
    const chatSocket = new WebSocket(buildWebSocketUrl("/ws/chat"));
    chatSocketRef.current = chatSocket;

    chatSocket.onopen = () => {
      chatSocket.send(JSON.stringify({ type: "auth", token: getToken() }));
    };

    chatSocket.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      // Only structured status replies are expected now. The server no longer
      // broadcasts other clients' text here.
      if (msg.type === "AUTH_OK") return;
      if (msg.type !== "STATUS" || !msg.content) return;

      const chatId = activeChatIdRef.current;
      const running = findRunningSession(chatId);
      if (running) {
        appendSessionChatMessage(chatId, running.id, msg.content, false);
        return;
      }
      appendMessageToChat(chatId, msg.content, false, "chat-socket");
    };

    const runSockets = runSocketsRef.current;
    return () => {
      if (chatSocketRef.current) {
        chatSocketRef.current.close();
        chatSocketRef.current = null;
      }

      // Close every run socket this page owns.
      for (const holder of runSockets.values()) {
        holder.current?.close();
      }
      runSockets.clear();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleLogout = () => {
    clearToken();
    setFirstname("");
    setDidUserVerifyIdentity(false);
    setPassword("");
    navigate("/");
  }

  // verify user identity to show credentials
  const verifyUser = async () => {
    try {
      const data = await api.verifyPassword(password);

      if (data.verified === true) {
        setDidUserVerifyIdentity(true);
        // The password is not needed after this point; holding it keeps the
        // account password in component state for the life of the page.
        setPassword("");
        await loadCredentialsFromServer();
      } else {
        setDidUserVerifyIdentity(false);
        alert(data.error || 'Verification failed.');
      }
    } catch (err) {
      alert(err.detail || 'Verification failed. Try again.');
    }
  };

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
    const credential = (Array.isArray(userCredentialsList) ? userCredentialsList : []).find(
      (service) => service.id === serviceId
    );
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
      const safePrev = Array.isArray(prev) ? prev : [];
      if (serviceView.mode === "create") return [...safePrev, payload];
      return safePrev.map((service) => (service.id === payload.id ? payload : service));
    });
    handleBackToServices();
  };

  const deleteServiceCredential = () => {
    if (!serviceView.selectedId) return;
    setUserCredentialsList((prev) =>
      (Array.isArray(prev) ? prev : []).filter((service) => service.id !== serviceView.selectedId)
    );
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

    // The CVV is deliberately not included. Retaining a card verification value is
    // prohibited by PCI-DSS whatever the storage medium, and the server strips the
    // field too. It stays in the form field for the current page only.
    const payload = {
      id: paymentForm.id || crypto.randomUUID(),
      cardNickname: paymentForm.cardNickname.trim(),
      cardholderName: paymentForm.cardholderName.trim(),
      cardNumber: cardDigits,
      maskedCardNumber: `**** **** **** ${cardDigits.slice(-4)}`,
      expiryMonth: paymentForm.expiryMonth.trim(),
      expiryYear: paymentForm.expiryYear.trim(),
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

  const createExperienceEntry = () => {
    setExperienceView({ mode: "create", selectedId: null });
    setExperienceForm({ ...defaultExperienceForm });
  };

  const openExperienceCard = (entryId) => {
    const entry = experienceEntries.find((item) => item.id === entryId);
    if (!entry) return;
    setExperienceForm({
      id: entry.id,
      entryType: entry.entryType || "work",
      title: entry.title || "",
      organization: entry.organization || "",
      location: entry.location || "",
      startDate: entry.startDate || "",
      endDate: entry.endDate || "",
      isCurrent: Boolean(entry.isCurrent),
      description: entry.description || "",
    });
    setExperienceView({ mode: "edit", selectedId: entryId });
  };

  const handleExperienceFormChange = (field, value) => {
    setExperienceForm((prev) => {
      if (field === "isCurrent" && value === true) {
        return { ...prev, isCurrent: true, endDate: "" };
      }
      return { ...prev, [field]: value };
    });
  };

  const handleBackToExperience = () => {
    setExperienceView({ mode: "list", selectedId: null });
    setExperienceForm({ ...defaultExperienceForm });
  };

  const saveExperienceEntry = () => {
    if (!experienceForm.title.trim()) {
      alert(experienceForm.entryType === "education" ? "Degree/program is required." : "Job title is required.");
      return;
    }
    if (!experienceForm.organization.trim()) {
      alert(experienceForm.entryType === "education" ? "School/institution is required." : "Company is required.");
      return;
    }
    if (!experienceForm.startDate) {
      alert("Start date is required.");
      return;
    }
    if (!experienceForm.isCurrent && !experienceForm.endDate) {
      alert("End date is required unless this is current.");
      return;
    }

    const payload = {
      id: experienceForm.id || crypto.randomUUID(),
      entryType: experienceForm.entryType,
      title: experienceForm.title.trim(),
      organization: experienceForm.organization.trim(),
      location: experienceForm.location.trim(),
      startDate: experienceForm.startDate,
      endDate: experienceForm.isCurrent ? "" : experienceForm.endDate,
      isCurrent: Boolean(experienceForm.isCurrent),
      description: experienceForm.description.trim(),
      updatedAt: new Date().toISOString(),
    };

    setExperienceEntries((prev) => {
      if (experienceView.mode === "create") return [...prev, payload];
      return prev.map((entry) => (entry.id === payload.id ? payload : entry));
    });
    handleBackToExperience();
  };

  const deleteExperienceEntry = () => {
    if (!experienceView.selectedId) return;
    setExperienceEntries((prev) => prev.filter((entry) => entry.id !== experienceView.selectedId));
    handleBackToExperience();
  };

  // Persist the whole vault to the server, encrypted at rest and keyed to the
  // authenticated user. Nothing sensitive is written to localStorage: it used to
  // hold third-party passwords, full card numbers, and CVVs in plaintext, and the
  // per-keystroke effects below wrote them out on every edit.
  const handleSaveGeneralUserData = async () => {
    setCredentialsError("");
    try {
      await api.storeCredentials(buildAgentCredentialsPayload());
      setShowUserCredentials(false);
    } catch (err) {
      setCredentialsError(
        err.detail || "Could not save your details. They have not been stored."
      );
    }
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeChatId, conversations, agentSessionsByChat]);

  const mainLaneMessages = (activeChat?.messages || []).filter((msg) => msg.channel !== "chat-socket");
  const activeChatSessions = agentSessionsByChat[activeChatId] || [];
  const runningSession =
    activeChatSessions.find((session) => session.status === "running") || null;
  const latestSession =
    activeChatSessions.length > 0 ? activeChatSessions[activeChatSessions.length - 1] : null;
  const thoughtSession = runningSession || latestSession;
  const thoughtSessionIndex = thoughtSession
    ? activeChatSessions.findIndex((session) => session.id === thoughtSession.id) + 1
    : 0;
  // Structured HITL: derived from the session, not from log sniffing.
  const activeHitl = runningSession?.hitl || null;
  const isAgentRunning = Boolean(runningSession);
  // The live view consumes the running session's own socket holder.
  const activeSocketHolder = runningSession
    ? runSocketsRef.current.get(runningSession.id) || { current: null }
    : { current: null };

  // Autoscroll the log panel only when the user is already at the bottom;
  // scrolling up to read must not fight a live stream.
  useEffect(() => {
    const container = thoughtsStreamRef.current;
    if (!container) return;
    const nearBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight < 120;
    if (nearBottom) {
      container.scrollTop = container.scrollHeight;
    }
  }, [thoughtSession?.id, thoughtSession?.logs.length, thoughtsTab]);

  // Takeover is allowed at any time during a run, not only in HITL pauses:
  // the live view is the escape hatch for CAPTCHAs and widgets the agent
  // cannot drive.
  const browserIsInteractive = Boolean(runningSession && hasStream);
  const browserStatusTone = browserIsInteractive ? "interactive" : runningSession ? "locked" : "idle";
  const browserStatusLabel = browserIsInteractive
    ? activeHitl
      ? "Action needed"
      : "Interactive"
    : runningSession
      ? "Connecting"
      : "Standby";
  const browserStatusDetail = browserIsInteractive
    ? activeHitl
      ? "The agent needs your help"
      : "Click the view to take over"
    : runningSession
      ? "Waiting for stream"
      : "Ready";

  const statusChipFor = (session) => {
    const value = session.status === "finished" ? "succeeded" : session.status;
    const labels = {
      running: "Running",
      succeeded: "Succeeded",
      failed: "Failed",
      aborted: "Stopped",
    };
    return { value, label: labels[value] || value };
  };

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
        <h1 className="dashboard-title">
          <Brand size={30} />
        </h1>

        <button className="sidebar-btn" onClick={() => { handleNewChat(); setMobileMenuOpen(false); }}>
          + New chat
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
        <div className="dashboard-shell">
          <section className="dashboard-stage">
            <section className={`dashboard-card live-agent-panel ${browserStatusTone}`}>
              <div className="panel-heading live-panel-heading">
                <div>
                  <p className="panel-kicker">Current Run</p>
                  <h2>Live Agent View</h2>
                </div>
                <div className="live-panel-controls">
                  {latestSession && !runningSession && (
                    <span className={`status-chip ${statusChipFor(latestSession).value}`}>
                      {statusChipFor(latestSession).label}
                    </span>
                  )}
                  {runningSession && <span className="status-chip running">Running</span>}
                  {runningSession && (
                    <button
                      type="button"
                      className="btn btn-danger stop-run-btn"
                      onClick={() => stopSession(activeChatId, runningSession)}
                    >
                      Stop
                    </button>
                  )}
                </div>
              </div>

              <div className="live-agent-viewport">
                <div className={`browser-status-indicator ${browserStatusTone}`}>
                  <span className="browser-status-dot" aria-hidden="true" />
                  <div className="browser-status-copy">
                    <strong>{browserStatusLabel}</strong>
                    <span>{browserStatusDetail}</span>
                  </div>
                </div>

                {(runningSession || hasStream) ? (
                  <div
                    className={`browser-frame-wrapper browser-frame-shell${browserIsInteractive ? " browser-interactive" : ""}`}
                  >
                    <LiveView
                      key={(runningSession || latestSession)?.id || "idle"}
                      socketRef={activeSocketHolder}
                      runActive={Boolean(runningSession)}
                      onStreamChange={setHasStream}
                    />
                  </div>
                ) : (
                  <div className="live-agent-placeholder">
                    <span className="placeholder-orbit placeholder-orbit-a" aria-hidden="true" />
                    <span className="placeholder-orbit placeholder-orbit-b" aria-hidden="true" />
                    <Brand size={52} wordmark={false} />
                    <p className="placeholder-kicker">
                      {latestSession ? "Run complete" : `Welcome${firstname ? `, ${firstname}` : ""}`}
                    </p>
                    <h3>{latestSession ? "Ready for the next run." : "Start a run to begin."}</h3>
                    <p>{latestSession ? "Review chat and logs, or start again." : "The stream will appear here."}</p>
                  </div>
                )}
              </div>
            </section>

            <section className="dashboard-card transcript-panel">
              <div className="panel-heading">
                <div>
                  <p className="panel-kicker">Messages</p>
                  <h2>Chat</h2>
                </div>
                <div className="panel-caption">
                  {activeChatSessions.length > 0
                    ? `${activeChatSessions.length} run${activeChatSessions.length === 1 ? "" : "s"}`
                    : "No messages yet"}
                </div>
              </div>

              <div className="transcript-scroll">
                {mainLaneMessages.length === 0 && activeChatSessions.length === 0 ? (
                  <div className="transcript-empty">
                    <p>No messages yet.</p>
                    <span>Start a run to begin.</span>
                  </div>
                ) : (
                  <>
                    {mainLaneMessages.map((msg, index) => (
                      <div key={msg.id || `main-${index}`} className={msg.isUser ? "chat-user" : "chat-system"}>
                        {msg.isUser ? msg.text : <ReactMarkdown>{msg.text}</ReactMarkdown>}
                      </div>
                    ))}

                    {activeChatSessions.map((session, sessionIndex) => (
                      <section key={session.id} className="transcript-run">
                        <div className="transcript-run-header">
                          <span className="transcript-run-title">Run {sessionIndex + 1}</span>
                          <span
                            className={`status-chip ${statusChipFor(session).value}`}
                            title={session.exitReason || undefined}
                          >
                            {statusChipFor(session).label}
                          </span>
                        </div>

                        <div className="transcript-stack">
                          <div className="chat-user transcript-bubble">{session.prompt}</div>

                          {/* Live thinking trace, in the style of the ChatGPT /
                              Claude chat transcript. Replaces the old static
                              "Waiting for agent response..." placeholder. */}
                          <ThinkingChatBlock session={session} />

                          {session.chatMessages.map((msg, index) => (
                            <div
                              key={msg.id || `${session.id}-chat-${index}`}
                              className={msg.isUser ? "chat-user transcript-bubble" : "chat-system transcript-bubble"}
                            >
                              {msg.isUser ? msg.text : <ReactMarkdown>{msg.text}</ReactMarkdown>}
                            </div>
                          ))}

                          {session.status === "running" && session.hitl && (
                            <HitlForm
                              key={`${session.id}-hitl-${session.hitl.message}`}
                              hitl={session.hitl}
                              onSubmit={(reply) => sendReplyToSession(activeChatId, session, reply)}
                            />
                          )}

                          {session.itemResults.length > 0 && (
                            <div className="transcript-bubble chat-system item-results">
                              <strong>Per-item results</strong>
                              <ul>
                                {session.itemResults.map((item, index) => (
                                  <li key={index}>
                                    <span
                                      className={`status-chip ${
                                        String(item.status || "").toLowerCase().includes("success")
                                          ? "succeeded"
                                          : "failed"
                                      }`}
                                    >
                                      {item.status || "?"}
                                    </span>
                                    <span>{item.description || `Item ${index + 1}`}</span>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}

                          {session.status !== "running" && session.exitReason && session.status !== "succeeded" && (
                            <p className="transcript-exit-reason">{session.exitReason}</p>
                          )}
                        </div>
                      </section>
                    ))}
                    <div ref={bottomRef}></div>
                  </>
                )}
              </div>
            </section>

            <div className="dashboard-card dashboard-input-bar">
              <label className="input-label" htmlFor="dashboard-input">
                {isAgentRunning ? "Reply" : "Input"}
              </label>
              <div className="input-row">
                <textarea
                  id="dashboard-input"
                  className="dashboard-input"
                  rows={1}
                  placeholder={
                    isAgentRunning
                      ? "Send a reply... (Shift+Enter for a new line)"
                      : "Start browsing... (Shift+Enter for a new line)"
                  }
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyPress}
                />
                {!isAgentRunning && (
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => setShowBatchComposer(true)}
                    title="Run the same task across a list of URLs"
                  >
                    Batch
                  </button>
                )}
                <button className="btn btn-primary dashboard-bar-btn" onClick={handleSend} disabled={!input.trim()}>
                  {isAgentRunning ? "Send" : "Launch"}
                </button>
              </div>
            </div>
          </section>

          <aside className="dashboard-card dashboard-thoughts-panel">
            <div className="panel-heading thoughts-panel-heading">
              <div>
                <p className="panel-kicker">Reasoning</p>
                <h2>Agent Thinking</h2>
              </div>
              {thoughtSession?.status === "running" ? (
                <div className="thinking-indicator" aria-live="polite">
                  <span className="thinking-spinner" aria-hidden="true" />
                  <span>(thinking...)</span>
                </div>
              ) : thoughtSession ? (
                <div className="thinking-complete">Complete</div>
              ) : null}
            </div>

            <div className="thoughts-tabs" role="tablist" aria-label="Agent activity view">
              <button
                type="button"
                role="tab"
                aria-selected={thoughtsTab === "thinking"}
                className={`thoughts-tab ${thoughtsTab === "thinking" ? "active" : ""}`}
                onClick={() => setThoughtsTab("thinking")}
              >
                Thinking
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={thoughtsTab === "logs"}
                className={`thoughts-tab ${thoughtsTab === "logs" ? "active" : ""}`}
                onClick={() => setThoughtsTab("logs")}
              >
                Logs
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={thoughtsTab === "history"}
                className={`thoughts-tab ${thoughtsTab === "history" ? "active" : ""}`}
                onClick={() => setThoughtsTab("history")}
              >
                History
              </button>
            </div>

            <div className="thoughts-meta">
              {thoughtsTab === "history" ? (
                <p className="thoughts-prompt">Every run, kept on the server.</p>
              ) : thoughtSession ? (
                <>
                  <span className="thoughts-run-label">Run {thoughtSessionIndex}</span>
                  <p className="thoughts-prompt">{thoughtSession.prompt}</p>
                </>
              ) : (
                <p className="thoughts-prompt">
                  {thoughtsTab === "thinking"
                    ? "The agent's thinking will appear here."
                    : "Logs will appear here."}
                </p>
              )}
            </div>

            {thoughtsTab === "history" ? (
              <div className="thoughts-stream">
                <RunHistory refreshKey={historyRefreshKey} />
              </div>
            ) : thoughtsTab === "thinking" ? (
              thoughtSession ? (
                <ThinkingStream key={thoughtSession.id} session={thoughtSession} />
              ) : (
                <div className="thoughts-stream">
                  <div className="thoughts-empty-state">Start a run to watch the agent think.</div>
                </div>
              )
            ) : (
              <div className="thoughts-stream" ref={thoughtsStreamRef}>
                {thoughtSession ? (
                  thoughtSession.logs.length > 0 ? (
                    groupAgentLogs(thoughtSession.logs).map((group, groupIndex) => (
                      <div key={`${thoughtSession.id}-thought-group-${groupIndex}`} className="thought-line">
                        <span className="thought-line-number">{String(group.startLineIndex + 1).padStart(2, "0")}</span>
                        <div className="thought-line-body">
                          {group.icon ? (
                            <div className="thought-line-group">
                              <div className="thought-line-group-header">
                                <img className="thought-line-icon" src={group.icon} alt={group.alt} />
                              </div>
                              <ul className="thought-line-list">
                                {group.items.map((item, itemIndex) => (
                                  <li key={`${thoughtSession.id}-thought-group-${groupIndex}-item-${itemIndex}`} className="thought-line-text">
                                    {item}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          ) : (
                            group.items.map((item, itemIndex) => (
                              <span
                                key={`${thoughtSession.id}-thought-group-${groupIndex}-item-${itemIndex}`}
                                className="thought-line-text"
                              >
                                {item}
                              </span>
                            ))
                          )}
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="thoughts-empty-state">
                      {thoughtSession.status === "running"
                        ? "Waiting for logs..."
                        : "No more logs."}
                    </div>
                  )
                ) : (
                  <div className="thoughts-empty-state">Start a run to view logs.</div>
                )}
              </div>
            )}
          </aside>
        </div>
      </main>
      {/* ---------- SETTINGS MODAL ---------- */}
      {showSettings && (
        <SettingsModal onClose={() => setShowSettings(false)} onLogout={handleLogout} />
      )}

      {showBatchComposer && (
        <BatchComposer
          onClose={() => setShowBatchComposer(false)}
          onLaunch={(prompt) => {
            setShowBatchComposer(false);
            launchRun(prompt);
          }}
        />
      )}

      {/* ---------- USER CREDENTIALS MODAL ---------- */}
      {showUserCredentials && (
        <Modal title="Your Details" onClose={() => setShowUserCredentials(false)} wide>
            {credentialsError && (
              <p className="creds-error" role="alert">{credentialsError}</p>
            )}

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
                experienceEntries={experienceEntries}
                experienceView={experienceView}
                experienceForm={experienceForm}
                onCreateExperience={createExperienceEntry}
                onOpenExperience={openExperienceCard}
                onExperienceFormChange={handleExperienceFormChange}
                onSaveExperience={saveExperienceEntry}
                onDeleteExperience={deleteExperienceEntry}
                onBackToExperience={handleBackToExperience}
              />
              </div>

            ) : (
              // FALSE - prompt user to verify their identity first
              <form
                className="password-verification-group"
                onSubmit={(e) => {
                  e.preventDefault();
                  verifyUser();
                }}
              >
                <h3 className="password-prompt">Confirm your password to view saved details.</h3>
                <input
                  className="text-input password-input"
                  placeholder="Your password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button className="btn btn-primary" type="submit">Verify identity</button>
              </form>
            )}

            {didUserVerifyIdentity && (
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowUserCredentials(false)}>
                  Cancel
                </button>
                <button type="button" className="btn btn-primary" onClick={handleSaveGeneralUserData}>
                  Save and close
                </button>
              </div>
            )}
        </Modal>
      )}

    </div>
  );
}

/**
 * Batch composer: paste a list of job URLs, get one mission whose work items
 * the planner turns into the deterministic outer loop ("apply to each").
 */
function BatchComposer({ onClose, onLaunch }) {
  const [instruction, setInstruction] = useState(
    "Apply to each of these jobs using my saved profile and documents."
  );
  const [urlText, setUrlText] = useState("");

  const urls = urlText
    .split(/\s+/)
    .map((u) => u.trim())
    .filter((u) => /^https?:\/\//i.test(u));

  const launch = () => {
    const lines = urls.map((u) => `- ${u}`).join("\n");
    onLaunch(`${instruction.trim()}\n\nWork through these one at a time:\n${lines}`);
  };

  return (
    <Modal title="Batch run" onClose={onClose}>
      <p className="settings-hint">
        One task, many pages. The agent works through the list one item at a
        time and reports the outcome of each.
      </p>
      <label className="field-label" htmlFor="batch-instruction">What should the agent do?</label>
      <input
        id="batch-instruction"
        className="text-input"
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
      />
      <label className="field-label" htmlFor="batch-urls">
        URLs (one per line){urls.length > 0 ? ` - ${urls.length} detected` : ""}
      </label>
      <textarea
        id="batch-urls"
        className="text-input batch-url-input"
        rows={6}
        placeholder={"https://example.com/careers/123\nhttps://example.org/jobs/456"}
        value={urlText}
        onChange={(e) => setUrlText(e.target.value)}
      />
      <div className="modal-footer">
        <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={urls.length === 0 || !instruction.trim()}
          onClick={launch}
        >
          Launch {urls.length > 0 ? `${urls.length} item${urls.length === 1 ? "" : "s"}` : "batch"}
        </button>
      </div>
    </Modal>
  );
}



