## Log Result of Action Prototype

This repository now focuses on the Information Gathering team's **Log Result of Action** tool.
The prototype validates, enriches, and stores action logs entirely in memory while producing
structured evidence payloads that align with the architecture outlined in the design document.

### Key Features
- Validated schemas for log payloads in `schemas/log_result_models.py`.
- In-memory logging service with UUID indexing in `tools/log_result.py`.
- Demonstration script covering success, failure, and validation error flows in `scripts/log_result_demo.py`.
- Legacy contact-agent code removed for a clean starting point.

### Installation
```bash
python -m venv .venv
.venv\Scripts\activate  # PowerShell on Windows
pip install -r requirements.txt
```

### Run the Demo
```bash
python -m scripts.log_result_demo
```

The script:
1. Logs a successful action with screenshot and DOM evidence.
2. Logs a failed action highlighting error messaging.
3. Attempts to log malformed data to demonstrate schema validation.
4. Displays stored records per trace and overall.

### Data Schema Summary
- Required fields: `tool_name`, `task_id`, `trace_id`, `status`, `timestamp`.
- `confidence_score` accepts values from 0.0–1.0.
- `evidence` optionally includes `screenshot_path`, `dom_snapshot`, and free-form `notes`.
- `metadata` captures timing, resource usage, and agent identifiers.
- Each log is persisted as a `LogRecord` with generated `id` and `received_at`.

### Next Steps
- Swap in persistent storage (SQLite or PostgreSQL).
- Provide a FastAPI endpoint to ingest logs over HTTP.
- Extend evidence handling to manage binary artifacts and retention policies.

