#!/usr/bin/env bash
# Start another workflow, retrying when GitHub's own servers fail.
#
#   bash scraper/gh_dispatch.sh <workflow.yml> [gh workflow run options...]
#
# Same arguments and exit status as `gh workflow run`. On 4 Nov 2026 two runs
# failed in one morning because the dispatch API answered HTTP 500 and 502;
# both were GitHub-side and passed on a retry. Server errors and dropped
# connections are retried with backoff (5, 10, 20, 40s). A client error (a
# missing workflow, a bad input, no permission) is a real fault and fails at
# once, so it is never hidden.
set -uo pipefail

attempts="${GH_DISPATCH_ATTEMPTS:-5}"
delay="${GH_DISPATCH_FIRST_DELAY:-5}"
err="$(mktemp)"
trap 'rm -f "$err"' EXIT

for attempt in $(seq 1 "$attempts"); do
  if gh workflow run "$@" 2>"$err"; then
    [ "$attempt" -gt 1 ] && echo "Dispatched $1 on attempt ${attempt}."
    exit 0
  fi
  cat "$err" >&2
  if ! grep -qiE 'HTTP 5[0-9][0-9]|server error|bad gateway|service unavailable|gateway time-?out|timed? ?out|connection (reset|refused)|EOF|TLS handshake' "$err"; then
    echo "::error::Dispatch of $1 failed with a non-retryable error." >&2
    exit 1
  fi
  if [ "$attempt" -lt "$attempts" ]; then
    echo "GitHub server error dispatching $1 (attempt ${attempt}/${attempts}); retrying in ${delay}s." >&2
    sleep "$delay"
    delay=$(( delay * 2 ))
  fi
done
echo "::error::Dispatch of $1 still failing after ${attempts} attempts of GitHub server errors." >&2
exit 1
