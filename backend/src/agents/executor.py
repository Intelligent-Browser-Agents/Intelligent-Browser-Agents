"""
Execution Agent
Translates high-level plan steps into specific browser actions.
Uses LangChain tool calls when possible; falls back to structured output.
"""

import asyncio
import json
import re
from typing import Any
from urllib.parse import urlparse

from execution import Action, dispatch_action, ActionArgs
from execution.langchain_tools import get_browser_tools
from execution.models import ExecutionOutput
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from schema import ExecutionResult
from state import ProjectState
from models import Models
from prompt_loader import get_execution_prompt, get_execution_tools_prompt
from dom_extraction import dom_extractor


class Executor:
    """
    LLM-powered Executor that translates plan steps into browser actions.
    Uses LangChain tools (bind_tools) when possible; falls back to structured output.
    """
    
    def __init__(self, runtime):
        self.llm_structured = Models.executor(ExecutionResult)
        self.llm_chat = Models.executor_chat()
        self.system_prompt_json = get_execution_prompt()
        self.system_prompt_tools = get_execution_tools_prompt()
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
        credentials_block = self._build_credentials_context(state, current_task, current_url)
        recent_actions_block = self._build_recent_actions(state)

        mission_status = state.get("mission_status") or ""
        context = f"""
        MAIN_GOAL: {user_intent}

        PLAN_STEP: {current_task}

        PLAN_STEP_URL_HINT: {plan_step_url}

        URL: {current_url}

        DOM_SNAPSHOT:
        {dom_snapshot}
        {credentials_block}
        {recent_actions_block}

        MISSION_STATUS:
        {mission_status}

        Use exactly one of the available tools to perform this plan step. Prefer duckduckgo.com or bing.com over google.com unless explicitly required.
        """

        tool_messages = [
            SystemMessage(content=self.system_prompt_tools),
            HumanMessage(content=context),
        ]
        json_messages = [
            SystemMessage(content=self.system_prompt_json),
            HumanMessage(content=context),
        ]

        # Prefer LangChain tool-calling path
        tools = get_browser_tools(page)
        llm_with_tools = self.llm_chat.bind_tools(tools)
        tool_map = {t.name: t for t in tools}

        ctx_chars = sum(len(m.content) for m in tool_messages)
        print(f"[executor] Calling LLM for tool selection... (context ~{ctx_chars} chars)", flush=True)
        try:
            response = await asyncio.wait_for(
                llm_with_tools.ainvoke(tool_messages),
                timeout=45,
            )
        except asyncio.TimeoutError:
            print("[executor] LLM call timed out after 45s", flush=True)
            return self._return_failure(
                state, current_url,
                action="none", args={},
                message="Executor LLM timed out (45s). Context may be too large or API unresponsive.",
                error_type="unknown",
            )
        except Exception as e:
            print(f"[executor] LLM call failed: {e}", flush=True)
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
            args = self._normalize_tool_args(name, args, current_task)

            # Deterministic credential enforcement for login-form typing.
            # The LLM may hallucinate placeholder credentials (e.g. NID@ucf.edu /
            # Password123). For `type` during a login step, we overwrite the
            # tool arg with the *actual* saved credentials for the best-matching
            # service, based on whether the tool arg looks "email-like"
            # (contains '@') or "password-like" (does not).
            if name == "type" and isinstance(args, dict) and isinstance(args.get("text"), str):
                if self._should_enforce_saved_credentials_for_typing(current_task):
                    creds = state.get("user_credentials") or {}
                    match = self._find_matching_service(creds, current_task, current_url)
                    if match:
                        expected_username = (match.get("username") or match.get("email") or "").strip()
                        expected_password = (match.get("password") or "").strip()
                        if expected_username and expected_password:
                            looks_emailish = "@" in args.get("text", "")
                            args["text"] = expected_username if looks_emailish else expected_password

            if name in {"navigate", "click", "type", "search", "scroll", "press_key", "wait"} and not args:
                return self._return_failure(
                    state, current_url,
                    action=name, args={},
                    message=f"Tool call missing required arguments for {name}.",
                    error_type="ambiguous_step",
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
            result = self._coerce_tool_result_to_output(name, result)
            return await self._finish_from_result(state, page, current_url, result)
        else:
            # Fallback: structured output (no tool_calls)
            try:
                action: ExecutionResult = self.llm_structured.invoke(json_messages)
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
                    max_chars=getattr(validated.args, "max_chars", None) or 15000,
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

    @staticmethod
    def _coerce_tool_result_to_output(tool_name: str, result: Any) -> ExecutionOutput:
        """
        Handler-based tools return ExecutionOutput; dom_search / list_links return lists
        of snippets or link dicts. Normalize so _finish_from_result always sees ExecutionOutput.
        """
        if isinstance(result, ExecutionOutput):
            return result
        if isinstance(result, dict):
            try:
                return ExecutionOutput.model_validate(result)
            except Exception:
                pass
        if isinstance(result, list):
            text = json.dumps(result, ensure_ascii=False, indent=2)
            if len(text) > 14000:
                text = text[:14000] + "\n... [truncated]"
            # Include a brief preview of discovered items so the next LLM call
            # can see *what* was found and click one instead of re-discovering.
            preview_parts = []
            for item in result[:5]:
                if isinstance(item, dict):
                    r = item.get("role", "")
                    n = item.get("name", "")
                    if r and n:
                        preview_parts.append(f"  - click(role={r}, name={n})")
            preview = "\n".join(preview_parts) if preview_parts else ""
            msg = f"Tool {tool_name} returned {len(result)} item(s)."
            if preview:
                msg += f" Clickable targets:\n{preview}"
            return ExecutionOutput(
                action=tool_name,
                args={},
                status="success",
                error_type="none",
                message=msg,
                execution_time_ms=0,
                extracted_text=text,
            )
        if isinstance(result, str):
            return ExecutionOutput(
                action=tool_name,
                args={},
                status="success",
                error_type="none",
                message=f"Tool {tool_name} completed.",
                execution_time_ms=0,
                extracted_text=result[:15000],
            )
        return ExecutionOutput(
            action=tool_name,
            args={},
            status="success",
            error_type="none",
            message=f"Tool {tool_name} returned {type(result).__name__}",
            execution_time_ms=0,
            extracted_text=repr(result)[:15000],
        )

    def _normalize_tool_args(self, tool_name: str, args: Any, current_task: str) -> dict:
        raw = args if isinstance(args, dict) else {}
        normalized = dict(raw)

        for key in ("url", "role", "name", "text", "direction", "key"):
            if key in normalized and isinstance(normalized[key], str):
                normalized[key] = self._clean_tool_string(normalized[key])

        if tool_name == "navigate":
            normalized["url"] = self._clean_url(normalized.get("url"))
        elif tool_name in ("search", "type"):
            text = normalized.get("text", "")
            if not text and tool_name == "search":
                text = self._infer_query_from_step(current_task)
            normalized["text"] = text
        elif tool_name == "click":
            role = (normalized.get("role") or "").strip().lower()
            name = (normalized.get("name") or "").strip()
            if role in ("a", "anchor", "hyperlink"):
                role = "link"
            normalized["role"] = role
            normalized["name"] = name

        required_missing = []
        required = {
            "navigate": ["url"],
            "click": ["role", "name"],
            "type": ["text"],
            "search": ["text"],
            "scroll": ["direction"],
            "press_key": ["key"],
            "wait": ["seconds"],
        }
        for field in required.get(tool_name, []):
            value = normalized.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                required_missing.append(field)
        if required_missing:
            return {}
        return normalized

    @staticmethod
    def _clean_tool_string(value: str) -> str:
        cleaned = (value or "").strip()
        # Common malformed trailing tokens from tool-call JSON rendering.
        cleaned = re.sub(r"[}\],\s]+$", "", cleaned)
        cleaned = cleaned.strip("\"'` ")
        return cleaned

    async def _finish_from_result(self, state, page, current_url, result):
        result_status = result.status
        result_error_type = result.error_type
        result_message = result.message

        # Handle links that open in a new tab/window: switch to the new page
        if result_status == "success":
            try:
                pages = page.context.pages
                if len(pages) > 1 and pages[-1] != page:
                    new_page = pages[-1]
                    await new_page.wait_for_load_state("domcontentloaded", timeout=8000)
                    self.runtime["page"] = new_page
                    page = new_page
                    result_message += " (switched to new tab)"
            except Exception:
                pass

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

        # For extract_content, show the extracted text to the verifier
        extracted = getattr(result, "extracted_text", None)
        if extracted and result.action == "extract_content":
            after_state = f"EXTRACTED_TEXT:\n{extracted.strip()[:4000]}\n\nDOM_SNAPSHOT:\n{after_state}"

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
            "extract_content": [],
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

    @staticmethod
    def _build_recent_actions(state: ProjectState) -> str:
        """Summarise recent executor actions so the LLM doesn't repeat itself."""
        logs = state.get("reasoning_log") or []
        executor_logs = [
            log for log in logs
            if isinstance(log, str) and log.startswith("[Executor]")
        ]
        if not executor_logs:
            return ""
        recent = executor_logs[-6:]
        summaries = []
        for i, log in enumerate(recent, 1):
            action_line = ""
            args_line = ""
            status_line = ""
            message_line = ""
            for line in log.split("\n"):
                stripped = line.strip()
                if stripped.startswith("[Executor] Action:"):
                    action_line = stripped.replace("[Executor] ", "")
                elif stripped.startswith("[Executor] Args:"):
                    args_line = stripped.replace("[Executor] ", "")
                elif stripped.startswith("[Executor] Status:"):
                    status_line = stripped.replace("[Executor] ", "")
                elif stripped.startswith("[Executor] Message:"):
                    message_line = stripped.replace("[Executor] ", "")
            if action_line:
                entry = f"  {i}. {action_line} | {args_line} | {status_line}"
                if message_line:
                    entry += f"\n     Result: {message_line[:500]}"
                summaries.append(entry)
        if not summaries:
            return ""
        return (
            "\n\nPREVIOUS_ACTIONS (already executed — do NOT repeat; if discovery found items, CLICK one):\n"
            + "\n".join(summaries)
        )

    _LOGIN_KEYWORDS = re.compile(
        r"\blog\s*in\b|\bsign\s*in\b|\bcredential|\busername\b|\bpassword\b"
        r"|\bauthenticat|\bsaved credentials\b",
        re.IGNORECASE,
    )

    @staticmethod
    def _should_enforce_saved_credentials_for_typing(current_task: str) -> bool:
        """
        Only rewrite `type` args when the plan step is clearly about login/credentials.
        URL-matched services alone are not enough — otherwise navigation on my.ucf.edu
        overwrites arbitrary typing with the saved password.
        """
        t = (current_task or "").lower()
        nav_like = any(p in t for p in (
            "navigate", "go to", "open the", "visit",
        ))
        if nav_like and not Executor._LOGIN_KEYWORDS.search(current_task or ""):
            return False
        return bool(Executor._LOGIN_KEYWORDS.search(current_task or ""))

    _FORM_FILL_KEYWORDS = re.compile(
        r"\bfill\b|\benter\b|\bsubmit\b|\bapply\b|\bregister\b|\bsign\s*up\b"
        r"|\bpersonal\s+info|\bprofile\b|\bpayment\b|\bcheckout\b",
        re.IGNORECASE,
    )

    def _build_credentials_context(self, state: ProjectState, current_task: str, current_url: str) -> str:
        """Inject relevant credentials when the step involves login or form-filling."""
        creds = state.get("user_credentials") or {}
        if not creds:
            print("[executor] No user_credentials in state", flush=True)
            return ""

        is_login_step = bool(self._LOGIN_KEYWORDS.search(current_task))
        is_form_step = bool(self._FORM_FILL_KEYWORDS.search(current_task))

        if not is_login_step and not is_form_step:
            return ""

        print(f"[executor] Credential injection: login={is_login_step} form={is_form_step}", flush=True)
        parts = []

        if is_login_step:
            match = self._find_matching_service(creds, current_task, current_url)
            if match:
                print(f"[executor] Matched service: {match.get('serviceName', '?')}", flush=True)
                username = match.get('username', '')
                password = match.get('password', '')
                parts.append(
                    f"SERVICE_CREDENTIALS (use these EXACT values — do NOT make up values):\n"
                    f"  Username/Email: {username}\n"
                    f"  Password: {password}\n\n"
                    f"FIELD MATCHING RULES:\n"
                    f"  - Look at DOM_SNAPSHOT for visible input fields (textbox, input, password field, etc.).\n"
                    f"  - Match each field to the correct credential by its label/name/placeholder "
                    f"(e.g. 'Email', 'Username', 'NID' → type the Username value; 'Password' → type the Password value).\n"
                    f"  - Fill ONE field per turn: `type` the matching value into the currently focused or next unfilled field.\n"
                    f"  - After all visible fields are filled (check PREVIOUS_ACTIONS), click the submit/sign-in/next button.\n"
                    f"  - If only ONE input field is visible (e.g. Microsoft login), fill it first, then click Next; "
                    f"the system will re-invoke you for the next field on the new page."
                )
            else:
                print(f"[executor] No matching service found for task='{current_task[:60]}' url='{current_url[:60]}'", flush=True)

        if is_form_step:
            personal = []
            for key in ("fullName", "email", "phoneNumber", "address"):
                val = creds.get(key, "").strip()
                if val:
                    personal.append(f"  {key}: {val}")
            if personal:
                parts.append("PERSONAL_INFO (use to fill form fields):\n" + "\n".join(personal))

            payments = creds.get("userPaymentMethods") or []
            if payments:
                p = payments[0]
                payment_lines = [f"  {k}: {v}" for k, v in p.items() if k != "id" and v]
                if payment_lines:
                    parts.append("PAYMENT_INFO:\n" + "\n".join(payment_lines))

            experience = creds.get("userExperienceEntries") or []
            if experience:
                exp_lines = []
                for entry in experience[:3]:
                    exp_lines.append(
                        f"  - {entry.get('title', '')} at {entry.get('organization', '')} "
                        f"({entry.get('startDate', '')} – {entry.get('endDate', '') or 'present'})"
                    )
                if exp_lines:
                    parts.append("EXPERIENCE/EDUCATION:\n" + "\n".join(exp_lines))

        if not parts:
            return ""
        return "\n\nUSER_CREDENTIALS (available for auto-fill — use `type` to enter these values):\n" + "\n".join(parts)

    @staticmethod
    def _find_matching_service(creds: dict, task: str, url: str) -> dict | None:
        """Find the best-matching saved service credential for the current task/URL."""
        services = creds.get("userCredentialsList") or []
        if not services:
            return None

        task_lower = task.lower()
        url_lower = url.lower()

        for service in services:
            if not isinstance(service, dict):
                continue
            name = (service.get("serviceName") or "").lower()
            svc_url = (service.get("serviceUrl") or "").lower()

            # Direct name match in the task or current URL
            if name and (name in task_lower or name in url_lower):
                return service
            # Saved service URL matches the current page
            if svc_url and svc_url in url_lower:
                return service
            # Check if the service URL's domain appears in the current URL
            if svc_url:
                from urllib.parse import urlparse as _urlparse
                svc_domain = _urlparse(svc_url).netloc.lower().replace("www.", "")
                cur_domain = _urlparse(url).netloc.lower().replace("www.", "")
                if svc_domain and svc_domain in cur_domain:
                    return service

        # If only one service is saved and the task mentions login, use it
        if len(services) == 1:
            return services[0]

        return None

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
        """Get a role/name snapshot including iframes from Playwright accessibility tree."""
        all_lines: list[str] = []

        # Main frame
        try:
            snapshot = await page.accessibility.snapshot(interesting_only=True)
            if snapshot:
                all_lines.extend(self._format_accessibility_tree(snapshot, max_lines=300))
        except Exception as e:
            all_lines.append(f"[DOM snapshot failed: {e}]")

        # Child frames / iframes (PeopleSoft, etc.)
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                frame_snap = await frame.evaluate(
                    """() => {
                        const walk = (el) => {
                            if (!el) return [];
                            const items = [];
                            const role = el.getAttribute && (el.getAttribute('role') || el.tagName.toLowerCase());
                            const name = el.getAttribute && (
                                el.getAttribute('aria-label') ||
                                el.getAttribute('title') ||
                                (el.innerText || '').trim().slice(0, 120)
                            );
                            if (name && role) items.push({role, name});
                            for (const child of (el.children || []))
                                items.push(...walk(child));
                            return items;
                        };
                        return walk(document.body);
                    }"""
                )
                if frame_snap:
                    all_lines.append(f'[iframe: {frame.url[:80]}]')
                    for item in frame_snap[:200]:
                        r = item.get("role", "")
                        n = (item.get("name", "") or "").strip()
                        if n:
                            line = f'[role="{r}"] "{n}"'
                            if len(line) > 200:
                                line = line[:197] + "..."
                            all_lines.append(line)
            except Exception:
                continue

        if not all_lines:
            return "[No interactive elements in snapshot]"
        return "\n".join(all_lines[:500])

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
