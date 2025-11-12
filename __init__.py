"""
IG Action Execution Module

A minimal browser action execution library using Playwright.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from models import ActionCommand, ActionResult, Target, ErrorInfo
from runner import run_action, run_action_sync
from browser import browser_manager

__version__ = "1.0.0"
__all__ = [
    "ActionCommand",
    "ActionResult",
    "Target",
    "ErrorInfo",
    "run_action",
    "run_action_sync",
    "browser_manager"
]