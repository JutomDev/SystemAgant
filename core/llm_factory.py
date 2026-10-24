"""Model Provider & Adapter Factory for SystemAgant.

Decouples agent nodes from hardcoded vendor endpoints.
Integrates Google GenAI SDK (google-genai) for Google AI Studio free tier,
with built-in rate-limiting backoff and thought-signature preservation.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from core.config import AppConfig, get_config

logger = logging.getLogger(__name__)


FALLBACK_MODELS = ["gemini-flash-lite-latest", "gemini-3.1-flash-lite", "gemini-2.5-flash", "gemini-3.5-flash"]


def _extract_retry_delay(err_msg: str, default_delay: float = 12.0) -> float | None:
    """Extracts retryDelay in seconds. If delay > 60s, returns None to indicate daily quota exhaustion."""
    match = re.search(r"retryDelay':\s*'(\d+)s'", err_msg)
    if match:
        delay = float(match.group(1)) + 1.0
        return delay if delay <= 60.0 else None
    match_sec = re.search(r"retry in (\d+(\.\d+)?)s", err_msg)
    if match_sec:
        delay = float(match_sec.group(1)) + 1.0
        return delay if delay <= 60.0 else None
    return default_delay


class GeminiArchitectAdapter(Runnable):
    """Adapter wrapping Google GenAI SDK for Architect planning & brainstorming."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.5-flash",
        temperature: float = 0.2,
        target_schema: type[Any] | None = None,
        max_retries: int = 4,
    ) -> None:
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.target_schema = target_schema
        self.max_retries = max_retries
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def with_structured_output(self, schema: type[Any]) -> GeminiArchitectAdapter:
        """Returns a cloned adapter configured for deterministic Pydantic output."""
        return GeminiArchitectAdapter(
            api_key=self.api_key,
            model=self.model,
            temperature=self.temperature,
            target_schema=schema,
            max_retries=self.max_retries,
        )

    def invoke(self, input: Any, config: Any | None = None) -> Any:
        client = self._get_client()
        from google.genai import errors, types

        # 1. Convert input to text prompt and optional system instruction
        system_instruction: str | None = None
        user_prompt_parts: list[str] = []

        if isinstance(input, list):
            for msg in input:
                if isinstance(msg, SystemMessage):
                    system_instruction = str(msg.content)
                elif isinstance(msg, (HumanMessage, ToolMessage)):
                    user_prompt_parts.append(str(msg.content))
                elif isinstance(msg, AIMessage):
                    user_prompt_parts.append(f"AI Context: {msg.content}")
                elif isinstance(msg, dict):
                    role = msg.get("role") or msg.get("type")
                    if role in ("system", "SystemMessage"):
                        system_instruction = str(msg.get("content", ""))
                    else:
                        user_prompt_parts.append(str(msg.get("content", "")))
        elif isinstance(input, str):
            user_prompt_parts.append(input)
        else:
            user_prompt_parts.append(str(input))

        prompt_text = "\n\n".join(user_prompt_parts)

        # 2. Build GenerateContentConfig
        cfg_kwargs: dict[str, Any] = {
            "temperature": self.temperature,
        }
        if system_instruction:
            cfg_kwargs["system_instruction"] = system_instruction

        if self.target_schema:
            cfg_kwargs["response_mime_type"] = "application/json"
            cfg_kwargs["response_schema"] = self.target_schema

        req_config = types.GenerateContentConfig(**cfg_kwargs)

        # 3. Execute with automatic rate-limit backoff and model candidate fallback
        model_candidates = [self.model] + [m for m in FALLBACK_MODELS if m != self.model]

        for current_model in model_candidates:
            for attempt in range(self.max_retries):
                try:
                    response = client.models.generate_content(
                        model=current_model,
                        contents=prompt_text,
                        config=req_config,
                    )

                    if self.target_schema:
                        raw_json = response.text or "{}"
                        try:
                            return self.target_schema.model_validate_json(raw_json)
                        except Exception:
                            data = json.loads(raw_json)
                            return self.target_schema(**data)
                    else:
                        return AIMessage(content=response.text or "")

                except errors.ClientError as err:
                    err_str = str(err)
                    if err.code == 429 or "RESOURCE_EXHAUSTED" in err_str:
                        delay = _extract_retry_delay(err_str)
                        if delay is None:
                            # Daily quota reached for current_model, switch to next model
                            logger.warning(
                                "[RateLimit] Daily quota reached for %s. Falling back to next model...", current_model
                            )
                            print(
                                f"[*] Daily quota reached for {current_model}. Switching to alternative model...",
                                flush=True,
                            )
                            break
                        else:
                            # Per-minute rate limit, wait and retry
                            logger.warning(
                                "[RateLimit] 429 received in Architect (%s). Pausing for %.1fs...", current_model, delay
                            )
                            print(
                                f"[*] Rate limit (429) on {current_model}. Waiting {delay:.1f}s before retry...",
                                flush=True,
                            )
                            time.sleep(delay)
                            continue
                    raise err
                except Exception as e:
                    if attempt == self.max_retries - 1:
                        logger.warning("Attempt %d failed on model %s: %s", attempt, current_model, e)
                    time.sleep(1.0)

        raise RuntimeError("Architect LLM invocation failed after maximum retries.")


