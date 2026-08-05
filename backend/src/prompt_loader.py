"""
Prompt Loader Utility
Loads system prompts from markdown files in the prompts directory.

Also loads per-domain site notes from prompts/site_notes/. Site notes hold
knowledge that is genuinely site-shaped (e.g. how a webmail's compose surface
behaves) so it never lives in the generic prompts: a Gmail rule must not be
able to affect a Workday run. A note applies only when the current host
matches its filename.
"""

from pathlib import Path
from functools import lru_cache
from urllib.parse import urlparse


# Get the directory where this file is located
_BASE_DIR = Path(__file__).parent
_PROMPTS_DIR = _BASE_DIR / "prompts"
_SITE_NOTES_DIR = _PROMPTS_DIR / "site_notes"


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


def load_site_notes(url_or_host: str) -> str:
    """Return site notes for the given URL or host, or "" when none apply.

    Matching walks parent domains, so notes named `office.com.md` apply to
    `outlook.office.com`. A bare TLD never matches. Notes are small and
    read per call; the host set is unbounded, so no lru_cache here.
    """
    raw = (url_or_host or "").strip().lower()
    if not raw:
        return ""
    host = urlparse(raw).netloc if "//" in raw else raw
    host = host.split("@")[-1].split(":")[0].strip(".")
    if not host or not _SITE_NOTES_DIR.is_dir():
        return ""

    parts = host.split(".")
    # Stop before the bare TLD: "com.md" must never match everything.
    for start in range(len(parts) - 1):
        candidate = ".".join(parts[start:])
        note_file = _SITE_NOTES_DIR / f"{candidate}.md"
        if note_file.is_file():
            return note_file.read_text(encoding="utf-8").strip()
    return ""


# Convenience functions for each agent type
def get_orchestration_prompt() -> str:
    """Load the orchestration agent prompt (planning). Backward-compat: same as plan."""
    return load_prompt("orchestration")


def get_orchestration_plan_prompt() -> str:
    """Load the orchestration prompt for creating a plan (first phase)."""
    return load_prompt("orchestration")


def get_orchestration_reasoning_prompt() -> str:
    """Load the orchestration prompt for reasoning and action (advance/retry/plan_complete)."""
    return load_prompt("orchestration_reasoning")


def get_execution_prompt() -> str:
    """Load the execution agent prompt."""
    return load_prompt("execution")


def get_execution_tools_prompt() -> str:
    """Load the execution agent prompt for tool-call mode."""
    return load_prompt("execution_tools")


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
