"""
Execution Agent
Translates high-level plan steps into specific browser actions.
Uses LangChain tool calls when possible; falls back to structured output.
"""

import re
from typing import Any
from urllib.parse import urlparse

from execution import Action, dispatch_action, ActionArgs
from execution.langchain_tools import get_browser_tools
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from schema import ExecutionResult
from state import ProjectState
from models import Models
from prompt_loader import get_execution_prompt
from dom_extraction import dom_extractor


class Executor:
    """
    LLM-powered Executor that translates plan steps into browser actions.
    Uses LangChain tools (bind_tools) when possible; falls back to structured output.
    """
    
    def __init__(self, runtime):
        self.llm_structured = Models.executor(ExecutionResult)
        self.llm_chat = Models.executor_chat()
        self.system_prompt = get_execution_prompt()
        self.runtime = runtime

    async def __call__(self, state: ProjectState) -> dict:
        page = self.runtime.get("page")
        if page is None:
            raise RuntimeError("[ERROR]: Executor called without a Playwright page!")
        
        current_task = state.get("current_task", "No task specified")
        current_url = state.get("current_url", "unknown")
        user_intent = self._get_user_intent(state)
        dom_snapshot = await self._get_real_dom_snapshot(page)
        plan_step_url = self._extract_first_url(current_task) or "none"
        
        context = f"""
        MAIN_GOAL: {user_intent}

        PLAN_STEP: {current_task}

        PLAN_STEP_URL_HINT: {plan_step_url}

        URL: {current_url}

        DOM_SNAPSHOT:
        {dom_snapshot}

        Use exactly one of the available tools to perform this plan step. Prefer duckduckgo.com or bing.com over google.com unless explicitly required.
        """

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=context),
        ]

        # Prefer LangChain tool-calling path
        tools = get_browser_tools(page)
        llm_with_tools = self.llm_chat.bind_tools(tools)
        tool_map = {t.name: t for t in tools}

        try:
            response = await llm_with_tools.ainvoke(messages)
        except Exception as e:
            return self._return_failure(
                state, current_url,
                action="none", args={},
                message=f"Executor LLM failed: {str(e)}",
                error_type="unknown",
            )

        if isinstance(response, AIMessage) and getattr(response, "tool_calls", None):
            tc = response.tool_calls[0]
            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
            args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {}) or {}
            if not name or name not in tool_map:
                return self._return_failure(
                    state, current_url,
                    action=name or "unknown", args=args,
                    message="Model returned invalid or unknown tool call.",
                    error_type="unknown",
                )
            try:
                result = await tool_map[name].ainvoke(args)
            except Exception as e:
                return self._return_failure(
                    state, current_url,
                    action=name, args=args,
                    message=str(e),
                    error_type="unknown",
                )
            # result is ExecutionOutput from handlers
            return await self._finish_from_result(state, page, current_url, result)
        else:
            # Fallback: structured output (no tool_calls)
            try:
                action: ExecutionResult = self.llm_structured.invoke(messages)
            except Exception as e:
                return self._return_failure(
                    state, current_url,
                    action="none", args={},
                    message=f"Executor output validation failed: {str(e)}",
                    error_type="unknown",
                )
            validated = self._validate_and_normalize_action(
                action=action,
                current_task=current_task,
                dom_snapshot=dom_snapshot,
                user_intent=user_intent,
            )
            if validated.status == "failure":
                return {
                    "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                    "reasoning_log": [self._build_execution_log(
                        action=validated.action,
                        args=self._action_args_to_dict(validated.args),
                        status=validated.status,
                        message=validated.message,
                        error_type=validated.error_type,
                    )],
                    "current_url": current_url,
                }
            tool_action = Action(
                action=validated.action,
                args=ActionArgs(
                    url=validated.args.url,
                    role=validated.args.role,
                    name=validated.args.name,
                    text=validated.args.text,
                    direction=validated.args.direction,
                    key=validated.args.key,
                    seconds=validated.args.seconds,
                ),
            )
            result = await dispatch_action(page, tool_action)
            print(f"[executor - {result.action} result]: ", result)
            return await self._finish_from_result(state, page, current_url, result)

    def _return_failure(self, state, current_url, action, args, message, error_type="unknown"):
        return {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "reasoning_log": [self._build_execution_log(
                action=action, args=args if isinstance(args, dict) else {},
                status="failure", message=message, error_type=error_type,
            )],
            "current_url": current_url,
        }

    async def _finish_from_result(self, state, page, current_url, result):
        result_status = result.status
        result_error_type = result.error_type
        result_message = result.message
        if result_status == "success" and self._is_anti_bot_page(page.url):
            result_status = "failure"
            result_error_type = "navigation_blocked"
            result_message = "Blocked by CAPTCHA or anti-bot challenge on the current search engine."
        new_url = current_url
        if result_status == "success":
            new_url = result.args.get("url") or page.url if result.action == "navigate" else page.url
        else:
            new_url = page.url
        after_state = ""
        try:
            after_state = await self._get_real_dom_snapshot(page)
        except Exception:
            after_state = f"[URL after action: {new_url}]"
        execution_log = self._build_execution_log(
            action=result.action,
            args=result.args,
            status=result_status,
            message=result_message,
            error_type=result_error_type,
            after_state=after_state,
        )
        out = {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "reasoning_log": [execution_log],
            "current_url": new_url,
        }
        extracted = getattr(result, "extracted_text", None)
        if extracted and isinstance(extracted, str) and extracted.strip():
            out["extracted_content"] = [extracted.strip()]
        # Also keep a lightweight DOM/text snapshot in dom_cache for later navigation tools
        try:
            dom_text = await dom_extractor.get_page_text(page, max_chars=8000)
            if dom_text and dom_text.strip():
                snapshot = f"URL: {new_url}\n\n{dom_text.strip()}"
                out["dom_cache"] = [snapshot]
        except Exception:
            pass
        return out


    def _get_user_intent(self, state: ProjectState) -> str:

        """Extract user intent from messages."""
        user_message = state["messages"][0] if state["messages"] else None
        text = "Unknown intent"
        if isinstance(user_message, dict):
            text = user_message.get("content", "Unknown intent")
        elif hasattr(user_message, "content"):
            text = user_message.content
        elif user_message:
            text = str(user_message)

        # Remove wrapper prefix so the model gets just the user intent.
        return re.sub(r"^\s*USER REQUEST:\s*", "", text, flags=re.IGNORECASE).strip() or "Unknown intent"

    def _validate_and_normalize_action(
        self,
        action: ExecutionResult,
        current_task: str,
        dom_snapshot: str,
        user_intent: str,
    ) -> ExecutionResult:
        args = action.args.model_copy(deep=True)

        # Controlled recovery: if the LLM selected the right action but returned failure
        # due to missing args, infer args from the current plan step when unambiguous.
        if action.status == "failure":
            if action.action == "search":
                inferred = self._infer_query_from_step(current_task)
                if inferred:
                    args.text = inferred
                    return ExecutionResult(
                        action="search",
                        args=args,
                        status="success",
                        error_type="none",
                        message=f"Recovered search text from PLAN_STEP: {inferred}",
                    )
            if action.action == "navigate":
                inferred_url = self._clean_url(self._extract_first_url(current_task))
                if inferred_url:
                    args.url = inferred_url
                    return ExecutionResult(
                        action="navigate",
                        args=args,
                        status="success",
                        error_type="none",
                        message=f"Recovered navigate URL from PLAN_STEP: {inferred_url}",
                    )
            return action

        if action.action == "search" and (args.text is None or not str(args.text).strip()):
            inferred = self._infer_query_from_step(current_task)
            if inferred:
                args.text = inferred

        missing = self._missing_required_args(action.action, args)
        if missing:
            return ExecutionResult(
                action=action.action,
                args=args,
                status="failure",
                error_type="ambiguous_step",
                message=f"Missing required args for {action.action}: {', '.join(missing)}",
            )

        if action.action == "navigate":
            step_url = self._clean_url(self._extract_first_url(current_task))
            proposed_url = self._clean_url(args.url)
            # If the plan step has an explicit URL, it must be used verbatim.
            final_url = step_url or proposed_url
            if step_url and proposed_url != step_url:
                final_url = step_url
            if not final_url:
                return ExecutionResult(
                    action=action.action,
                    args=args,
                    status="failure",
                    error_type="ambiguous_step",
                    message="Missing or invalid URL for navigate.",
                )
            if self._is_google_url(final_url) and not self._user_explicitly_requires_google(
                current_task, user_intent
            ):
                final_url = "https://duckduckgo.com"
            args.url = final_url

        # Click: allow attempt even if snapshot format doesn't match (handler will fail if element missing)
        if action.action == "click":
            pass

        if action.action in {"type", "search"} and args.text:
            args.text = args.text.strip()

        if action.action == "wait" and (args.seconds is None or args.seconds <= 0):
            return ExecutionResult(
                action=action.action,
                args=args,
                status="failure",
                error_type="ambiguous_step",
                message="wait requires args.seconds > 0",
            )

        return ExecutionResult(
            action=action.action,
            args=args,
            status="success",
            error_type="none",
            message=action.message,
        )

    def _missing_required_args(self, action_name: str, args: Any) -> list[str]:
        required = {
            "navigate": ["url"],
            "click": ["role", "name"],
            "type": ["text"],
            "search": ["text"],
            "scroll": ["direction"],
            "press_key": ["key"],
            "wait": ["seconds"],
        }
        missing = []
        for field in required.get(action_name, []):
            value = getattr(args, field, None)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(field)
        return missing

    def _extract_first_url(self, text: str) -> str:
        if not text:
            return ""
        match = re.search(r"https?://[^\s\"'<>]+", text)
        if not match:
            return ""
        return match.group(0).rstrip(".,;:!?)]}\"'")

    def _infer_query_from_step(self, step: str) -> str:
        if not step:
            return ""

        single = re.search(r"'([^']+)'", step)
        if single and single.group(1).strip():
            return self._clean_inferred_query(single.group(1))

        double = re.search(r'"([^"]+)"', step)
        if double and double.group(1).strip():
            return self._clean_inferred_query(double.group(1))

        patterns = [
            r"search(?:\s+(?:google|duckduckgo|bing))?(?:\s+for)?\s+([a-z0-9][a-z0-9\s\-_]{1,120})",
            r"look\s+up\s+([a-z0-9][a-z0-9\s\-_]{1,120})",
            r"(?:find|locate)\s+(?:information|info|details)\s+(?:about|on)\s+([a-z0-9][a-z0-9\s\-_]{1,120})",
            r"(?:information|info|details)\s+(?:about|on)\s+([a-z0-9][a-z0-9\s\-_]{1,120})",
            r"director\s+of\s+([a-z0-9][a-z0-9\s\-_]{1,120})",
        ]
        lowered = step.lower()
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

    def _clean_url(self, url: str | None) -> str:
        if not url:
            return ""
        candidate = url.strip().rstrip(".,;:!?)]}\"'")
        if any(char.isspace() for char in candidate):
            return ""
        parsed = urlparse(candidate)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return ""
        return candidate

    def _is_google_url(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        return host == "google.com" or host == "www.google.com" or host.endswith(".google.com")

    def _user_explicitly_requires_google(self, current_task: str, user_intent: str) -> bool:
        text = f"{current_task}\n{user_intent}".lower()
        return "google.com" in text or re.search(r"\bgoogle\b", text) is not None

    def _is_anti_bot_page(self, url: str) -> bool:
        text = (url or "").lower()
        patterns = [
            "google.com/sorry",
            "/sorry/index",
            "captcha",
            "unusual+traffic",
            "challenge",
        ]
        return any(pattern in text for pattern in patterns)

    def _is_click_target_in_dom(self, role: str | None, name: str | None, dom_snapshot: str) -> bool:
        if not role or not name:
            return False
        r, n = role.strip(), name.strip()
        escaped_role = re.escape(r)
        escaped_name = re.escape(n)
        exact = re.search(rf'\[role="{escaped_role}"\]\s*"{escaped_name}"', dom_snapshot, flags=re.IGNORECASE)
        if exact:
            return True
        partial = re.search(rf'\[role="{escaped_role}"\][^\n]*{re.escape(n)}', dom_snapshot, flags=re.IGNORECASE)
        return partial is not None

    def _action_args_to_dict(self, args: Any) -> dict:
        if hasattr(args, "model_dump"):
            return args.model_dump()
        return {}

    def _build_execution_log(
        self,
        action: str,
        args: dict,
        status: str,
        message: str,
        error_type: str | None = None,
        after_state: str | None = None,
    ) -> str:
        args_str = []
        for key in ["url", "role", "name", "text", "direction", "key", "seconds"]:
            value = args.get(key) if isinstance(args, dict) else None
            if value is not None and str(value).strip() != "":
                args_str.append(f"{key}={value}")

        log = (
            f"[Executor] Action: {action}\n"
            f"[Executor] Args: {', '.join(args_str) or 'None'}\n"
            f"[Executor] Status: {status}\n"
            f"[Executor] Message: {message}"
        )
        if error_type and error_type != "none":
            log += f"\n[Executor] Error Type: {error_type}"
        if after_state and after_state.strip():
            snippet = after_state.strip()[:3000]
            if len(after_state.strip()) > 3000:
                snippet += "\n... (truncated)"
            log += f"\n[Executor] AFTER_STATE (page content for verification):\n{snippet}"
        return log
    


    async def _get_real_dom_snapshot(self, page) -> str:
        """Get a role/name snapshot of the page from Playwright accessibility tree for the LLM and verifier."""
        try:
            snapshot = await page.accessibility.snapshot(interesting_only=True)
        except Exception as e:
            return f"[DOM snapshot failed: {e}]"
        if not snapshot:
            return "[No accessibility snapshot]"
        lines = self._format_accessibility_tree(snapshot, max_lines=500)
        return "\n".join(lines) if lines else "[No interactive elements in snapshot]"

    def _format_accessibility_tree(self, node: dict | None, prefix: str = "", max_lines: int = 500) -> list[str]:
        """Flatten accessibility tree to lines like [role=\"button\"] \"Submit\" for verifier and LLM."""
        if node is None or max_lines <= 0:
            return []
        lines = []
        role = node.get("role") or "generic"
        name = (node.get("name") or "").strip()
        if name and role not in ("generic", "text", "StaticText"):
            line = f'[role="{role}"] "{name}"'
            if len(line) > 200:
                line = line[:197] + "..."
            lines.append(line)
        for child in node.get("children") or []:
            lines.extend(self._format_accessibility_tree(child, prefix, max_lines - len(lines)))
            if len(lines) >= max_lines:
                break
        return lines
