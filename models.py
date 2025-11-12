"""
Pydantic schemas for action commands and results
"""

from typing import Optional, Dict, Any, List, Literal
from pydantic import BaseModel, Field


class Target(BaseModel):
    """Target element specification"""
    selector: Optional[str] = None
    selector_type: Literal["css", "xpath", "role", "text", "none"] = "css"
    selector_strategy: Literal["strict", "role_or_text"] = "strict"
    role_hint: Optional[str] = None
    text_hint: Optional[str] = None
    frame_path: Optional[List[str]] = Field(default_factory=list)


class DragTarget(BaseModel):
    """Drag and drop target specification"""
    selector: str
    selector_type: Literal["css", "xpath", "role", "text"] = "css"


class ScrollConfig(BaseModel):
    """Scroll configuration"""
    direction: Literal["down", "up", "left", "right"] = "down"
    amount: int = 600


class ScreenshotConfig(BaseModel):
    """Screenshot configuration"""
    enabled: bool = True
    clip_to_element: bool = True


class ActionCommand(BaseModel):
    """Input command for an action"""
    trace_id: str
    session_id: str
    action_type: Literal[
        "navigate_to_url", "click_element", "double_click_element", 
        "type_input", "press_key", "hover_over", "scroll", "scroll_to",
        "upload_file", "drag_and_drop", "go_back", "go_forward",
        "reload_page", "close_tab", "switch_tab", "extract_dom",
        "get_element_text", "get_element_attribute", "take_screenshot",
        "search_and_click", "fill_out_form"
    ]
    target: Optional[Target] = Field(default_factory=Target)
    input_value: Optional[str] = None
    key: Optional[str] = None
    upload_path: Optional[str] = None
    drag_source: Optional[DragTarget] = None
    drop_target: Optional[DragTarget] = None
    scroll: Optional[ScrollConfig] = None
    timeout_ms: int = 8000
    screenshot: ScreenshotConfig = Field(default_factory=ScreenshotConfig)
    dom_snippet_chars: int = 4000
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class Timings(BaseModel):
    """Timing information in milliseconds"""
    resolve: int = 0
    interact: int = 0
    post_capture: int = 0


class Evidence(BaseModel):
    """Evidence captured during action execution"""
    screenshot_path: Optional[str] = None
    dom_snippet_path: Optional[str] = None
    dom_context_selector: Optional[str] = None
    visible_text: Optional[str] = None


class Details(BaseModel):
    """Additional action details"""
    navigated_url: Optional[str] = None
    element_final_selector: Optional[str] = None
    element_role: Optional[str] = None
    element_text_sample: Optional[str] = None


class ErrorInfo(BaseModel):
    """Error information"""
    code: Literal[
        "timeout", "element_not_found", "not_interactable", "detached",
        "navigation_failed", "upload_failed", "unsupported_action",
        "bad_command", "internal"
    ]
    message: str
    selector_attempted: Optional[str] = None
    stack: Optional[str] = None


class ActionResult(BaseModel):
    """Result of an action execution"""
    trace_id: str
    status: Literal["success", "failure", "partial"]
    action_type: str
    session_id: str
    timings_ms: Timings = Field(default_factory=Timings)
    evidence: Evidence = Field(default_factory=Evidence)
    details: Details = Field(default_factory=Details)
    error: Optional[ErrorInfo] = None