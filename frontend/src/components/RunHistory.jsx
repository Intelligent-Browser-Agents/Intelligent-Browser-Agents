import { useEffect, useState } from "react";
import { api } from "../lib/api";

function when(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function Screenshot({ runId }) {
  const [url, setUrl] = useState(null);
  useEffect(() => {
    let revoked = false;
    let objectUrl = null;
    api.fetchRunScreenshot(runId)
      .then((u) => {
        objectUrl = u;
        if (!revoked) setUrl(u);
        else URL.revokeObjectURL(u);
      })
      .catch(() => {});
    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [runId]);
  if (!url) return null;
  return <img className="run-screenshot" src={url} alt="Final page of the run" />;
}

/**
 * Server-backed run history: what was asked, how it ended, the final answer,
 * per-item outcomes for batch missions, and the closing screenshot. Survives
 * refreshes because it never lived in this browser to begin with.
 */
export default function RunHistory({ refreshKey }) {
  const [runs, setRuns] = useState(null);
  const [error, setError] = useState("");
  const [openRunId, setOpenRunId] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api.listRuns()
      .then(({ runs: rows }) => {
        if (!cancelled) {
          setRuns(rows || []);
          setError("");
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setRuns([]);
          setError(err.detail || "Could not load run history.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  if (runs === null) {
    return <div className="thoughts-empty-state">Loading run history...</div>;
  }
  if (error) {
    return <div className="thoughts-empty-state">{error}</div>;
  }
  if (runs.length === 0) {
    return <div className="thoughts-empty-state">No runs yet. Your history will appear here.</div>;
  }

  return (
    <div className="run-history">
      {runs.map((run) => {
        const open = openRunId === run.run_id;
        return (
          <article key={run.run_id} className={`run-card${open ? " open" : ""}`}>
            <button
              type="button"
              className="run-card-summary"
              aria-expanded={open}
              onClick={() => setOpenRunId(open ? null : run.run_id)}
            >
              <span className="run-card-prompt">{run.prompt}</span>
              <span className="run-card-meta">
                <span className={`status-chip ${run.status}`}>{run.status}</span>
                <time>{when(run.started_at)}</time>
              </span>
            </button>
            {open && (
              <div className="run-card-detail">
                {run.exit_reason && <p className="run-exit-reason">{run.exit_reason}</p>}
                {Array.isArray(run.item_results) && run.item_results.length > 0 && (
                  <ul className="run-item-results">
                    {run.item_results.map((item, index) => (
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
                )}
                {run.final_response && <p className="run-final-response">{run.final_response}</p>}
                {run.has_screenshot && <Screenshot runId={run.run_id} />}
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}
