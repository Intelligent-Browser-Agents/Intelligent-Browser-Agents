#!/usr/bin/env python3
"""Entry point for running the Log Result of Action API server."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
load_dotenv()

if __name__ == "__main__":
    # Configuration from environment variables with defaults
    host = os.getenv("LOG_API_HOST", "127.0.0.1")
    port = int(os.getenv("LOG_API_PORT", "8000"))
    reload = os.getenv("LOG_API_RELOAD", "false").lower() == "true"
    log_level = os.getenv("LOG_API_LOG_LEVEL", "info")

    print(f"Starting Log Result API server on http://{host}:{port}")
    print(f"Reload: {reload}, Log Level: {log_level}")
    print(f"API Documentation: http://{host}:{port}/docs")

    uvicorn.run(
        "api.log_result_api:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )

