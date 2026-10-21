"""Write configs/frozen.lock and tag frozen-v1 (spec 16). Run ONLY after the humans approved PREREG.md.

python scripts/freeze.py [--tag frozen-v1]
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from dgap.freeze import write_lock  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--tag", default="frozen-v1")
a = ap.parse_args()
hashes = write_lock()
print(f"locked {len(hashes)} files")
subprocess.run(["git", "tag", a.tag], cwd=ROOT, check=False)
print("tagged", a.tag, "(commit the lock first so the tag includes it)")
