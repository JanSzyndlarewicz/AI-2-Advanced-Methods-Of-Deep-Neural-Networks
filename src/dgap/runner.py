"""Grid runner: resumable, concurrent, flushes after every episode and branch (spec 10).

python -m dgap.runner --grid configs/grid_pilot.yaml --workers 2 --resume
"""
from __future__ import annotations

import argparse
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml
from tqdm import tqdm

from . import DATA, ROOT
from .branches import BRANCH_PLAN, run_branch, run_p4
from .episode import config_hash, normalize_cfg, run_episode
from .freeze import verify_lock
from .llm import OpenAIClient, load_model_cfg


class HaltRun(RuntimeError):
    """Raised after repeated API failures; state is already flushed (spec 19)."""


class Store:
    """Append-only JSONL store with an in-memory index; thread-safe."""

    def __init__(self, data_dir: Path, run_id: str):
        self.dir, self.run_id, self.lock = Path(data_dir), run_id, threading.Lock()
        for sub in ("episodes", "branches", "judge"):
            (self.dir / sub).mkdir(parents=True, exist_ok=True)
        self.ep_path = self.dir / "episodes" / f"{run_id}.jsonl"
        self.br_path = self.dir / "branches" / f"{run_id}.jsonl"
        self.episodes = {(e["meta"]["config_hash"], e["seed"]): e for e in self._read(self.ep_path)}
        self.branch_keys = {(b["episode_id"], b["protocol"], b["request"], b["k"]) for b in self._read(self.br_path)}

    @staticmethod
    def _read(path: Path):
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()] if path.exists() else []

    def _append(self, path: Path, rec: dict):
        with self.lock, open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()

    def add_episode(self, ep):
        self._append(self.ep_path, ep)
        self.episodes[(ep["meta"]["config_hash"], ep["seed"])] = ep

    def add_branch(self, b):
        self._append(self.br_path, b)
        self.branch_keys.add((b["episode_id"], b["protocol"], b["request"], b["k"]))

    def all_episodes(self):
        return self._read(self.ep_path)

    def all_branches(self):
        return self._read(self.br_path)


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "none"


def expand_cell(cell: dict, idx: int, grid: dict, cap: int | None) -> list[tuple[dict, int]]:
    n = cell.get("n", 20)
    cfg = {k: v for k, v in cell.items() if k not in ("n", "adaptive")}
    base = grid["seed_start"] + idx * grid.get("seed_stride", 0)
    return [(cfg, base + i) for i in range(min(n, cap) if cap else n)]


