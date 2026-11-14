"""frozen-v5 driver (PREREG.md "Addendum v5"): new scenarios S3/S4 with paraphrases, second model Qwen3-4B.

python -m dgap.v5 --model qwen3-8b      # needs the matching model loaded on the server (model_id is checked)
python -m dgap.v5 --model qwen3-4b
Each episode is followed immediately by all its branches (P0, P1, P2, C, P3, P2s, P2o, P3s, P6 per act). Resumable.
S1/S2 episodes use the frozen-v2 episode loop and presets unchanged; S3/S4 use scenarios_v5.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml
from tqdm import tqdm

from . import CONFIGS, DATA, ROOT
from .branches import run_branch
from .branches_v3 import run_branch_v3
from .branches_v4 import list_acts, run_p6_act
from .episode import config_hash, normalize_cfg, run_episode
from .freeze import verify_lock
from .llm import OpenAIClient, load_model_cfg
from .runner import HaltRun, Store, git_commit
from .scenarios_v5 import V5_SCENARIOS, list_acts_v5, run_episode_v5

RUN = "v5"


def acts_for(ep: dict) -> list[dict]:
    return list_acts_v5(ep) if ep["config"]["scenario"] in V5_SCENARIOS else list_acts(ep)


class _Streak:
    def __init__(self):
        self.n = 0

    def note(self, failed: bool):
        self.n = self.n + 1 if failed else 0
        if self.n >= 5:
            raise HaltRun("5 consecutive API failures; state flushed")


def run_branches(llm, ep: dict, plan: list[str], store: Store, streak: _Streak):
    if ep["status"] != "ok":
        return
    for p in plan:
        if p == "P6":
            for act in acts_for(ep):
                if (ep["episode_id"], "P6", "none", act["act_index"]) in store.branch_keys:
                    continue
                b = run_p6_act(llm, ep, act)
                streak.note(b is None)
                if b is not None:
                    b["act"]["contributes"] = act.get("contributes", act["is_violating_act"])
                    store.add_branch(b)
            continue
        if (ep["episode_id"], p, "none", None) in store.branch_keys:
            continue
        b = run_branch_v3(llm, ep, p) if p in ("P2s", "P2o", "P3s") else run_branch(llm, ep, p, "none")
        streak.note(b is None)
        if b is not None:
            store.add_branch(b)


def run_model(grid: dict, model: dict, llm, model_cfg: dict, store: Store, quiet: bool = False):
    commit, streak = git_commit(), _Streak()
    for idx, cell in enumerate(model["cells"]):
        cfg = {k: v for k, v in cell.items() if k != "n"}
        cfg.update({"thinking": "off", "kpi": "none"})
        scen = cfg["scenario"]
        base = grid["seed_start"] + model["model_offset"] + idx * grid["seed_stride"]
        desc = f"{model['name']}:{scen}/{cfg['task_variant']}"
        for i in tqdm(range(cell["n"]), desc=desc, disable=quiet):
            seed = base + i
            ncfg = dict(cfg) if scen in V5_SCENARIOS else normalize_cfg(cfg)
            if scen in V5_SCENARIOS:
                ncfg = {"pressure": "none", "pressure_preset": None, **ncfg}
                if ncfg["task_variant"] != "tempting":
                    ncfg["pressure"] = "none"
                ncfg["pressure_preset"] = "v5_single" if ncfg["pressure"] == "escalation" else None
                ncfg["para"] = seed % 3
            key = (config_hash(ncfg, model_cfg), seed)
            ep = store.episodes.get(key)
            if ep is None:
                meta = {"config_hash": key[0], "git_commit": commit, "model_id": model_cfg["model_id"],
                        "lmstudio_version": model_cfg.get("lmstudio_version"), "thinking_strategy": model_cfg["thinking_strategy"],
                        "model_name": model["name"]}
                ep = (run_episode_v5 if scen in V5_SCENARIOS else run_episode)(cfg, seed, llm, RUN, meta)
                store.add_episode(ep)
            streak.note(ep["end_reason"] == "api_error")
            run_branches(llm, ep, grid["branches"], store, streak)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--grid", default=str(CONFIGS / "grid_v5.yaml"))
    ap.add_argument("--data-dir", default=str(DATA))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-per-cell", type=int, default=None, help="dry runs only")
    a = ap.parse_args(argv)
    grid = yaml.safe_load(open(a.grid, encoding="utf-8"))
    model = next(m for m in grid["models"] if m["name"] == a.model)
    if a.max_per_cell:
        model = {**model, "cells": [{**c, "n": min(c["n"], a.max_per_cell)} for c in model["cells"]]}
    model_cfg = load_model_cfg(ROOT / model["model_cfg"])
    if a.dry_run:
        from .fake import PolicyLLM
        llm = PolicyLLM(seed=1)
    else:
        problems = verify_lock()
        if problems or "src/dgap/scenarios_v5.py" not in open(CONFIGS / "frozen.lock", encoding="utf-8").read():
            raise SystemExit("REFUSING to run v5: frozen-v5 lock missing or not matching:\n  " + "\n  ".join(problems))
        llm = OpenAIClient(model_cfg)
        served = [m["id"] for m in llm.client.models.list().data] if hasattr(llm, "client") else []
        if served and model_cfg["model_id"] not in served:
            raise SystemExit(f"server serves {served}, expected {model_cfg['model_id']}")
    run_model(grid, model, llm, model_cfg, Store(Path(a.data_dir), RUN))


if __name__ == "__main__":
    main()
