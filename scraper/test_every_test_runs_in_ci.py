#!/usr/bin/env python3
"""Every scraper/test_*.py file must be run by the CI workflow.

24 Oct 2026: 34 of 124 test files were never run by CI, and five of them had
been failing unseen (a broken push-recovery path, a taken-down story back in
the feed, robots wildcard rules ignored on the runners' Python). A test that
CI does not run protects nothing.
Run: python scraper/test_every_test_runs_in_ci.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
missing = sorted(p.name for p in (ROOT / "scraper").glob("test_*.py") if p.name not in ci)
if missing:
    raise SystemExit("Test files not run by .github/workflows/ci.yml: " + ", ".join(missing))
print(f"All {len(list((ROOT / 'scraper').glob('test_*.py')))} test files run in CI.")