class Runner:
    def __init__(self, grid: dict, llm, store: Store, model_cfg: dict, workers: int = 2, cap: int | None = None,
                 quiet: bool = False):
        self.grid, self.llm, self.store, self.model_cfg = grid, llm, store, model_cfg
        self.workers, self.cap, self.quiet = workers, cap, quiet
        self.plan = [tuple(x) for x in grid.get("branches", BRANCH_PLAN)]
        self.commit = git_commit()
        self.api_fail_streak = 0

    def meta(self, cfg: dict) -> dict:
        return {"config_hash": config_hash(cfg, self.model_cfg), "git_commit": self.commit, "model_id": self.model_cfg["model_id"],
                "lmstudio_version": self.model_cfg.get("lmstudio_version"), "thinking_strategy": self.model_cfg["thinking_strategy"]}

    def _job(self, cfg: dict, seed: int):
        cfg = normalize_cfg(cfg)
        key = (config_hash(cfg, self.model_cfg), seed)
        ep = self.store.episodes.get(key)
        if ep is None:
            ep = run_episode(cfg, seed, self.llm, self.grid["run_id"], self.meta(cfg))
            self.store.add_episode(ep)
        if ep["end_reason"] == "api_error":
            self._note_api(True)
            return ep
        self._note_api(False)
        if ep["status"] != "ok":
            return ep
        for proto, req in self.plan:
            if (ep["episode_id"], proto, req, None) in self.store.branch_keys:
                continue
            b = run_branch(self.llm, ep, proto, req)
            self._note_api(b is None)
            if b is not None:
                self.store.add_branch(b)
        return ep

    def _note_api(self, failed: bool):
        self.api_fail_streak = self.api_fail_streak + 1 if failed else 0
        if self.api_fail_streak >= 5:
            raise HaltRun("5 consecutive API failures; state flushed")

    def _run_jobs(self, jobs, desc):
        eps = []
        with ThreadPoolExecutor(self.workers) as pool, tqdm(total=len(jobs), desc=desc, disable=self.quiet) as bar:
            futs = [pool.submit(self._job, c, s) for c, s in jobs]
            for f in as_completed(futs):
                eps.append(f.result())
                bar.update()
        return eps

    def run(self):
        for idx, cell in enumerate(self.grid["cells"]):
            desc = f"{cell['scenario']}/{cell['task_variant']}/{cell.get('thinking')}/{cell.get('pressure', 'none')}/{cell.get('kpi', 'none')}"
            ad = cell.get("adaptive")
            if not ad:
                self._run_jobs(expand_cell(cell, idx, self.grid, self.cap), desc)
                continue
            # adaptive stopping rule (spec 12.2): batches until enough informed violations or max episodes
            cfg = {k: v for k, v in cell.items() if k not in ("n", "adaptive")}
            base, done, informed = self.grid["seed_start"] + idx * self.grid.get("seed_stride", 0), 0, 0
            cap = min(ad["max"], self.cap) if self.cap else ad["max"]
            while done < cap and informed < ad["target_informed"]:
                nb = min(ad["batch"], cap - done)
                for ep in self._run_jobs([(cfg, base + done + i) for i in range(nb)], desc):
                    informed += int(ep["status"] == "ok" and ep["violation"]["informed"])
                done += nb


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", required=True)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--resume", action="store_true", default=True)
    ap.add_argument("--data-dir", default=str(DATA))
    ap.add_argument("--dry-run", action="store_true", help="scripted fake LLM; data goes to --data-dir only")
    ap.add_argument("--max-per-cell", type=int, default=None)
    ap.add_argument("--p4", action="store_true", help="run P4 on informed violations + 100 benign controls (spec 12.3)")
    a = ap.parse_args(argv)
    grid = yaml.safe_load(open(a.grid, encoding="utf-8"))
    if grid["run_id"] == "main" and not a.dry_run:
        problems = verify_lock()
        if problems:
            raise SystemExit("REFUSING to run main grid; freeze check failed:\n  " + "\n  ".join(problems))
    model_cfg = load_model_cfg()
    if a.dry_run:
        from .fake import PolicyLLM
        llm = PolicyLLM(seed=1)
    else:
        llm = OpenAIClient(model_cfg)
    store = Store(Path(a.data_dir), grid["run_id"])
    runner = Runner(grid, llm, store, model_cfg, a.workers, a.max_per_cell)
    if a.p4:
        run_p4_stage(runner)
    else:
        runner.run()


def run_p4_stage(runner: Runner):
    import random
    st = runner.store
    eps = [e for e in st.all_episodes() if e["status"] == "ok"]
    informed = [e for e in eps if e["violation"]["informed"]]
    benign = sorted((e for e in eps if e["control_type"] == "benign" and e["config"]["kpi"] == "none"), key=lambda e: e["seed"])
    random.Random(12345).shuffle(benign)
    p0 = {(b["episode_id"]): b for b in st.all_branches() if b["protocol"] == "P0" and b["request"] == "none"}
    for ep in tqdm(informed + benign[:100], desc="P4"):
        if (ep["episode_id"], "P4", "none", 1) in st.branch_keys or ep["episode_id"] not in p0:
            continue
        for b in run_p4(runner.llm, ep, p0[ep["episode_id"]]):
            st.add_branch(b)


if __name__ == "__main__":
    main()
