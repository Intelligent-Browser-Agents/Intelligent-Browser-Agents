# === IG_DOM_Extraction.py ===
# Temporary mock Information Gathering (IG) output
# Purpose: Emit LROA-style logs for Execution Agent testing

from datetime import datetime


def main():
    print("IG_DOM_Extraction running...")

    timestamp = datetime.utcnow().isoformat() + "Z"

    lroa_logs = [

        # ---- LOG 1: DOM Extraction ----
        {
            "id": "log-002",
            "tool_name": "DOMExtraction",
            "task_id": "task-uuid-hotel-001",
            "trace_id": "trace-002",
            "status": "success",
            "timestamp": timestamp,
            "confidence_score": 1.0,
            "message": "Page loaded successfully",

            "evidence": {
                "screenshot_path": "evidence/task-001/home.png",
                "dom_snapshot": "evidence/task-001/home.html",
                "notes": "Mock DOM extraction. Status 200 OK."
            },

            "output": {
                "data": {
                    "url": "https://www.sunshine-inn-orlando.com",
                    "title": "Sunshine Inn - Home",
                    "content_length": 45210
                }
            },

            "metadata": {
                "execution_time_ms": 3100,
                "tool": "IG/Extraction"
            }
        },

        # ---- LOG 2: DOM Understanding ----
        {
            "id": "log-003",
            "tool_name": "DOMUnderstandingAgent",
            "task_id": "task-uuid-hotel-001",
            "trace_id": "trace-003",
            "status": "success",
            "timestamp": timestamp,
            "confidence_score": 0.96,
            "message": "Identified primary booking interaction",

            "evidence": {
                "screenshot_path": "evidence/task-001/home.png",
                "dom_snapshot": None,
                "notes": "Mock semantic analysis of interactive elements."
            },

            "output": {
                "data": {
                    "interactive_elements": [
                        {
                            "element_id": "nav-book-btn",
                            "tag": "a",
                            "xpath": "/html/body/header/nav/div[2]/a[1]",
                            "description": "Primary 'Book Now' button",
                            "semantic_role": "booking_entry_point",
                            "action_type": "click"
                        }
                    ]
                }
            },

            "metadata": {
                "execution_time_ms": 1200,
                "tool": "IG/Understanding"
            }
        }
    ]

    return lroa_logs


if __name__ == "__main__":
    logs = main()
    for log in logs:
        print(log)
