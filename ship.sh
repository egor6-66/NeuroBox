#!/usr/bin/env bash
# Раскатка на машине. Запускается НА сервере (обычно через ship.ps1 с ноутбука):
#
#   bash /opt/neurobox/ship.sh              # всё: вход, бокс, соседи — пересобрать и поднять
#   bash /opt/neurobox/ship.sh skin-web     # только названные службы бокса (и вход всё равно)
#   bash /opt/neurobox/ship.sh --no-build   # поднять без пересборки образов
#
# Порядок: git pull в обоих репозиториях, затем сборка и подъём. Ничего по месту не правится —
# на машине только то, что уже стало файлом в репозитории. В конце — проверка, что каждый
# сосед отвечает, а не только что контейнеры запущены.

set -euo pipefail

GATE=/opt/gate
BOX=/opt/neurobox

BUILD=1
SERVICES=()
for arg in "$@"; do
  case "$arg" in
    --no-build) BUILD=0 ;;
    *) SERVICES+=("$arg") ;;
  esac
done

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

say "вход: git pull"
git -C "$GATE" pull --ff-only -q && git -C "$GATE" log --oneline -1

say "бокс: git pull"
git -C "$BOX" pull --ff-only -q && git -C "$BOX" log --oneline -1

cd "$BOX"
if [ "$BUILD" = 1 ]; then
  say "бокс: сборка ${SERVICES[*]:-всех образов}"
  docker compose build "${SERVICES[@]}" 2>&1 | grep -E '^ Image|ERROR|error:' || true
fi

say "бокс: подъём"
docker compose up -d --remove-orphans

say "вход: подъём"
docker compose -f "$GATE/compose.yaml" --project-directory "$GATE" up -d

say "состояние"
docker compose ps --format 'table {{.Name}}\t{{.Status}}'

say "проверка"
# Только что поднятый контейнер отвечает не сразу: node стартует секунды. Каждой проверке даётся
# до полуминуты повторов, а не одна попытка — иначе раскатка краснела бы на живом соседе.
ok=1
check() {
  local name=$1 code=000 i
  for i in $(seq 1 15); do
    code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "$2" || true)
    [ "$code" = "$3" ] && break
    sleep 2
  done
  if [ "$code" = "$3" ]; then printf '  ok    %s\t%s\n' "$name" "$code"
  else printf '  FAIL  %s\t%s (ждали %s)\n' "$name" "$code" "$3"; ok=0; fi
}
check "сервис /health"       http://127.0.0.1:8000/health            200
check "сервис за входом"     https://127.0.0.1/api/health            200
check "пульт :443"           https://127.0.0.1/                      200
check "пульт :8443"          https://127.0.0.1:8443/                 200
check "пресеты /healthz"     http://127.0.0.1:8787/healthz           200

mcp=""
for i in $(seq 1 15); do
  mcp=$(curl -s --max-time 10 -X POST http://127.0.0.1:8788/mcp \
    -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"ship","version":"0"}}}' \
    | grep -o '"name":"web-core-skin"' || true)
  [ -n "$mcp" ] && break
  sleep 2
done
if [ -n "$mcp" ]; then echo "  ok    MCP скинов (initialize)"; else echo "  FAIL  MCP скинов (initialize)"; ok=0; fi

[ "$ok" = 1 ] && say "готово" || { say "есть отказы — смотри выше"; exit 1; }
