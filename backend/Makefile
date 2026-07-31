# Makefile for Intelligent Browser Agents Backend
#
# Pytest configuration lives in ../pyproject.toml, so test targets run from the
# repository root. Targets here are thin wrappers; nothing duplicates the
# dependency list, which is requirements.txt.

PYTHON = python
PIP = $(PYTHON) -m pip
PYTEST = $(PYTHON) -m pytest
ROOT = ..

# Default target
.PHONY: help
help:
	@echo "Intelligent Browser Agents - Backend Makefile"
	@echo ""
	@echo "Available commands:"
	@echo "  make install          - Install runtime dependencies"
	@echo "  make install-dev      - Install runtime + test dependencies"
	@echo "  make playwright       - Install the Chromium browser binary"
	@echo "  make test             - Run the offline test suite"
	@echo "  make test-browser     - Run tests that need a real browser + network"
	@echo "  make test-llm         - Run tests that make billable model calls"
	@echo "  make test-all         - Run every test, including browser and llm"
	@echo "  make test-server      - Run server tests only"
	@echo "  make test-execution   - Run execution handler tests only"
	@echo "  make serve            - Run the API server with reload"
	@echo "  make lint-frontend    - Run eslint in ../frontend"
	@echo "  make clean            - Clean up cache files"

# Install dependencies
.PHONY: install
install:
	@echo "Installing runtime dependencies..."
	$(PIP) install --upgrade pip
	$(PIP) install -r $(ROOT)/requirements.txt
	@echo "Dependencies installed successfully!"

.PHONY: install-dev
install-dev:
	@echo "Installing runtime + test dependencies..."
	$(PIP) install --upgrade pip
	$(PIP) install -r $(ROOT)/requirements-dev.txt
	@echo "Dev dependencies installed successfully!"

# Install Playwright browsers
.PHONY: playwright
playwright:
	@echo "Installing Playwright browsers..."
	$(PYTHON) -m playwright install chromium
	@echo "Playwright browsers installed successfully!"

# Offline suite. Browser and llm tests are deselected by default via addopts.
.PHONY: test
test:
	cd $(ROOT) && $(PYTEST) -q

.PHONY: test-browser
test-browser:
	cd $(ROOT) && $(PYTEST) -m browser -v

.PHONY: test-llm
test-llm:
	cd $(ROOT) && $(PYTEST) -m llm -v

.PHONY: test-all
test-all:
	cd $(ROOT) && $(PYTEST) -m "" -v

.PHONY: test-server
test-server:
	cd $(ROOT) && $(PYTEST) backend/tests/test_server.py -v

.PHONY: test-execution
test-execution:
	cd $(ROOT) && $(PYTEST) -m browser backend/tests/execution/ -v

# Run the API server
.PHONY: serve
serve:
	$(PYTHON) -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload

.PHONY: lint-frontend
lint-frontend:
	cd $(ROOT)/frontend && npx eslint .

# Clean up cache files
.PHONY: clean
clean:
	@echo "Cleaning up cache files..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(ROOT)/.pytest_cache
	@echo "Clean complete!"
