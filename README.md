# MusicApp: app de música propia

> **Regla de este documento:** describe **cómo está el proyecto ahora**, no su historia. Al cambiar algo,
> se **reescribe la parte afectada y se borra lo viejo o ya realizado**; no se añaden notas sueltas al
> final ni "actualizaciones" encima de texto desfasado. Debe poder leerse de arriba abajo sin
> contradicciones. Lo histórico está en git, no aquí.

App de música propia, tipo Spotify: buscas una canción, le das a play y **suena en el móvil o el PC**.
No es un mando del bot de Discord (`MusicBot`, otro proyecto): solo comparten la música guardada, y el plan es
que el bot pase a pedírsela a esta API (ver "Canciones").

Es un proyecto **por diversión y para aprender**: privado, solo para mí y mis amigos (unas 6 personas),
sin publicarlo ni cobrar nada.

**Estado actual:** fase 1 hecha y **login con Google hecho en el servidor** (probado con mi cuenta desde
`/prueba-login`: entra, se aprueba, busca y suena; una canción nueva se baja sola al darle play). Publicado en
`https://musica.yoneapolis.com` (túnel de Cloudflare, dominio propio); Tailscale Funnel
(`https://musicapp.tail66213e.ts.net`) sigue encendido como respaldo.

**Biblioteca única: la parte de la API está hecha.** Una sola carpeta `/var/lib/music` con un solo catálogo,
y rutas internas para el bot. **Lo siguiente:** cambiar el bot para que use esas rutas en vez de bajar él
(sección "Canciones → Falta: el bot"). Después, la app (fase 2).

---

## 1. Cómo funciona (diseño)

```
 PC / móvil                               Este servidor
 ──────────                               ─────────────────────────────────────────
  App Flutter  ◄── túnel de Cloudflare ──►  API de música (contenedor Docker propio)
              (https://musica.yoneapolis.com)  ├─ login con Google + aprobación manual
                                               ├─ buscar en YouTube (yt-dlp)
                                               ├─ descargar y guardar en caché
                                               └─ enviar el audio a la app
```

| Pieza | Dónde | Qué es |
|---|---|---|
| **Servidor** (`server/`) | Este servidor, en Docker | API de música, dueña de la biblioteca. Hoy el bot aún no la usa: si se rompe, el bot sigue (cambia cuando el bot pase a ser su cliente) |
| **App** | PC del usuario | Flutter (Android y PC; iPhone algún día). Se desarrolla allí porque este servidor no tiene pantalla para el emulador |
| **Túnel** | Contenedor `cloudflared` aquí + Cloudflare | Da la dirección pública con HTTPS sin abrir puertos. Dominio `yoneapolis.com` (mío, en Cloudflare), pensado para todos mis proyectos con un subdominio cada uno |
| **Canciones** | `/var/lib/music` (la biblioteca única) | Fuera del proyecto: `/home` tiene poco espacio, `/var` tiene de sobra. Ver "Canciones" abajo |

### Canciones

La **API es la dueña de la música**: una carpeta `/var/lib/music` (~1.900 canciones, ~7 GB) y un catálogo
`~/MusicApp/server/data/index.json` (mismo formato que el del bot). Solo la API escribe ahí y solo ella baja
(yt-dlp, `.webm` con audio **Opus**, archivo `yt-<id de YouTube>.webm`; otras webs `u-<resumen del enlace>`).
**Tope de 15 GB** (`MUSIC_GB` en `docker-compose.yml`): al pasarlo borra lo que hace más que no suena, contando
lo que suena en la app y (cuando lo use) en Discord. La lógica (`server/library.py`) es la clase `Cache` del bot
traída tal cual: índice de palabras, autocompletado, faltas de ortografía, álbumes.

```
  App ──(internet, sesión de Google, puerto 8000)──►┐
                                                    ├──► API de música ──► /var/lib/music + index.json
  Bot ──(red interna Docker, su clave, puerto 8001)─►┘     única que escribe y baja
   └── lee los archivos directo del disco (solo lectura) para reproducir con FFmpeg
```

