import { useState } from "react";

/**
 * Structured human-in-the-loop form. The backend sends `requested_fields`
 * (one short label per thing the agent needs); this renders one labeled input
 * per field instead of the old blank chat box, and submits a single reply.
 *
 * "confirmation" fields are the browser-interaction case ("do it in the live
 * view, then tell me when you're done"), so they get a one-click Done button.
 * "approval" fields are the sensitive-action checkpoint and get Yes/No buttons:
 * a typed "yesd" once stalled a run for three transactions.
 */
export default function HitlForm({ hitl, onSubmit }) {
  const fields = hitl.requestedFields.length > 0 ? hitl.requestedFields : ["reply"];
  const [values, setValues] = useState(() => Object.fromEntries(fields.map((f) => [f, ""])));
  const [sent, setSent] = useState(false);

  const isConfirmationOnly = fields.length === 1 && fields[0] === "confirmation";
  const isApprovalOnly = fields.length === 1 && fields[0] === "approval";

  const send = (reply) => {
    if (sent) return;
    setSent(true);
    onSubmit(reply);
  };

  const submit = (e) => {
    e.preventDefault();
    if (sent) return;
    let reply;
    if (isConfirmationOnly) {
      reply = "done";
    } else if (fields.length === 1) {
      reply = values[fields[0]].trim();
      if (!reply) return;
    } else {
      const parts = fields
        .map((field) => ({ field, value: values[field].trim() }))
        .filter(({ value }) => value)
        .map(({ field, value }) => `${field}: ${value}`);
      if (parts.length === 0) return;
      reply = parts.join("\n");
    }
    send(reply);
  };

  return (
    <form className="hitl-form" onSubmit={submit} aria-label="The agent needs input">
      <p className="hitl-form-title">
        {isApprovalOnly ? "The agent needs your approval" : "The agent needs your input"}
      </p>
      {isApprovalOnly ? (
        <>
          <p className="hitl-form-hint">
            Approve the action described above, or cancel it. Nothing runs until you choose.
          </p>
          <div className="hitl-form-actions">
            <button type="button" className="btn btn-primary" disabled={sent} onClick={() => send("yes")}>
              Yes, proceed
            </button>
            <button type="button" className="btn btn-secondary" disabled={sent} onClick={() => send("no")}>
              No, cancel
            </button>
          </div>
        </>
      ) : isConfirmationOnly ? (
        <p className="hitl-form-hint">
          Take over the live view if needed, then confirm when you are done.
        </p>
      ) : (
        fields.map((field) => (
          <label key={field} className="hitl-form-field">
            <span className="field-label">{field}</span>
            <input
              className="text-input"
              type="text"
              value={values[field]}
              disabled={sent}
              onChange={(e) => setValues((prev) => ({ ...prev, [field]: e.target.value }))}
            />
          </label>
        ))
      )}
      {!isApprovalOnly && (
        <button type="submit" className="btn btn-primary" disabled={sent}>
          {sent ? "Sent" : isConfirmationOnly ? "Done, continue" : "Send"}
        </button>
      )}
    </form>
  );
}
