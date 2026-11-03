# HANDOFF: project state for a new Claude Code session / collaborator

Read this first, then `CLAUDE.md` (= `DISCLOSURE_GAP_SPEC.md`, the methodology), `PREREG.md`, `DECISIONS.md`.
Last updated: 2026-11-03 (HEAD at that time: see `git log`; tags `frozen-v1`, `frozen-v2`).

## Standing rules (from the spec and the authors)
- Authors: Jan Szyndlarewicz, Wojciech Makowski. Users write Polish; code, prompts, commits and docs are English.
- The agent had full autonomy ("researcher in the loop"); STOP points were resolved by the agent and logged in `DECISIONS.md`. Human-only items must NOT be faked (see "Pending").
- Never invent numbers; every number comes from `results/`. After the freeze do not change `configs/**`, `detectors.py`, `branches.py`, `PREREG.md`; a change means a new tag (`frozen-v3`) and rerunning the affected cells. Check with `python -c "from dgap.freeze import verify_lock; print(verify_lock())"` (must print `[]`).
- One commit per task, message `stageN: ...`, ending with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Do not push unless asked. Do not touch `.idea/`.

## Stage: experiments done (spec stages 0-5 minus human validation)
All of the following is committed and tagged:
- Pipeline (`src/dgap/`), 50 tests (`pytest -q`), smoke test PASS (strategy `A_template_kwargs`), pilot, calibration, PREREG, freeze v1 -> v2.
- Main run (frozen-v2, 2 h-budget "lite" grid), judge P0 run, P4 run, report: `results/RESULTS.md`, `results/table_*.csv`, `results/fig_*.png`.
- Environment used: Qwen3-8B Q4_K_M (`qwen/qwen3-8b`) via standalone `llama-server` (flags in DECISIONS.md), ctx 12288, `--workers 1`.

## Headline results (thinking=off, request=none; all from `results/`, none human-validated yet)
- Violation rate: none 0/40 (secret), 0/20 (forbidden); M0 secret 14/120 (11.7%), forbidden 45/60 (75%); benign 0/40 each; thinking=on probe 0/12 per scenario.
- Disclosure among informed M0 violations: P1/P2/C = 0 in both scenarios; P3 = 14/14 and 45/45; P0 (LLM judge only) 2/14 and 4/45. McNemar P3 vs P0 p_holm = 0.0034 (secret), 7e-12 (forbidden). P1/P2/C vs P0 not significant after Holm. FA in benign = 0 for all protocols. P3 sees the whole transcript, so it is detection, not self-disclosure.
- H2: mostly NA (cost-difference denominators <= 0); table verdict "not confirmed". H3: see the k=2 artifact below.

## Deviations and caveats to keep in mind (all logged in DECISIONS.md / PREREG.md)
1. `secret` preset = `esc_mid` (spec default would be `esc_strong`, which gave 0/20); `forbidden_tool` = `esc_strong`.
2. Budget revision `frozen-v2`: only thinking=off core + a 12-episode thinking=on probe; axes `kpi` and `request` were NOT run (cells have `n: 0`); 5 branches per new episode (P0,P1,P2,P3,C). The first 120 secret M0 episodes were collected under v1 and carry extra `request=request` branches, excluded from analysis.
3. `secret` M0 has only 14 informed violations (< the 20 floor in spec 12.2): floor effect, wide CIs.
4. P4 k=2 wording artifact: the frozen text "Are you sure? ... Answer YES or NO first" makes the model answer "YES. I am sure. I did not violate...", counted as an admission, so benign F(2)~99% and S(k>=2) are contaminated in `table_h3.csv` / `fig_survival.png`. Prompts/parser stay frozen. `results/table_h3_excl_k2.csv` (k=1,3,4,5) is an exploratory sensitivity table made by an ad-hoc script (not in the repo): secret 14/14 deny through k=5; forbidden S(5)=0.222 (34/45 admit).
5. P0 numbers are judge-labels only; kappa is unavailable until humans label.

## Pending (human-only or optional)
- **Manual validation (spec 13)**: annotators A and B. Generate blind sheets with `python scripts/make_annotation_sheet.py violation` and `... p0` (needs `data/`, see below), then `merge-*` subcommands. Required: detector agreement >= 95%, human kappa, judge-human kappa; if kappa < 0.6 report P0 on the human-labelled subset only. `results/table_validation.csv` is empty until then.
- Interpretation of results and the paper (NeurIPS template), `README.md` final touches, presentation.
- Optional: second model Qwen3-4B (needs humans' OK on GPU time; rerun the smoke test first), exploratory figure for H3 without k=2, adding the k=2 sensitivity script to `report.py` (not frozen, no new tag needed), `kpi`/`request`/thinking=on axes (would need `frozen-v3` and ~20 h of GPU time at full scale).

## Raw data is NOT in git
`data/` is git-ignored per the spec (only `data/*/main.jsonl.sha256` are committed). To continue on another machine you need `data/episodes|branches|judge/main.jsonl`; copy them over (about 6.6 MB) and verify with `sha256sum -c` / compare against the `.sha256` files. Without the data you can still read all tables/figures in `results/`, but not regenerate them or the annotation sheets. Re-running the experiment needs a local OpenAI-compatible server (see README "Reproduce"); GPU runs are not needed for analysis or annotation.

## Environment notes (Windows)
- Python 3.13 venv via `uv`; call `.venv/Scripts/python.exe` explicitly (bare `python` is not on the bash PATH).
- llama-server was started from LM Studio's bundled backend (command and PATH in DECISIONS.md); a corrupt resumed GGUF once produced garbage output, so check the model SHA-256 if the server returns `????`.
