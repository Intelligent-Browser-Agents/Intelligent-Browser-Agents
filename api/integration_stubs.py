from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from schemas import LogActionResult


class ProcessingDataIntegration:
    """Stub integration for receiving logs from the Processing Data module.

    The Processing Data module normalizes and scores extracted information
    before sending results to the logging system.
    """

    @staticmethod
    def create_log_payload(
        *,
        tool_name: str = "ProcessingData",
        task_id: UUID,
        trace_id: UUID,
        status: str,
        confidence_score: Optional[float] = None,
        output_data: Dict[str, Any],
        execution_time_ms: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Create a log payload from Processing Data module output.

        Args:
            tool_name: Name of the processing tool.
            task_id: Task identifier.
            trace_id: Trace identifier.
            status: Action status (success, fail, error).
            confidence_score: Confidence score from processing (0.0-1.0).
            output_data: Structured output data from processing.
            execution_time_ms: Execution time in milliseconds.

        Returns:
            Dictionary payload ready for LogResultService.
        """
        return {
            "tool_name": tool_name,
            "task_id": str(task_id),
            "trace_id": str(trace_id),
            "status": status,
            "confidence_score": confidence_score,
            "message": f"Processed data with confidence {confidence_score:.2f}" if confidence_score else "Data processing completed",
            "output": {
                "data": output_data,
            },
            "metadata": {
                "execution_time_ms": execution_time_ms,
                "agent": "IG/ProcessingData",
            },
        }

    @staticmethod
    def example_payload() -> Dict[str, Any]:
        """Generate an example payload for testing."""
        return ProcessingDataIntegration.create_log_payload(
            tool_name="ProcessingData",
            task_id=uuid4(),
            trace_id=uuid4(),
            status="success",
            confidence_score=0.85,
            output_data={
                "answer": "The hotel is located in downtown Orlando",
                "source_xpath": "/html/body/div[2]/p[1]",
                "chunk_text": "Our hotel is conveniently located in downtown Orlando...",
            },
            execution_time_ms=234.5,
        )


class ActionExecutionIntegration:
    """Stub integration for receiving logs from Action Execution tools.

    Action Execution tools perform browser interactions (clicks, inputs, etc.)
    and log their results with evidence (screenshots, DOM snapshots).
    """

    @staticmethod
    def create_log_payload(
        *,
        tool_name: str,
        task_id: UUID,
        trace_id: UUID,
        status: str,
        action_type: str,
        target_selector: str,
        screenshot_path: Optional[str] = None,
        dom_snapshot: Optional[str] = None,
        confirmation_message: Optional[str] = None,
        execution_time_ms: Optional[float] = None,
        error_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a log payload from Action Execution tool output.

        Args:
            tool_name: Name of the action tool (e.g., "IdentifyClickButton", "InputText").
            task_id: Task identifier.
            trace_id: Trace identifier.
            status: Action status (success, fail, error).
            action_type: Type of action performed (click, fill, submit, etc.).
            target_selector: CSS selector or XPath of the target element.
            screenshot_path: Path to screenshot evidence.
            dom_snapshot: DOM snapshot HTML string.
            confirmation_message: Success confirmation message.
            execution_time_ms: Execution time in milliseconds.
            error_message: Error message if action failed.

        Returns:
            Dictionary payload ready for LogResultService.
        """
        message = confirmation_message or error_message or f"{action_type} action on {target_selector}"

        return {
            "tool_name": tool_name,
            "task_id": str(task_id),
            "trace_id": str(trace_id),
            "status": status,
            "confidence_score": 0.95 if status == "success" else 0.3,
            "message": message,
            "evidence": {
                "screenshot_path": screenshot_path,
                "dom_snapshot": dom_snapshot,
            },
            "output": {
                "data": {
                    "action_type": action_type,
                    "target_selector": target_selector,
                    "status": status,
                },
            },
            "metadata": {
                "execution_time_ms": execution_time_ms,
                "agent": "IG/ActionExecutor",
            },
        }

    @staticmethod
    def example_click_payload() -> Dict[str, Any]:
        """Generate an example click action payload."""
        return ActionExecutionIntegration.create_log_payload(
            tool_name="IdentifyClickButton",
            task_id=uuid4(),
            trace_id=uuid4(),
            status="success",
            action_type="click",
            target_selector="#book-now-button",
            screenshot_path="evidence/click_action_123.png",
            dom_snapshot="<button id='book-now-button'>Book Now</button>",
            confirmation_message="Successfully clicked Book Now button",
            execution_time_ms=187.5,
        )

    @staticmethod
    def example_input_payload() -> Dict[str, Any]:
        """Generate an example input action payload."""
        return ActionExecutionIntegration.create_log_payload(
            tool_name="InputText",
            task_id=uuid4(),
            trace_id=uuid4(),
            status="fail",
            action_type="fill",
            target_selector="#email-input",
            screenshot_path="evidence/input_failed_456.png",
            dom_snapshot="<input id='email-input' type='email' disabled />",
            error_message="Input field is disabled or masked by modal",
            execution_time_ms=342.8,
        )


class DOMExtractionIntegration:
    """Stub integration for receiving logs from DOM Extraction module."""

    @staticmethod
    def create_log_payload(
        *,
        task_id: UUID,
        trace_id: UUID,
        status: str,
        url: str,
        dom_size: int,
        extraction_time_ms: Optional[float] = None,
        error_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a log payload from DOM Extraction output.

        Args:
            task_id: Task identifier.
            trace_id: Trace identifier.
            status: Extraction status.
            url: URL of the extracted page.
            dom_size: Size of extracted DOM in bytes.
            extraction_time_ms: Extraction time in milliseconds.
            error_message: Error message if extraction failed.

        Returns:
            Dictionary payload ready for LogResultService.
        """
        return {
            "tool_name": "DOMExtraction",
            "task_id": str(task_id),
            "trace_id": str(trace_id),
            "status": status,
            "confidence_score": 0.9 if status == "success" else 0.2,
            "message": error_message or f"Successfully extracted DOM from {url}",
            "output": {
                "data": {
                    "url": url,
                    "dom_size_bytes": dom_size,
                },
            },
            "metadata": {
                "execution_time_ms": extraction_time_ms,
                "agent": "IG/DOMExtraction",
            },
        }