class GeminiCoderAdapter(Runnable):
    """Adapter wrapping Google GenAI SDK for Coder multi-turn tool calling."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.5-flash",
        temperature: float = 0.1,
        tools: list[Any] | None = None,
        max_retries: int = 4,
    ) -> None:
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.tools = tools or []
        self.max_retries = max_retries
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> GeminiCoderAdapter:
        """Binds tool declarations for function calling."""
        return GeminiCoderAdapter(
            api_key=self.api_key,
            model=self.model,
            temperature=self.temperature,
            tools=tools,
            max_retries=self.max_retries,
        )

    def invoke(self, input: Any, config: Any | None = None) -> AIMessage:
        client = self._get_client()
        from google.genai import errors, types

        # 1. Convert LangChain tools to Gemini types.Tool
        gemini_tools = []
        if self.tools:
            function_declarations = []
            for t in self.tools:
                if isinstance(t, BaseTool):
                    schema = t.args_schema.model_json_schema() if t.args_schema else None
                    function_declarations.append(
                        types.FunctionDeclaration(
                            name=t.name,
                            description=t.description or "",
                            parameters=schema,
                        )
                    )
                elif callable(t) and hasattr(t, "__name__"):
                    function_declarations.append(
                        types.FunctionDeclaration(
                            name=t.__name__,
                            description=t.__doc__ or "",
                        )
                    )
            if function_declarations:
                gemini_tools.append(types.Tool(function_declarations=function_declarations))

        # 2. Convert messages to Gemini Content objects preserving thought signatures
        system_instruction: str | None = None
        contents: list[types.Content] = []

        if isinstance(input, str):
            raw_messages = [HumanMessage(content=input)]
        elif isinstance(input, list):
            raw_messages = [HumanMessage(content=m) if isinstance(m, str) else m for m in input]
        else:
            raw_messages = [HumanMessage(content=str(input))]
        for msg in raw_messages:
            if isinstance(msg, SystemMessage):
                if system_instruction is None:
                    system_instruction = str(msg.content)
                else:
                    system_instruction += "\n\n" + str(msg.content)

            elif isinstance(msg, HumanMessage):
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=str(msg.content))],
                    )
                )

            elif isinstance(msg, AIMessage):
                parts: list[types.Part] = []
                if msg.content:
                    parts.append(types.Part.from_text(text=str(msg.content)))

                signatures = (msg.additional_kwargs or {}).get("thought_signatures", {})
                tool_calls = getattr(msg, "tool_calls", []) or []

                for tc in tool_calls:
                    tc_id = tc.get("id") or tc.get("name")
                    sig = signatures.get(tc_id)
                    if sig:
                        # Re-attach genuine thought signature
                        parts.append(
                            types.Part(
                                function_call=types.FunctionCall(
                                    name=tc["name"],
                                    args=tc.get("args", {}),
                                    id=tc_id,
                                ),
                                thought_signature=sig,
                            )
                        )
                    else:
                        # If signature is missing, format as text context to avoid Gemini 400 error
                        parts.append(
                            types.Part.from_text(
                                text=f"[Action taken: {tc['name']} with arguments: {json.dumps(tc.get('args', {}))}]"
                            )
                        )

                if parts:
                    contents.append(types.Content(role="model", parts=parts))

            elif isinstance(msg, ToolMessage):
                # Gemini requires role="user" with function_response part
                tool_name = msg.name or "tool"
                result_str = str(msg.content)
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=tool_name,
                                response={"result": result_str},
                            )
                        ],
                    )
                )

        req_config = types.GenerateContentConfig(
            temperature=self.temperature,
            system_instruction=system_instruction,
            tools=gemini_tools if gemini_tools else None,
        )

        # 3. Execute with rate-limit retry and model candidate fallback
        model_candidates = [self.model] + [m for m in FALLBACK_MODELS if m != self.model]

        for current_model in model_candidates:
            for attempt in range(self.max_retries):
                try:
                    response = client.models.generate_content(
                        model=current_model,
                        contents=contents,
                        config=req_config,
                    )

                    # Extract tool calls and thought signatures
                    tool_calls_out: list[dict[str, Any]] = []
                    saved_signatures: dict[str, bytes] = {}
                    text_content = ""

                    cand = response.candidates[0] if response.candidates else None
                    if cand and cand.content and cand.content.parts:
                        for i, part in enumerate(cand.content.parts):
                            if part.text:
                                text_content += part.text
                            if part.function_call:
                                fc = part.function_call
                                call_id = getattr(fc, "id", None) or f"call_{fc.name}_{i}_{int(time.time())}"
                                tool_calls_out.append(
                                    {
                                        "name": fc.name,
                                        "args": dict(fc.args) if fc.args else {},
                                        "id": call_id,
                                    }
                                )
                                if part.thought_signature:
                                    saved_signatures[call_id] = part.thought_signature

                    return AIMessage(
                        content=text_content.strip(),
                        tool_calls=tool_calls_out,
                        additional_kwargs={"thought_signatures": saved_signatures},
                    )

                except errors.ClientError as err:
                    err_str = str(err)
                    if err.code == 429 or "RESOURCE_EXHAUSTED" in err_str:
                        delay = _extract_retry_delay(err_str)
                        if delay is None:
                            logger.warning(
                                "[RateLimit] Daily quota reached for %s. Falling back to next model...", current_model
                            )
                            print(
                                f"[*] Daily quota reached for {current_model}. Switching to alternative model...",
                                flush=True,
                            )
                            break
                        else:
                            logger.warning(
                                "[RateLimit] 429 received in Coder (%s). Pausing for %.1fs...", current_model, delay
                            )
                            print(
                                f"[*] Rate limit (429) on {current_model}. Waiting {delay:.1f}s before retry...",
                                flush=True,
                            )
                            time.sleep(delay)
                            continue
                    raise err
                except Exception as e:
                    if attempt == self.max_retries - 1:
                        logger.warning("Attempt %d failed on model %s: %s", attempt, current_model, e)
                    time.sleep(1.0)

        raise RuntimeError("Coder LLM invocation failed after maximum retries.")


def get_architect_llms(config: AppConfig | None = None) -> dict[str, Any]:
    """Provides consultant and planner models based on active runtime configuration."""
    cfg = config or get_config()

    if cfg.mode == "simulation":
        from tests.fakes import FakeArchitectStructured

        sim = FakeArchitectStructured()
        return {"consultant": sim, "planner": sim}

    elif cfg.mode == "gemini-free":
        api_key = cfg.gemini_api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required for 'gemini-free' mode.")

        consultant = GeminiArchitectAdapter(
            api_key=api_key,
            model=cfg.gemini_model,
            temperature=0.6,
        )
        planner = GeminiArchitectAdapter(
            api_key=api_key,
            model=cfg.gemini_model,
            temperature=0.2,
        )
        return {"consultant": consultant, "planner": planner}

    # Vertex AI legacy fallback
    from langchain_google_vertexai import ChatVertexAI

    project = cfg.gcp_project_id or os.getenv("GCP_PROJECT_ID")
    if not project:
        raise ValueError("GCP_PROJECT_ID is required for 'vertex' mode.")

    consultant_llm = ChatVertexAI(
        model_name="gemini-1.5-pro",
        location=cfg.gcp_location,
        project=project,
        temperature=0.6,
        max_output_tokens=8192,
    )
    planner_llm = ChatVertexAI(
        model_name="gemini-1.5-pro",
        location=cfg.gcp_location,
        project=project,
        temperature=0.2,
        max_output_tokens=8192,
    )
    return {"consultant": consultant_llm, "planner": planner_llm}


def get_coder_llm(config: AppConfig | None = None) -> Any:
    """Provides coder model bound to filesystem/system tools."""
    cfg = config or get_config()

    if cfg.mode == "simulation":
        from tests.fakes import FakeCoderLLM

        return FakeCoderLLM()

    elif cfg.mode == "gemini-free":
        api_key = cfg.gemini_api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required for 'gemini-free' mode.")

        return GeminiCoderAdapter(
            api_key=api_key,
            model=cfg.gemini_model,
            temperature=0.1,
        )

    from langchain_google_vertexai import ChatVertexAI

    project = cfg.gcp_project_id or os.getenv("GCP_PROJECT_ID")
    if not project:
        raise ValueError("GCP_PROJECT_ID is required for 'vertex' mode.")

    return ChatVertexAI(
        model_name="gemini-1.5-flash",
        location=cfg.gcp_location,
        project=project,
        temperature=0.1,
        max_output_tokens=8192,
    )
