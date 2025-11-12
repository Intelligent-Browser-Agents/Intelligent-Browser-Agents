"""
Error taxonomy and exception mapping
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import traceback
from typing import Optional
from playwright.async_api import TimeoutError, Error as PlaywrightError
from models import ErrorInfo


class ActionExecutionError(Exception):
    """Base exception for action execution errors"""
    def __init__(self, code: str, message: str, selector: Optional[str] = None):
        self.code = code
        self.message = message
        self.selector = selector
        super().__init__(message)


def map_exception_to_error(
    exception: Exception,
    selector_attempted: Optional[str] = None
) -> ErrorInfo:
    """
    Map an exception to an ErrorInfo object
    
    Args:
        exception: The exception to map
        selector_attempted: The selector that was attempted
        
    Returns:
        ErrorInfo object with appropriate error code and message
    """
    error_code = "internal"
    message = str(exception)
    
    if isinstance(exception, TimeoutError):
        error_code = "timeout"
        message = f"Action timed out: {message}"
    elif isinstance(exception, PlaywrightError):
        if "not found" in message.lower():
            error_code = "element_not_found"
        elif "not visible" in message.lower() or "not interactable" in message.lower():
            error_code = "not_interactable"
        elif "detached" in message.lower():
            error_code = "detached"
        elif "navigation" in message.lower():
            error_code = "navigation_failed"
    elif isinstance(exception, FileNotFoundError):
        error_code = "upload_failed"
        message = f"File not found for upload: {message}"
    elif isinstance(exception, ActionExecutionError):
        error_code = exception.code
        message = exception.message
        selector_attempted = exception.selector or selector_attempted
    elif isinstance(exception, ValueError):
        error_code = "bad_command"
    elif isinstance(exception, NotImplementedError):
        error_code = "unsupported_action"
    
    return ErrorInfo(
        code=error_code,  # type: ignore
        message=message,
        selector_attempted=selector_attempted,
        stack=traceback.format_exc()
    )