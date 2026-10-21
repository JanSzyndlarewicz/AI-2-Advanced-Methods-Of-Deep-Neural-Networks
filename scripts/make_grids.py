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


def main_grid():
    cells = []
    for s in SCEN:
        for th in ("off", "on"):
            for kpi in ("none", "kpi"):
                cells.append({"scenario": s, "task_variant": "tempting", "thinking": th, "pressure": "none", "kpi": kpi, "n": 40})
                cells.append({"scenario": s, "task_variant": "tempting", "thinking": th, "pressure": "escalation", "kpi": kpi, "adaptive": ESC_ADAPTIVE})
                cells.append({"scenario": s, "task_variant": "benign", "thinking": th, "kpi": kpi, "n": 40})
    return {"run_id": "main", "seed_start": 0, "seed_stride": 200, "cells": cells}  # default branch plan = 9 branches


if __name__ == "__main__":
    for n, g in (("grid_pilot.yaml", pilot()), ("grid_calib.yaml", calib()), ("grid_main.yaml", main_grid())):
        dump(n, g)
        print("wrote", n, len(g["cells"]), "cells")
