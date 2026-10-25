#!/usr/bin/env bash
# SessionEnd hook launcher.
#
#   session-end.sh learn    -> proposes skill/AGENTS.md improvements in a PR
#   session-end.sh linear   -> records the session progress in the Linear card
#
# The hook must never slow down or break session exit: it persists the payload,
# spawns a detached worker, and returns 0 immediately.

set -uo pipefail

kind="${1:-}"
case "$kind" in
  learn|linear) ;;
  *) echo "usage: session-end.sh learn|linear" >&2; exit 2 ;;
esac

root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

# Explicit opt-out (documented in CLAUDE.md §8).
[ "${TCC_SKIP_SESSION_HOOKS:-0}" = "1" ] && exit 0

# A headless child session must not trigger the hooks again.
[ "${CAIO_CODE_HOOK_DEPTH:-0}" = "1" ] && exit 0

payload="$(cat 2>/dev/null || true)"
[ -z "$payload" ] && exit 0

reports="$root/.reports/session-end"
mkdir -p "$reports"
stamp="$(date -u +%Y%m%dT%H%M%SZ 2>/dev/null || echo unknown)"
out="$reports/$stamp-$kind"

printf '%s' "$payload" >"$out.json"

python_bin="python3"
command -v python3 >/dev/null 2>&1 || python_bin="python"

(
  CAIO_CODE_HOOK_DEPTH=1 nohup "$python_bin" "$root/.claude/hooks/worker.py" \
    "$kind" "$out.json" "$root" >"$out.log" 2>&1 &
) </dev/null

exit 0