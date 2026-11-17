"""frozen-v3 driver (PREREG.md "Addendum v3"). Writes everything to run_id `v3`; the `main` data are read-only here.

python -m dgap.v3 all                       # everything below, in order (resumable)
python -m dgap.v3 branches --source main    # P2s, P2o, P3s, P5 on eligible main episodes
python -m dgap.v3 p4b --source main         # P4b on informed violations + benign/nearmiss controls
python -m dgap.v3 episodes                  # configs/grid_v3.yaml (near-miss controls, secret M0 extension) + frozen-v2 branches
Eligible episodes: status ok, thinking off, kpi none; informed violations (M0) and controls (benign, resisted, nearmiss).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml
from tqdm import tqdm

from . import CONFIGS, DATA
from .branches_v3 import V3_PROTOCOLS, run_branch_v3, run_p4b
from .freeze import verify_lock
from .llm import OpenAIClient, load_model_cfg
from .runner import HaltRun, Runner, Store

RUN = "v3"


def eligible(ep: dict) -> bool:
    c = ep["config"]
    if ep["status"] != "ok" or c["thinking"] != "off" or c["kpi"] != "none":
        return False
    if ep["violation"]["informed"]:
        return c["task_variant"] == "tempting" and c["pressure"] == "escalation"
    return ep["control_type"] in ("benign", "nearmiss") or (ep["control_type"] == "resisted" and c["pressure"] == "escalation")


class _Streak:
    def __init__(self):
        self.n = 0

    def note(self, failed: bool):
        self.n = self.n + 1 if failed else 0
        if self.n >= 5:
            raise HaltRun("5 consecutive API failures; state flushed")


def run_branches(llm, source: Store, out: Store, quiet=False):
    eps = [e for e in source.all_episodes() if eligible(e)]
    streak = _Streak()
    for ep in tqdm(eps, desc=f"v3 branches on {source.run_id}", disable=quiet):
        for proto in V3_PROTOCOLS:
            if (ep["episode_id"], proto, "none", None) in out.branch_keys:
                continue
            b = run_branch_v3(llm, ep, proto)
            streak.note(b is None)
            if b is not None:
                out.add_branch(b)


def run_p4b_stage(llm, source: Store, out: Store, quiet=False):
    eps = [e for e in source.all_episodes() if eligible(e) and (e["violation"]["informed"] or e["control_type"] in ("benign", "nearmiss"))]
    p0 = {b["episode_id"]: b for b in source.all_branches() if b["protocol"] == "P0" and b["request"] == "none"}
    streak = _Streak()
    for ep in tqdm(eps, desc=f"P4b on {source.run_id}", disable=quiet):
        if (ep["episode_id"], "P4b", "none", 1) in out.branch_keys or ep["episode_id"] not in p0:
            continue
        bs = run_p4b(llm, ep, p0[ep["episode_id"]])
        streak.note(len(bs) == 0)
        for b in bs:
            out.add_branch(b)


def run_episodes(llm, out: Store, model_cfg: dict, grid_path: Path):
    grid = yaml.safe_load(open(grid_path, encoding="utf-8"))
    assert grid["run_id"] == RUN, "grid_v3 must write to run_id v3"
    Runner(grid, llm, out, model_cfg, workers=1).run()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["all", "branches", "p4b", "episodes"])
    ap.add_argument("--source", default="main", choices=["main", "v3"])
    ap.add_argument("--data-dir", default=str(DATA))
    ap.add_argument("--grid", default=str(CONFIGS / "grid_v3.yaml"))
    ap.add_argument("--dry-run", action="store_true", help="scripted fake LLM; use with a temporary --data-dir")
    a = ap.parse_args(argv)
    if not a.dry_run:
        problems = verify_lock()
        if problems or "configs/protocols_v3.yaml" not in open(CONFIGS / "frozen.lock", encoding="utf-8").read():
            raise SystemExit("REFUSING to run v3: frozen-v3 lock missing or not matching:\n  " + "\n  ".join(problems))
    model_cfg = load_model_cfg()
    if a.dry_run:
        from .fake import PolicyLLM
        llm = PolicyLLM(seed=1)
    else:
        llm = OpenAIClient(model_cfg)
    d = Path(a.data_dir)
    out = Store(d, RUN)
    if a.stage == "all":
        main_store = Store(d, "main")
        run_branches(llm, main_store, out)
        run_p4b_stage(llm, main_store, out)
        run_episodes(llm, out, model_cfg, Path(a.grid))
        out = Store(d, RUN)  # reload (episodes + frozen-v2 branches just written)
        run_branches(llm, out, out)
        run_p4b_stage(llm, out, out)
        return
    src = Store(d, a.source) if a.source != RUN else out
    if a.stage == "branches":
        run_branches(llm, src, out)
    elif a.stage == "p4b":
        run_p4b_stage(llm, src, out)
    else:
        run_episodes(llm, out, model_cfg, Path(a.grid))


if __name__ == "__main__":
    main()
