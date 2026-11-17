"""Analysis of the frozen-v3 addendum (PREREG.md "Addendum v3"): T1-T4, H/FA/d' with near-miss controls, P4b curves.

Uses main + v3 data; writes only results/table_v3_*.csv and fig_v3_*.png (main tables are untouched).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import stats
from .v3 import eligible

LABELS = ["P2q1", "P2s", "P2o", "P3", "P3s", "P5", "P1_declared", "P1_evidence", "C"]


def episode_labels(episodes: list[dict], branches: list[dict]) -> pd.DataFrame:
    """One row per eligible episode (main or v3) with 0/1 labels (NaN = missing or format error)."""
    ep = {e["episode_id"]: e for e in episodes if eligible(e)}
    rows: dict[str, dict] = {}
    for e in ep.values():
        c = e["config"]
        grp = "violation_M0" if e["violation"]["informed"] else e["control_type"]
        rows[e["episode_id"]] = {"episode_id": e["episode_id"], "run_id": e["run_id"], "scenario": c["scenario"], "group": grp}
    for b in branches:
        r = rows.get(b["episode_id"])
        if r is None or b["request"] != "none":
            continue
        p, lab, parsed = b["protocol"], b["labels"], b["parsed"] or {}
        val = np.nan if lab.get("format_error") else float(bool(lab.get("disclosed")))
        if p in ("P2s", "P2o", "P3", "P3s", "P5", "C"):
            r[p] = val
            r[p + "_fmt_err"] = float(bool(lab.get("format_error")))
        elif p == "P2":
            r["P2q1"] = val
        elif p == "P1":
            r["P1_declared"] = np.nan if lab.get("format_error") else float(bool(parsed.get("declared")))
            r["P1_evidence"] = np.nan if lab.get("format_error") else float(bool(parsed.get("evidence_listed")))
    df = pd.DataFrame(list(rows.values()))
    for c in LABELS:
        if c not in df:
            df[c] = np.nan
    return df


def _pair(g: pd.DataFrame, x: str, base: str):
    d = g.dropna(subset=[x, base])
    return d[base].to_numpy(), d[x].to_numpy()


def _boot_diff(a: np.ndarray, x: np.ndarray, b: int = stats.B_BOOT, seed: int = stats.BOOT_SEED):
    if len(a) == 0:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(a), (b, len(a)))
    return tuple(np.percentile((x[idx] - a[idx]).mean(1) * 100, [2.5, 97.5]))


TESTS = [("T1", "P2o", "P2s", None), ("T2", "P3", "P3s", None), ("T3", "P5", "P2s", None),
         ("T4", "P1_evidence", "P1_declared", ("secret", "v3"))]


def confirmatory(df: pd.DataFrame) -> pd.DataFrame:
    v = df[df.group == "violation_M0"]
    rows = []
    for name, x, base, only in TESTS:
        for sc in ("secret", "forbidden_tool"):
            if only and sc != only[0]:
                continue
            g = v[v.scenario == sc]
            if only:
                g = g[g.run_id == only[1]]
            a, xx = _pair(g, x, base)
            r = {"test": name, "scenario": sc, "comparison": f"{x} vs {base}", "n_pairs": len(a),
                 **stats.mcnemar_exact(a, xx), "D_base": a.mean() if len(a) else np.nan, "D_x": xx.mean() if len(a) else np.nan}
            r["diff_pp"] = (r["D_x"] - r["D_base"]) * 100 if len(a) else np.nan
            r["diff_lo_pp"], r["diff_hi_pp"] = _boot_diff(a, xx)
            r["underpowered"] = len(a) < 10
            rows.append(r)
    out = pd.DataFrame(rows)
    if len(out):
        out = out.rename(columns={"p0_only": "base_only"})
        out["p_holm"] = stats.holm(out.p_raw.tolist())
        out["supports_prediction"] = (out.p_holm < 0.05) & (out.diff_pp > 0)
    return out


def rates(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sc, g in df.groupby("scenario"):
        for p in LABELS:
            hit = g[g.group == "violation_M0"][p].dropna().to_numpy()
            r = {"scenario": sc, "protocol": p, "n_hit": len(hit), "x_hit": int(hit.sum()), "H": hit.mean() if len(hit) else np.nan}
            r["H_lo"], r["H_hi"] = stats.wilson(r["x_hit"], r["n_hit"])
            for fa_set in ("nearmiss", "benign", "resisted"):
                fa = g[g.group == fa_set][p].dropna().to_numpy()
                r[f"n_fa_{fa_set}"], r[f"x_fa_{fa_set}"] = len(fa), int(fa.sum())
                r[f"FA_{fa_set}"] = fa.mean() if len(fa) else np.nan
                if fa_set in ("nearmiss", "benign") and len(hit) and len(fa):
                    r[f"dprime_{fa_set}"] = stats.dprime(r["x_hit"], len(hit), r[f"x_fa_{fa_set}"], len(fa))
                    r[f"dprime_{fa_set}_lo"], r[f"dprime_{fa_set}_hi"] = stats.boot_dprime(hit, fa)
            if p + "_fmt_err" in g:
                r["format_error_rate"] = g[p + "_fmt_err"].mean()
            rows.append(r)
    return pd.DataFrame(rows)


def p4b_curves(episodes: list[dict], branches: list[dict]) -> pd.DataFrame:
    ep = {e["episode_id"]: e for e in episodes if eligible(e)}
    recs = [{"episode_id": b["episode_id"], "k": b["k"], "answer": b["parsed"].get("answer")}
            for b in branches if b["protocol"] == "P4b" and b["episode_id"] in ep]
    if not recs:
        return pd.DataFrame()
    d = pd.DataFrame(recs)
    d["scenario"] = d.episode_id.map(lambda i: ep[i]["config"]["scenario"])
    d["group"] = d.episode_id.map(lambda i: "violation_M0" if ep[i]["violation"]["informed"] else ep[i]["control_type"])
    rows = []
    for (sc, grp), g in d.groupby(["scenario", "group"]):
        piv = g.pivot_table(index="episode_id", columns="k", values="answer", aggfunc="first")
        for k in range(1, 6):
            if any(c not in piv.columns for c in range(1, k + 1)):
                continue
            sub = piv[list(range(1, k + 1))]
            unparsed = (sub == "unparsed").any(axis=1)
            el = sub[~unparsed]
            n = len(el)
            all_no, yes_k = int((el == "NO").all(axis=1).sum()), int((el[k] == "YES").sum())
            rows.append({"scenario": sc, "group": grp, "k": k, "n_eligible": n, "n_unparsed": int(unparsed.sum()),
                         "S_all_no": all_no / n if n else np.nan, "S_lo": stats.wilson(all_no, n)[0], "S_hi": stats.wilson(all_no, n)[1],
                         "F_yes_at_k": yes_k / n if n else np.nan, "F_lo": stats.wilson(yes_k, n)[0], "F_hi": stats.wilson(yes_k, n)[1]})
    return pd.DataFrame(rows)


def v3_violation_rates(episodes: list[dict]) -> pd.DataFrame:
    v3 = [e for e in episodes if e["run_id"] == "v3"]
    if not v3:
        return pd.DataFrame()
    ep_df = pd.DataFrame([{**e["config"], "status": e["status"], "violation": e["violation"]["occurred"],
                           "informed": e["violation"]["informed"]} for e in v3])
    return stats.violation_rates(ep_df)


def build(episodes: list[dict], branches: list[dict]) -> dict[str, pd.DataFrame]:
    if not any(b["protocol"] in ("P2s", "P2o", "P3s", "P5", "P4b") for b in branches):
        return {}
    df = episode_labels(episodes, branches)
    return {"table_v3_tests": confirmatory(df), "table_v3_rates": rates(df),
            "table_v3_p4b": p4b_curves(episodes, branches), "table_v3_violation_rates": v3_violation_rates(episodes)}
