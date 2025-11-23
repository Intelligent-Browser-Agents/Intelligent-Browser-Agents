from __future__ import annotations

import asyncio
from typing import List, Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from schemas import LogActionResult, LogRecord
from tools.evidence_manager import EvidenceManager
from tools.log_result import LogResultService

app = FastAPI(
    title="Log Result of Action API",
    description="API for logging and retrieving action results from Information Gathering tools",
    version="1.0.0",
)

# Global service instance (initialized on startup)
service: Optional[LogResultService] = None
evidence_manager: Optional[EvidenceManager] = None


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize service and evidence manager on startup."""
    global service, evidence_manager
    evidence_manager = EvidenceManager()
    service = LogResultService(evidence_manager=evidence_manager)


@app.get("/ig/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "log_result",
        "version": "1.0.0",
    }


@app.post("/ig/log", status_code=status.HTTP_201_CREATED)
async def log_action_result(payload: dict) -> JSONResponse:
    """Receive and store a log entry from an IG tool.

    This is the main endpoint for Information Gathering tools to submit
    their action results. The payload is validated against the LogActionResult
    schema and stored with evidence file management.

    Args:
        payload: JSON payload matching LogActionResult schema.

    Returns:
        JSON response with the created log record.

    Raises:
        HTTPException: If validation fails or service is unavailable.
    """
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Log service not initialized",
        )

    try:
        # Validate payload
        action_result = LogActionResult.model_validate(payload)

        # Store evidence files if provided
        if evidence_manager and action_result.evidence:
            evidence = action_result.evidence
            task_id = action_result.task_id
            timestamp = action_result.timestamp

            # Store DOM snapshot if provided as string
            if evidence.dom_snapshot:
                dom_path = await evidence_manager.store_dom_snapshot(
                    task_id=task_id,
                    timestamp=timestamp,
                    dom_content=evidence.dom_snapshot,
                )
                # Update evidence path if it was a placeholder
                if not evidence.screenshot_path or evidence.screenshot_path.startswith("evidence/"):
                    evidence.screenshot_path = str(dom_path)

        # Store log record
        record = service.log_action_result(action_result)

        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=record.model_dump(mode="json"),
        )

    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "Validation failed",
                "errors": e.errors(),
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}",
        )


@app.get("/ig/log/{trace_id}")
async def get_logs_by_trace(trace_id: UUID) -> dict:
    """Retrieve all log records for a specific trace.

    Args:
        trace_id: Trace identifier linking multiple action steps.

    Returns:
        JSON response with list of log records for the trace.

    Raises:
        HTTPException: If service is unavailable.
    """
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Log service not initialized",
        )

    records = service.get_records_for_trace(trace_id)

    return {
        "trace_id": str(trace_id),
        "count": len(records),
        "records": [record.model_dump(mode="json") for record in records],
    }


@app.get("/ig/log/record/{record_id}")
async def get_log_record(record_id: UUID) -> dict:
    """Retrieve a specific log record by ID.

    Args:
        record_id: Unique identifier for the log record.

    Returns:
        JSON response with the log record.

    Raises:
        HTTPException: If record not found or service unavailable.
    """
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Log service not initialized",
        )

    record = service.get_record(record_id)

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Log record {record_id} not found",
        )

    return record.model_dump(mode="json")


@app.get("/ig/log")
async def list_all_logs(limit: int = 100, offset: int = 0) -> dict:
    """List all stored log records with pagination.

    Args:
        limit: Maximum number of records to return.
        offset: Number of records to skip.

    Returns:
        JSON response with paginated list of log records.
    """
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Log service not initialized",
        )

    all_records = service.list_records()
    total = len(all_records)
    paginated = all_records[offset : offset + limit]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "records": [record.model_dump(mode="json") for record in paginated],
    }


@app.get("/ig/evidence/stats")
async def get_evidence_stats() -> dict:
    """Get statistics about evidence file storage.

    Returns:
        JSON response with storage statistics.
    """
    if evidence_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Evidence manager not initialized",
        )

    return evidence_manager.get_storage_stats()


@app.post("/ig/evidence/cleanup")
async def cleanup_expired_evidence() -> dict:
    """Trigger cleanup of expired evidence files.

    Returns:
        JSON response with cleanup results.
    """
    if evidence_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Evidence manager not initialized",
        )

    removed_count = await evidence_manager.cleanup_expired()

    return {
        "removed_files": removed_count,
        "status": "completed",
    }