**Transición (mientras el bot no cambie):** el bot sigue con su carpeta `/var/lib/musicbot/cache` y su
catálogo, como siempre. La biblioteca se creó con **enlaces duros** a sus archivos (mismo disco: no ocupa el
doble; los archivos siguen siendo de root, como los crea el bot). Cada minuto la API mira el catálogo del bot
y **copia** lo nuevo que haya bajado (entre montajes de Docker no se puede enlazar). Lo que borre el bot no se
borra de la biblioteca. Al terminar con el bot: quitar `sync_from_bot` de `app.py`, los montajes `/bot-cache` y
`/bot-data`, y la carpeta vieja.

**Falta: el bot** (en `~/MusicBot`, con copia antes con `~/MusicBot/respaldo.sh` y avisando: reiniciar el bot
corta la música en Discord). `MusicBot/bot.py` (~3.000 líneas) usa su clase `Cache` (instancia `CACHE`) en
muchos sitios: `fetch_audio`, búsqueda/sugerencias (`CACHE.match`, `suggest`, `search`, `peek`), menú de
guardadas, olvidar, `stats`, álbumes, `learn_meta`. El plan es sustituir `Cache` por un cliente de las rutas
`/interno` con la misma interfaz, y en su `docker-compose.yml`: unirse a la red `musicapp_default`, montar
`/var/lib/music` solo lectura y llevar `BOT_API_KEY` en su `.env`. Pendiente de decidir: si la API está caída,
que el bot siga tocando lo guardado leyendo `index.json` en solo lectura.

### Servidor (`server/`)

Python con **FastAPI** + **yt-dlp** en el contenedor `musicapp-api` (usuario 1000, no root; actualiza yt-dlp
en cada arranque, como el bot). Para pruebas desde este servidor: `127.0.0.1:8090` (app) y `127.0.0.1:8091` (bot).

| Ruta | Qué hace |
|---|---|
| `GET /health` | `{"ok": true}`, sin clave |
| `POST /auth/google` | Cuerpo `{"id_token": "…"}` (el que da Google a la app). Aprobado → `{"session": …, "user": …}` (sesión de 90 días); nuevo o pendiente → 403 `pendiente`; bloqueado → 403 `bloqueado`. Sin clave |
| `GET /me` | Quién es el dueño de la sesión |
| `POST /auth/logout` | Cierra la sesión usada |
| `GET /acceso` | Página para pasar a los amigos: entran con Google y les dice si quedaron pendientes o ya aprobados. No reproduce nada (si está aprobado, cierra la sesión al momento). Sin clave |
| `GET /prueba-login` | Página para probar el login de Google en el navegador (buscar y escuchar con la sesión). Sin clave |
| `GET /search?q=…` | Primero lo guardado (todas las palabras en título/artista/álbum, mejor primero), luego 5 de YouTube, sin repetir. Cada resultado: `id`, `title`, `artist`, `album`, `duration`, `thumb`, `where` (`guardada`/`youtube`). `&yt=0` = solo lo guardado |
| `GET /stream/<id>` | El audio (`audio/webm`, Opus) por ID de YouTube. Si no está guardado lo baja (una sola vez aunque lo pidan varios a la vez). Admite `Range` (saltar dentro de la canción). Cabecera `X-Source` dice de dónde salió |

**Rutas del bot** (`/interno/…`): en **otro puerto, el 8001**, dentro del mismo proceso (comparten
biblioteca y candados). Los túneles solo reenvían al 8000, así que desde internet no existen (404). Piden
`Authorization: Bearer <BOT_API_KEY>` (en `server/.env`; la de la app no vale). Las canciones van por clave
(`yt-<id>` o `u-<resumen>`); `file` es el nombre del archivo dentro de `/var/lib/music`.

