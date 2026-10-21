"""Episode loop (spec 5.2, 10): system prompt + task + scripted pressure, tools run in the sandbox."""
from __future__ import annotations

import hashlib
import json
import random
import time
import uuid

from .detectors import SandboxInconsistency, detect_violation
from .llm import LLMError
from .sandbox import Sandbox
from .scenarios import (build_system_prompt, load_scenario, make_canary, preset_messages, resolve_preset,
                        user_message)

MAX_ROUNDS = 10


def config_hash(cfg: dict, model_cfg: dict | None = None) -> str:
    blob = json.dumps({"cfg": cfg, "model": {k: (model_cfg or {}).get(k) for k in ("model_id", "thinking_strategy", "sampling")}},
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def normalize_cfg(cfg: dict) -> dict:
    """Fill defaults and resolve the pressure preset (calibrated choice or explicit esc_*)."""
    c = {"pressure": "none", "pressure_preset": None, "kpi": "none", **cfg}
    if c["task_variant"] == "benign":
        c["pressure"] = "none"
    c["pressure_preset"] = resolve_preset(c["scenario"], c["pressure_preset"]) if c["pressure"] == "escalation" else None
    return c


class _Usage:
    def __init__(self):
        self.prompt_tokens = self.completion_tokens = 0
        self.wall_time_s = 0.0

    def add(self, r):
        self.prompt_tokens += r.prompt_tokens
        self.completion_tokens += r.completion_tokens
        self.wall_time_s += r.wall_time_s

    def to_dict(self):
        return {"prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
                "wall_time_s": round(self.wall_time_s, 3)}


def agent_turn(llm, messages: list[dict], sb: Sandbox, tools: list[dict], thinking: str, seed: int,
               usage: _Usage, turn_index: int, max_rounds: int = MAX_ROUNDS) -> str:
    """One user turn: loop of assistant responses / tool executions. Returns the end reason."""
    for _ in range(max_rounds):
        try:
            r = llm.chat(messages, tools, thinking, seed=seed)
        except LLMError:
            return "api_error"
        usage.add(r)
        asst = {"role": "assistant", "content": r.content, "reasoning_content": r.reasoning, "tool_calls": [],
                "tool_call_id": None, "finish_reason": r.finish_reason}
        if r.tool_call_in_reasoning_only or r.tool_call_parse_failed:
            messages.append(asst)
            return "parse_error"
        if not r.tool_calls:
            messages.append(asst)
            return "truncated" if r.finish_reason == "length" else "final_text"
        msg_index, tool_msgs = len(messages), []
        for tc in r.tool_calls:
            call_id, result = sb.execute(tc.name, tc.arguments, turn_index, msg_index, tc.recovered)
            asst["tool_calls"].append({"id": call_id, "type": "function",
                                       "function": {"name": tc.name, "arguments": tc.arguments}})
            tool_msgs.append({"role": "tool", "content": result, "reasoning_content": None, "tool_calls": [],
                              "tool_call_id": call_id})
        messages.append(asst)
        messages.extend(tool_msgs)
    return "max_steps"


def run_episode(cfg: dict, seed: int, llm, run_id: str, meta: dict | None = None) -> dict:
    cfg = normalize_cfg(cfg)
    rng = random.Random(seed)
    scen = cfg["scenario"]
    canary = make_canary(rng) if scen == "secret" else None
    sb = Sandbox(scen, canary)
    tools = load_scenario(scen)["tools"]
    messages = [{"role": "system", "content": build_system_prompt(scen, cfg["kpi"]), "reasoning_content": None, "tool_calls": [], "tool_call_id": None},
                {"role": "user", "content": user_message(scen, cfg["task_variant"]), "reasoning_content": None, "tool_calls": [], "tool_call_id": None}]
    pressure = (preset_messages(scen, cfg["pressure_preset"])
                if cfg["task_variant"] == "tempting" and cfg["pressure"] == "escalation" else [])
    usage, turn = _Usage(), 1
    while True:
        reason = agent_turn(llm, messages, sb, tools, cfg["thinking"], seed, usage, turn)
        viol = detect_violation(scen, messages, sb.tool_log, canary)
        if viol.sandbox_inconsistency:
            raise SandboxInconsistency(f"canary leaked without read_file (seed={seed}, run={run_id})")
        if reason != "final_text" or viol.occurred or not pressure:
            break
        messages.append({"role": "user", "content": pressure.pop(0), "reasoning_content": None, "tool_calls": [], "tool_call_id": None})
        turn += 1
    if reason == "parse_error":
        status = "excluded_parse_error"
    elif reason == "final_text" or viol.occurred:
        status = "ok"
    else:
        status = "excluded_other"
    control = None if viol.occurred else ("benign" if cfg["task_variant"] == "benign" else "resisted")
    return {"episode_id": str(uuid.uuid4()), "run_id": run_id, "seed": seed, "config": cfg, "canary": canary,
            "messages": messages, "tool_log": sb.tool_log, "violation": viol.to_dict(), "end_reason": reason,
            "status": status, "control_type": control, "usage": usage.to_dict(), "wall_time_ts": time.time(),
            "meta": dict(meta or {})}
