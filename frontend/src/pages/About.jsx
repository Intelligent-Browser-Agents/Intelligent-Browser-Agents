import React from "react";
import { useNavigate } from "react-router-dom";
import "./About.css";

const workflow = [
  {
    title: "You set the goal",
    body: "You describe what you want done in plain language, the same way you would explain a task to a capable assistant.",
  },
  {
    title: "The agent gets to work",
    body: "Your request is handed off to several agents, each with a specific role in moving the task forward and keeping it on track.",
  },
  {
    title: "You can follow along",
    body: "You are not left guessing. The platform is designed to make progress feel visible, so you can stay aware of what is happening while the work is being completed.",
  },
  {
    title: "You step in if needed",
    body: "If a task needs clarification or confirmation, you can step in briefly and let the agents continue with better direction.",
  },
];

const agentRoles = [
  {
    label: "Planner",
    body: "Breaks your request into a clear path toward the result you asked for.",
  },
  {
    label: "Operator",
    body: "Handles the browser work itself and carries out the steps needed to move the task forward.",
  },
  {
    label: "Checker",
    body: "Looks at what happened and helps make sure the task is moving in the right direction.",
  },
  {
    label: "Guide",
    body: "Reaches back to you when a decision or clarification would improve the outcome.",
  },
];

export default function About() {
  const navigate = useNavigate();

  return (
    <div className="about-site">
      <div className="about-overlay" />

      <header className="about-header">
        <div className="about-brand">
          <span className="about-brand-tag">IBA</span>
          <div>
            <p className="about-brand-name">Intelligent Browser Agents</p>
            <p className="about-brand-meta">University of Central Florida Senior Design Project</p>
          </div>
        </div>

        <button
          type="button"
          className="about-return"
          onClick={() => navigate("/")}
        >
          Back to login
        </button>
      </header>

      <main className="about-main">
        <section className="about-hero">
          <p className="about-kicker">What is Intelligent Browser Agents?</p>
          <h1 className="about-hero-title">
            Browser work, handled.
          </h1>
          <p className="about-hero-copy">
            Intelligent Browser Agents is built for people who are tired of repeating the same browser work by hand.
            You describe the task in natural language, the platform takes over the repetitive parts, and you stay
            involved only when your input actually matters.
          </p>

          <div className="about-hero-rail">
            <span>Natural-language requests</span>
            <span>Less repetitive browser work</span>
            <span>Human guidance when needed</span>
          </div>
        </section>

        <section className="about-section about-section-story">
          <div className="about-section-heading">
            <p className="about-kicker">Why it exists</p>
            <h2>Less busywork. More control.</h2>
          </div>

          <div className="about-story-layout">
            <div className="about-story-copy-block">
              <p>
                This platform is meant to reduce the need to repeat tedious digital tasks over and over.
                Instead of manually clicking through the same websites, forms, dashboards, and workflows,
                you can hand off the routine part and focus on the result you actually care about.
              </p>
              <p>
                In that sense, the experience is meant to feel familiar: if tools like ChatGPT help people
                turn natural-language questions into useful answers, Intelligent Browser Agents is meant to
                turn natural-language requests into completed work inside a browser.
              </p>
            </div>

            <aside className="about-aside">
              <p className="about-aside-label">Core principle</p>
              <p>
                The goal is not to replace the user. The goal is to remove repetition, keep the experience clear,
                and let the user stay in control of meaningful decisions.
              </p>
            </aside>
          </div>
        </section>

        <section className="about-section">
          <div className="about-section-heading">
            <p className="about-kicker">How a run works</p>
            <h2>Visible from start to finish.</h2>
          </div>

          <ol className="about-workflow">
            {workflow.map((item, index) => (
              <li key={item.title} className="about-workflow-item">
                <span className="about-workflow-number">{String(index + 1).padStart(2, "0")}</span>
                <div>
                  <h3>{item.title}</h3>
                  <p>{item.body}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section className="about-section about-section-system">
          <div className="about-section-heading">
            <p className="about-kicker">Who is handling the task?</p>
            <h2>Several agents. One outcome.</h2>
          </div>

          <div className="about-system-table">
            {agentRoles.map((section) => (
              <div key={section.label} className="about-system-row">
                <p className="about-system-label">{section.label}</p>
                <p className="about-system-body">{section.body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="about-section about-section-closing">
          <div className="about-section-heading">
            <p className="about-kicker">What users can expect</p>
            <h2>Automation you can trust.</h2>
          </div>

          <div className="about-closing-layout">
            <p>
              The experience is meant to be simple: say what you need, let the platform handle the tedious
              parts, and check in only when your judgment adds value.
            </p>
            <p>
              Over time, the value is not just speed. It is relief from repeated browser work and the feeling
              that a natural-language request can lead to real progress, not just an answer on a screen.
            </p>
          </div>
        </section>
      </main>
    </div>
  );
}
