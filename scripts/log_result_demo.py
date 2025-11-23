from __future__ import annotations

import asyncio
import json
from pprint import pprint
from uuid import uuid4

import httpx
from pydantic import ValidationError

from api.integration_stubs import ActionExecutionIntegration, ProcessingDataIntegration
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


async def test_api_endpoints(base_url: str = "http://127.0.0.1:8000") -> None:
    """Test the API endpoints with HTTP requests.

    Args:
        base_url: Base URL of the running API server.
    """
    print("\n" + "=" * 60)
    print("=== API Endpoint Testing ===")
    print("=" * 60 + "\n")

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        # Health check
        print("=== Health Check ===")
        try:
            response = await client.get("/ig/health")
            print(f"Status: {response.status_code}")
            pprint(response.json())
        except httpx.ConnectError:
            print("ERROR: API server is not running!")
            print(f"Start the server with: python -m scripts.run_log_api")
            return
        print()

        # Test logging via API
        print("=== POST /ig/log (Action Execution) ===")
        action_payload = ActionExecutionIntegration.example_click_payload()
        response = await client.post("/ig/log", json=action_payload)
        print(f"Status: {response.status_code}")
        if response.status_code == 201:
            record = response.json()
            print(f"Created record ID: {record['id']}")
            record_id = record["id"]
            trace_id = record["trace_id"]
        else:
            print(f"Error: {response.text}")
            return
        print()

        # Test Processing Data integration
        print("=== POST /ig/log (Processing Data) ===")
        processing_payload = ProcessingDataIntegration.example_payload()
        processing_payload["trace_id"] = trace_id  # Use same trace
        response = await client.post("/ig/log", json=processing_payload)
        print(f"Status: {response.status_code}")
        if response.status_code == 201:
            print(f"Created record ID: {response.json()['id']}")
        print()

        # Retrieve by trace
        print(f"=== GET /ig/log/{trace_id} ===")
        response = await client.get(f"/ig/log/{trace_id}")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Found {data['count']} records for trace {trace_id}")
        print()

        # Retrieve specific record
        print(f"=== GET /ig/log/record/{record_id} ===")
        response = await client.get(f"/ig/log/record/{record_id}")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            print("Record retrieved successfully")
            pprint(response.json())
        print()

        # List all logs
        print("=== GET /ig/log (list all) ===")
        response = await client.get("/ig/log", params={"limit": 10})
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Total records: {data['total']}, Showing: {len(data['records'])}")
        print()

        # Evidence stats
        print("=== GET /ig/evidence/stats ===")
        response = await client.get("/ig/evidence/stats")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            pprint(response.json())
        print()


def main_with_api() -> None:
    """Run both direct service demo and API tests."""
    print("=" * 60)
    print("=== Direct Service Demo ===")
    print("=" * 60 + "\n")
    main()

    # Run API tests
    try:
        asyncio.run(test_api_endpoints())
    except KeyboardInterrupt:
        print("\nAPI testing interrupted.")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--api":
        # Run API tests only (assumes server is running)
        asyncio.run(test_api_endpoints())
    else:
        # Run full demo (direct service + API if server available)
        main_with_api()