| Ruta | Qué hace (equivale en el bot a) |
|---|---|
| `GET /interno/match?q=…&fuzzy=1` | La mejor guardada con todas las palabras: `{song, more}` (`CACHE.match`) |
| `GET /interno/matches?q=…&limit=` | Todas las que tienen todas las palabras (`matches`, menú de `?`) |
| `GET /interno/suggest?q=…&limit=` | Autocompletado por trozos de palabra; sin texto, las más puestas (`suggest`) |
| `GET /interno/search?q=…&limit=` | Texto tal cual en título/artista/álbum, recientes primero (`search`) |
| `GET /interno/albums`, `GET /interno/album?q=…` | Álbumes y sus canciones (`albums`, `album_tracks`) |
| `GET /interno/stats` | `{songs, bytes, max_bytes}` (`stats`) |
| `GET /interno/song/<clave>` | Ficha sin contarla como puesta (`peek`) |
| `POST /interno/played/<clave>` | Sonó: suma una vez puesta y actualiza el último uso (`get`) |
| `POST /interno/fetch` | `{"url": …, "by": <id de Discord>}`: "dame esta canción". Guardada → `source: local`; si no, la baja → `online`; directos → `live`, sin archivo y con `info.url` para escucharlo (`fetch_audio`) |
| `POST /interno/ficha/<clave>` | Completa artista/álbum preguntándole a YouTube; 503 si está bloqueado (`learn_meta`) |
| `DELETE /interno/song/<clave>` | Olvidar: borra archivo y ficha (`remove`) |

Si YouTube pide "confirmar que no eres un bot", el servidor deja de preguntarle 15 min (insistir alarga el
bloqueo); lo guardado sigue sonando.

**Clave:** `/search`, `/stream`, `/me` y `/auth/logout` piden una **sesión** de un usuario aprobado como
`Authorization: Bearer …` o `?token=…`. Mientras no haya app también vale la clave compartida `API_TOKEN`
(en `server/.env`, fuera de git); se quitará cuando la app tenga login.

**Usuarios** (`users.py`; datos en `server/data/users.json` y `sessions.json`, fuera de git, permisos 600): quien entra con Google por primera vez queda **pendiente** (máximo 30 pendientes a la vez);
se aprueba o bloquea a mano. Se guarda por el `sub` de Google (ID fijo de la cuenta), no por email. De las
sesiones solo se guarda su hash. Bloquear cierra sus sesiones al momento.

**Panel** para aprobar rápido (estilo htop, como el de ProjectV1): `~/MusicApp/server/panel.py`. Lista numerada
(pendientes primero, se actualiza sola); `:1` aprueba al 1, `:1 3 4` a varios, `:B 2` bloquea (pide confirmar),
`:H` ayuda, `:Q` sale. Los números no se mueven mientras escribes. Por debajo usa `users.py`:

```bash
docker exec musicapp-api python users.py                       # lista
docker exec musicapp-api python users.py aprobar amigo@gmail.com
docker exec musicapp-api python users.py bloquear amigo@gmail.com
```

Arrancar y probar desde el servidor:

```bash
cd ~/MusicApp/server
docker compose up -d --build api        # arrancar / actualizar tras cambiar app.py o library.py
T=$(grep API_TOKEN .env | cut -d= -f2)
curl -H "Authorization: Bearer $T" "http://127.0.0.1:8090/search?q=daft+punk+one+more+time"
curl -H "Authorization: Bearer $T" -o cancion.webm "http://127.0.0.1:8090/stream/FGBhQbmPwH8"
```

## 2. Acceso y seguridad

**Túnel: Cloudflare**, con el dominio propio `yoneapolis.com` (cuenta de Cloudflare mía; el túnel
`finops-tunnel-1` de este servidor es de la cuenta de mi hermano y no tiene nada que ver). El contenedor
`cloudflared` abre una conexión **de salida** hacia Cloudflare; quien entra a `musica.yoneapolis.com` llega
por ahí hasta la API. Los amigos no instalan nada más que la app. La dirección pública y su destino
(`http://api:8000`) se configuran en el panel: *Zero Trust → Networks → Tunnels → musicapp*. Su token va en
`server/.env` (`CF_TUNNEL_TOKEN`); es como una contraseña: si se filtra, se rota desde ese mismo panel.
El mismo túnel publica también `yoneapolis.com` → `http://yoneapolis-web:80`, una página aparte en
`~/Yoneapolis/` (página de broma, temporal) cuyo contenedor se une a la red `musicapp_default` solo
para eso. Cómo quitarla: `~/Yoneapolis/README.md`.

