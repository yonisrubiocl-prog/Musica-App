#!/bin/sh
# Prueba la web (server/web/web.html del disco) en un Chromium de verdad con Playwright en Docker, contra la API local.
# Usa la clave interna API_TOKEN solo contra 127.0.0.1 (no sale del servidor). Uso: tools/probar-web.sh [script.js]
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
. "$D/server/.env"
docker run --rm --network host -e TOKEN="$API_TOKEN" -v "$D/tools:/t:ro" -v "$D/server/web/web.html:/web.html:ro" -w /tmp \
  mcr.microsoft.com/playwright:v1.48.2-jammy sh -c "npm i -s playwright@1.48.2 >/dev/null 2>&1 && NODE_PATH=/tmp/node_modules node /t/${1:-prueba-cola.js} /web.html \"\$TOKEN\""
