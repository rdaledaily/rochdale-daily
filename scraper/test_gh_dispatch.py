"""Workflow dispatches retry GitHub server errors and fail fast on real faults.

Run: python scraper/test_gh_dispatch.py
"""
import glob
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scraper' / 'gh_dispatch.sh'
FAILURES = []


def check(condition, label):
    print(('PASS ' if condition else 'FAIL ') + label)
    if not condition:
        FAILURES.append(label)


FAKE = '''#!/usr/bin/env bash
n=$(cat "$COUNT" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$COUNT"
case "$FAKE_MODE" in
  flaky) [ $n -lt 3 ] && { echo "could not create workflow dispatch event: HTTP 502: Server Error" >&2; exit 1; }; exit 0;;
  client) echo "could not find any workflows named nope.yml" >&2; exit 1;;
  down) echo "could not create workflow dispatch event: HTTP 500" >&2; exit 1;;
  ok) exit 0;;
esac
'''

with tempfile.TemporaryDirectory() as tmp:
    fake = Path(tmp) / 'gh'
    fake.write_text(FAKE)
    fake.chmod(0o755)
    for mode, want_exit, want_calls in (('ok', 0, 1), ('flaky', 0, 3), ('client', 1, 1), ('down', 1, 5)):
        count = Path(tmp) / f'count-{mode}'
        env = dict(os.environ, PATH=f'{tmp}:{os.environ["PATH"]}', FAKE_MODE=mode, COUNT=str(count),
                   GH_DISPATCH_FIRST_DELAY='0')
        result = subprocess.run(['bash', str(SCRIPT), 'x.yml', '--ref', 'main'], env=env, capture_output=True, text=True)
        calls = int(count.read_text())
        check(result.returncode == want_exit and calls == want_calls,
              f'{mode}: exit {result.returncode} after {calls} call(s) (want {want_exit}, {want_calls})')

direct = [f for f in glob.glob(str(ROOT / '.github' / 'workflows' / '*.yml')) if 'gh workflow run ' in Path(f).read_text()]
check(not direct, f'no workflow dispatches without retry ({[Path(f).name for f in direct]})')

print()
if FAILURES:
    print(f'{len(FAILURES)} FAILED')
    sys.exit(1)
print('all dispatch checks passed')
