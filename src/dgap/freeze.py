"""Pre-registration freeze (spec 16): SHA-256 lock over configs, detectors, branches and PREREG.md."""
from __future__ import annotations

import hashlib
import json

from . import CONFIGS, ROOT

LOCK = CONFIGS / "frozen.lock"
EXTRA = ["src/dgap/detectors.py", "src/dgap/branches.py", "PREREG.md"]


def tracked_files() -> list[str]:
    files = [p.relative_to(ROOT).as_posix() for p in CONFIGS.rglob("*") if p.is_file() and p != LOCK]
    return sorted(files + EXTRA)


def compute_hashes() -> dict[str, str]:
    out = {}
    for f in tracked_files():
        p = ROOT / f
        out[f] = hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() if p.exists() else "MISSING"
    return out


def write_lock() -> dict[str, str]:
    h = compute_hashes()
    LOCK.write_text(json.dumps(h, indent=2, sort_keys=True), encoding="utf-8")
    return h


def verify_lock() -> list[str]:
    """Returns a list of problems (empty = OK)."""
    if not LOCK.exists():
        return ["configs/frozen.lock does not exist (run scripts/freeze.py after PREREG approval)"]
    locked, now = json.loads(LOCK.read_text(encoding="utf-8")), compute_hashes()
    return [f"{f}: {'changed' if f in locked else 'not in lock'}" for f in now if locked.get(f) != now[f]] + \
           [f"{f}: removed" for f in locked if f not in now]
