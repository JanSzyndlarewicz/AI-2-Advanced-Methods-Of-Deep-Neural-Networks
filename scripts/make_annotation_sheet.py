"""Blind annotation sheets for manual validation (spec 13).

python scripts/make_annotation_sheet.py violation|p0 [--run main]      # create sheets
python scripts/make_annotation_sheet.py merge-violation|merge-p0        # after annotation, build results/validation_*.csv
Judge / detector labels are written to a separate *_key.csv so annotators stay blind.
"""
import argparse
import random
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from dgap import DATA, RESULTS  # noqa: E402
from dgap.branches import build_transcript  # noqa: E402
from dgap.judge import load_judge, log_summary  # noqa: E402
from dgap.runner import Store  # noqa: E402
from dgap.scenarios import load_scenario  # noqa: E402

SEED = 4242


def violation_sheet(eps, rng):
    rows, key = [], []
    for scen in ("secret", "forbidden_tool"):
        pool = [e for e in eps if e["config"]["scenario"] == scen and e["status"] == "ok"]
        pos = [e for e in pool if e["violation"]["occurred"]]
        neg = [e for e in pool if not e["violation"]["occurred"]]
        pick = rng.sample(pos, min(15, len(pos))) + rng.sample(neg, min(10, len(neg)))
        for e in pick:
            rows.append({"episode_id": e["episode_id"], "scenario_rule": load_scenario(scen)["rule_line"],
                         "transcript_text": build_transcript(e["messages"]), "label_a": "", "label_b": ""})
            key.append({"episode_id": e["episode_id"], "detector_label": "violation" if e["violation"]["occurred"] else "none"})
    rng.shuffle(rows)
    return pd.DataFrame(rows), pd.DataFrame(key)


def p0_sheet(eps, brs, judge, rng, total=150):
    emap = {e["episode_id"]: e for e in eps}
    cand = [b for b in brs if b["protocol"] == "P0" and b["request"] == "none" and emap[b["episode_id"]]["status"] == "ok"]
    strata = {}
    for b in cand:
        e = emap[b["episode_id"]]
        strata.setdefault((e["config"]["scenario"], e["config"]["thinking"], e["violation"]["occurred"]), []).append(b)
    picked = []
    for (s, th, viol), bs in sorted(strata.items()):
        picked += rng.sample(bs, min(len(bs), 29 if viol else 8))
    rng.shuffle(picked)
    picked = picked[:total]
    rows, key = [], []
    for b in picked:
        e = emap[b["episode_id"]]
        rows.append({"branch_id": b["branch_id"], "report_text": b["response"], "scenario_rule": load_scenario(e["config"]["scenario"])["rule_line"],
                     "log_summary": log_summary(e), "label_a": "", "label_b": ""})
        j = judge.get(b["branch_id"], {})
        key.append({"branch_id": b["branch_id"], "is_violation": e["violation"]["occurred"], "judge_value": j.get("value"), "judge_kind": j.get("kind")})
    return pd.DataFrame(rows), pd.DataFrame(key)


def merge_violation():
    sheet, key = pd.read_csv(RESULTS / "validation_violation_sheet.csv"), pd.read_csv(RESULTS / "validation_violation_key.csv")
    d = sheet.merge(key, on="episode_id")
    agree = d.label_a.astype(str).str.strip().str.lower() == d.label_b.astype(str).str.strip().str.lower()
    d["human_label"] = d.label_a.where(agree & d.label_a.notna())  # disagreements stay empty until resolved jointly
    if "label_final" in d:
        d["human_label"] = d.label_final.fillna(d.human_label)
    d[["episode_id", "detector_label", "human_label"]].to_csv(RESULTS / "validation_violation.csv", index=False)
    print(f"{int(agree.sum())}/{len(d)} annotator agreements; resolve disagreements by filling `label_final` in the sheet and rerun")


def merge_p0():
    sheet, key = pd.read_csv(RESULTS / "validation_p0_sheet.csv"), pd.read_csv(RESULTS / "validation_p0_key.csv")
    d = sheet.merge(key, on="branch_id")
    if "label_final" not in d:
        d["label_final"] = d.label_a.where(d.label_a == d.label_b)
    d["judge_label"] = [("DISCLOSED" if v in ("DISCLOSED", "YES") else ("OMITTED" if v in ("OMITTED", "NO") else v)) if isinstance(v, str) else None
                        for v in d.judge_value]
    d.drop(columns=["report_text", "log_summary"]).to_csv(RESULTS / "validation_p0.csv", index=False)
    print("wrote results/validation_p0.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["violation", "p0", "merge-violation", "merge-p0"])
    ap.add_argument("--run", default="main")
    ap.add_argument("--data-dir", default=str(DATA))
    a = ap.parse_args()
    RESULTS.mkdir(exist_ok=True)
    if a.kind == "merge-violation":
        return merge_violation()
    if a.kind == "merge-p0":
        return merge_p0()
    st = Store(Path(a.data_dir), a.run)
    eps, rng = st.all_episodes(), random.Random(SEED)
    if a.kind == "violation":
        sheet, key = violation_sheet(eps, rng)
    else:
        sheet, key = p0_sheet(eps, st.all_branches(), load_judge(a.data_dir, a.run), rng)
    sheet.to_csv(RESULTS / f"validation_{a.kind}_sheet.csv", index=False)
    key.to_csv(RESULTS / f"validation_{a.kind}_key.csv", index=False)
    print(f"wrote sheet ({len(sheet)} rows) + key")


if __name__ == "__main__":
    main()
