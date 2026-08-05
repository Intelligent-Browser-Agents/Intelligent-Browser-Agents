Outlook (web) compose notes.

- A compose draft is open when the page shows a "To" recipients field, an "Add a subject" field, a message body editor, and a "Send" button; a new draft may show "(No subject)". A step whose objective is only to open or start a draft is complete at that point; do not start filling fields under that step.
- Recipient entry has two parts: enter the address into the recipients field, then commit it by pressing Enter or clicking the matching suggestion so it becomes a chip. A typed address without its chip is not committed.
- Prefer filling the inline recipients field directly. The "To" button and "Add Recipients"/"People" controls open a directory picker dialog; do not use them while an inline editable recipients field is visible.
- Work on one field per step: recipients, subject, and body are separate milestones. Do not re-enter a field that already holds the right value.
- The body editor is a contenteditable region. It may not read back like a plain textbox; a fill that reports verified=false there can still have landed - check the snapshot.
- "Send" is irreversible. Everything else in compose is a draft edit.
