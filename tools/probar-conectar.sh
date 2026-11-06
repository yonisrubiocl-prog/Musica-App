#!/bin/sh
# Prueba "escuchar en varios dispositivos" con dos navegadores (PC y celular) contra un /conectar de mentira con la
# lógica real (tools/conectar-falso.py + server/conectar.py); lo demás, contra la API local con la clave interna.
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
. "$D/server/.env"
docker run --rm --network host -e TOKEN="$API_TOKEN" -v "$D/tools:/t:ro" -v "$D/server/conectar.py:/cx/conectar.py:ro" \
  -v "$D/server/web/web.html:/web.html:ro" -w /tmp mcr.microsoft.com/playwright:v1.48.2-jammy \
  sh -c "(python3 /t/conectar-falso.py &) ; npm i -s playwright@1.48.2 >/dev/null 2>&1 && NODE_PATH=/tmp/node_modules node /t/prueba-conectar.js /web.html \"\$TOKEN\""
