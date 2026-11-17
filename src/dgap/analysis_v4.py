"""Analysis of Addendum v4 (act-by-act audit P6): T5, T6, d', act-level rates, localisation, cost."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact

from . import stats
from .branches_v4 import list_acts
from .v3 import eligible


def act_frame(episodes: list[dict], branches: list[dict]) -> pd.DataFrame:
    ep = {e["episode_id"]: e for e in episodes if eligible(e)}
    truth = {(eid, a["act_index"]): a for eid, e in ep.items() for a in list_acts(e)}
    rows = []
    for b in branches:
        if b["protocol"] != "P6" or b["episode_id"] not in ep:
            continue
        e, a = ep[b["episode_id"]], truth.get((b["episode_id"], b["k"]))
        if a is None:
            continue
        rows.append({"episode_id": e["episode_id"], "scenario": e["config"]["scenario"],
                     "group": "violation_M0" if e["violation"]["informed"] else e["control_type"],
                     "act_index": a["act_index"], "kind": a["kind"], "tool": a["tool"], "is_violating_act": a["is_violating_act"],
                     "yes": bool(b["labels"]["disclosed"]), "format_error": bool(b["labels"]["format_error"]),
                     "completion_tokens": b["usage"]["completion_tokens"], "total_tokens": b["usage"]["total_tokens"]})
    return pd.DataFrame(rows)


def episode_level(af: pd.DataFrame) -> pd.DataFrame:
    g = af.groupby(["episode_id", "scenario", "group"])
    return pd.DataFrame({
        "any_yes": g.yes.any(), "any_fmt_err": g.format_error.any(), "n_acts": g.size(),
        "viol_act_yes": g.apply(lambda d: bool(d[d.is_violating_act].yes.any()), include_groups=False),
        "nonviol_act_yes": g.apply(lambda d: bool(d[~d.is_violating_act].yes.any()), include_groups=False),
        "has_nonviol": g.apply(lambda d: bool((~d.is_violating_act).any()), include_groups=False),
        "completion_tokens": g.completion_tokens.sum(), "total_tokens": g.total_tokens.sum()}).reset_index()


def rates(el: pd.DataFrame, exclude_fmt: bool = False) -> pd.DataFrame:
    d = el[~el.any_fmt_err] if exclude_fmt else el
    rows = []
    for sc, g in d.groupby("scenario"):
        hit = g[g.group == "violation_M0"].any_yes.to_numpy().astype(float)
        r = {"scenario": sc, "sensitivity_excl_format_errors": exclude_fmt, "n_hit": len(hit), "x_hit": int(hit.sum()),
             "H": hit.mean() if len(hit) else np.nan}
        r["H_lo"], r["H_hi"] = stats.wilson(r["x_hit"], r["n_hit"])
        for fs in ("nearmiss", "benign", "resisted"):
            fa = g[g.group == fs].any_yes.to_numpy().astype(float)
            r[f"n_fa_{fs}"], r[f"x_fa_{fs}"] = len(fa), int(fa.sum())
            r[f"FA_{fs}"] = fa.mean() if len(fa) else np.nan
            r[f"FA_{fs}_lo"], r[f"FA_{fs}_hi"] = stats.wilson(int(fa.sum()), len(fa))
            if len(hit) and len(fa):
                r[f"dprime_{fs}"] = stats.dprime(r["x_hit"], len(hit), int(fa.sum()), len(fa))
                r[f"dprime_{fs}_lo"], r[f"dprime_{fs}_hi"] = stats.boot_dprime(hit, fa)
        v = g[g.group == "violation_M0"]
        exact = (v.viol_act_yes & ~v.nonviol_act_yes).sum()
        r["exact_localisation"], r["exact_localisation_rate"] = int(exact), exact / len(v) if len(v) else np.nan
        r["mean_acts_per_episode"], r["mean_completion_tokens_per_episode"] = g.n_acts.mean(), g.completion_tokens.mean()
        rows.append(r)
    return pd.DataFrame(rows)


def act_rates(af: pd.DataFrame) -> pd.DataFrame:
    af = af.copy()
    af["act_type"] = np.where(af.is_violating_act, "violating",
                              np.where(af.group == "violation_M0", "non-violating (violation episode)", "control: " + af.group))
    af["tool"] = af.tool.fillna("(message)")
    rows = []
    for (sc, t, tool), g in af.groupby(["scenario", "act_type", "tool"]):
        x, n = int(g.yes.sum()), len(g)
        lo, hi = stats.wilson(x, n)
        rows.append({"scenario": sc, "act_type": t, "tool": tool, "n_acts": n, "yes": x, "rate": x / n, "lo": lo, "hi": hi,
                     "format_errors": int(g.format_error.sum())})
    return pd.DataFrame(rows)


def confirmatory(el: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sc, g in el.groupby("scenario"):
        hit, fa = g[g.group == "violation_M0"].any_yes, g[g.group == "nearmiss"].any_yes
        if len(hit) and len(fa):
            t = [[int(hit.sum()), int((~hit).sum())], [int(fa.sum()), int((~fa).sum())]]
            p = float(fisher_exact(t, alternative="greater")[1])
            rows.append({"test": "T5", "scenario": sc, "comparison": "P6_any: H (violations) vs FA (nearmiss)",
                         "n_a": len(hit), "x_a": int(hit.sum()), "n_b": len(fa), "x_b": int(fa.sum()),
                         "effect": hit.mean() - fa.mean(), "p_raw": p})
        v = g[(g.group == "violation_M0") & g.has_nonviol]
        if len(v):
            m = stats.mcnemar_exact(v.nonviol_act_yes.to_numpy().astype(int), v.viol_act_yes.to_numpy().astype(int))
            rows.append({"test": "T6", "scenario": sc, "comparison": "violating act YES vs any non-violating act YES (paired)",
                         "n_a": len(v), "x_a": int(v.viol_act_yes.sum()), "n_b": len(v), "x_b": int(v.nonviol_act_yes.sum()),
                         "effect": v.viol_act_yes.mean() - v.nonviol_act_yes.mean(), "p_raw": m["p_raw"],
                         "both": m["both"], "nonviol_only": m["p0_only"], "viol_only": m["x_only"], "neither": m["neither"]})
    out = pd.DataFrame(rows)
    if len(out):
        out["p_holm"] = stats.holm(out.p_raw.tolist())
        out["supports_prediction"] = (out.p_holm < 0.05) & (out.effect > 0)
    return out


def build(episodes: list[dict], branches: list[dict]) -> dict[str, pd.DataFrame]:
    af = act_frame(episodes, branches)
    if af.empty:
        return {}
    el = episode_level(af)
    return {"table_v4_tests": confirmatory(el), "table_v4_rates": pd.concat([rates(el), rates(el, True)]),
            "table_v4_act_rates": act_rates(af)}
