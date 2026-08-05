// Turns raw agent run logs into a readable "thinking" feed, in the style of
// ChatGPT / Claude thinking traces. Pure functions only: the same log array
// always derives the same feed, so the UI can re-derive on every append.
//
// Input lines are the sanitized session logs the Dashboard already stores,
// e.g. "STDOUT: [NODE]: ORCHESTRATOR" or "STATUS: Warming up browser...".

export const THINKING_PHASES = {
  setup: { label: "Warming up" },
  orchestrating: { label: "Orchestrating" },
  executing: { label: "Executing" },
  verifying: { label: "Verifying" },
  recovering: { label: "Recovering" },
  waiting: { label: "Waiting for you" },
  responding: { label: "Responding" },
  done: { label: "Finished" },
};

const NODE_INFO = {
  ORCHESTRATOR: { phase: "orchestrating", section: "Deciding the next move" },
  EXECUTION: { phase: "executing", section: "Working in the browser" },
  VERIFICATION: { phase: "verifying", section: "Checking the result" },
  FALLBACK: { phase: "recovering", section: "Rethinking the approach" },
  INTERACTION: { phase: "responding", section: "Talking to you" },
  __INTERRUPT__: { phase: "waiting", section: "Paused - your turn" },
};

const DECISION_ACTIONS = {
  advance: "Moving on to the next step.",
  retry: "Giving this step another try.",
  replan: "Rebuilding the plan from here.",
  plan_complete: "That completes the plan.",
  interaction: "Time to report back.",
  fallback: "Escalating to recovery.",
};

const FALLBACK_UPDATES = {
  revise_step: "I'll revise the current step and retry.",
  insert_step_before: "Inserting an extra step to unblock this one.",
  replan: "Rebuilding the plan from here.",
  request_human_action: "I need you to do something in the browser.",
  request_context: "I need more information from you.",
  abort: "Calling this mission off.",
};

const ARG_LABEL_KEYS = ["target_name", "name", "label", "option", "key", "url"];

function extractArg(argsRaw, key) {
  // Args arrive as "k=v, k=v" with free-text values; capture until the next
  // ", key=" boundary rather than the next comma.
  const match = new RegExp(`(?:^|,\\s*)${key}=(.*?)(?=,\\s*\\w+=|$)`).exec(argsRaw || "");
  if (!match) return "";
  return match[1].trim().replace(/^["']|["']$/g, "");
}

function clip(text, max = 180) {
  const value = String(text || "").trim();
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1).trimEnd()}…`;
}

function executorThoughtText(pending) {
  const action = (pending.action || "").toLowerCase();
  const argsRaw = pending.argsRaw || "";
  let label = "";
  for (const key of ARG_LABEL_KEYS) {
    label = extractArg(argsRaw, key);
    if (label) break;
  }
  label = clip(label, 70);

  const url = extractArg(argsRaw, "url");
  const named = label ? ` "${label}"` : "";
  let text;
  switch (action) {
    case "navigate":
      text = url ? `Navigating to ${clip(url, 90)}` : "Navigating to a new page";
      break;
    case "click":
      text = `Clicking${named || " an element"}`;
      break;
    case "fill":
      text = `Filling in${named ? ` the${named} field` : " a field"}`;
      break;
    case "type":
      text = `Typing into${named || " the page"}`;
      break;
    case "select_option":
      text = `Choosing${named || " an option"}`;
      break;
    case "set_checkbox":
      text = `Toggling${named ? ` the${named} checkbox` : " a checkbox"}`;
      break;
    case "upload_file":
      text = `Uploading a file${named ? ` to${named}` : ""}`;
      break;
    case "read_form":
      text = "Reading the form to see which fields still need values";
      break;
    case "extract":
    case "read_page":
      text = "Reading the page";
      break;
    case "scroll":
      text = "Scrolling to bring more of the page into view";
      break;
    case "press_key":
    case "press":
      text = `Pressing${named || " a key"}`;
      break;
    case "go_back":
      text = "Going back to the previous page";
      break;
    case "wait":
      text = "Waiting for the page to settle";
      break;
    default:
      text = `Running "${pending.action}"`;
  }

  const status = (pending.status || "").toLowerCase();
  if (status === "failure") {
    const detail = clip(pending.message, 160);
    return { text: `${text} - that didn't work.${detail ? ` ${detail}` : ""}`, tone: "error" };
  }
  return { text: `${text}.`, tone: "neutral" };
}

