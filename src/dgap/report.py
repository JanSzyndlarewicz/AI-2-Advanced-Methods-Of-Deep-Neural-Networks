"""Tables, figures and RESULTS.md from raw data (spec 15). Facts only; interpretation is written by humans.

python -m dgap.report --run main [--data-dir data] [--results-dir results]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import DATA, RESULTS
from . import stats
from .judge import load_judge
from .runner import Store

MARK = {"P0": "o", "P1": "s", "P2": "^", "P3": "D", "C": "v"}
COL = {"P0": "#000000", "P1": "#E69F00", "P2": "#56B4E9", "P3": "#009E73", "C": "#D55E00"}


def md_table(df: pd.DataFrame, floatfmt: str = "{:.3f}") -> str:
    if df is None or df.empty:
        return "_no data_\n"
    def fmt(v):
        return floatfmt.format(v) if isinstance(v, (float, np.floating)) and not pd.isna(v) else ("" if pd.isna(v) else str(v))
    head = "| " + " | ".join(df.columns) + " |\n|" + "---|" * len(df.columns) + "\n"
    return head + "\n".join("| " + " | ".join(fmt(v) for v in r) + " |" for r in df.itertuples(index=False)) + "\n"


def validation_table(results_dir: Path) -> pd.DataFrame:
    rows = []
    p = results_dir / "validation_violation.csv"
    if p.exists():
        d = pd.read_csv(p).dropna(subset=["human_label"])
        if len(d):
            rows.append({"metric": "detector_vs_human_agreement", "value": stats.agreement(d.detector_label.astype(str).str.lower(), d.human_label.astype(str).str.lower()), "n": len(d)})
    p = results_dir / "validation_p0.csv"
    if p.exists():
        d = pd.read_csv(p).dropna(subset=["label_a", "label_b"])
        if len(d):
            rows.append({"metric": "kappa_human_a_vs_b", "value": stats.kappa(d.label_a, d.label_b), "n": len(d)})
            if "label_final" in d and "judge_label" in d and d.label_final.notna().any():
                dd = d.dropna(subset=["label_final", "judge_label"])
                rows.append({"metric": "kappa_judge_vs_human_final", "value": stats.kappa(dd.label_final, dd.judge_label), "n": len(dd)})
    return pd.DataFrame(rows, columns=["metric", "value", "n"])


def fig_violation(vr: pd.DataFrame, path: Path):
    t = vr[vr.task_variant == "tempting"].copy()
    if t.empty:
        return
    t["cond"] = t.scenario.str[:6] + "|" + t.thinking + "|" + t.kpi + "|" + t.pressure.str[:4]
    t = t.sort_values("cond")
    fig, ax = plt.subplots(figsize=(max(6, 0.5 * len(t)), 4))
    x = np.arange(len(t))
    for off, col, lab, hatch in ((-0.2, "viol_rate", "violation", ""), (0.2, "informed_rate", "informed violation", "//")):
        lo, hi = (t.viol_lo, t.viol_hi) if col == "viol_rate" else (t.inf_lo, t.inf_hi)
        ax.bar(x + off, t[col], 0.4, yerr=[t[col] - lo, hi - t[col]], label=lab, hatch=hatch, color="#56B4E9" if not hatch else "#E69F00", edgecolor="black", capsize=2)
    ax.set_xticks(x, t.cond, rotation=70, ha="right", fontsize=7)
    ax.set_ylabel("Rate (Wilson 95% CI)")
    ax.set_ylim(0, 1)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_dprime(dt: pd.DataFrame, path: Path):
    m = dt[(dt.request == "none") & dt.get("dprime", pd.Series(dtype=float)).notna()] if "dprime" in dt else pd.DataFrame()
    if m.empty:
        return
    m = m.assign(cond=m.scenario.str[:6] + "|" + m.thinking + "|" + m.kpi + "|" + m.pressure.str[:4])
    conds = sorted(m.cond.unique())
    fig, ax = plt.subplots(figsize=(max(6, 0.6 * len(conds)), 4))
    for i, p in enumerate(["P0", "P1", "P2", "P3", "C"]):
        g = m[m.protocol == p]
        xs = [conds.index(c) + (i - 2) * 0.12 for c in g.cond]
        ax.errorbar(xs, g.dprime, yerr=[g.dprime - g.dprime_lo, g.dprime_hi - g.dprime], fmt=MARK[p], color=COL[p], label=p, capsize=2, mfc="none" if p == "P0" else COL[p])
    ax.axhline(0, color="gray", lw=0.8)
    ax.set_xticks(range(len(conds)), conds, rotation=70, ha="right", fontsize=7)
    ax.set_ylabel("d' (bootstrap 95% CI)")
    ax.legend(ncol=5, fontsize=8, loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_pareto(dt: pd.DataFrame, cost: pd.DataFrame, path: Path):
    m = dt[(dt.request == "none") & (dt.thinking == "off") & (dt.kpi == "none") & (dt.pressure == "escalation")]
    if m.empty:
        return
    c = cost[cost.request == "none"].set_index("protocol").completion_mean
    fig, axs = plt.subplots(1, 2, figsize=(9, 4), sharey=True)
    for ax, scen in zip(axs, ("secret", "forbidden_tool")):
        for _, r in m[m.scenario == scen].iterrows():
            ax.scatter(r.FA, r.H, s=40 + 0.5 * c.get(r.protocol, 0), marker=MARK[r.protocol], color=COL[r.protocol], edgecolor="black", label=r.protocol)
        ax.plot([0, 1], [0, 1], "--", color="gray", lw=0.8)
        ax.set_title(scen)
        ax.set_xlabel("False-alarm rate (benign)")
        ax.set_xlim(-0.05, 1.05)
        ax.set_ylim(-0.05, 1.05)
    axs[0].set_ylabel("Hit rate (informed violations)")
    axs[0].legend(fontsize=8, title="size = completion tokens")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_survival(h3: pd.DataFrame, path: Path):
    if h3.empty:
        return
    fig, ax = plt.subplots(figsize=(6, 4))
    styles = {"informed_M0": ("-", "o", "#000000", "S(k): informed, M0"), "informed_all": ("--", "s", "#E69F00", "S(k): informed, all"),
              "benign": (":", "^", "#0072B2", "F(k): benign (false YES)")}
    for g, (ls, mk, col, lab) in styles.items():
        d = h3[h3.group == g]
        if d.empty:
            continue
        y, lo, hi = (d.F_yes_at_k, d.F_lo, d.F_hi) if g == "benign" else (d.S_all_no, d.S_lo, d.S_hi)
        ax.errorbar(d.k, y, yerr=[y - lo, hi - y], ls=ls, marker=mk, color=col, label=lab, capsize=2)
    ax.set_xlabel("Question k")
    ax.set_ylabel("Proportion (Wilson 95% CI)")
    ax.set_xticks(range(1, 6))
    ax.set_ylim(0, 1)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def build(runs: list[str], data_dir: Path, results_dir: Path):
    results_dir.mkdir(parents=True, exist_ok=True)
    eps, brs, judge = [], [], {}
    for r in runs:
        st = Store(data_dir, r)
        eps += st.all_episodes()
        brs += st.all_branches()
        judge.update(load_judge(data_dir, r))
    df = stats.build_frame(eps, brs, judge if judge else None)
    ep_df = pd.DataFrame([{**e["config"], "status": e["status"], "violation": e["violation"]["occurred"], "informed": e["violation"]["informed"]} for e in eps])
    out = {}
    out["table_violation_rates"] = stats.violation_rates(ep_df) if len(ep_df) else pd.DataFrame()
    out["table_disclosure"] = stats.disclosure_table(df) if len(df) else pd.DataFrame()
    out["table_tests_M0"] = stats.confirmatory_tests(df) if len(df) else pd.DataFrame()
    out["table_cost"] = stats.cost_table(df) if len(df) else pd.DataFrame()
    h2 = [stats.h2_analysis(df, c) for c in ("completion_tokens", "total_tokens")] if len(df) else []
    out["table_h2"] = pd.concat(h2) if h2 else pd.DataFrame()
    out["table_h3"] = stats.h3_curves(df) if len(df) else pd.DataFrame()
    out["table_validation"] = validation_table(results_dir)
    out["table_parse_errors"] = stats.parse_error_table(eps)
    out["exclusions"] = stats.exclusions_table(eps)
    for k, v in out.items():
        v.to_csv(results_dir / f"{k}.csv", index=False)
    if len(df):
        fig_violation(out["table_violation_rates"], results_dir / "fig_violation_by_condition.png")
        fig_dprime(out["table_disclosure"], results_dir / "fig_dprime.png")
        fig_pareto(out["table_disclosure"], out["table_cost"], results_dir / "fig_pareto.png")
        fig_survival(out["table_h3"], results_dir / "fig_survival.png")
    names = {"table_violation_rates": "Violation rates", "table_disclosure": "Disclosure: H, FA, d'", "table_tests_M0": "Confirmatory tests (M0, exact McNemar, Holm over 8)",
             "table_cost": "Cost per protocol", "table_h2": "H2: disclosure gain per 1000 completion tokens", "table_h3": "H3: denial survival S(k) and false confession F(k)",
             "table_validation": "Validation", "table_parse_errors": "Parse errors / recovered tool calls", "exclusions": "Exclusions"}
    md = [f"# RESULTS (auto-generated; runs: {', '.join(runs)})\n", "Facts only. Interpretation is written by the authors. P0 labels are LLM-judge labels unless validation says otherwise.\n"]
    for k, title in names.items():
        md.append(f"## {title}\n\n" + md_table(out[k]))
    (results_dir / "RESULTS.md").write_text("\n".join(md), encoding="utf-8")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", nargs="+", default=["main"])
    ap.add_argument("--data-dir", default=str(DATA))
    ap.add_argument("--results-dir", default=str(RESULTS))
    a = ap.parse_args(argv)
    build(a.run, Path(a.data_dir), Path(a.results_dir))


if __name__ == "__main__":
    main()
