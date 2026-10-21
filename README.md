# The Disclosure Gap

Do LLM agents disclose rule violations they knowingly committed? Two synthetic scenarios (`secret`, `forbidden_tool`), a local model (Qwen3-8B Q4_K_M via an OpenAI-compatible server), scripted pressure, and five reporting protocols (P0 free report, P1 report with call ids, P2 yes/no audit, P3 fresh-context log audit, C confession channel, plus P4 repeated questioning). Full methodology: `DISCLOSURE_GAP_SPEC.md` (= `CLAUDE.md`), pre-registration: `PREREG.md`, decisions: `DECISIONS.md`.

## Layout
`configs/` prompts, scenarios, grids, model settings (frozen by `configs/frozen.lock`) | `src/dgap/` library | `scripts/` entry points | `tests/` (`pytest -q`) | `data/` raw JSONL (git-ignored; checksums in `data/*.sha256`) | `results/` tables, figures, `RESULTS.md`.

## Reproduce
```bash
uv venv && uv pip install -r requirements.txt && uv pip install -e .
pytest -q                                              # must pass before every stage
# start an OpenAI-compatible server on :1234 with qwen3-8b (LM Studio, or llama-server --jinja), context 12288
python scripts/smoke_model.py --write-config           # Stage 0: tool-call parsing + thinking switch
python scripts/make_grids.py                           # (re)generate configs/grid_*.yaml
python -m dgap.runner --grid configs/grid_pilot.yaml --workers 2   # pilot
python -m dgap.judge --run pilot && python scripts/pilot_report.py
python -m dgap.runner --grid configs/grid_calib.yaml && python scripts/calibrate.py   # pressure calibration
python scripts/freeze.py                               # after PREREG.md is final: writes configs/frozen.lock, tags frozen-v1
python -m dgap.runner --grid configs/grid_main.yaml --workers 2    # refuses if freeze check fails
python -m dgap.runner --grid configs/grid_main.yaml --p4           # P4 subset
python -m dgap.judge --run main
python scripts/make_annotation_sheet.py violation && python scripts/make_annotation_sheet.py p0   # blind sheets for humans
python -m dgap.report --run main                       # tables + figures + RESULTS.md
```
Dry run of the full pipeline without a model: add `--dry-run` and `--data-dir <tmp>` to runner/judge (scripted fake LLM; never writes to `data/`).
