#!/usr/bin/env bash
# Wrapper para hooks do pre-commit.
# Uso: run-step.sh "<label>" <comando> [args...]
#
# Imprime banner de inicio, captura modificacoes feitas pelo comando
# (ex.: ruff --fix) e orienta a proxima acao em caso de auto-fix ou falha.

set -uo pipefail

if [ "$#" -lt 2 ]; then
  echo "uso: $0 <label> <comando> [args...]" >&2
  exit 2
fi

LABEL="$1"
shift

echo ""
echo "==> [$LABEL] iniciando..."

snapshot() {
  git diff --name-only 2>/dev/null
  git diff --name-only --cached 2>/dev/null
}

BEFORE=$(snapshot)
"$@"
RC=$?
AFTER=$(snapshot)

CHANGED=""
if [ "$BEFORE" != "$AFTER" ]; then
  CHANGED=$(diff <(printf '%s\n' "$BEFORE") <(printf '%s\n' "$AFTER") \
    | sed -n 's/^> //p' \
    | sort -u)
fi

if [ "$RC" -eq 0 ] && [ -z "$CHANGED" ]; then
  echo "OK: [$LABEL]"
  exit 0
fi

if [ -n "$CHANGED" ]; then
  echo ""
  echo "INFO: [$LABEL] modificou arquivo(s):"
  while IFS= read -r f; do
    [ -n "$f" ] && echo "  - $f"
  done <<< "$CHANGED"
  echo ""
  echo "ACAO: rode 'git add -u && git commit' novamente para incluir as correcoes."
  exit 1
fi

echo ""
echo "FAIL: [$LABEL] falhou (exit=$RC) e nao foi auto-corrigivel."
echo "ACAO: corrija os erros acima a mao, depois 'git add' e 'git commit' de novo."
exit "$RC"
