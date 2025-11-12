from __future__ import annotations

import json
from pprint import pprint
from uuid import uuid4

from pydantic import ValidationError

from tools.log_result import LogResultService


def serialize(record) -> dict:
    """Helper to convert Pydantic models into JSON-serialisable dicts."""
    return json.loads(record.model_dump_json())


def main() -> None:
    service = LogResultService()

    shared_trace_id = uuid4()
    task_a = uuid4()
    task_b = uuid4()

    print("=== Logging successful action ===")
    success_record = service.log_action_result(
        {
            "tool_name": "IdentifyClickButton",
            "task_id": str(task_a),
            "trace_id": str(shared_trace_id),
            "status": "success",
            "confidence_score": 0.92,
            "message": "Clicked primary call-to-action button.",
            "evidence": {
                "screenshot_path": "evidence/identify_click_button_1.png",
                "dom_snapshot": "<button id='cta'>Book Now</button>",
            },
            "output": {
                "data": {
                    "action": "click",
                    "target": "#cta",
                    "confirmation": "Navigation triggered",
                }
            },
            "metadata": {
                "execution_time_ms": 187.5,
                "agent": "IG/ActionExecutor",
            },
        }
    )
    pprint(serialize(success_record))
    print()

    print("=== Logging failed action ===")
    failure_record = service.log_action_result(
        {
            "tool_name": "InputText",
            "task_id": str(task_b),
            "trace_id": str(shared_trace_id),
            "status": "fail",
            "message": "Field masked by modal dialog.",
            "evidence": {
                "screenshot_path": "evidence/input_text_modal_block.png",
            },
            "output": {"data": {"field": "#email", "value": "user@example.com"}},
            "metadata": {
                "execution_time_ms": 342.8,
                "agent": "IG/ActionExecutor",
            },
        }
    )
    pprint(serialize(failure_record))
    print()

    print("=== Attempting to log malformed payload (expect ValidationError) ===")
    try:
        service.log_action_result({"tool_name": "Broken", "status": "success"})
    except ValidationError as exc:
        print("ValidationError captured:")
        print(exc)
    print()

    print("=== Records for shared trace ===")
    trace_records = service.get_records_for_trace(shared_trace_id)
    for idx, record in enumerate(trace_records, start=1):
        print(f"Record {idx}:")
        pprint(serialize(record))
    print()

    print("=== All stored records ===")
    for record in service.list_records():
        pprint(serialize(record))


if __name__ == "__main__":
    main()

