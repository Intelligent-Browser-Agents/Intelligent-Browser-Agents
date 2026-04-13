import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BACKEND_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dom_extraction import dom_extractor


def test_list_click_targets_promotes_generic_role_from_card_markers():
    payload = {
        "interactive_elements": [
            {
                "role": "generic",
                "name": "",
                "url": "https://booking.com",
                "title": "Booking",
                "attributes": {
                    "class": ["property-card", "clickable"],
                    "data-testid": "property-card-title",
                },
            }
        ]
    }

    targets = dom_extractor.list_dom_click_targets_from_interactive_json(
        json.dumps(payload),
        max_results=10,
        roles=("link", "button", "tab"),
    )

    assert targets
    assert targets[0]["role"] == "button"


def test_list_click_targets_recovers_name_from_data_testid_when_missing():
    payload = {
        "interactive_elements": [
            {
                "role": "button",
                "name": "",
                "url": "https://booking.com",
                "title": "Booking",
                "attributes": {
                    "data-testid": "show-prices-button",
                },
            }
        ]
    }

    targets = dom_extractor.list_dom_click_targets_from_interactive_json(
        json.dumps(payload),
        max_results=10,
        roles=("link", "button", "tab"),
    )

    assert targets
    assert "show prices" in targets[0]["name"].lower()
