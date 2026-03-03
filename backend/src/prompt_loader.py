"""
Prompt Loader Utility
Loads system prompts from markdown files in the prompts directory.
"""

import os
from pathlib import Path
from functools import lru_cache


# Get the directory where this file is located
_BASE_DIR = Path(__file__).parent
_PROMPTS_DIR = _BASE_DIR / "prompts"


@lru_cache(maxsize=10)
def load_prompt(prompt_name: str) -> str:
    """
    Load a prompt from the prompts directory.
    
    Args:
        prompt_name: Name of the prompt file (without .prompt.md extension)
                    e.g., "orchestration", "execution", "verification"
    
    Returns:
        The contents of the prompt file as a string.
    
    Raises:
        FileNotFoundError: If the prompt file doesn't exist.
    """
    prompt_file = _PROMPTS_DIR / f"{prompt_name}.prompt.md"
    
    if not prompt_file.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {prompt_file}\n"
            f"Available prompts: {list_available_prompts()}"
        )
    
    with open(prompt_file, "r", encoding="utf-8") as f:
        return f.read()


def list_available_prompts() -> list[str]:
    """
    List all available prompt files in the prompts directory.
    
    Returns:
        List of prompt names (without .prompt.md extension)
    """
    if not _PROMPTS_DIR.exists():
        return []
    
    prompts = []
    for file in _PROMPTS_DIR.glob("*.prompt.md"):
        # Remove the .prompt.md extension
        name = file.stem.replace(".prompt", "")
        prompts.append(name)
    
    return sorted(prompts)


def get_prompts_directory() -> Path:
    """Return the path to the prompts directory."""
    return _PROMPTS_DIR


# Convenience functions for each agent type
def get_orchestration_prompt() -> str:
    """Load the orchestration agent prompt."""
    return load_prompt("orchestration")


def get_execution_prompt() -> str:
    """Load the execution agent prompt."""
    return load_prompt("execution")


def get_verification_prompt() -> str:
    """Load the verification agent prompt."""
    return load_prompt("verification")


def get_fallback_prompt() -> str:
    """Load the fallback agent prompt."""
    return load_prompt("fallback")


def get_interaction_prompt() -> str:
    """Load the interaction agent prompt."""
    return load_prompt("interaction")


if __name__ == "__main__":
    # Test the loader
    print("Available prompts:", list_available_prompts())
    print("\n" + "=" * 50)
    for name in list_available_prompts():
        print(f"\n--- {name.upper()} ---")
        content = load_prompt(name)
        print(content[:200] + "..." if len(content) > 200 else content)
