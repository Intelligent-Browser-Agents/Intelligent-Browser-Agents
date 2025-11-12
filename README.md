# Intelligent Browser Agents

A minimal browser action execution library using Playwright.

## Setup

### Prerequisites
- Python 3.10+
- macOS/Linux/Windows

### Installation

1. Clone/navigate to repository:
```bash
cd intelligent_browser_agents
```

2. Create and activate virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Running the Project

### ✅ Run Demo Directly (RECOMMENDED)

From **inside** the `intelligent_browser_agents` folder:

```bash
source venv/bin/activate
python demo.py
```

This works because all Python files use absolute imports with `sys.path.insert()` at the top.

### ✅ Run Tests

From the **parent directory** (one level up):

```bash
source intelligent_browser_agents/venv/bin/activate
python -m pytest intelligent_browser_agents/tests/ -v
```

Or run a specific test:
```bash
python -m pytest intelligent_browser_agents/tests/test_primitives.py::test_click_button -v
```

## Import Strategy

**All files use the same pattern:**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

# Now absolute imports work
from models import ActionCommand, Target
from runner import run_action
from browser import browser_manager
```

**Why this works:**
- ✅ `python demo.py` from inside folder → works
- ✅ `pytest` from parent folder → works  
- ✅ No relative imports (no dots) → simple and consistent
- ✅ No circular imports → clean dependencies

## Project Structure

```
intelligent_browser_agents/
├── __init__.py              # Package init (with sys.path setup)
├── demo.py                  # Demo entry point
├── actions.py               # Browser actions (click, type, scroll)
├── models.py                # Pydantic data models
├── runner.py                # Action execution runner
├── browser.py               # Playwright browser manager
├── errors.py                # Error handling & mapping
├── resolver.py              # CSS/XPath selector resolution
├── sensing.py               # DOM extraction
├── evidence.py              # Screenshot & DOM capture
├── metrics.py               # Timing metrics
├── requirements.txt         # pip dependencies
├── README.md                # This file
├── tests/
│   ├── __init__.py
│   ├── test_primitives.py
│   └── fixtures/
│       └── test_page.html
└── venv/                    # Virtual environment
```

## Dependencies

- **playwright** - Browser automation
- **pydantic** - Data validation  
- **pytest** - Testing framework
- **pytest-asyncio** - Async test support

See `requirements.txt` for versions.

## Troubleshooting

### "No module named X"
- Check you're in the right directory
- Ensure venv is activated: `source venv/bin/activate`
- Verify sys.path.insert() is in all module files

### "Playwright executable not found"
```bash
playwright install
```

### Tests not collecting
```bash
python -m pytest --collect-only intelligent_browser_agents/tests/
```

## Development

### File descriptions:
- **models.py** - Pydantic models for commands/results/targets
- **runner.py** - Main dispatch loop that executes actions
- **actions.py** - Implementation of all primitive actions
- **resolver.py** - Selector resolution (CSS/XPath/role)
- **browser.py** - Playwright browser & context management
- **sensing.py** - DOM extraction & analysis utilities
- **evidence.py** - Screenshot and DOM snippet capture

### Running with coverage:
```bash
python -m pytest intelligent_browser_agents/tests/ --cov=intelligent_browser_agents
```

## License

MIT