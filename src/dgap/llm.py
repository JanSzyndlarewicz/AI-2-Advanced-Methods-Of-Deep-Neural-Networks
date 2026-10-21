"""LLM client: OpenAI-compatible (LM Studio) calls, thinking control, tool-call parsing."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import yaml
from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from . import CONFIGS

SOFT_SWITCH = {"on": " /think", "off": " /no_think"}
_TOOL_BLOCK = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S)


class LLMError(RuntimeError):
    """API failure after retries (episode gets end_reason=api_error)."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string
    recovered: bool = False


@dataclass
class ChatResult:
    content: str = ""
    reasoning: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    wall_time_s: float = 0.0
    tool_call_in_reasoning_only: bool = False
    tool_call_parse_failed: bool = False
    raw: Any = None


class LLM(Protocol):
    model_id: str

    def chat(self, messages: list[dict], tools: list[dict] | None, thinking: str,
             seed: int | None = None, judge: bool = False) -> ChatResult: ...


def load_model_cfg(path=None) -> dict:
    return yaml.safe_load(open(path or CONFIGS / "model.yaml", encoding="utf-8"))


def split_think(content: str) -> tuple[str, str | None]:
    """Separate <think>...</think> from visible content (Qwen3 may emit only the closing tag)."""
    if "</think>" not in content:
        if "<think>" in content:  # unterminated reasoning (truncated)
            head, _, tail = content.partition("<think>")
            return head.strip(), tail.strip()
        return content, None
    reasoning, _, visible = content.rpartition("</think>")
    reasoning = reasoning.replace("<think>", "").strip()
    return visible.strip(), reasoning


def parse_fallback_tool_calls(content: str) -> tuple[list[ToolCall], bool]:
    """Recover <tool_call>{json}</tool_call> blocks from content. Returns (calls, parse_failed)."""
    calls, failed = [], False
    for block in _TOOL_BLOCK.findall(content or ""):
        try:
            obj = json.loads(block)
            args = obj.get("arguments", {})
            calls.append(ToolCall("", obj["name"], args if isinstance(args, str) else json.dumps(args),
                                  recovered=True))
        except Exception:
            failed = True
    return calls, failed


def to_wire_messages(messages: list[dict], thinking: str, strategy: str) -> list[dict]:
    """Strip reasoning from history (Qwen3 convention) and apply the soft switch to EVERY user turn."""
    out = []
    for m in messages:
        w = {k: m[k] for k in ("role", "content", "tool_calls", "tool_call_id") if m.get(k)}
        w["role"] = m["role"]
        w.setdefault("content", "")
        if m["role"] == "user" and strategy == "B_soft_switch":
            w["content"] = m["content"] + SOFT_SWITCH[thinking]
        out.append(w)
    return out


class OpenAIClient:
    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or load_model_cfg()
        self.model_id = self.cfg["model_id"]
        self.strategy = self.cfg["thinking_strategy"]
        self.client = OpenAI(base_url=self.cfg["base_url"], api_key=self.cfg.get("api_key", "x"),
                             timeout=600, max_retries=0)

    def _request(self, **kw):
        @retry(stop=stop_after_attempt(3), wait=wait_fixed(2), reraise=True,
               retry=retry_if_exception_type((APIConnectionError, APITimeoutError, InternalServerError)))
        def go():
            return self.client.chat.completions.create(**kw)
        return go()

    def chat(self, messages, tools, thinking, seed=None, judge=False) -> ChatResult:
        s = dict(self.cfg["judge"] if judge else self.cfg["sampling"][thinking])
        extra = {"top_k": s.pop("top_k")}
        if "min_p" in s:
            extra["min_p"] = s.pop("min_p")
        if self.strategy == "A_template_kwargs":
            extra["chat_template_kwargs"] = {"enable_thinking": thinking == "on"}
        kw = dict(model=self.model_id, messages=to_wire_messages(messages, thinking, self.strategy),
                  extra_body=extra, **s)
        if seed is not None:
            kw["seed"] = seed
        if tools:
            kw["tools"] = tools
        t0 = time.time()
        try:
            resp = self._request(**kw)
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"{type(e).__name__}: {e}") from e
        wall = time.time() - t0
        ch = resp.choices[0]
        msg = ch.message
        content = msg.content or ""
        reasoning = getattr(msg, "reasoning_content", None) or (msg.model_extra or {}).get("reasoning_content")
        content, think = split_think(content)
        reasoning = reasoning or think
        calls = [ToolCall("", tc.function.name, tc.function.arguments or "{}") for tc in (msg.tool_calls or [])]
        failed = False
        if not calls and "<tool_call>" in content:
            calls, failed = parse_fallback_tool_calls(content)
        in_reasoning_only = bool(not calls and not failed and reasoning and "<tool_call>" in reasoning)
        u = resp.usage
        return ChatResult(content=content, reasoning=reasoning, tool_calls=calls,
                          finish_reason=ch.finish_reason or "stop",
                          prompt_tokens=getattr(u, "prompt_tokens", 0), completion_tokens=getattr(u, "completion_tokens", 0),
                          wall_time_s=wall, tool_call_in_reasoning_only=in_reasoning_only,
                          tool_call_parse_failed=failed, raw=resp.model_dump(mode="json"))