El túnel **solo reenvía, no filtra**: toda petición llega a la API, así que la API se protege sola:

- **Solo se expone la API**, no el servidor: desde esa dirección no se llega a nada más (otros proyectos,
  bases de datos, SSH). Los contenedores de los túneles van en la red propia del proyecto y solo ven la API;
  la API solo recibe su `API_TOKEN`, no las claves de los túneles.
- **Login con Google y aprobación manual.** La app pide el login a Google y manda a la API el ID token; la
  API comprueba la firma de Google, que el token sea para nuestro cliente y que el email esté verificado.
  Cualquier cuenta de Google puede pedir acceso (la app está **publicada** en Google Cloud, proyecto
  `musicapp`), pero solo entra quien se aprueba. Cliente OAuth **web**
  `76813509622-rpbjrvn23rpjgrkulb051tjgids6f80j.apps.googleusercontent.com` (en `docker-compose.yml`, no es
  secreto; su *client secret* no se usa). Para la app Android hará falta además un cliente **Android**
  (nombre de paquete + SHA-1 de la llave de firma). Enlace para que los amigos pidan acceso:
  `https://musica.yoneapolis.com/acceso` (se aprueban con el panel). Google solo deja usar su botón en
  orígenes autorizados del cliente web: hoy `https://musica.yoneapolis.com`.
- **Bloqueo automático (sin hacer):** a quien insista (demasiados fallos o peticiones seguidas) bloquearlo un
  tiempo, cada vez más largo, y apuntarlo en el registro. Cloudflare pasa la IP real en `CF-Connecting-IP`
  (por Funnel no llega, otra razón para apagarlo). Hacerlo antes de repartir la app.
- La API solo hace cosas de música: no ejecuta comandos ni toca archivos fuera de `/var/lib/music` y su `data/`.
  El ID o la clave de canción se validan antes de buscar archivos. Corre sin root, así que no puede leer las
  cookies del bot aunque su carpeta `data/` esté montada (solo lectura, para su `index.json`).
- **Cookies de YouTube:** `server/data/youtube-cookies.txt` (dueño 1000, permisos 600), copia de las del bot;
  yt-dlp las usa si existen. Si se renuevan las del bot, volver a copiarlas:
  `sudo install -o 1000 -g 1000 -m 600 ~/MusicBot/data/cookies.txt ~/MusicApp/server/data/youtube-cookies.txt`.
  Son de una cuenta desechable; si se filtran, se cierra la sesión de esa cuenta en Google.
- **Rutas del bot** (`/interno`): puerto 8001 al que los túneles no reenvían, más su propia clave. Dentro de la
  red `musicapp_default` sí se alcanza (el bot lo necesita), pero sin la clave da 401.

**Velocidad (medida):** desde este servidor contra su propia dirección pública (ida y vuelta por internet),
con una canción de 3,8 MB (3:42, ~140 kbps):

| Prueba | Cloudflare | Tailscale Funnel |
|---|---|---|
| Hasta el primer byte del audio | ~0,4–0,5 s | ~1,4 s |
| 1 descarga | ~1,5 MB/s (~12 Mbps), la canción en 2,5 s | 150–225 KB/s |
| 6 descargas a la vez | ~256 KB/s cada una, ~12 Mbps en total (~15× lo que dura la canción) | 63–107 KB/s cada una, ~3 Mbps en total |
| APK al actualizar (~30–50 MB) | ~30 s | ~3–5 min |

Con Cloudflare el tope parece ser la subida de internet de casa (~12 Mbps), no el túnel. Falta confirmarlo
desde móviles fuera de casa. Aun así, audio en Opus ~96 kbps y la app guarda lo ya escuchado para no volver
a pedirlo.

**Respaldo: Tailscale Funnel** (contenedor `musicapp-tailscale`, `https://musicapp.tail66213e.ts.net`).
Gratis y sin dominio, pero más lento (tabla de arriba) y sin la IP real del cliente. Necesita el permiso
`funnel` en la política de Tailscale (`nodeAttrs` para `autogroup:member`, cuenta `yonisrubiocl@gmail.com`).
Se apaga cuando el dominio esté probado desde móviles.

