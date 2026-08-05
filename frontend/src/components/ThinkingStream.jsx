import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  deriveThinkingFeed,
  formatThinkingDuration,
  thinkingActivityLabel,
  THINKING_PHASES,
} from "../lib/thinking";
import "./ThinkingStream.css";

const WORD_STAGGER_MS = 26;
const MAX_WORD_DELAY_MS = 950;

/** Words fade in one after another, like the ChatGPT / Claude thinking UIs. */
function AnimatedText({ text, animate }) {
  if (!animate) return text;
  const tokens = String(text).split(/(\s+)/);
  let wordIndex = 0;
  return tokens.map((token, tokenIndex) => {
    if (/^\s+$/.test(token)) return token;
    const delay = Math.min(wordIndex * WORD_STAGGER_MS, MAX_WORD_DELAY_MS);
    wordIndex += 1;
    return (
      <span key={tokenIndex} className="thinking-word" style={{ animationDelay: `${delay}ms` }}>
        {token}
      </span>
    );
  });
}

function ThinkingItem({ item, animate }) {
  if (item.kind === "section") {
    return (
      <div className={`thinking-item thinking-section phase-${item.phase}`}>
        <span className="thinking-section-label">{item.label}</span>
      </div>
    );
  }

  if (item.kind === "plan") {
    return (
      <ul className={`thinking-item thinking-plan phase-${item.phase}`}>
        {item.steps.map((step) => (
          <li key={step.num} className={step.current ? "current" : ""}>
            <span className="thinking-plan-num">{step.num}.</span>
            <span className="thinking-plan-text">
              <AnimatedText text={step.text} animate={animate} />
            </span>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <p className={`thinking-item thinking-thought tone-${item.tone} phase-${item.phase}`}>
      <AnimatedText text={item.text} animate={animate} />
    </p>
  );
}

/** Memoized so the 1-second elapsed timer tick doesn't re-render the feed. */
const ThinkingFeedBody = React.memo(function ThinkingFeedBody({ items, running }) {
  return (
    <>
      {items.map((item) => (
        <ThinkingItem key={item.id} item={item} animate={running} />
      ))}
      {running && items.length > 0 && <span className="thinking-cursor" aria-hidden="true" />}
    </>
  );
});

function ThinkingSkeleton() {
  return (
    <div className="thinking-skeleton" aria-label="Waiting for the first thought">
      <span className="thinking-skeleton-bar" style={{ width: "86%" }} />
      <span className="thinking-skeleton-bar" style={{ width: "68%" }} />
      <span className="thinking-skeleton-bar" style={{ width: "52%" }} />
    </div>
  );
}

/** Milliseconds since the session started, ticking once a second while live. */
function useElapsedMs(session, running) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running]);
  if (!session.startedAt) return null;
  return (running ? now : session.finishedAt ?? now) - session.startedAt;
}

/** Keep a scroll container pinned to the newest thought until the user scrolls up. */
function useFollowBottom(itemCount, running) {
  const scrollRef = useRef(null);
  const stickToBottomRef = useRef(true);
  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  };
  useEffect(() => {
    const el = scrollRef.current;
    if (el && running && stickToBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [itemCount, running]);
  return { scrollRef, handleScroll };
}

/**
 * In-chat thinking block, in the style of the ChatGPT / Claude transcript:
 * a shimmer activity line ("Thinking…" while reasoning, "Executing: <task>"
 * while acting) over a collapsible stream of thoughts. Collapses to
 * "Thought for Xs" once the run finishes.
 */
export function ThinkingChatBlock({ session }) {
  const running = session.status === "running";
  const feed = useMemo(() => deriveThinkingFeed(session.logs), [session.logs]);
  const elapsedMs = useElapsedMs(session, running);
  const { scrollRef, handleScroll } = useFollowBottom(feed.items.length, running);

  // Open while live, collapsed once finished — unless the user has toggled it.
  const [userExpanded, setUserExpanded] = useState(null);
  const expanded = userExpanded ?? running;

  if (!running && feed.items.length === 0) return null;

  const label = running
    ? `${thinkingActivityLabel(feed)}…`
    : elapsedMs != null
      ? `Thought for ${formatThinkingDuration(elapsedMs)}`
      : "Thoughts";

  return (
    <div className={`thinking-chatblock ${running ? "live" : "static"}`}>
      <button
        type="button"
        className="thinking-chatblock-header"
        aria-expanded={expanded}
        onClick={() => setUserExpanded(!expanded)}
      >
        <span
          className={`thinking-orb ${running ? "live" : ""} phase-${running ? feed.phase : "done"}`}
          aria-hidden="true"
        />
        <span className={`thinking-chatblock-label ${running ? "thinking-shimmer" : ""}`}>
          {label}
        </span>
        {running && elapsedMs != null && (
          <span className="thinking-elapsed">{formatThinkingDuration(elapsedMs)}</span>
        )}
        <span className={`thinking-chevron ${expanded ? "open" : ""}`} aria-hidden="true" />
      </button>
      {expanded && (
        <div className="thinking-chatblock-body" ref={scrollRef} onScroll={handleScroll}>
          {feed.items.length > 0 ? (
            <ThinkingFeedBody items={feed.items} running={running} />
          ) : (
            <ThinkingSkeleton />
          )}
        </div>
      )}
    </div>
  );
}

/** Full-height thinking view for the right-hand panel's Thinking tab. */
export default function ThinkingStream({ session }) {
  const running = session.status === "running";
  const feed = useMemo(() => deriveThinkingFeed(session.logs), [session.logs]);
  const elapsedMs = useElapsedMs(session, running);
  const { scrollRef, handleScroll } = useFollowBottom(feed.items.length, running);

  const phase = running ? feed.phase : "done";
  const phaseLabel = (THINKING_PHASES[phase] || THINKING_PHASES.setup).label;

  return (
    <div className={`thinking-view ${running ? "" : "static"}`}>
      <div className={`thinking-statusline phase-${phase}`} aria-live="polite">
        <span className={`thinking-orb ${running ? "live" : ""}`} aria-hidden="true" />
        {running ? (
          <span className="thinking-status-text thinking-shimmer">{phaseLabel}&hellip;</span>
        ) : (
          <span className="thinking-status-text">
            {elapsedMs != null && session.logs.length > 0
              ? `Thought for ${formatThinkingDuration(elapsedMs)}`
              : "Thinking will appear here"}
          </span>
        )}
        {running && elapsedMs != null && (
          <span className="thinking-elapsed">{formatThinkingDuration(elapsedMs)}</span>
        )}
      </div>

      <div className="thinking-scroll" ref={scrollRef} onScroll={handleScroll}>
        {feed.items.length > 0 ? (
          <ThinkingFeedBody items={feed.items} running={running} />
        ) : running ? (
          <ThinkingSkeleton />
        ) : (
          <div className="thinking-empty">
            {session.logs.length > 0
              ? "Nothing readable came out of this run's logs."
              : "Start a run to watch the agent think."}
          </div>
        )}
      </div>
    </div>
  );
}
