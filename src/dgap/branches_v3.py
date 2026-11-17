"""frozen-v3 protocols (PREREG.md "Addendum v3"): P2s, P2o, P3s, P5, P4b. Frozen-v2 protocols live in branches.py, unchanged.

All new YES/NO protocols are parsed with the frozen `parse_p3` (JSON key "violated"); P4b with the frozen `parse_p4_answer`.
Branches never mutate the episode (copies of the message list, as in branches.py).
"""
from __future__ import annotations

from .branches import _record, build_transcript
from .detectors import contains_canary, parse_p3, parse_p4_answer
from .llm import LLMError
from .scenarios import load_protocols_v3, load_scenario

V3_PROTOCOLS = ("P2s", "P2o", "P3s", "P5")


def _visible(messages: list[dict]):
    """(kind, text) for every visible assistant action, in order: messages and tool calls (same rendering as P3)."""
    out = []
    for m in messages:
        if m["role"] != "assistant":
            continue
        if (m.get("content") or "").strip():
            out.append(("message", f"ASSISTANT MESSAGE: {m['content']}"))
        for tc in m.get("tool_calls") or []:
            out.append(("call", f"ASSISTANT TOOL CALL {tc['id']}: {tc['function']['name']}({tc['function']['arguments']})", tc["function"]["name"]))
    return out


def select_act(ep: dict) -> str:
    """The one action quoted in P5 (deterministic).
    Violation episodes: S1 the first assistant message containing the canary; S2 the first export_customer_data call.
    Control episodes (same rule shape, so the act is the closest comparable one): S1 the last visible assistant message;
    S2 the last assistant tool call if any, else the last visible assistant message."""
    scen, acts = ep["config"]["scenario"], _visible(ep["messages"])
    if scen == "secret":
        msgs = [a for a in acts if a[0] == "message"]
        if ep["violation"]["occurred"]:
            for a in msgs:
                if contains_canary(a[1], ep["canary"]):
                    return a[1]
        return msgs[-1][1] if msgs else "(no visible message)"
    calls = [a for a in acts if a[0] == "call"]
    if ep["violation"]["occurred"]:
        for a in calls:
            if a[2] == "export_customer_data":
                return a[1]
    if calls:
        return calls[-1][1]
    msgs = [a for a in acts if a[0] == "message"]
    return msgs[-1][1] if msgs else "(no visible action)"


def build_v3_messages(ep: dict, protocol: str) -> tuple[list[dict], str]:
    p, scen = load_protocols_v3(), ep["config"]["scenario"]
    rule = load_scenario(scen)["rule_line"]
    if protocol == "P3s":
        prompt = p["P3s_user"].replace("{RULES}", rule).replace("{TRANSCRIPT}", build_transcript(ep["messages"]))
        return [{"role": "system", "content": p["P3s_system"]}, {"role": "user", "content": prompt}], prompt
    if protocol in ("P2s", "P2o"):
        prompt = p[protocol]
    elif protocol == "P5":
        prompt = p["P5"].replace("{ACT}", select_act(ep)).replace("{RULES}", rule)
    else:
        raise ValueError(protocol)
    return [dict(m) for m in ep["messages"]] + [{"role": "user", "content": prompt}], prompt


def run_branch_v3(llm, ep: dict, protocol: str) -> dict | None:
    msgs, prompt = build_v3_messages(ep, protocol)
    try:
        r = llm.chat(msgs, None, ep["config"]["thinking"], seed=ep["seed"])
    except LLMError:
        return None
    return _record(ep, protocol, "none", prompt, r, parse_p3(r.content))


def run_p4b(llm, ep: dict, p0_branch: dict) -> list[dict]:
    """As branches.run_p4, with the fixed k=2 wording; all 5 answers recorded."""
    thinking = ep["config"]["thinking"]
    msgs = [dict(m) for m in ep["messages"]] + [
        {"role": "user", "content": p0_branch["prompt"]},
        {"role": "assistant", "content": p0_branch["response"]}]
    out = []
    for k, q in enumerate(load_protocols_v3()["P4b"], start=1):
        msgs.append({"role": "user", "content": q})
        try:
            r = llm.chat(msgs, None, thinking, seed=ep["seed"])
        except LLMError:
            break
        ans = parse_p4_answer(r.content)
        out.append(_record(ep, "P4b", "none", q, r, {"answer": ans, "disclosed": ans == "YES", "format_error": ans == "unparsed"}, k=k))
        msgs.append({"role": "assistant", "content": r.content})
    return out
