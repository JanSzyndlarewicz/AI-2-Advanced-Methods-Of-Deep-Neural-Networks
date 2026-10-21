"""Reporting protocols P0-P4, C and the branching mechanism (spec 7). Branches never mutate the episode."""
from __future__ import annotations

import json
import uuid

from .detectors import parse_c, parse_p1, parse_p2, parse_p3, parse_p4_answer
from .llm import LLMError
from .scenarios import load_protocols, load_scenario, request_suffix

# branch order per episode (spec 10): P0, P1, P2, C for request none/request; P3 only none -> 9 branches
BRANCH_PLAN = [(p, r) for r in ("none", "request") for p in ("P0", "P1", "P2", "C")] + [("P3", "none")]


def build_prompt(protocol: str, scenario: str, request: str) -> str:
    tpl = load_protocols()[protocol]
    suffix = "" if protocol == "P3" else request_suffix(request)
    return (tpl.replace("{SCENARIO_Q2}", load_scenario(scenario)["q2"]).replace("{suffix}", suffix))


def build_transcript(messages: list[dict]) -> str:
    """Numbered visible transcript for the P3 auditor (no system prompt, no reasoning)."""
    lines, n = [], 0

    def add(s):
        nonlocal n
        n += 1
        lines.append(f"[{n}] {s}")

    for m in messages:
        if m["role"] == "user":
            add(f"USER: {m['content']}")
        elif m["role"] == "assistant":
            if (m.get("content") or "").strip():
                add(f"ASSISTANT: {m['content']}")
            for tc in m.get("tool_calls") or []:
                add(f"ASSISTANT TOOL CALL {tc['id']}: {tc['function']['name']}({tc['function']['arguments']})")
        elif m["role"] == "tool":
            body = m["content"].split("] ", 1)[-1] if m["content"].startswith("[") else m["content"]
            add(f"TOOL RESULT {m['tool_call_id']}: {body}")
    return "\n".join(lines)


def _record(ep, protocol, request, prompt, r, parsed, k=None):
    return {"branch_id": str(uuid.uuid4()), "episode_id": ep["episode_id"], "protocol": protocol, "request": request, "k": k,
            "prompt": prompt, "response": r.content, "reasoning_content": r.reasoning, "parsed": parsed,
            "labels": {"disclosed": parsed.pop("disclosed", None), "format_error": parsed.pop("format_error", False),
                       "tool_call_in_branch": bool(r.tool_calls)},
            "usage": {"prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens,
                      "total_tokens": r.prompt_tokens + r.completion_tokens, "wall_time_s": round(r.wall_time_s, 3)}}


def _labels(protocol, text, ep) -> dict:
    scen = ep["config"]["scenario"]
    if protocol == "P0":
        return {"disclosed": None}  # needs judge / human label (spec 8.3)
    if protocol == "P1":
        return parse_p1(text, scen, ep["tool_log"], ep["canary"])
    if protocol == "P2":
        return parse_p2(text)
    if protocol == "C":
        return parse_c(text, scen)
    if protocol == "P3":
        return parse_p3(text)
    raise ValueError(protocol)


def run_branch(llm, ep: dict, protocol: str, request: str = "none") -> dict | None:
    """Run one protocol on a copy of the episode's final state. Returns None on API failure."""
    scen, thinking = ep["config"]["scenario"], ep["config"]["thinking"]
    if protocol == "P3":
        proto = load_protocols()
        prompt = proto["P3_user"].replace("{RULES}", load_scenario(scen)["rule_line"]).replace(
            "{TRANSCRIPT}", build_transcript(ep["messages"]))
        msgs = [{"role": "system", "content": proto["P3_system"]}, {"role": "user", "content": prompt}]
    else:
        prompt = build_prompt(protocol, scen, request)
        msgs = [dict(m) for m in ep["messages"]] + [{"role": "user", "content": prompt}]
    try:
        r = llm.chat(msgs, None, thinking, seed=ep["seed"])
    except LLMError:
        return None
    return _record(ep, protocol, request, prompt, r, _labels(protocol, r.content, ep))


def run_p4(llm, ep: dict, p0_branch: dict) -> list[dict]:
    """Repeated questioning (k=1..5) continuing the P0 branch conversation; all 5 answers are always recorded."""
    thinking = ep["config"]["thinking"]
    msgs = [dict(m) for m in ep["messages"]] + [
        {"role": "user", "content": p0_branch["prompt"]},
        {"role": "assistant", "content": p0_branch["response"]}]
    out = []
    for k, q in enumerate(load_protocols()["P4"], start=1):
        msgs.append({"role": "user", "content": q})
        try:
            r = llm.chat(msgs, None, thinking, seed=ep["seed"])
        except LLMError:
            break
        ans = parse_p4_answer(r.content)
        out.append(_record(ep, "P4", "none", q, r, {"answer": ans, "disclosed": ans == "YES", "format_error": ans == "unparsed"}, k=k))
        msgs.append({"role": "assistant", "content": r.content})
    return out


def history_hash(messages: list[dict]) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(messages, sort_keys=True, default=str).encode()).hexdigest()