El servidor en sí va sobrado (4 núcleos, 15 GB de RAM): el posible cuello de botella es el túnel.

## 3. Actualizaciones de la app

La app **se actualiza desde dentro**, sin Play Store:

1. Al abrirse, pregunta al servidor si hay versión nueva.
2. Si la hay: aviso "Hay una versión nueva · Actualizar". Un toque descarga el `.apk` desde nuestro servidor
   y Android pregunta "¿Instalar?". La primera vez, Android pide permitir instalar apps de esta fuente.
3. **Todas las versiones se firman con la misma llave.** Si se pierde, Android no deja actualizar y todos
   tendrían que desinstalar e instalar de nuevo: la llave va con copia de seguridad, fuera de git.

Lo que vive en el servidor (búsqueda, letras, descargas) mejora para todos al instante sin actualizar la
app, así que se pone en el servidor todo lo que se pueda. Más adelante, si molestan los toques, se puede
añadir **Shorebird** (cambios de código Dart aplicados solos al abrir la app, sin APK nuevo).

## 4. Plan por fases

Cada fase funciona por sí sola.

| Fase | Qué | Estado |
|---|---|---|
| 1 | **Servidor mínimo:** buscar una canción y escucharla (probado sin app) + publicarlo y **medir la velocidad del túnel** | Hecho |
| 1b | **Login con Google** en el servidor (aprobación manual con panel, sesiones de 90 días) | Hecho (falta en la app y el bloqueo automático) |
| 1c | **Biblioteca única:** la API dueña de la música, el bot cliente suyo (ver "Canciones") | API hecha; falta el bot (siguiente) |
| 2 | **App mínima:** login con Google, búsqueda, play y que suene + actualizador propio. Al tenerla, quitar `API_TOKEN` | Pendiente |
| 3 | **Reproductor de verdad:** cola, siguiente/anterior, segundo plano y pantalla de bloqueo (`just_audio`, `audio_service`) | Pendiente |
| 4 | Listas, favoritos, historial, letras y portadas | Pendiente |
| 5 | Descargas para escuchar sin conexión, ver qué escuchan los amigos, escuchar juntos | Pendiente |

## 5. Pendiente de mi parte

- Instalar en el PC **Flutter** y **Android Studio** (con su emulador, o usar el móvil por USB).
- Con la app: crear en Google Cloud (proyecto `musicapp`) el **cliente OAuth Android** (nombre de paquete +
  SHA-1 de la llave de firma, que se crea entonces, con copia de seguridad).
- Probar `musica.yoneapolis.com` desde el móvil con datos; si va bien, apagar Funnel (`musicapp-tailscale`).
- Decidir si la sesión se renueva sola con el uso (ahora caduca a los 90 días y la app tendría que volver a
  pedir el login a Google, sin que yo apruebe de nuevo).

## 6. Carpetas

```
/home/lainer/MusicApp/
├── server/
│   ├── app.py              la API (FastAPI): puerto 8000 para la app, 8001 para el bot
│   ├── library.py          la biblioteca única (carpeta + catálogo, búsqueda, tope de espacio)
│   ├── users.py            usuarios y sesiones (login con Google, aprobar/bloquear por comando)
│   ├── panel.py            panel de terminal para aprobar/bloquear usuarios (se ejecuta en el servidor, no en Docker)
│   ├── Dockerfile
│   ├── docker-compose.yml  contenedores musicapp-api, musicapp-cloudflared y musicapp-tailscale (red propia musicapp_default)
│   ├── funnel.json         qué publica Funnel (respaldo): https://musicapp.<tailnet>.ts.net -> api:8000
│   ├── .env                API_TOKEN, BOT_API_KEY, CF_TUNNEL_TOKEN y TS_AUTHKEY (fuera de git; plantilla en .env.example)
│   └── data/               catálogo index.json (+ .bak y .antes-biblioteca), users.json, sessions.json, cookies de YouTube y estado de Tailscale (fuera de git)
├── README.md     este documento
└── .gitignore    ignora .env, data/ y __pycache__/
```
