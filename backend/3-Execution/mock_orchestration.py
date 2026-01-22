# === mock_orchestration.py ===
# Temporary mock orchestration agent
# Purpose: Provide structured planning output for Execution Agent testing

def main():
    print("mock_orchestration.py running...")

    orchestration_output = {
        "session_id": "session-001",
        "task_id": "task-uuid-hotel-001",

        # High-level intent
        "overall_goal": (
            "Book a room at the Sunshine Inn Orlando "
            "for John Doe from Dec 1 to Dec 3"
        ),

        # Current step the Execution Agent should handle
        "current_step": {
            "step_id": 2,
            "step_name": "identify_booking_entry_point",
            "description": "Identify and confirm the 'Book Now' entry point on the homepage",

            # What success means for THIS step
            "success_criteria": [
                "At least one interactive element is identified",
                "An element semantically matches a booking action",
                "Confidence score >= 0.90"
            ],

            # What kind of IG tools are allowed to be used
            "expected_ig_tools": [
                "DOMExtraction",
                "DOMUnderstandingAgent"
            ]
        },

        # Constraints the Execution Agent must respect
        "constraints": {
            "requires_auth": False,
            "headless_allowed": True,
            "max_ig_calls": 3
        },

        # Context passed down for reasoning
        "context": {
            "target_url": "https://www.sunshine-inn-orlando.com",
            "user_data": {
                "guest_name": "John Doe",
                "check_in_date": "12/01/2025",
                "check_out_date": "12/03/2025"
            }
        }
    }

    return orchestration_output


if __name__ == "__main__":
    output = main()
    print(output)
