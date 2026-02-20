"""
Fallback Agent
Creates deterministic recovery instructions from real execution failures.
"""

import re

from state import ProjectState


class Fallback:
    """
    Deterministic fallback to avoid hallucinated recovery plans.

    It rewrites the current task based on actual executor/verifier logs.
    """

    def __init__(self):
        # Compatibility constructor
        pass

    def __call__(self, state: ProjectState) -> dict:
        current_task = state.get("current_task", "Unknown task")
        reasoning_log = state.get("reasoning_log", [])
        user_intent = self._get_user_intent(state)

        last_verification = self._find_latest_log(reasoning_log, "[Verifier]") or "Verification failed."
        last_execution = (
            self._find_latest_log(reasoning_log, "[Executor]")
            or self._find_latest_log(reasoning_log, "[Verifier]")
            or "No execution log."
        )

        revised_task, diagnosis = self._revise_task(current_task, user_intent, last_execution)

        fallback_log = (
            "[Fallback] Update Type: revise_step\n"
            f"[Fallback] Diagnosis: {diagnosis}\n"
            f"[Fallback] Message to Orchestration: Retry the current step with a grounded instruction.\n"
            f"[Fallback] Proposed Step: {revised_task}\n"
            f"[Fallback] Last Verification: {last_verification[:180]}"
        )

        return {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "current_task": revised_task,
            "reasoning_log": [fallback_log],
            "needs_fallback": False,
        }

    def _revise_task(self, current_task: str, user_intent: str, last_execution: str) -> tuple[str, str]:
        text = last_execution.lower()
        task = (current_task or "").strip()
        intent = (user_intent or "").lower()

        if "missing required args for click" in text:
            query = self._infer_query(task, user_intent)
            if query:
                return (
                    f"Search DuckDuckGo for '{query}' using a single search action.",
                    f"Click target args were missing. Reframed step to a direct DuckDuckGo search for '{query}'.",
                )
            return (
                "Identify a visible clickable target and include both role and name before clicking.",
                "Click target args were missing. Required role/name was not grounded.",
            )

        if "missing required args for search: text" in text:
            query = self._infer_query(task, user_intent)
            if query:
                return (
                    f"Search DuckDuckGo for '{query}' using a single search action.",
                    f"Search query text was missing. Reframed step with explicit query '{query}'.",
                )

            derived_query = self._clean_inferred_query(task)
            if derived_query:
                return (
                    f"Search DuckDuckGo for '{derived_query}' using a single search action.",
                    "Search action was missing text; derived query from current task text.",
                )

            return (
                "Search DuckDuckGo using an explicit query copied from the user request.",
                "Search action was missing text and no reliable query could be inferred without fabricating one.",
            )

        if "captcha" in text or "unusual traffic" in text or "sorry" in text:
            query = self._infer_query(task, user_intent)
            if query:
                return (
                    f"Navigate to https://duckduckgo.com and search for '{query}'.",
                    "Encountered anti-bot challenge. Switching to DuckDuckGo for recovery.",
                )
            return (
                "Navigate to https://duckduckgo.com and continue the search there.",
                "Encountered anti-bot challenge. Switching search engine.",
            )

        if "missing or invalid url for navigate" in text:
            return (
                task,
                "Navigate URL was invalid or not grounded in the current step. Retrying with stricter URL extraction.",
            )

        if "requires non-empty 'text'" in text or "requires a text argument" in text or "search text" in text:
            query = self._infer_query(task, user_intent)
            if query:
                return (
                    f"Enter '{query}' in the search box and submit the search.",
                    f"Search text was missing. Inferred query '{query}' from task/user intent.",
                )
            return (
                "Enter the intended query into the search box and submit the search.",
                "Search text was missing and could not be inferred confidently.",
            )

        if "click action requires" in text or "could not find element to click" in text or "missing click target" in text:
            if "search" in task.lower() or "search" in intent:
                return (
                    "Use a direct search action on DuckDuckGo with the intended query.",
                    "Click target was missing; selected explicit search textbox target.",
                )
            return (
                f"Locate and click the exact UI control required for this step: {task}",
                "Click target was missing; rewrote task to require explicit target resolution.",
            )

        if "navigation" in text and "failed" in text:
            return (
                task,
                "Navigation failed due to transient page/network issue. Retrying same step.",
            )

        return (
            task,
            "Step failed without a precise error pattern. Retrying the same step with current context.",
        )

    def _infer_query(self, task: str, user_intent: str) -> str:
        for source in [task, user_intent]:
            if not source:
                continue
            single = re.search(r"'([^']+)'", source)
            if single and single.group(1).strip():
                return self._clean_inferred_query(single.group(1))
            double = re.search(r'"([^"]+)"', source)
            if double and double.group(1).strip():
                return self._clean_inferred_query(double.group(1))

            patterns = [
                r"search(?:\s+(?:google|duckduckgo|bing))?(?:\s+for)?\s+([a-z0-9][a-z0-9\s\-_]{1,120})",
                r"look\s+up\s+([a-z0-9][a-z0-9\s\-_]{1,120})",
                r"(?:find|locate)\s+(?:information|info|details)\s+(?:about|on)\s+([a-z0-9][a-z0-9\s\-_]{1,120})",
                r"(?:information|info|details)\s+(?:about|on)\s+([a-z0-9][a-z0-9\s\-_]{1,120})",
                r"director\s+of\s+([a-z0-9][a-z0-9\s\-_]{1,120})",
            ]
            lowered = source.lower()
            for pattern in patterns:
                inferred = re.search(pattern, lowered)
                if inferred and inferred.group(1).strip():
                    candidate = inferred.group(1).strip()
                    if pattern.startswith("director"):
                        candidate = f"director of {candidate}"
                    cleaned = self._clean_inferred_query(candidate)
                    if cleaned:
                        return cleaned
        return ""

    def _clean_inferred_query(self, text: str) -> str:
        candidate = (text or "").strip(" .,:;!?")
        if not candidate:
            return ""

        stop_markers = [
            " and present",
            " from the search results",
            " from search results",
            " and summarize",
            " then ",
            " using ",
        ]
        lowered = candidate.lower()
        for marker in stop_markers:
            idx = lowered.find(marker)
            if idx > 0:
                candidate = candidate[:idx].strip(" .,:;!?")
                lowered = candidate.lower()

        candidate = re.sub(r"^(google|duckduckgo|bing)\s+for\s+", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"^(for)\s+", "", candidate, flags=re.IGNORECASE)
        return candidate.strip(" .,:;!?")

    def _find_latest_log(self, reasoning_log: list, prefix: str) -> str:
        for entry in reversed(reasoning_log or []):
            if isinstance(entry, str) and prefix in entry:
                return entry
        return ""

    def _get_user_intent(self, state: ProjectState) -> str:
        user_message = state["messages"][0] if state["messages"] else None
        if isinstance(user_message, dict):
            return user_message.get("content", "Unknown intent")
        if hasattr(user_message, "content"):
            return user_message.content
        return str(user_message) if user_message else "Unknown intent"
