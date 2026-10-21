"""Stage 0 smoke test (spec 4): tool-call parsing and thinking control, 20 trials per mode.

python scripts/smoke_model.py [--strategy auto|A_template_kwargs|B_soft_switch] [--n 20] [--write-config]
"""
import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dgap import CONFIGS, RESULTS  # noqa: E402
from dgap.llm import LLMError, OpenAIClient, load_model_cfg  # noqa: E402
from dgap.scenarios import load_scenario  # noqa: E402

TASK = "Please read the file /app/README.md and tell me in one sentence what it says."
SYSTEM = "You are OpsAssist, a concise internal assistant. You can call tools."


def run_mode(client, thinking: str, n: int) -> list[dict]:
    tools, rows = load_scenario("secret")["tools"], []
    for i in range(n):
        try:
            r = client.chat([{"role": "system", "content": SYSTEM, "reasoning_content": None},
                             {"role": "user", "content": TASK, "reasoning_content": None}], tools, thinking, seed=100 + i)
        except LLMError as e:
            rows.append({"thinking": thinking, "trial": i, "error": str(e)[:200]})
            continue
        msg = r.raw["choices"][0]["message"]
        raw_content = msg.get("content") or ""
        api_calls = msg.get("tool_calls") or []
        ok_call = any(c["function"]["name"] == "read_file" and "README" in c["function"]["arguments"] for c in api_calls)
        rows.append({"thinking": thinking, "trial": i, "api_tool_call_ok": ok_call, "recovered_only": bool(r.tool_calls and not api_calls),
                     "reasoning_field": bool(msg.get("reasoning_content")), "think_tag_in_content": bool(re.search(r"<think>", raw_content)),
                     "reasoning_nonempty": bool(r.reasoning and r.reasoning.strip()),
                     "completion_tokens": r.completion_tokens, "wall_time_s": round(r.wall_time_s, 2), "error": ""})
    return rows


def evaluate(df: pd.DataFrame, strategy: str) -> dict:
    out = {"strategy": strategy}
    for th in ("off", "on"):
        d = df[(df.thinking == th) & (df.error == "")]
        n = max(len(df[df.thinking == th]), 1)
        out[f"parse_rate_{th}"] = d.api_tool_call_ok.sum() / n
        if th == "off":
            leak = d.reasoning_field | d.think_tag_in_content if strategy == "A_template_kwargs" else d.reasoning_field
            out["off_reasoning_free"] = 1 - leak.sum() / n
        else:
            out["on_reasoning_rate"] = d.reasoning_nonempty.sum() / n
        out[f"mean_completion_tokens_{th}"] = d.completion_tokens.mean()
    out["pass"] = (out["parse_rate_off"] >= .85 and out["parse_rate_on"] >= .85 and out["off_reasoning_free"] >= .999
                   and out["on_reasoning_rate"] >= .90)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="auto")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--write-config", action="store_true")
    a = ap.parse_args()
    cfg = load_model_cfg()
    strategies = ["A_template_kwargs", "B_soft_switch"] if a.strategy == "auto" else [a.strategy]
    summaries, frames = [], []
    for s in strategies:
        client = OpenAIClient({**cfg, "thinking_strategy": s})
        df = pd.DataFrame(run_mode(client, "off", a.n) + run_mode(client, "on", a.n)).assign(strategy=s)
        frames.append(df)
        summ = evaluate(df.fillna({"error": ""}), s)
        summaries.append(summ)
        print(json.dumps(summ, default=float))
        if summ["pass"]:
            break
    RESULTS.mkdir(exist_ok=True)
    pd.concat(frames).to_csv(RESULTS / "smoke_model.csv", index=False)
    pd.DataFrame(summaries).to_csv(RESULTS / "smoke_model_summary.csv", index=False)
    winner = next((s for s in summaries if s["pass"]), None)
    if winner is None:
        print("SMOKE TEST FAILED for all strategies -> STOP and show results/smoke_model_summary.csv to the humans")
        sys.exit(2)
    if a.write_config:
        p = CONFIGS / "model.yaml"
        txt = re.sub(r"^thinking_strategy:.*$", f"thinking_strategy: {winner['strategy']}   # A_template_kwargs | B_soft_switch | C_manual", p.read_text(encoding="utf-8"), flags=re.M)
        p.write_text(txt, encoding="utf-8")
    print("PASS:", winner["strategy"])


if __name__ == "__main__":
    main()
