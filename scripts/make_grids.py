"""Generate configs/grid_{pilot,calib,main}.yaml (spec 11, 12.2). Deterministic; rerun is a no-op."""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCEN = ("secret", "forbidden_tool")
ESC_ADAPTIVE = {"batch": 20, "target_informed": 50, "max": 120}


def dump(name, grid):
    (ROOT / "configs" / name).write_text(yaml.safe_dump(grid, sort_keys=False, default_flow_style=None, width=140), encoding="utf-8")


def pilot():
    cells = [{"scenario": "secret", "task_variant": "tempting", "thinking": th, "pressure": pr,
              **({"pressure_preset": "esc_mid"} if pr == "escalation" else {}), "kpi": "none", "n": 10}
             for th in ("off", "on") for pr in ("none", "escalation")]
    cells.append({"scenario": "secret", "task_variant": "benign", "thinking": "off", "kpi": "none", "n": 10})
    return {"run_id": "pilot", "seed_start": 8000, "seed_stride": 10, "branches": [[p, "none"] for p in ("P0", "P1", "P2", "P3", "C")], "cells": cells}


def calib():
    cells = [{"scenario": s, "task_variant": "tempting", "thinking": "off", "pressure": "escalation", "pressure_preset": p, "kpi": "none", "n": 20}
             for s in SCEN for p in ("esc_weak", "esc_mid", "esc_strong")]
    # violation rate only needs the episode itself; branches are skipped to save GPU time (DECISIONS.md)
    return {"run_id": "calib", "seed_start": 9000, "seed_stride": 0, "branches": [], "cells": cells}


LITE_BRANCHES = [[p, "none"] for p in ("P0", "P1", "P2", "P3", "C")]
# frozen-v2 budget profile (PREREG.md "Budget revision"): thinking=off core + small thinking=on probe.
# Cell order (hence seeds idx*stride+i and resume keys) is unchanged; disabled cells get n=0 / max=0.
LITE = {  # (scenario, thinking, kpi, kind) -> setting; anything missing is disabled
    ("secret", "off", "none", "none"): {"n": 40},
    ("secret", "off", "none", "escalation"): {"adaptive": {"batch": 20, "target_informed": 50, "max": 120}},
    ("secret", "off", "none", "benign"): {"n": 40},
    ("secret", "on", "none", "escalation"): {"adaptive": {"batch": 12, "target_informed": 50, "max": 12}},
    ("forbidden_tool", "off", "none", "none"): {"n": 20},
    ("forbidden_tool", "off", "none", "escalation"): {"adaptive": {"batch": 20, "target_informed": 40, "max": 60}},
    ("forbidden_tool", "off", "none", "benign"): {"n": 40},
    ("forbidden_tool", "on", "none", "escalation"): {"adaptive": {"batch": 12, "target_informed": 50, "max": 12}},
}


def main_grid(lite: bool = True):
    cells = []
    for s in SCEN:
        for th in ("off", "on"):
            for kpi in ("none", "kpi"):
                for kind in ("none", "escalation", "benign"):
                    base = {"scenario": s, "task_variant": "benign" if kind == "benign" else "tempting", "thinking": th}
                    if kind != "benign":
                        base["pressure"] = kind
                    base["kpi"] = kpi
                    if lite:
                        cells.append({**base, **LITE.get((s, th, kpi, kind), {"n": 0})})
                    else:
                        cells.append({**base, **({"adaptive": ESC_ADAPTIVE} if kind == "escalation" else {"n": 40})})
    grid = {"run_id": "main", "seed_start": 0, "seed_stride": 200}
    if lite:
        grid["branches"] = LITE_BRANCHES
    return {**grid, "cells": cells}  # non-lite: default branch plan = 9 branches


if __name__ == "__main__":
    for n, g in (("grid_pilot.yaml", pilot()), ("grid_calib.yaml", calib()), ("grid_main.yaml", main_grid())):
        dump(n, g)
        print("wrote", n, len(g["cells"]), "cells")
