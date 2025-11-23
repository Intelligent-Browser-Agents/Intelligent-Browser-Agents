from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"

DEFAULT_CONFIG: Dict[str, Any] = {
    "retrieval": {
        "method": "bm25",
        "top_k": 3,
    },
    "parser": {
        "max_chunk_len": 1200,
        "include_tables": True,
    },
    "qa": {
        "model_name": "distilbert-base-cased-distilled-squad",
        "max_answer_len": 64,
    },
    "scoring": {
        "weight_retriever": 0.35,
        "weight_qa": 0.65,
        "min_answer_chars": 2,
        "max_answer_chars": 200,
    },
    "api": {
        "max_dom_size_mb": 10,  # Maximum DOM size in MB (default 10MB for real-world DOMs)
    },
}

_cached_config: Dict[str, Any] | None = None


def load_config(force_reload: bool = False) -> Dict[str, Any]:
    """
    Load configuration from config.yaml with defaults.

    Args:
        force_reload: Whether to force reloading from disk.

    Returns:
        Configuration dictionary.
    """
    global _cached_config

    if _cached_config is not None and not force_reload:
        return _cached_config

    config = DEFAULT_CONFIG.copy()

    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            for section, defaults in DEFAULT_CONFIG.items():
                section_data = loaded.get(section, {})
                if isinstance(defaults, dict):
                    merged = defaults.copy()
                    merged.update(section_data)
                    config[section] = merged
                else:
                    config[section] = section_data or defaults
        except Exception:
            config = DEFAULT_CONFIG.copy()

    _cached_config = config
    return config


def get_config_value(path: str, default: Any = None) -> Any:
    """
    Retrieve a configuration value using dot notation.

    Args:
        path: Dot-separated path (e.g., "parser.max_chunk_len")
        default: Default value if the key is missing

    Returns:
        Config value or default.
    """
    config = load_config()
    keys = path.split(".")
    value: Any = config
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    return value

