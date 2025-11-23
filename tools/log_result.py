from __future__ import annotations

from collections import defaultdict
from threading import RLock
from typing import Dict, Iterable, List, MutableMapping, Optional, Sequence, Union
from uuid import UUID

from schemas import LogActionResult, LogRecord
from tools.evidence_manager import EvidenceManager


class LogResultService:
    """In-memory implementation of the Log Result of Action tool.

    This prototype validates incoming payloads against the LogActionResult schema,
    enriches them with service-level metadata (record id, receipt timestamp),
    and stores them in a trace-indexed registry for retrieval.
    """

    def __init__(
        self,
        *,
        initial_records: Optional[MutableMapping[UUID, Sequence[LogRecord]]] = None,
        evidence_manager: Optional[EvidenceManager] = None,
    ) -> None:
        self._lock = RLock()
        self._records_by_trace: Dict[UUID, List[LogRecord]] = defaultdict(list)
        self._records_by_id: Dict[UUID, LogRecord] = {}
        self._evidence_manager = evidence_manager or EvidenceManager()

        if initial_records:
            for trace_id, records in initial_records.items():
                for record in records:
                    self._store_record(record, trace_id)

    def log_action_result(
        self, payload: Union[LogActionResult, Dict]
    ) -> LogRecord:
        """Validate and store a log entry.

        Args:
            payload: A LogActionResult model or dict payload.

        Returns:
            The persisted LogRecord instance.

        Raises:
            pydantic.ValidationError: If payload fails schema validation.
        """
        model = (
            payload
            if isinstance(payload, LogActionResult)
            else LogActionResult.model_validate(payload)
        )
        record = LogRecord(**model.model_dump())

        with self._lock:
            self._store_record(record, record.trace_id)

        return record

    def list_records(self) -> List[LogRecord]:
        """Return all stored log records (chronological per trace)."""
        with self._lock:
            return list(self._records_by_id.values())

    def get_records_for_trace(self, trace_id: UUID) -> List[LogRecord]:
        """Fetch all records associated with a trace identifier."""
        with self._lock:
            return list(self._records_by_trace.get(trace_id, []))

    def get_record(self, record_id: UUID) -> Optional[LogRecord]:
        """Lookup a single record by its unique identifier."""
        with self._lock:
            return self._records_by_id.get(record_id)

    def clear(self) -> None:
        """Remove all stored records (useful for tests)."""
        with self._lock:
            self._records_by_trace.clear()
            self._records_by_id.clear()

    def get_evidence_manager(self) -> EvidenceManager:
        """Get the evidence manager instance."""
        return self._evidence_manager

    def _store_record(self, record: LogRecord, trace_id: UUID) -> None:
        """Internal helper to store a record in all indexes."""
        self._records_by_trace[trace_id].append(record)
        self._records_by_id[record.id] = record


