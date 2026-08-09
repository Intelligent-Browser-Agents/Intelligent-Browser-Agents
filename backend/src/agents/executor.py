"""
Execution Agent
Translates high-level plan steps into specific browser actions.
Uses LangChain tool calls when possible; falls back to structured output.
"""

import asyncio
import base64
import json
import os
import re
from typing import Any
from urllib.parse import urlparse

from execution import Action, dispatch_action, ActionArgs
from execution.langchain_tools import get_browser_tools
from execution.models import ExecutionOutput
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from schema import ExecutionResult, LastExecutionEvent
from state import ProjectState
from models import Models
from prompt_loader import get_execution_prompt, get_execution_tools_prompt, load_site_notes
from autonomy import assess_action
from dom_extraction import dom_extractor
from dom_extraction.snapshot import SNAPSHOT_SECTION_MAX_CHARS, capture_page_snapshot


# Wall-clock ceilings for a single executor step. Both paths that can block are
# wrapped, so one unresponsive call cannot stall a run indefinitely.
_LLM_CALL_TIMEOUT_SECONDS = int(os.getenv("EXECUTOR_LLM_TIMEOUT", "45"))
_TOOL_CALL_TIMEOUT_SECONDS = int(os.getenv("EXECUTOR_TOOL_TIMEOUT", "60"))


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

    @staticmethod
    def _last_execution_event_dict(
        *,
        action: str,
        args,
        status: str,
        message: str,
        error_type: str | None,
        extracted_content_present: bool = False,
        verified: bool | None = None,
    ) -> dict:
        """Single source of truth for schema.LastExecutionEvent in state."""
        args_dict: dict = {}
        if isinstance(args, dict):
            args_dict = {str(k): v for k, v in args.items() if v is not None}
        elif args is not None and hasattr(args, "model_dump"):
            args_dict = {
                str(k): v
                for k, v in args.model_dump(exclude_none=True).items()
                if v is not None
            }
        return LastExecutionEvent(
            action=action or "",
            args=args_dict,
            status=status or "unknown",
            error_type=error_type,
            message=message or "",
            extracted_content_present=extracted_content_present,
            verified=verified,
        ).model_dump()

    _RECOVERY_SCREENSHOT_MAX_BYTES = 220_000
    _RECOVERY_SCREENSHOT_MAX_DATA_URL_CHARS = 420_000

    async def __call__(self, state: ProjectState) -> dict:
        page = self.runtime.get("page")
        if page is None:
            raise RuntimeError("[ERROR]: Executor called without a Playwright page!")

        # Pages that already exist before this action. The new-tab auto-adopt in
        # _finish_from_result compares against this so it only adopts tabs the
        # action itself opened; without it, any pre-existing later tab would be
        # re-adopted on the next success, undoing an explicit switch_tab.
        try:
            self.runtime["pages_before_action"] = list(page.context.pages)
        except Exception:
            self.runtime["pages_before_action"] = []

        # Refreshed each turn so redaction covers whatever is in the vault now.
        self._secret_values = self._collect_secret_values(state)

        current_task = state.get("current_task", "No task specified")
        current_url = state.get("current_url", "unknown")
        user_intent = self._get_user_intent(state)
        current_plan = state.get("current_plan", []) or []
        current_step = int(state.get("current_step_index", 0) or 0)
        step_attempts = int(state.get("step_attempts", 0) or 0)
        canonical_step = current_task
        if current_plan:
            safe_idx = min(max(current_step, 0), len(current_plan) - 1)
            canonical_step = (current_plan[safe_idx] or current_task).strip() or current_task

        dom_snapshot = await self._get_real_dom_snapshot(page, max_chars=self._dom_snapshot_budget(current_task))
        plan_step_url = self._extract_first_url(current_task) or "none"
        credentials_block = self._build_credentials_context(state, current_task, current_url)
        recent_actions_block = self._build_recent_actions(state)
        adaptive_guidance_block = self._build_adaptive_guidance(state, current_task)
        dom_cache_block = (
            self._build_dom_cache_context(state)
            if self._should_include_dom_cache_context(state, current_task)
            else ""
        )
        field_priority_block = self._build_field_priority_context(dom_snapshot, current_task, state)
        status_context_block = self._build_execution_status_context(state, current_task, step_attempts)
        site_notes_block = self._build_site_notes_context(current_url)

        context = f"""
        MAIN_GOAL: {user_intent}

        STEP_OBJECTIVE (stable): {canonical_step}

        PLAN_STEP (tactical): {current_task}

        PLAN_STEP_URL_HINT: {plan_step_url}

        URL: {current_url}

        DOM_SNAPSHOT:
        {dom_snapshot}
        {dom_cache_block}
        {field_priority_block}
        {credentials_block}
        {recent_actions_block}
        {adaptive_guidance_block}
        {status_context_block}
        {site_notes_block}

        Use exactly one of the available tools to perform this plan step. If the step names a specific site/domain, navigate there directly instead of going through a search engine first. For open-web discovery when no target site is known, prefer duckduckgo.com or bing.com over google.com unless explicitly required.
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
        tools = get_browser_tools(page, runtime=self.runtime)
        llm_with_tools = self.llm_chat.bind_tools(tools)
        tool_map = {t.name: t for t in tools}

        # Approximate from characters instead of calling
        # get_num_tokens_from_messages, which runs a full tiktoken encode of the
        # whole prompt on every step purely to print this line.
        ctx_tokens = sum(len(str(m.content)) for m in tool_messages) // 4
        print(
            f"[executor] Calling LLM for tool selection... (~{ctx_tokens} tokens, LangChain)",
            flush=True,
        )
        call_started = asyncio.get_event_loop().time()
        try:
            response = await asyncio.wait_for(
                llm_with_tools.ainvoke(tool_messages),
                timeout=_LLM_CALL_TIMEOUT_SECONDS,
            )
            print(
                f"[executor] LLM responded in {asyncio.get_event_loop().time() - call_started:.1f}s",
                flush=True,
            )
        except asyncio.TimeoutError:
            print(f"[executor] LLM call timed out after {_LLM_CALL_TIMEOUT_SECONDS}s", flush=True)
            return self._return_failure(
                state, current_url,
                action="none", args={},
                message=(
                    f"Executor LLM timed out ({_LLM_CALL_TIMEOUT_SECONDS}s). "
                    "Context may be too large or the API unresponsive."
                ),
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

            # Deterministic credential enforcement for login-form entry.
            # The LLM may hallucinate placeholder credentials (e.g. user@example.com /
            # Password123). For `fill` or `type` during a login step, we overwrite
            # the text arg with the *actual* saved credentials for the best-matching
            # service. `fill` names its field, so the field's accessible name decides
            # which credential it gets; the legacy `type` has no target, so we fall
            # back to whether the value looks "email-like" (contains '@').
            if name in {"fill", "type"} and isinstance(args, dict) and isinstance(args.get("text"), str):
                if self._should_enforce_saved_credentials_for_typing(current_task):
                    creds = state.get("user_credentials") or {}
                    match = self._find_matching_service(creds, current_task, current_url)
                    if match:
                        expected_username = (match.get("username") or match.get("email") or "").strip()
                        expected_password = (match.get("password") or "").strip()
                        if expected_username and expected_password:
                            field_name = str(args.get("name") or "").lower()
                            if name == "fill":
                                # The field is named, so only credential-shaped
                                # fields are overwritten. A fill on any other
                                # field (OTP code, phone, company) keeps the
                                # model's value: forcing the password into a
                                # visible non-password field would leak it.
                                if "password" in field_name:
                                    args["text"] = expected_password
                                elif re.search(r"user|email|login|account|\bid\b|\bnid\b", field_name):
                                    args["text"] = expected_username
                            else:
                                # Legacy `type` has no target; infer from the
                                # value's shape.
                                looks_emailish = "@" in args.get("text", "")
                                args["text"] = expected_username if looks_emailish else expected_password

            missing_required = await self._required_empty_fields_before_finalization(
                page,
                state,
                name,
                args,
            )
            if missing_required:
                return self._return_failure(
                    state,
                    current_url,
                    action=name,
                    args=args,
                    message=(
                        "Cannot finalize yet. Required fields are still incomplete: "
                        f"{', '.join(missing_required)}"
                    ),
                    error_type="ambiguous_step",
                )

            if name in {"navigate", "click", "type", "search", "scroll", "press_key", "wait"} and not args:
                return self._return_failure(
                    state, current_url,
                    action=name, args={},
                    message=f"Tool call missing required arguments for {name}.",
                    error_type="ambiguous_step",
                )

            consume_sensitive_approval = False
            decision = assess_action(
                name,
                args if isinstance(args, dict) else {},
                policy=state.get("autonomy_policy"),
                url=state.get("current_url"),
            )
            sensitive_reason = str(decision.get("reason") or "") if decision.get("mode") == "confirm" else None
            if sensitive_reason:
                signature = self._action_signature(name, args)
                if not self._is_sensitive_action_approved(state, signature):
                    return self._request_sensitive_confirmation(
                        state=state,
                        current_url=current_url,
                        action=name,
                        args=args,
                        current_task=current_task,
                        reason=sensitive_reason,
                        action_signature=signature,
                    )
                consume_sensitive_approval = True

            try:
                # Browser tools had no timeout. A click cascading through frames,
                # role aliases and name variants can spend minutes before failing,
                # with nothing above it to cut the step short.
                result = await asyncio.wait_for(
                    tool_map[name].ainvoke(args),
                    timeout=_TOOL_CALL_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                return self._return_failure(
                    state, current_url,
                    action=name, args=args,
                    message=f"Browser action '{name}' timed out after {_TOOL_CALL_TIMEOUT_SECONDS}s.",
                    error_type="tool_limit",
                    clear_sensitive_approval=consume_sensitive_approval,
                )
            except Exception as e:
                return self._return_failure(
                    state, current_url,
                    action=name, args=args,
                    message=str(e),
                    error_type="unknown",
                    clear_sensitive_approval=consume_sensitive_approval,
                )
            result = self._coerce_tool_result_to_output(name, result)
            return await self._finish_from_result(
                state,
                page,
                current_url,
                result,
                clear_sensitive_approval=consume_sensitive_approval,
            )
        else:
            # Fallback: structured output (no tool_calls).
            #
            # This was a synchronous `.invoke()` inside an async node with no
            # asyncio timeout. It blocked the event loop for the whole call, which
            # also stalls Playwright's I/O, and with the provider's own 60s request
            # timeout plus client-side retries a single step could exceed two
            # minutes before returning.
            print("[executor] No tool call returned; retrying via structured output...", flush=True)
            fallback_started = asyncio.get_event_loop().time()
            try:
                action: ExecutionResult = await asyncio.wait_for(
                    self.llm_structured.ainvoke(json_messages),
                    timeout=_LLM_CALL_TIMEOUT_SECONDS,
                )
                print(
                    f"[executor] Structured fallback responded in "
                    f"{asyncio.get_event_loop().time() - fallback_started:.1f}s",
                    flush=True,
                )
            except asyncio.TimeoutError:
                return self._return_failure(
                    state, current_url,
                    action="none", args={},
                    message=f"Executor structured fallback timed out ({_LLM_CALL_TIMEOUT_SECONDS}s).",
                    error_type="unknown",
                )
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
                    "last_execution_event": self._last_execution_event_dict(
                        action=validated.action,
                        args=self._action_args_to_dict(validated.args),
                        status=validated.status,
                        message=validated.message,
                        error_type=validated.error_type,
                    ),
                }
            # Forward the whole arg set. This used to copy only the legacy
            # fields, silently dropping nth/label/value/checked/document_id and
            # friends, which made select_option and upload_file unusable through
            # the structured-output path no matter what the model emitted.
            full_args = validated.args.model_dump()
            full_args["max_chars"] = full_args.get("max_chars") or 15000
            tool_action = Action(
                action=validated.action,
                args=ActionArgs(**full_args),
            )

            validated_args = validated.args.model_dump(
                exclude_none=True, exclude_defaults=True
            )

            consume_sensitive_approval = False
            decision = assess_action(
                validated.action,
                validated_args,
                policy=state.get("autonomy_policy"),
                url=state.get("current_url"),
            )
            sensitive_reason = str(decision.get("reason") or "") if decision.get("mode") == "confirm" else None
            if sensitive_reason:
                signature = self._action_signature(validated.action, validated_args)
                if not self._is_sensitive_action_approved(state, signature):
                    return self._request_sensitive_confirmation(
                        state=state,
                        current_url=current_url,
                        action=validated.action,
                        args=validated_args,
                        current_task=current_task,
                        reason=sensitive_reason,
                        action_signature=signature,
                    )
                consume_sensitive_approval = True

            missing_required = await self._required_empty_fields_before_finalization(
                page,
                state,
                validated.action,
                validated_args,
            )
            if missing_required:
                return self._return_failure(
                    state,
                    current_url,
                    action=validated.action,
                    args=validated_args,
                    message=(
                        "Cannot finalize yet. Required fields are still incomplete: "
                        f"{', '.join(missing_required)}"
                    ),
                    error_type="ambiguous_step",
                    clear_sensitive_approval=consume_sensitive_approval,
                )

            result = await dispatch_action(page, tool_action, runtime=self.runtime)
            print(
                f"[executor - {result.action} result]: ",
                self._execution_output_for_log(result),
                flush=True,
            )
            return await self._finish_from_result(
                state,
                page,
                current_url,
                result,
                clear_sensitive_approval=consume_sensitive_approval,
            )

    @staticmethod
    def _collect_secret_values(state: ProjectState) -> tuple[str, ...]:
        """Exact secret strings from the user's vault, for redaction.

        Redacting by value rather than by field name means a password is scrubbed
        wherever it appears, while functionally necessary text (a search query, a
        cover letter) is left intact.
        """
        creds = state.get("user_credentials") or {}
        if not isinstance(creds, dict):
            return ()

        secrets: set[str] = set()

        for service in creds.get("userCredentialsList") or []:
            if isinstance(service, dict):
                value = service.get("password")
                if isinstance(value, str) and len(value.strip()) >= 4:
                    secrets.add(value.strip())

        for payment in creds.get("userPaymentMethods") or []:
            if isinstance(payment, dict):
                for key in ("cardNumber", "cvv", "cvc", "securityCode"):
                    value = payment.get(key)
                    if isinstance(value, str) and len(value.strip()) >= 4:
                        secrets.add(value.strip())

        # Longest first so a secret containing another is masked whole.
        return tuple(sorted(secrets, key=len, reverse=True))

    def _redact(self, text: str) -> str:
        """Replace any known secret value inside ``text`` with a placeholder."""
        if not isinstance(text, str) or not text:
            return text
        for secret in getattr(self, "_secret_values", ()) or ():
            if secret and secret in text:
                text = text.replace(secret, f"<redacted len={len(secret)}>")
        return text

    def _execution_output_for_log(self, result: ExecutionOutput) -> dict[str, Any]:
        """Strip/redact values that must not appear in logs (typed secrets, extracted page text)."""
        payload = result.model_dump()
        args = dict(payload.get("args") or {})
        for key in ("text", "query"):
            val = args.get(key)
            if isinstance(val, str) and val:
                args[key] = f"<redacted len={len(val)}>"
        payload["args"] = args
        et = payload.get("extracted_text")
        if isinstance(et, str) and et:
            payload["extracted_text"] = f"<redacted len={len(et)}>"
        message = payload.get("message")
        if isinstance(message, str) and message:
            payload["message"] = self._redact(message)
        return payload

    def _return_failure(
        self,
        state,
        current_url,
        action,
        args,
        message,
        error_type="unknown",
        clear_sensitive_approval: bool = False,
    ):
        out = {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "reasoning_log": [self._build_execution_log(
                action=action, args=args if isinstance(args, dict) else {},
                status="failure", message=message, error_type=error_type,
            )],
            "current_url": current_url,
            "last_execution_event": Executor._last_execution_event_dict(
                action=str(action or ""),
                args=args if isinstance(args, dict) else {},
                status="failure",
                message=message,
                error_type=error_type,
            ),
            "screenshot": None,
            "screenshot_meta": None,
        }
        if clear_sensitive_approval:
            out["sensitive_action_approval"] = None
        return out

    def _request_sensitive_confirmation(
        self,
        *,
        state: ProjectState,
        current_url: str,
        action: str,
        args: dict,
        current_task: str,
        reason: str,
        action_signature: str,
    ) -> dict:
        target_label = self._describe_sensitive_target(action, args)
        prompt = (
            "Sensitive action checkpoint. "
            f"I am about to execute {target_label}. "
            f"Reason: {reason}. "
            "Reply 'yes' to proceed or 'no' to cancel."
        )
        blocked_log = self._build_execution_log(
            action=action,
            args=args if isinstance(args, dict) else {},
            status="failure",
            message="Sensitive action requires explicit user confirmation before execution.",
            error_type="tool_limit",
        )
        return {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "reasoning_log": [blocked_log],
            "current_url": current_url,
            "last_execution_event": self._last_execution_event_dict(
                action=str(action or ""),
                args=args if isinstance(args, dict) else {},
                status="failure",
                message="Sensitive action requires explicit user confirmation before execution.",
                error_type="tool_limit",
            ),
            "handoff_interaction": True,
            "pending_sensitive_action": {
                "action": action,
                "args": args if isinstance(args, dict) else {},
                "current_task": current_task,
                "reason": reason,
                "target": target_label,
                "message": prompt,
                "action_signature": action_signature,
            },
            "sensitive_action_approval": None,
        }

    @classmethod
    def _sensitive_action_reason(cls, action: str | None, args: dict, current_task: str) -> str | None:
        decision = assess_action(action or "", args if isinstance(args, dict) else {}, policy=None, url=None)
        if decision.get("mode") == "confirm":
            return str(decision.get("reason") or "This action requires explicit confirmation")
        return None

    @staticmethod
    def _action_signature(action: str | None, args: dict) -> str:
        action_l = (action or "").strip().lower()
        safe_args = {}
        if isinstance(args, dict):
            for key in ("url", "role", "name", "text", "direction", "key", "seconds"):
                value = args.get(key)
                if value is None:
                    continue
                if isinstance(value, str):
                    value = value.strip().lower()
                safe_args[key] = value
        encoded = json.dumps(safe_args, ensure_ascii=True, sort_keys=True, default=str)
        return f"{action_l}:{encoded}"

    @staticmethod
    def _is_sensitive_action_approved(state: ProjectState, action_signature: str) -> bool:
        approval = state.get("sensitive_action_approval") or {}
        if not isinstance(approval, dict):
            return False
        return bool(approval.get("approved") is True and approval.get("action_signature") == action_signature)

    @staticmethod
    def _describe_sensitive_target(action: str, args: dict) -> str:
        if not isinstance(args, dict):
            return action
        role = (args.get("role") or "").strip()
        name = (args.get("name") or "").strip()
        key = (args.get("key") or "").strip()
        if action == "click" and role and name:
            return f"click({role}, {name})"
        if action == "press_key" and key:
            return f"press_key({key})"
        return action

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
            try:
                text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
            except Exception:
                text = repr(result)
            if len(text) > 8000:
                text = text[:8000] + "\n... [truncated]"
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
                extracted_text=result[:8000],
            )
        return ExecutionOutput(
            action=tool_name,
            args={},
            status="success",
            error_type="none",
            message=f"Tool {tool_name} returned {type(result).__name__}",
            execution_time_ms=0,
            extracted_text=repr(result)[:8000],
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
            if self._is_dismissive_click_name(name) and not self._task_explicitly_allows_dismissive(current_task):
                return {}
            if self._is_finalization_task(current_task) and self._is_dismissive_click_name(name):
                return {}
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
    def _is_finalization_task(current_task: str) -> bool:
        text = (current_task or "").lower()
        return any(token in text for token in (
            "send",
            "submit",
            "review",
            "confirm",
            "finalize",
            "finish",
            "complete",
        ))

    @staticmethod
    def _is_dismissive_click_name(name: str) -> bool:
        lowered = (name or "").strip().lower()
        if not lowered:
            return False
        return any(token in lowered for token in (
            "cancel",
            "close",
            "discard",
            "back",
            "hide",
            "dismiss",
            "exit",
        ))

    @staticmethod
    def _task_explicitly_allows_dismissive(current_task: str) -> bool:
        text = (current_task or "").lower()
        allow_tokens = (
            "close",
            "cancel",
            "dismiss",
            "hide",
            "discard",
            "go back",
            "back button",
            "exit",
        )
        return any(token in text for token in allow_tokens)

    @staticmethod
    def _is_finalization_action(action_name: str | None, args: dict) -> bool:
        if not isinstance(args, dict):
            return False
        action_name = (action_name or "").strip().lower()
        if action_name == "click":
            role = (args.get("role") or "").strip().lower()
            return role in {"button", "menuitem", "tab", "link"}
        if action_name == "press_key":
            key = (args.get("key") or "").strip().lower()
            return key in {"enter", "return"}
        return False

    @staticmethod
    def _missing_required_field_names(form_report: str) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for raw in (form_report or "").splitlines():
            line = raw.strip()
            if "required" not in line:
                continue
            if not any(token in line for token in (": empty", ": no file", ": unchecked")):
                continue
            match = re.search(r'"([^"]+)"', line)
            if not match:
                continue
            name = match.group(1).strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        return names

    async def _required_empty_fields_before_finalization(
        self,
        page,
        state: ProjectState,
        action_name: str | None,
        args: dict,
    ) -> list[str]:
        if (state.get("step_intent") or "").strip().lower() != "finalize":
            return []
        if not self._is_finalization_action(action_name, args):
            return []
        try:
            from execution.actions import do_read_form

            result = await do_read_form(page)
        except Exception:
            return []
        if getattr(result, "status", "failure") != "success":
            return []
        return self._missing_required_field_names(getattr(result, "extracted_text", "") or "")

    @staticmethod
    def _dom_snapshot_budget(current_task: str) -> int:
        return SNAPSHOT_SECTION_MAX_CHARS

    @staticmethod
    def _split_dom_cache_snapshot(snapshot: str) -> tuple[str, list[str]]:
        lines = [line.strip() for line in (snapshot or "").splitlines() if line and line.strip()]
        if not lines:
            return "", []
        url = ""
        if lines[0].lower().startswith("url:"):
            url = lines[0][4:].strip()
            lines = lines[1:]
        return url, lines

    @staticmethod
    def _build_dom_delta_lines(latest_lines: list[str], previous_lines: list[str], max_items: int = 8) -> tuple[list[str], list[str]]:
        prev_set = set(previous_lines)
        latest_set = set(latest_lines)
        added = [line for line in latest_lines if line not in prev_set][:max_items]
        removed = [line for line in previous_lines if line not in latest_set][:max_items]
        return added, removed

    @staticmethod
    def _build_dom_cache_context(state: ProjectState) -> str:
        cache = state.get("dom_cache") or []
        if not cache:
            return ""
        latest = (cache[-1] or "").strip()
        if not latest:
            return ""
        if len(cache) == 1:
            clipped = latest[:650]
            if len(latest) > 650:
                clipped += "\n... [truncated]"
            return f"\n\nDOM_TEXT_CONTEXT (latest page text snapshot):\n{clipped}"

        previous = (cache[-2] or "").strip()
        latest_url, latest_lines = Executor._split_dom_cache_snapshot(latest)
        previous_url, previous_lines = Executor._split_dom_cache_snapshot(previous)
        added, removed = Executor._build_dom_delta_lines(latest_lines, previous_lines, max_items=8)

        added_block = "\n".join(f"- {line[:140]}" for line in added) if added else "- none"
        removed_block = "\n".join(f"- {line[:140]}" for line in removed) if removed else "- none"
        same_url = bool(latest_url and previous_url and latest_url == previous_url)
        delta = (
            "\n\nDOM_TEXT_CONTEXT (cached diff summary):\n"
            f"- latest_url: {latest_url or 'unknown'}\n"
            f"- previous_url: {previous_url or 'unknown'}\n"
            f"- url_unchanged: {same_url}\n"
            f"- text_added_count: {len(added)}\n"
            f"- text_removed_count: {len(removed)}\n"
            "Added text highlights:\n"
            f"{added_block}\n"
            "Removed text highlights:\n"
            f"{removed_block}"
        )
        return Executor._clip_text(delta, 900)

    @staticmethod
    def _is_data_entry_task(current_task: str) -> bool:
        text = (current_task or "").lower()
        return bool(re.search(
            r"\b(fill|enter|type|write|input|provide|set|update|complete|"
            r"log\s*in|sign\s*in|authenticate|credentials?)\b",
            text,
        ))

    @staticmethod
    def _task_keywords(current_task: str) -> set[str]:
        stop = {
            "the", "and", "for", "with", "from", "into", "onto", "that", "this", "then",
            "step", "page", "field", "fields", "button", "click", "open", "use", "using",
            "form", "draft", "write", "enter", "fill", "type", "input", "update", "set",
        }
        words = re.findall(r"[a-z0-9]{3,}", (current_task or "").lower())
        return {w for w in words if w not in stop}

    @staticmethod
    def _name_keywords(name: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]{3,}", (name or "").lower()))

    @classmethod
    def _build_field_priority_context(
        cls,
        dom_snapshot: str,
        current_task: str,
        state: ProjectState | None = None,
    ) -> str:
        if not cls._is_data_entry_task(current_task):
            return ""

        fields: list[tuple[str, str]] = []
        controls: list[tuple[str, str]] = []
        seen = set()
        for line in (dom_snapshot or "").splitlines():
            m = re.search(r'\[role="(?P<role>[^"]+)"\]\s+"(?P<name>[^"]+)"', line.strip())
            if not m:
                continue
            role = (m.group("role") or "").strip().lower()
            name = (m.group("name") or "").strip()
            if not name:
                continue
            key = (role, name.lower())
            if key in seen:
                continue
            seen.add(key)
            if role in {"textbox", "searchbox", "combobox", "textarea", "spinbutton"}:
                fields.append((role, name))
            elif role in {"button", "tab", "menuitem"}:
                controls.append((role, name))

        if not fields and not controls:
            return ""

        task_keywords = cls._task_keywords(current_task)
        scored_fields: list[tuple[int, str, str]] = []
        for role, name in fields:
            overlap = len(task_keywords & cls._name_keywords(name))
            scored_fields.append((overlap, role, name))
        scored_fields.sort(key=lambda item: (-item[0], item[2].lower()))
        relevant_fields = [(r, n) for score, r, n in scored_fields if score > 0]
        shown_fields = (relevant_fields or [(r, n) for _, r, n in scored_fields])[:8]
        shown_controls = controls[:6]

        field_lines = "\n".join(f"- {r}: {n}" for r, n in shown_fields) if shown_fields else "- none detected"
        control_lines = "\n".join(f"- {r}: {n}" for r, n in shown_controls) if shown_controls else "- none detected"

        text = (
            "\n\nFIELD_PRIORITY_CONTEXT:\n"
            "Use this as an action-order hint, not a hard ban.\n"
            "If a relevant editable field is visible, prefer filling fields (focus/type) over clicking generic buttons.\n"
            "Click buttons when needed to reveal/focus the required field, advance auth flow, or submit after required fields are complete.\n"
            "Visible editable fields:\n"
            f"{field_lines}\n"
            "Visible actionable controls:\n"
            f"{control_lines}"
        )
        return cls._clip_text(text, 1200)

    @classmethod
    def _build_site_notes_context(cls, current_url: str) -> str:
        """Per-domain guidance, injected only when the current host matches."""
        notes = load_site_notes(current_url)
        if not notes:
            return ""
        return cls._clip_text(
            f"\n\nSITE_NOTES (guidance specific to the current site):\n{notes}", 1500
        )

    @staticmethod
    def _clean_tool_string(value: str) -> str:
        cleaned = (value or "").strip()
        # Common malformed trailing tokens from tool-call JSON rendering.
        cleaned = re.sub(r"[}\],\s]+$", "", cleaned)
        cleaned = cleaned.strip("\"'` ")
        return cleaned

    @staticmethod
    def _clip_text(value: str, max_chars: int) -> str:
        text = (value or "").strip()
        if max_chars <= 0:
            return ""
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n... [truncated]"

    async def _finish_from_result(self, state, page, current_url, result, clear_sensitive_approval: bool = False):
        result_status = result.status
        result_error_type = result.error_type
        result_message = result.message

        # Handle links that open in a new tab/window: adopt a tab the action
        # itself opened. Never second-guess an explicit tab-management action:
        # switch_tab and close_tab already retargeted self.runtime["page"].
        # Comparing against pages_before_action keeps this from re-adopting a
        # pre-existing later tab, which would undo an explicit switch_tab on
        # the very next success.
        if result_status == "success" and result.action in {"switch_tab", "close_tab"}:
            page = self.runtime.get("page") or page
        elif result_status == "success":
            try:
                pages_before = self.runtime.get("pages_before_action") or []
                opened = [
                    p for p in page.context.pages
                    if p not in pages_before and p != page
                ]
                if opened:
                    new_page = opened[-1]
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
            after_state = await self._get_real_dom_snapshot(page, max_chars=SNAPSHOT_SECTION_MAX_CHARS)
        except Exception:
            after_state = f"[URL after action: {new_url}]"

        # For extract_content, show the extracted text to the verifier
        extracted = getattr(result, "extracted_text", None)
        if extracted and result.action == "extract_content":
            after_state = (
                f"EXTRACTED_TEXT:\n{extracted.strip()[:SNAPSHOT_SECTION_MAX_CHARS]}\n\n"
                f"DOM_SNAPSHOT:\n{after_state}"
            )

        execution_log = self._build_execution_log(
            action=result.action,
            args=result.args,
            status=result_status,
            message=result_message,
            error_type=result_error_type,
            after_state=after_state,
        )
        extracted_present = bool(
            extracted and isinstance(extracted, str) and extracted.strip()
        ) and result.action == "extract_content"
        out = {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "reasoning_log": [execution_log],
            "current_url": new_url,
            "last_execution_event": self._last_execution_event_dict(
                action=result.action,
                args=result.args,
                status=result_status,
                message=result_message,
                error_type=result_error_type,
                extracted_content_present=extracted_present,
                verified=result.verified,
            ),
            "last_page_snapshot": after_state,
        }
        if extracted and isinstance(extracted, str) and extracted.strip():
            out["extracted_content"] = [extracted.strip()]
        # Also keep a lightweight DOM/text snapshot in dom_cache for later navigation tools
        try:
            dom_text = await dom_extractor.get_page_text(page, max_chars=3500)
            if dom_text and dom_text.strip():
                snapshot = f"URL: {new_url}\n\n{dom_text.strip()}"
                out["dom_cache"] = [snapshot]
        except Exception:
            pass

        should_capture_screenshot = self._should_capture_recovery_screenshot(
            state=state,
            result_status=result_status,
            result_error_type=result_error_type,
        )
        if should_capture_screenshot:
            screenshot_data_url = await self._capture_recovery_screenshot(page)
            if screenshot_data_url:
                out["screenshot"] = screenshot_data_url
                out["screenshot_meta"] = self._build_recovery_screenshot_meta(
                    state=state,
                    transaction_index=out["number_of_transactions"],
                    result_status=result_status,
                    result_error_type=result_error_type,
                    action=result.action,
                )
            else:
                out["screenshot"] = None
                out["screenshot_meta"] = None
        else:
            # Clear stale screenshot artifacts so fallback does not use old visuals.
            out["screenshot"] = None
            out["screenshot_meta"] = None

        if clear_sensitive_approval:
            out["sensitive_action_approval"] = None
        return out

    @classmethod
    def _should_capture_recovery_screenshot(
        cls,
        *,
        state: ProjectState,
        result_status: str,
        result_error_type: str | None,
    ) -> bool:
        status = (result_status or "").strip().lower()
        error_type = (result_error_type or "").strip().lower()
        step_attempts = int(state.get("step_attempts", 0) or 0)
        stall_cycles = int(state.get("stall_cycles", 0) or 0)

        high_signal_error_tokens = (
            "blocked",
            "captcha",
            "navigation_blocked",
            "tool_limit",
            "unexpected_state",
        )
        has_high_signal_error = any(tok in error_type for tok in high_signal_error_tokens)

        if status != "success":
            return has_high_signal_error or step_attempts >= 1 or stall_cycles >= 1
        return False

    @classmethod
    async def _capture_recovery_screenshot(cls, page) -> str | None:
        """Capture a compressed screenshot suitable for occasional fallback escalation."""
        try:
            image_bytes = await page.screenshot(
                type="jpeg",
                quality=45,
                full_page=False,
                animations="disabled",
            )
            if not image_bytes:
                return None
            if len(image_bytes) > cls._RECOVERY_SCREENSHOT_MAX_BYTES:
                image_bytes = await page.screenshot(
                    type="jpeg",
                    quality=30,
                    full_page=False,
                    animations="disabled",
                )
            if not image_bytes or len(image_bytes) > cls._RECOVERY_SCREENSHOT_MAX_BYTES:
                return None
            encoded = base64.b64encode(image_bytes).decode("ascii")
            data_url = f"data:image/jpeg;base64,{encoded}"
            if len(data_url) > cls._RECOVERY_SCREENSHOT_MAX_DATA_URL_CHARS:
                return None
            return data_url
        except Exception:
            return None

    @staticmethod
    def _build_recovery_screenshot_meta(
        *,
        state: ProjectState,
        transaction_index: int,
        result_status: str,
        result_error_type: str | None,
        action: str,
    ) -> dict:
        return {
            "transaction_index": int(transaction_index),
            "step_index": int(state.get("current_step_index", 0) or 0),
            "step_attempts": int(state.get("step_attempts", 0) or 0),
            "status": (result_status or "unknown").strip().lower(),
            "error_type": (result_error_type or "none").strip().lower(),
            "action": (action or "").strip().lower(),
            "capture_mode": "fallback_last_resort",
        }


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
        recent = executor_logs[-4:]
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
        text = (
            "\n\nPREVIOUS_ACTIONS (already executed — do NOT repeat; if discovery found items, CLICK one):\n"
            + "\n".join(summaries)
        )
        return Executor._clip_text(text, 1200)

    @staticmethod
    def _build_adaptive_guidance(state: ProjectState, current_task: str) -> str:
        """Create generic, non-domain-specific guidance from recent outcomes."""
        logs = state.get("reasoning_log") or []
        recent = [log for log in logs if isinstance(log, str)][-10:]
        if not recent:
            return ""

        last_executor = next((e for e in reversed(recent) if e.startswith("[Executor]")), "")
        if not last_executor:
            return ""

        action = ""
        status = ""
        message = ""
        args = ""
        for line in last_executor.split("\n"):
            s = line.strip()
            if s.startswith("[Executor] Action:"):
                action = s.split(":", 1)[1].strip().lower()
            elif s.startswith("[Executor] Status:"):
                status = s.split(":", 1)[1].strip().lower()
            elif s.startswith("[Executor] Message:"):
                message = s.split(":", 1)[1].strip().lower()
            elif s.startswith("[Executor] Args:"):
                args = s.split(":", 1)[1].strip().lower()

        hints: list[str] = []

        # Generic failure guidance: avoid repeating the exact failed target.
        if status == "failure" and "element_not_found" in last_executor.lower():
            hints.append(
                "The previous action failed with element_not_found. Do not repeat the same role/name target; choose a different locator strategy or complementary action."
            )

        # Generic anti-loop guidance for in-progress retries.
        recent_executor = [e for e in recent if e.startswith("[Executor]")][-4:]
        if len(recent_executor) >= 2:
            action_seq = []
            for entry in recent_executor:
                for line in entry.split("\n"):
                    s = line.strip()
                    if s.startswith("[Executor] Action:"):
                        action_seq.append(s.split(":", 1)[1].strip().lower())
                        break
            if len(action_seq) >= 2 and action_seq[-1] == action_seq[-2]:
                hints.append(
                    "You are repeating the same action type on this step. Try the next complementary action (e.g., after click use type/press_key; after type use confirm/select action)."
                )

        # If current task is data-entry and last click target was text-like but failed,
        # suggest typing only when an input lane is clearly visible in snapshot.
        task_lower = (current_task or "").lower()
        if ("fill" in task_lower or "address" in task_lower or "enter" in task_lower or "draft" in task_lower):
            if action == "click" and status == "failure":
                hints.append(
                    "For data-entry steps, if click-to-focus fails, choose a direct field-entry strategy into a visible input/combo/contenteditable lane instead of re-clicking the same label."
                )

        if not hints:
            return ""
        text = "\n\nADAPTIVE_GUIDANCE (from recent outcomes):\n- " + "\n- ".join(hints)
        return Executor._clip_text(text, 420)

    @staticmethod
    def _is_navigation_or_retrieval_task(current_task: str) -> bool:
        text = (current_task or "").lower()
        return any(tok in text for tok in (
            "navigate",
            "open",
            "visit",
            "go to",
            "search",
            "find",
            "look up",
            "extract",
            "gather",
            "collect",
            "summarize",
            "result",
            "listing",
        ))

    @classmethod
    def _should_include_dom_cache_context(cls, state: ProjectState, current_task: str) -> bool:
        attempts = int(state.get("step_attempts", 0) or 0)
        signals = state.get("status_signals") or {}
        blocking_issue = (signals.get("blocking_issue") or "").strip()
        if attempts >= 2 or blocking_issue:
            return True
        if cls._is_navigation_or_retrieval_task(current_task):
            return True
        if cls._is_data_entry_task(current_task):
            return False
        return attempts >= 1

    def _build_execution_status_context(
        self,
        state: ProjectState,
        current_task: str,
        step_attempts: int,
    ) -> str:
        signals = state.get("status_signals") or {}
        login_phase = (signals.get("login_phase") or "not_started").strip()
        blocking_issue = (signals.get("blocking_issue") or "").strip()
        step_intent = (state.get("step_intent") or "").strip()
        lines = [
            "\n\nEXECUTION_STATUS_SIGNALS:",
            f"- step_attempts: {step_attempts}",
            f"- step_intent: {step_intent or 'unknown'}",
            f"- login_phase: {login_phase}",
            f"- blocking_issue: {blocking_issue or 'none'}",
        ]

        # Include mission status only when retries/blockers suggest it is needed.
        if step_attempts >= 2 or blocking_issue:
            mission_excerpt = self._clip_text(state.get("mission_status") or "", 900)
            if mission_excerpt:
                lines.extend([
                    "MISSION_STATUS_EXCERPT:",
                    mission_excerpt,
                ])

        return self._clip_text("\n".join(lines), 1400)

    _LOGIN_KEYWORDS = re.compile(
        r"\blog\s*in\b|\bsign\s*in\b|\bcredential|\busername\b|\bpassword\b"
        r"|\bauthenticat|\bsaved credentials\b",
        re.IGNORECASE,
    )

    @staticmethod
    def _should_enforce_saved_credentials_for_typing(current_task: str) -> bool:
        """
        Only rewrite `type` args when the plan step is clearly about login/credentials.
        URL-matched services alone are not enough — otherwise unrelated typing
        can be overwritten with saved credentials.
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
            return ""

        is_login_step = bool(self._LOGIN_KEYWORDS.search(current_task))
        is_form_step = bool(self._FORM_FILL_KEYWORDS.search(current_task))

        if not is_login_step and not is_form_step:
            return ""

        parts = []

        if is_login_step:
            match = self._find_matching_service(creds, current_task, current_url)
            if match:
                username = match.get('username', '')
                password = match.get('password', '')
                parts.append(
                    f"SERVICE_CREDENTIALS (use these EXACT values - do NOT make up values):\n"
                    f"  Username/Email: {username}\n"
                    f"  Password: {password}\n\n"
                    f"FIELD MATCHING RULES:\n"
                    f"  - Look at DOM_SNAPSHOT for visible input fields (textbox, password field, etc.).\n"
                    f"  - Match each field to the correct credential by its accessible name/label "
                    f"(e.g. 'Email', 'Username', 'User ID' → the Username value; 'Password' → the Password value).\n"
                    f"  - Fill ONE field per turn: `fill(role, name, text)` with the matching value.\n"
                    f"  - After all visible fields are filled (check PREVIOUS_ACTIONS), click the submit/sign-in/next button.\n"
                    f"  - Some logins show ONE field per page (username first, password after 'Next'); "
                    f"fill the visible field, click Next, and the system will re-invoke you on the new page."
                )

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

            documents = creds.get("userDocuments") or {}
            if isinstance(documents, dict):
                doc_lines = [
                    f"  {label}: {path}"
                    for label, path in documents.items()
                    if isinstance(path, str) and path.strip()
                ]
                if doc_lines:
                    parts.append(
                        "DOCUMENTS (stored files; attach with upload_file(file_path=<path>)):\n"
                        + "\n".join(doc_lines)
                    )

        if not parts:
            return ""
        text = "\n\nUSER_CREDENTIALS (available for auto-fill - enter these values with `fill`):\n" + "\n".join(parts)
        return self._clip_text(text, 1300)

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
        """
        Detect genuine anti-bot/CAPTCHA pages from URL signals.

        Keep this strict: broad substring matching (for example "challenge")
        can incorrectly classify OAuth URLs that include parameters like
        "code_challenge".
        """
        parsed = urlparse((url or "").strip())
        host = (parsed.netloc or "").lower()
        path = (parsed.path or "").lower()
        query = (parsed.query or "").lower()

        # Google anti-bot interstitials.
        if ("google." in host and path.startswith("/sorry")) or "/sorry/index" in path:
            return True

        # Known challenge/captcha hosts.
        if any(token in host for token in ("challenges.cloudflare.com", "captcha", "recaptcha")):
            return True

        # Challenge/captcha paths.
        if any(token in path for token in ("/captcha", "/recaptcha", "/hcaptcha")):
            return True
        if re.search(r"(^|/)challenge(s)?(/|$)", path):
            return True

        # Query parameters indicating a challenge. Exclude OAuth PKCE params
        # (code_challenge, code_challenge_method), which are not anti-bot.
        sanitized_query = re.sub(r"(^|&)code_challenge(?:_method)?=[^&]*", "", query)
        if "unusual+traffic" in sanitized_query or "unusual%20traffic" in sanitized_query:
            return True
        if re.search(r"(^|[&])(captcha|recaptcha|hcaptcha|g-recaptcha-response|h-captcha-response)=", sanitized_query):
            return True
        if re.search(r"(^|[&])challenge=", sanitized_query):
            return True

        return False

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
        for key in [
            "url",
            "role",
            "name",
            "nth",
            "text",
            "checked",
            "value",
            "label",
            "document_id",
            "url_contains",
            "text_contains",
            "index",
            "section",
            "direction",
            "key",
            "seconds",
        ]:
            value = args.get(key) if isinstance(args, dict) else None
            if value is not None and str(value).strip() != "":
                args_str.append(f"{key}={self._redact(str(value))}")

        # reasoning_log is re-fed to the model by _build_recent_actions, so a secret
        # left here would re-enter the prompt on every subsequent turn.
        log = (
            f"[Executor] Action: {action}\n"
            f"[Executor] Args: {', '.join(args_str) or 'None'}\n"
            f"[Executor] Status: {status}\n"
            f"[Executor] Message: {self._redact(str(message))}"
        )
        if error_type and error_type != "none":
            log += f"\n[Executor] Error Type: {error_type}"
        if after_state and after_state.strip():
            snippet = after_state.strip()[:1600]
            if len(after_state.strip()) > 1600:
                snippet += "\n... (truncated)"
            log += f"\n[Executor] AFTER_STATE (page content for verification):\n{snippet}"
        return log
    


    async def _get_real_dom_snapshot(self, page, max_chars: int = 8000, section: int = 1) -> str:
        """One section of the unified page snapshot (see dom_extraction.snapshot).

        Args:
            max_chars: Character budget per section. A page that does not fit is
                       paginated, not truncated: the rendered section says how
                       many elements are hidden and which read_page(section=N)
                       call shows them, so a long form's bottom fields are
                       reachable instead of silently cut.
            section:   1-based section to render.
        """
        try:
            snapshot = await capture_page_snapshot(page)
        except Exception as e:
            return f"[DOM snapshot failed: {e}]"
        return snapshot.render(max_chars=max_chars, section=section)
