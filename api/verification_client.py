from __future__ import annotations

import asyncio
from typing import Optional
from uuid import UUID

import httpx
from schemas import LogRecord


class VerificationClient:
    """Stub client for sending logs to the Verification Agent.

    This client provides the interface for communicating with the Verification Agent,
    which will handle PostgreSQL persistence and validation of action results.
    """

    def __init__(
        self,
        *,
        verification_agent_url: Optional[str] = None,
        timeout: float = 5.0,
    ) -> None:
        """Initialize the verification client.

        Args:
            verification_agent_url: Base URL for Verification Agent API.
                If None, operations will be stubbed (no actual HTTP calls).
            timeout: Request timeout in seconds.
        """
        self.verification_agent_url = verification_agent_url
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> VerificationClient:
        """Async context manager entry."""
        if self.verification_agent_url:
            self._client = httpx.AsyncClient(
                base_url=self.verification_agent_url,
                timeout=self.timeout,
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def send_to_verification(self, record: LogRecord) -> dict:
        """Send a log record to the Verification Agent.

        The Verification Agent will persist the record to PostgreSQL and
        perform validation checks.

        Args:
            record: LogRecord to send to Verification Agent.

        Returns:
            Response dictionary with verification status.

        Note:
            If verification_agent_url is not set, this method returns
            a stub response without making HTTP calls.
        """
        if not self.verification_agent_url or not self._client:
            # Stub mode: return mock response
            return {
                "status": "stubbed",
                "message": "Verification Agent URL not configured",
                "record_id": str(record.id),
                "trace_id": str(record.trace_id),
            }

        try:
            response = await self._client.post(
                "/verify/log",
                json=record.model_dump(mode="json"),
            )
            response.raise_for_status()
            return response.json()

        except httpx.HTTPError as e:
            return {
                "status": "error",
                "error": str(e),
                "record_id": str(record.id),
            }

    async def check_trace_complete(self, trace_id: UUID) -> dict:
        """Check if all actions for a trace have been verified.

        Args:
            trace_id: Trace identifier to check.

        Returns:
            Dictionary with completion status and verification results.

        Note:
            If verification_agent_url is not set, this method returns
            a stub response without making HTTP calls.
        """
        if not self.verification_agent_url or not self._client:
            # Stub mode: return mock response
            return {
                "status": "stubbed",
                "message": "Verification Agent URL not configured",
                "trace_id": str(trace_id),
                "complete": False,
            }

        try:
            response = await self._client.get(
                f"/verify/trace/{trace_id}",
            )
            response.raise_for_status()
            return response.json()

        except httpx.HTTPError as e:
            return {
                "status": "error",
                "error": str(e),
                "trace_id": str(trace_id),
                "complete": False,
            }

    async def send_batch(self, records: list[LogRecord]) -> dict:
        """Send multiple log records in a batch.

        Args:
            records: List of LogRecords to send.

        Returns:
            Dictionary with batch processing results.
        """
        if not self.verification_agent_url or not self._client:
            return {
                "status": "stubbed",
                "message": "Verification Agent URL not configured",
                "count": len(records),
            }

        try:
            response = await self._client.post(
                "/verify/log/batch",
                json=[record.model_dump(mode="json") for record in records],
            )
            response.raise_for_status()
            return response.json()

        except httpx.HTTPError as e:
            return {
                "status": "error",
                "error": str(e),
                "count": len(records),
            }