/**
 * Derive the thinking feed from raw session log lines.
 *
 * Returns { items, phase, currentTask, lastActionText } where each item is:
 *   { kind: "section", id, phase, label }
 *   { kind: "thought", id, phase, tone, text }
 *   { kind: "plan",    id, phase, steps: [{ num, text, current }] }
 */
export function deriveThinkingFeed(logs) {
  const items = [];
  let phase = "setup";
  let lastSectionPhase = null;
  let lastTask = null;
  let expectPlan = false;
  let planBuffer = null;
  let lastPlanSignature = null;
  let lastPlanCurrentNum = null;
  let pendingExec = null;
  let pendingVerdict = null;
  let lastActionText = null;

  const lastThought = () => {
    for (let i = items.length - 1; i >= 0; i -= 1) {
      if (items[i].kind === "thought") return items[i];
    }
    return null;
  };

  const pushThought = (id, text, tone = "neutral") => {
    const value = String(text || "").trim();
    if (!value) return;
    const previous = lastThought();
    if (previous && previous.text === value) return;
    items.push({ kind: "thought", id, phase, tone, text: value });
  };

  const pushSection = (id, label) => {
    if (lastSectionPhase === phase) return;
    lastSectionPhase = phase;
    items.push({ kind: "section", id, phase, label });
  };

  const flushExec = () => {
    if (!pendingExec) return;
    const { text, tone } = executorThoughtText(pendingExec);
    lastActionText = text.replace(/\.$/, "");
    pushThought(pendingExec.id, text, tone);
    pendingExec = null;
  };

  const flushVerdict = () => {
    if (!pendingVerdict) return;
    const ok = pendingVerdict.verdict === "success";
    pushThought(
      pendingVerdict.id,
      ok ? "That step checks out." : "That didn't pass my check.",
      ok ? "success" : "warn"
    );
    pendingVerdict = null;
  };

  const flushPlan = () => {
    if (!planBuffer || planBuffer.steps.length === 0) {
      planBuffer = null;
      return;
    }
    const signature = planBuffer.steps.map((step) => step.text).join("|");
    const current = planBuffer.steps.find((step) => step.current);
    if (signature === lastPlanSignature) {
      // Same plan reprinted on a later cycle: collapse to a progress note.
      if (current && current.num !== lastPlanCurrentNum) {
        pushThought(
          `${planBuffer.id}-progress`,
          `Now on step ${current.num} of ${planBuffer.steps.length}: ${clip(current.text, 120)}`
        );
      }
    } else {
      items.push({ kind: "plan", id: planBuffer.id, phase, steps: planBuffer.steps });
      lastPlanSignature = signature;
    }
    if (current) lastPlanCurrentNum = current.num;
    planBuffer = null;
  };

  // Anything that is not an [Executor]/[Verifier] continuation line closes out
  // the buffered executor action / verifier verdict before being handled.
  const flushPending = () => {
    flushExec();
    flushVerdict();
  };

  const handleTagged = (id, text) => {
    let match;

    if ((match = /^\[Decision\]\s*(.*)$/.exec(text))) {
      flushPending();
      const body = match[1].trim();
      if (/^Status:/i.test(body)) return;
      if ((match = /^Action:\s*(\S+)/i.exec(body))) {
        const action = match[1].toLowerCase();
        pushThought(id, DECISION_ACTIONS[action] || `Next: ${action}.`);
        return;
      }
      if ((match = /^Safety Stop:\s*(.*)$/i.exec(body))) {
        pushThought(id, `Safety stop: ${clip(match[1])}`, "error");
        return;
      }
      if ((match = /^Task refinement:\s*(.*)$/i.exec(body))) {
        pushThought(id, `Refining the step: ${clip(match[1])}`);
        return;
      }
      pushThought(id, clip(body, 220));
      return;
    }

    if ((match = /^\[Executor\]\s*Action:\s*(.*)$/i.exec(text))) {
      flushPending();
      pendingExec = { id, action: match[1].trim(), argsRaw: "", status: "", message: "" };
      return;
    }
    if ((match = /^\[Executor\]\s*Args:\s*(.*)$/i.exec(text))) {
      if (pendingExec) pendingExec.argsRaw = match[1];
      return;
    }
    if ((match = /^\[Executor\]\s*Status:\s*(.*)$/i.exec(text))) {
      if (pendingExec) pendingExec.status = match[1].trim();
      return;
    }
    if ((match = /^\[Executor\]\s*Message:\s*(.*)$/i.exec(text))) {
      if (pendingExec) {
        let message = match[1];
        const afterState = message.indexOf("AFTER_STATE");
        if (afterState >= 0) message = message.slice(0, afterState);
        pendingExec.message = message.trim();
        flushExec();
      }
      return;
    }
    if (/^\[Executor\]\s*(Error Type|AFTER_STATE)/i.test(text)) {
      flushExec();
      return;
    }
    if (/^\[Executor\]/i.test(text)) return;

    if ((match = /^\[Verifier\]\s*Verdict:\s*(\S+)/i.exec(text))) {
      flushPending();
      pendingVerdict = { id, verdict: match[1].toLowerCase() };
      return;
    }
    if ((match = /^\[Verifier\]\s*Message:\s*(.*)$/i.exec(text))) {
      const ok = pendingVerdict ? pendingVerdict.verdict === "success" : true;
      pendingVerdict = null;
      pushThought(id, clip(match[1], 220), ok ? "success" : "warn");
      return;
    }
    if ((match = /^\[Verifier\]\s*Goal Complete:\s*True/i.exec(text))) {
      pushThought(id, "The overall goal looks complete.", "success");
      return;
    }
    if (/^\[Verifier\]\s*Handoff:\s*fallback/i.test(text)) {
      flushPending();
      pushThought(id, "Handing this over to recovery.");
      return;
    }
    if ((match = /^\[Verifier\]\s*LLM failed:/i.exec(text))) {
      flushPending();
      pushThought(id, "My verification call failed - assuming this step needs another look.", "warn");
      return;
    }
    if (/^\[Verifier\]/i.test(text)) return;

    if ((match = /^\[Fallback\]\s*Diagnosis:\s*(.*)$/i.exec(text))) {
      flushPending();
      pushThought(id, `What went wrong: ${clip(match[1], 220)}`, "warn");
      return;
    }
    if ((match = /^\[Fallback\]\s*Update Type:\s*(\S+)/i.exec(text))) {
      flushPending();
      const update = match[1].toLowerCase();
      pushThought(id, FALLBACK_UPDATES[update] || `Recovery plan: ${update}.`);
      return;
    }
    if ((match = /^\[Fallback\]\s*(.*)$/.exec(text))) {
      flushPending();
      pushThought(id, clip(match[1], 220), "warn");
      return;
    }

    if ((match = /^\[Interaction\]\s*User replied:\s*(.*)$/i.exec(text))) {
      flushPending();
      pushThought(id, `You said: "${clip(match[1], 140)}"`);
      return;
    }
    if (/^\[Interaction\]\s*Final:/i.test(text)) {
      flushPending();
      pushThought(id, "Writing up my final answer...");
      return;
    }
    // Remaining [Interaction] bookkeeping lines are noise here.
  };

  logs.forEach((rawLine, index) => {
    const id = `t${index}`;
    const line = String(rawLine || "");
    const sourceMatch = /^(STDOUT|STDERR|STATUS|AGENT):\s*(.*)$/.exec(line);
    if (!sourceMatch) return;
    const [, source, content] = sourceMatch;

    // STATUS/STDERR/AGENT frames come from the server, not the agent's stdout,
    // so they can interleave mid-printout. They must not flush the stdout
    // buffers (plan block, executor action) that are still being assembled.
    if (source === "STATUS") {
      if (/^Warming up browser/i.test(content)) {
        phase = "setup";
        pushThought(id, "Warming up a fresh browser...");
      } else if (/^Agent finished task/i.test(content)) {
        phase = "done";
        pushThought(id, "Run finished.");
      } else if (/^Abort requested/i.test(content)) {
        pushThought(id, "Stopping the run at your request...", "warn");
      } else {
        pushThought(id, clip(content, 180));
      }
      return;
    }

    if (source === "STDERR") {
      if (/Connection to the agent failed/i.test(content)) {
        pushThought(id, "I lost my connection to the agent.", "error");
      }
      return;
    }

    if (source === "AGENT") {
      const needsInput = /^\[NEEDS INPUT\]\s*(.*)$/.exec(content);
      if (needsInput) {
        phase = "waiting";
        pushThought(id, `Asking you: ${clip(needsInput[1], 200)}`);
      } else {
        phase = "responding";
        pushThought(id, "Sending you my answer.");
      }
      return;
    }

    // ── STDOUT ──
    const nodeMatch = /^\[NODE\]:\s*(\S+)/.exec(content);
    if (nodeMatch) {
      flushPending();
      flushPlan();
      const info = NODE_INFO[nodeMatch[1].toUpperCase()];
      if (info) {
        phase = info.phase;
        pushSection(id, info.section);
        expectPlan = true;
      }
      return;
    }

    // The plan printout is "PLAN:" followed by one line per step, with ">>>"
    // marking the current step.
    if (/^PLAN:$/i.test(content)) {
      flushPending();
      expectPlan = true;
      return;
    }
    const planMatch = /^(>{2,3}\s*)?(\d+)\.\s+(.+)$/.exec(content);
    if (expectPlan && planMatch) {
      flushPending();
      if (!planBuffer) planBuffer = { id, steps: [] };
      planBuffer.steps.push({
        num: Number(planMatch[2]),
        text: clip(planMatch[3], 160),
        current: Boolean(planMatch[1]),
      });
      return;
    }
    // The plan printout is contiguous; the first non-plan line closes it.
    expectPlan = false;
    flushPlan();

    let match;
    if ((match = /^Reasoning:\s*(.*)$/.exec(content))) {
      handleTagged(id, match[1].trim());
      return;
    }
    if (/^\[(Decision|Executor|Verifier|Fallback|Interaction)\]/i.test(content)) {
      handleTagged(id, content);
      return;
    }
    if ((match = /^Current Task:\s*(.*)$/.exec(content))) {
      flushPending();
      const task = match[1].trim();
      if (task && task !== lastTask) {
        lastTask = task;
        pushThought(id, `Focusing on: ${clip(task, 180)}`);
      }
      return;
    }
    if ((match = /^Plan Status:\s*(\S+)/.exec(content))) {
      flushPending();
      if (match[1].toUpperCase() === "CREATE") {
        pushThought(id, "Sketching a step-by-step plan for this mission...");
      }
      return;
    }
    if (/^Is Complete:\s*True/i.test(content)) {
      flushPending();
      pushThought(id, "Mission accomplished.", "success");
      return;
    }
    if (/^Needs Fallback:\s*True/i.test(content)) {
      flushPending();
      pushThought(id, "That approach needs a rethink.", "warn");
      return;
    }
    if ((match = /^User Request:\s*(.*)$/.exec(content))) {
      flushPending();
      pushThought(id, `Reading the task: "${clip(match[1], 140)}"`);
      return;
    }
    if (/^Launching browser/i.test(content)) {
      flushPending();
      pushThought(id, "Opening a browser window...");
      return;
    }
    if (/^Browser launched/i.test(content)) {
      flushPending();
      pushThought(id, "Browser is ready - connecting the live view...");
      return;
    }
    if (/^Restoring saved browser session/i.test(content)) {
      flushPending();
      pushThought(id, "Restoring my saved session (cookies and logins)...");
      return;
    }
    if ((match = /^\[executor\]\s*(.*)$/.exec(content))) {
      flushPending();
      const note = match[1];
      if (/timed out/i.test(note)) {
        pushThought(id, "My reasoning call timed out - retrying.", "warn");
      } else if (/failed/i.test(note)) {
        pushThought(id, "My reasoning call failed - retrying.", "warn");
      } else if (/No tool call/i.test(note)) {
        pushThought(id, "No action came back - asking again in a stricter format.", "warn");
      }
      return;
    }
    if (/^\[HITL\]\s*Waiting for user input/i.test(content)) {
      flushPending();
      phase = "waiting";
      pushThought(id, "Waiting for your reply...");
      return;
    }
    if ((match = /^\[FATAL\]\s*(.*)$/.exec(content))) {
      flushPending();
      pushThought(id, `Something went wrong: ${clip(match[1], 200)}`, "error");
      return;
    }
    if (/^SIMULATION COMPLETE/i.test(content)) {
      flushPending();
      phase = "done";
      pushThought(id, "All done.");
      return;
    }
    // Everything else (Run ID, Starting URL, [HITL]/[startup] bookkeeping,
    // unprefixed continuation fragments) stays in the raw Logs tab only.
  });

  flushPending();
  flushPlan();

  return { items, phase, currentTask: lastTask, lastActionText };
}

/**
 * Short status label in the style of the ChatGPT / Claude activity line:
 * "Thinking" while the agent reasons, "Executing: <task>" while it acts.
 */
export function thinkingActivityLabel(feed) {
  switch (feed.phase) {
    case "executing": {
      const detail = feed.currentTask || feed.lastActionText;
      return detail ? `Executing: ${clip(detail, 80)}` : "Executing";
    }
    case "waiting":
      return "Waiting for you";
    case "responding":
      return "Replying";
    case "done":
      return "Finished";
    default:
      return "Thinking";
  }
}

export function formatThinkingDuration(ms) {
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}
