Gmail compose notes.

- A compose draft is open when the page shows a "To" recipients field, a "Subject" field, a message body editor, and a "Send" button. A step whose objective is only to open or start a draft is complete at that point; do not start filling fields under that step.
- Recipient entry has two parts: enter the address into the recipients combobox, then commit it by pressing Enter or clicking the matching suggestion. A typed address that has not become a chip is not committed, and Send will not deliver to it.
- The recipients field is a combobox that offers suggestions while typing. Prefer filling it directly over clicking "To" (which opens the contacts picker dialog).
- Work on one field per step: recipients, subject, and body are separate milestones. Do not re-enter a field that already holds the right value.
- The body editor is a contenteditable region, typically named "Message Body". It may not read back like a plain textbox; a fill that reports verified=false there can still have landed - check the snapshot.
- "Send" is irreversible. Everything else in compose is a draft edit.
