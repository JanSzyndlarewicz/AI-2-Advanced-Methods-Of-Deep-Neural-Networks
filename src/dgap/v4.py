"""frozen-v4 driver: act-by-act audit P6 (PREREG.md "Addendum v4"). Reads main + v3 episodes, writes branches to run_id `v4`.

python -m dgap.v4            # resumable
"""
from __future__ import annotations

import argparse
from pathlib import Path

from tqdm import tqdm

from . import CONFIGS, DATA
from .branches_v4 import list_acts, run_p6_act
from .freeze import verify_lock
from .llm import OpenAIClient, load_model_cfg
from .runner import HaltRun, Store
from .v3 import eligible

RUN = "v4"


def run_p6(llm, sources: list[Store], out: Store, quiet: bool = False):
    eps = [e for s in sources for e in s.all_episodes() if eligible(e)]
    streak = 0
    for ep in tqdm(eps, desc="P6 act-by-act", disable=quiet):
        for act in list_acts(ep):
            if (ep["episode_id"], "P6", "none", act["act_index"]) in out.branch_keys:
                continue
            b = run_p6_act(llm, ep, act)
            streak = streak + 1 if b is None else 0
            if streak >= 5:
                raise HaltRun("5 consecutive API failures; state flushed")
            if b is not None:
                out.add_branch(b)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(DATA))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if not a.dry_run:
        problems = verify_lock()
        if problems or "src/dgap/branches_v4.py" not in open(CONFIGS / "frozen.lock", encoding="utf-8").read():
            raise SystemExit("REFUSING to run v4: frozen-v4 lock missing or not matching:\n  " + "\n  ".join(problems))
    if a.dry_run:
        from .fake import PolicyLLM
        llm = PolicyLLM(seed=1)
    else:
        llm = OpenAIClient(load_model_cfg())
    d = Path(a.data_dir)
    run_p6(llm, [Store(d, "main"), Store(d, "v3")], Store(d, RUN))


if __name__ == "__main__":
    main()
