# Makefile for Intelligent Browser Agents Backend

# Variables
PYTHON = python3
PIP = $(PYTHON) -m pip
PYTEST = $(PYTHON) -m pytest

# Default target
.PHONY: help
help:
	@echo "Intelligent Browser Agents - Backend Makefile"
	@echo ""
	@echo "Available commands:"
	@echo "  make install          - Install all dependencies"
	@echo "  make install-dev      - Install dev dependencies (pytest, etc.)"
	@echo "  make test             - Run all tests"
	@echo "  make test-actions     - Run action execution tests only"
	@echo "  make test-server      - Run server tests only"
	@echo "  make run              - Run the main application"
	@echo "  make clean            - Clean up cache files"
	@echo "  make playwright       - Install Playwright browsers"
	@echo ""

# Install dependencies
.PHONY: install
install:
	@echo "Installing dependencies..."
	$(PIP) install --upgrade pip
	$(PIP) install playwright
	$(PIP) install langchain
	$(PIP) install langchain-core
	$(PIP) install langgraph
	$(PIP) install google-generativeai
	$(PIP) install beautifulsoup4
	$(PIP) install pympler
	$(PIP) install pydantic
	$(PIP) install fastapi
	$(PIP) install uvicorn
	@echo "Dependencies installed successfully!"

# Install development dependencies
.PHONY: install-dev
install-dev: install
	@echo "Installing dev dependencies..."
	$(PIP) install pytest
	$(PIP) install pytest-asyncio
	@echo "Dev dependencies installed successfully!"

# Install Playwright browsers
.PHONY: playwright
playwright:
	@echo "Installing Playwright browsers..."
	$(PYTHON) -m playwright install chromium
	@echo "Playwright browsers installed successfully!"

# Run all tests
.PHONY: test
test:
	@echo "Running all tests..."
	$(PYTEST) tests/ -v

# Run action execution tests only
.PHONY: test-actions
test-actions:
	@echo "Running action execution tests..."
	$(PYTHON) -m tests.test_action_system

# Run server tests only
.PHONY: test-server
test-server:
	@echo "Running server tests..."
	$(PYTEST) tests/test_server.py -v

# Run execution handler unit tests
.PHONY: test-execution
test-execution:
	@echo "Running execution handler tests..."
	$(PYTEST) tests/execution/ -v

# Run the main application
.PHONY: run
run:
	@echo "Starting application..."
	$(PYTHON) -m src.app

# Clean up cache files
.PHONY: clean
clean:
	@echo "Cleaning up cache files..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@echo "Cache files cleaned!"

# Full setup (install everything)
.PHONY: setup
setup: install install-dev playwright
	@echo ""
	@echo "Setup complete! Run 'make test' to verify everything works."
