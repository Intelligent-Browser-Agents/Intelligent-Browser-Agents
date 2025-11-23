## Log Result of Action Tool

This repository implements the Information Gathering team's **Log Result of Action** tool.
The system validates, enriches, and stores action logs with evidence file management,
providing both direct Python API and HTTP endpoints for integration with other modules.

### Key Features

- **Validated Schemas**: Pydantic models for type-safe log payloads (`schemas/log_result_models.py`)
- **In-Memory Service**: Thread-safe logging service with UUID indexing (`tools/log_result.py`)
- **Evidence Management**: Automatic file storage with hashing, versioning, and retention (`tools/evidence_manager.py`)
- **FastAPI Endpoints**: RESTful API for HTTP integration (`api/log_result_api.py`)
- **Integration Stubs**: Ready-to-use stubs for Processing Data and Action Execution modules
- **Verification Client**: Stub client for sending logs to Verification Agent (PostgreSQL handled by BI team)

### Installation

```bash
python -m venv .venv
.venv\Scripts\activate  # PowerShell on Windows
pip install -r requirements.txt
```

### Quick Start

#### Direct Python Usage

```bash
python -m scripts.log_result_demo
```

#### Start API Server

```bash
python -m scripts.run_log_api
```

The API will be available at `http://127.0.0.1:8000` with interactive documentation at `/docs`.

#### Test API Endpoints

```bash
# Run demo with API tests (requires server running)
python -m scripts.log_result_demo

# Or test API only
python -m scripts.log_result_demo --api
```

### API Endpoints

#### POST `/ig/log`

Receive and store a log entry from an IG tool.

**Request Body:**

```json
{
  "tool_name": "IdentifyClickButton",
  "task_id": "uuid",
  "trace_id": "uuid",
  "status": "success",
  "confidence_score": 0.95,
  "message": "Clicked button successfully",
  "evidence": {
    "screenshot_path": "evidence/screenshot.png",
    "dom_snapshot": "<button>Click Me</button>"
  },
  "output": {
    "data": {
      "action": "click",
      "target": "#button-id"
    }
  },
  "metadata": {
    "execution_time_ms": 150.0,
    "agent": "IG/ActionExecutor"
  }
}
```

**Response:** `201 Created` with the created log record.

#### GET `/ig/log/{trace_id}`

Retrieve all log records for a specific trace.

**Response:**

```json
{
  "trace_id": "uuid",
  "count": 2,
  "records": [...]
}
```

#### GET `/ig/log/record/{record_id}`

Retrieve a specific log record by ID.

#### GET `/ig/log`

List all stored log records with pagination (`?limit=100&offset=0`).

#### GET `/ig/health`

Health check endpoint.

#### GET `/ig/evidence/stats`

Get statistics about evidence file storage.

#### POST `/ig/evidence/cleanup`

Trigger cleanup of expired evidence files.

### Integration Examples

#### Processing Data Module

```python
from api.integration_stubs import ProcessingDataIntegration
from uuid import uuid4

payload = ProcessingDataIntegration.create_log_payload(
    tool_name="ProcessingData",
    task_id=uuid4(),
    trace_id=uuid4(),
    status="success",
    confidence_score=0.85,
    output_data={"answer": "Extracted answer", "source": "xpath"},
    execution_time_ms=234.5,
)

# Send via API
import httpx
async with httpx.AsyncClient() as client:
    response = await client.post("http://localhost:8000/ig/log", json=payload)
```

#### Action Execution Module

```python
from api.integration_stubs import ActionExecutionIntegration

payload = ActionExecutionIntegration.create_log_payload(
    tool_name="IdentifyClickButton",
    task_id=uuid4(),
    trace_id=uuid4(),
    status="success",
    action_type="click",
    target_selector="#button-id",
    screenshot_path="evidence/click.png",
    dom_snapshot="<button>Click</button>",
    confirmation_message="Button clicked successfully",
    execution_time_ms=187.5,
)
```

#### Verification Agent Integration

```python
from api.verification_client import VerificationClient
from schemas import LogRecord

async with VerificationClient(
    verification_agent_url="http://verification-agent:8001"
) as client:
    # Send log record to Verification Agent
    result = await client.send_to_verification(record)

    # Check if trace is complete
    status = await client.check_trace_complete(trace_id)
```

### Data Schema Summary

**Required Fields:**

- `tool_name`: Name of the tool that produced the result
- `task_id`: Unique identifier for the task (UUID)
- `trace_id`: Trace identifier linking execution steps (UUID)
- `status`: Outcome (`"success"`, `"fail"`, or `"error"`)

**Optional Fields:**

- `confidence_score`: Float between 0.0 and 1.0
- `message`: Human-readable summary or error message
- `evidence`: Object with `screenshot_path`, `dom_snapshot`, and `notes`
- `output`: Structured output payload with tool-specific `data` dictionary
- `metadata`: Execution context with `execution_time_ms`, `memory_usage_mb`, `agent`, and `extra`

**Auto-Generated:**

- `id`: Unique record identifier (UUID)
- `timestamp`: UTC timestamp of action
- `received_at`: UTC timestamp when service accepted the record

### Evidence File Management

Evidence files (screenshots, DOM snapshots) are automatically stored with:

- **Hashed filenames**: Based on task_id + timestamp for security
- **Version tracking**: Retries create `evidence_1.png`, `evidence_2.png`, etc.
- **Retention policy**: Default 7 days, configurable
- **Automatic cleanup**: Use `/ig/evidence/cleanup` endpoint or call `EvidenceManager.cleanup_expired()`

### Architecture Integration

The Log Result tool integrates with:

1. **Processing Data Module**: Receives normalized, scored extraction results
2. **Action Execution Tools**: Receives browser interaction logs with evidence
3. **Verification Agent**: Sends formatted logs for PostgreSQL persistence and validation
4. **DOM Extraction**: Can receive DOM extraction completion logs

All communication uses the standardized `LogActionResult` schema, ensuring consistency across modules.

### Configuration

Environment variables (via `.env` file):

- `LOG_API_HOST`: API server host (default: `127.0.0.1`)
- `LOG_API_PORT`: API server port (default: `8000`)
- `LOG_API_RELOAD`: Enable auto-reload (default: `false`)
- `LOG_API_LOG_LEVEL`: Logging level (default: `info`)
- `VERIFICATION_AGENT_URL`: Verification Agent base URL (optional)

### Next Steps

- **PostgreSQL Persistence**: Handled by BI team's Verification Agent
- **WebSocket Support**: Future enhancement for real-time updates
- **Advanced Analytics**: Aggregation and analysis of log patterns
