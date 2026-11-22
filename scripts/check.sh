#!/usr/bin/env bash
# GranniAI check: run before every push. Exits non-zero on the first failure.
# Runs only what exists so an early skeleton passes; a tool that is installed is a tool that runs.
set -euo pipefail
cd "$(dirname "$0")/.."
status=0

echo "== ruff"
if command -v ruff >/dev/null 2>&1; then ruff check backend integrations tests || status=1; else echo "skip: ruff not installed (pip install ruff)"; fi

echo "== pytest"
if command -v pytest >/dev/null 2>&1; then
  # exit 5 = nothing collected; fine while the skeleton is empty
  pytest -q backend integrations tests || { rc=$?; [ "$rc" -eq 5 ] && echo "no tests collected yet" || status=1; }
else echo "skip: pytest not installed"; fi

echo "== frontend"
if [ -d frontend/node_modules ]; then
  (cd frontend && npm run -s lint && npx tsc --noEmit) || status=1
else echo "skip: frontend/node_modules missing (cd frontend && npm install)"; fi

echo "== secrets"
# Key shapes only, each preceded by a non-identifier character so names like task_projection pass:
# Stripe sk_live_/sk_test_, ElevenLabs sk_ + 32 hex, OpenAI-style sk-, Twilio AC + 32 hex, NVIDIA nvapi-, Google AIza.
secret_re='(^|[^A-Za-z0-9_])(sk_(live|test)_[A-Za-z0-9]{16,}|sk_[0-9a-f]{32,}|sk-[A-Za-z0-9_-]{20,}|AC[0-9a-f]{32}|nvapi-[A-Za-z0-9_-]{20,}|AIza[A-Za-z0-9_-]{30,})'
if git grep --untracked -nE "$secret_re" -- ':!scripts/check.sh' >/dev/null; then echo "::error::possible secret committed"; status=1; fi

[ "$status" -eq 0 ] && echo "check: ok" || echo "check: FAILED"
exit $status
