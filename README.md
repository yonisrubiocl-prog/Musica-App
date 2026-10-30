# MusicApp: app de música propia

> **Regla de este documento:** describe **cómo está el proyecto ahora**, no su historia. Al cambiar algo,
> se **reescribe la parte afectada y se borra lo viejo o ya realizado**; no se añaden notas sueltas al
> final ni "actualizaciones" encima de texto desfasado. Debe poder leerse de arriba abajo sin
> contradicciones. Lo histórico está en git, no aquí.

App de música propia, tipo Spotify: buscas una canción, le das a play y **suena en el móvil o el PC**.
No es un mando del bot de Discord (`MusicBot`, otro proyecto): solo comparten la música guardada, que es de esta
API; el bot se la pide (ver "Canciones").

Es un proyecto **por diversión y para aprender**: privado, solo para mí y mis amigos (unas 6 personas),
sin publicarlo ni cobrar nada.

**Estado actual:**
- **Servidor** hecho y publicado en `https://musica.yoneapolis.com` (túnel de Cloudflare, dominio propio;
  `https://yoneapolis.com` lleva aquí). Tailscale Funnel (`https://musicapp.tail66213e.ts.net`) sigue encendido
  como respaldo. Login con Google con aprobación manual, búsqueda tolerante a faltas, búsquedas a YouTube
  recordadas, y la página principal que reparte la app a los aprobados.
- **Biblioteca única** hecha: la API es la dueña de la música (`/var/lib/music`) y el bot de Discord es cliente suyo.
- **App** (fase 2) en marcha: **1.0.2 (build 3) publicada**, con aviso de actualización propio (`/app/version`).

**Quién hace qué:** el servidor (este repo) se trabaja en una sesión de Claude en este servidor. La **app
Flutter** se trabaja en otra sesión de Claude **en el PC**, con su propio proyecto: desde el servidor no se
puede hablar con ella (no sale en la lista de sesiones), así que los avisos de cambios de la API que le afecten
se le pasan a mano, como texto. Cada sesión toca solo lo suyo: la app no toca `server/` y el servidor no toca
la app ni `/var/lib/musicapp/app/` (lo que ella publica).

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
| **Servidor** (`server/`) | Este servidor, en Docker | API de música, dueña de la biblioteca. Si se cae, el bot sigue tocando lo guardado pero no puede bajar nada nuevo |
| **App** | PC del usuario | Flutter (Android y PC; iPhone algún día). Se desarrolla allí porque este servidor no tiene pantalla para el emulador |
| **Túnel** | Contenedor `cloudflared` aquí + Cloudflare | Da la dirección pública con HTTPS sin abrir puertos. Dominio `yoneapolis.com` (mío, en Cloudflare), pensado para todos mis proyectos con un subdominio cada uno |
| **Canciones** | `/var/lib/music` (la biblioteca única) | Fuera del proyecto: `/home` tiene poco espacio, `/var` tiene de sobra. Ver "Canciones" abajo |

### Canciones

La **API es la dueña de la música**: una carpeta `/var/lib/music` (~1.900 canciones, ~7 GB) con su catálogo
`index.json` dentro (y `index.json.bak`, la versión anterior). Solo la API escribe ahí y solo ella habla con
YouTube: buscar y bajar (yt-dlp, `.webm` con audio **Opus**, archivo `yt-<id de YouTube>.webm`; otras webs
`u-<resumen del enlace>`). **Tope de 15 GB** (`MUSIC_GB` en `docker-compose.yml`): al pasarlo borra lo que hace
más que no suena, contando la app y Discord. La lógica está en `server/library.py`: índice de palabras,
autocompletado, faltas de ortografía, álbumes (la misma que tenía el bot).

```
  App ──(internet, sesión de Google, puerto 8000)──►┐
                                                    ├──► API de música ──► /var/lib/music (canciones + index.json)
  Bot ──(red interna Docker, su clave, puerto 8001)─►┘     única que escribe y habla con YouTube
   └── lee index.json y los archivos directo del disco (solo lectura): buscar al instante y FFmpeg
```

**Quién hace qué con `index.json`:**

- **La API lo controla:** es la única que lo escribe (añadir, borrar, contar veces puesta, completar fichas).
- **El bot solo lo lee:** lo tiene montado en solo lectura (no podría escribirlo aunque quisiera) y guarda una
  copia en memoria. Cada 3 s mira si el archivo cambió y, si cambió, lo relee (~0,03 s). Con esa copia busca y
  reproduce lo guardado sin preguntar a nadie: instantáneo, y sigue sonando aunque la API esté caída. Lo que
  cambia algo (bajar, "sonó", olvidar, fichas) o busca en YouTube se lo pide a la API por las rutas `/interno`.
- **La app** no ve el disco (está en el móvil): todo lo consulta a la API por internet (`/search`, `/stream`).
- **Los dos usan el mismo catálogo y la misma carpeta.** Una canción bajada desde la app la ve el bot en unos
  segundos y suena en Discord como 💾 Local sin volver a bajarse; una bajada desde Discord la encuentra la app
  al buscar. Probado el 29-10-2026 (Culpables · KAROL G: primera vez 🌐 Online, la segunda 💾 Local).

### Repartir la app

La app (Android) se baja desde la página principal: `https://musica.yoneapolis.com/` (también `/acceso`;
`https://yoneapolis.com` lleva aquí). Quien entra con
Google y **ya está aprobado** empieza a bajarla sola, sin ver ningún enlace (por si el navegador bloquea la
descarga automática hay un "¿No empezó? toca aquí"); el resto, lo de siempre (pendiente o sin acceso). Por
debajo es un enlace de 10 min sin la sesión dentro. No es de un solo uso a propósito: los navegadores de Android
a veces piden el archivo dos veces o retoman una descarga cortada, y gastarían el enlace. Tampoco hace falta
más: lo que protege la música es el login dentro de la app; un APK pasado por WhatsApp no reproduce nada sin una
cuenta aprobada. Mientras no haya APK, al aprobado le dice "todavía no está lista".

**Publicar una versión:** lo hace la sesión de la app desde el PC (`tools/publicar.ps1` del proyecto Flutter):
sube el APK firmado a `/var/lib/musicapp/app/musica.apk` y escribe al lado `version.json` (`build` y `version`).
La carpeta está montada solo lectura en la API como `/app-dist`. Sin reiniciar nada: el siguiente que entre en
la página baja la nueva, y la app instalada lo ve en `/app/version` y avisa. **No hacer pruebas en esa carpeta**
(una prueba ya borró un APK publicado): probar con otro nombre de archivo. Solo Android: en iPhone no se
pueden instalar apps fuera de la tienda. El actualizador de la app usa este mismo archivo.

Restos de antes de juntar las carpetas (se pueden borrar cuando se quiera, con `sudo`):
`/var/lib/musicbot/cache` (los mismos archivos que la biblioteca, enlazados: borrarla casi no libera espacio
ni quita canciones), `/var/lib/musicapp/cache`, `~/MusicBot/data/index.json*` y `~/MusicBot/data/cookies.txt`;
y en `server/data/`, `index.json.antes-biblioteca`.

### Servidor (`server/`)

Python con **FastAPI** + **yt-dlp** en el contenedor `musicapp-api` (usuario 1000, no root; actualiza yt-dlp
en cada arranque, como el bot). Para pruebas desde este servidor: `127.0.0.1:8090` (app) y `127.0.0.1:8091` (bot).

| Ruta | Qué hace |
|---|---|
| `GET /health` | `{"ok": true}`, sin clave |
| `POST /auth/google` | Cuerpo `{"id_token": "…"}` (el que da Google a la app). Aprobado → `{"session": …, "user": …}` (sesión de 90 días); nuevo o pendiente → 403 `pendiente`; bloqueado → 403 `bloqueado`. Sin clave |
| `GET /me` | Quién es el dueño de la sesión |
| `POST /auth/logout` | Cierra la sesión usada |
| `GET /` y `GET /acceso` | **La página principal** (`server/web/acceso.html`, con el estilo Dark Premium de la app y el logo del perrito). Página para pasar a los amigos: entran con Google y les dice si quedaron pendientes o ya aprobados. **Al aprobado le empieza a bajar la app sola** (ver "Repartir la app"); su sesión solo se usa para pedir ese enlace y se cierra al momento. No reproduce nada. Sin clave |
| `GET /logo.png` | El logo (`server/web/logo.png`, 512×512), también icono de la pestaña. Sin clave |
| `POST /app/enlace` | Para aprobados: enlace de descarga de la app que sirve 10 min (`{url, minutes, size, date}`); 404 si aún no hay APK |
| `GET /app/version` | Versión publicada de la app (`version.json` junto al APK: `{"build": 3, "version": "1.0.2"}`); la app avisa si `build` es mayor que el suyo y se actualiza con `/app/enlace`. 404 si no hay. Pide sesión |
| `GET /app/descargar/<enlace>` | El APK (`musica.apk`). Enlace caducado o inventado → 404. Sin clave: el enlace ya lo es |
| `GET /prueba-login` | Página para probar el login de Google en el navegador (buscar y escuchar con la sesión). Sin clave |
| `GET /search?q=…` | Primero lo guardado (hasta 20; todas las palabras en título/artista/álbum, pero cada una vale exacta, a medio escribir, en plural/singular o con faltas: "one pilot", "chayane", "stresed out" encuentran lo suyo; las exactas primero. Ver `Library.find`), luego 5 de YouTube, sin repetir. Cada resultado: `id`, `title`, `artist`, `album`, `duration`, `thumb`, `where` (`guardada`/`youtube`). `&yt=0` = solo lo guardado |
| `GET /stream/<id>` | El audio (`audio/webm`, Opus) por ID de YouTube. Si no está guardado lo baja (una sola vez aunque lo pidan varios a la vez). Admite `Range` (saltar dentro de la canción). Cabecera `X-Source` dice de dónde salió |

**Rutas del bot** (`/interno/…`; el bot lee el catálogo del disco, así que de búsqueda solo usa `resolve`, y el
resto están para lo que haga falta): en **otro puerto, el 8001**, dentro del mismo proceso (comparten
biblioteca y candados). Los túneles solo reenvían al 8000, así que desde internet no existen (404). Piden
`Authorization: Bearer <BOT_API_KEY>` (en `server/.env`; la de la app no vale). Las canciones van por clave
(`yt-<id>` o `u-<resumen>`); `file` es el nombre del archivo dentro de `/var/lib/music`.

| Ruta | Qué hace |
|---|---|
| `GET /interno/match?q=…&fuzzy=1` | La mejor guardada con todas las palabras: `{song, more}` |
| `GET /interno/matches?q=…&limit=` | Todas las que tienen todas las palabras |
| `GET /interno/suggest?q=…&limit=` | Autocompletado por trozos de palabra; sin texto, las más puestas |
| `GET /interno/search?q=…&limit=` | Texto tal cual en título/artista/álbum, recientes primero |
| `GET /interno/albums`, `GET /interno/album?q=…` | Álbumes y sus canciones |
| `GET /interno/stats` | `{songs, bytes, max_bytes}` |
| `POST /interno/resolve` | `{"query": …, "limit": n}`: buscar en YouTube (un nombre o `ytsearch5:…`) o leer un enlace (video, lista, SoundCloud…) sin bajar nada. Título, duración, miniatura y `entries` si es lista o búsqueda |
| `GET /interno/song/<clave>` | Ficha sin contarla como puesta |
| `POST /interno/played/<clave>` | Sonó: suma una vez puesta y actualiza el último uso |
| `POST /interno/fetch` | `{"url": …, "by": <id de Discord>}`: "dame esta canción". Guardada → `source: local`; si no, la baja → `online`; directos → `live`, sin archivo y con `info.url` para escucharlo |
| `POST /interno/ficha/<clave>` | Completa artista/álbum preguntándole a YouTube; 503 si está bloqueado |
| `DELETE /interno/song/<clave>` | Olvidar: borra archivo y ficha |

**Pocas peticiones a YouTube** (para YouTube buscar y bajar son lo mismo: peticiones desde nuestra IP, y muchas
seguidas parecen un bot):

- La app lista **solo lo guardado** (`/search?…&yt=0`, al instante) y tiene un botón aparte "buscar en YouTube".
- **Búsquedas recordadas 7 días** (`YouTubeSearches` en `app.py`, en `server/data/youtube-searches.json`, hasta
  3.000): la misma búsqueda, desde la app o desde el bot, no vuelve a preguntarle a YouTube. Sin distinguir
  mayúsculas, tildes ni espacios ("Karol G" = "karol g"). El registro dice cuántas salieron de memoria.
- Una canción se baja **una sola vez** para todos (biblioteca única) y su ficha se pide una sola vez.
- **Ritmo con YouTube** (`yt_turn` en `app.py`): lo que hace saltar el bloqueo son las ráfagas (el del 25-10-2026
  fue una importación de 1.236 canciones seguidas), no el uso normal. Toda petición a YouTube (búsqueda, descarga
  o ficha; de la app, del bot o de una importación) espera su turno: **una cada 4 s y como mucho 120 por hora**.
  Si el turno tardaría más de 45 s, contesta 429 "muchas peticiones a YouTube, prueba en ~N min" (el bot lo
  trata como un bloqueo: una importación espera y sigue). Lo recordado (búsquedas, canciones guardadas) no pasa
  por aquí. Constantes `YT_GAP`, `YT_PER_HOUR`, `YT_MAX_WAIT`.
- **Por dónde sale:** la API sale a YouTube solo por **IPv4** (la pública de casa; los contenedores no tienen
  IPv6). La tele, los móviles y los navegadores de casa suelen ir a YouTube por IPv6, así que un bloqueo por culpa
  del servidor casi no se notaría en casa (no es seguro al 100 %). **Último recurso** si bloquean la IPv4:
  apagar el router un rato suele dar otra IP (depende del proveedor: a veces devuelve la misma si vuelve
  pronto). El túnel de Cloudflare se reconecta solo con la IP nueva.
- **Ideas pendientes** si hiciera falta más: generador de "PO tokens" para yt-dlp (`bgutil-ytdlp-pot-provider`,
  que YouTube nos vea como un navegador) y **Cloudflare WARP** como salida de reserva o para picos (sus IP las
  comparten miles: YouTube desconfía más de ellas; por ahí, sin cookies).
- Si YouTube pide "confirmar que no eres un bot", el servidor deja de preguntarle 15 min (insistir alarga el
  bloqueo); lo guardado sigue sonando.

**Clave:** `/search`, `/stream`, `/me` y `/auth/logout` piden una **sesión** de un usuario aprobado como
`Authorization: Bearer …` o `?token=…`. Mientras no haya app también vale la clave compartida `API_TOKEN`
(en `server/.env`, fuera de git); se quitará cuando la app tenga login.

**Usuarios** (`users.py`; datos en `server/data/users.json` y `sessions.json`, fuera de git, permisos 600): quien entra con Google por primera vez queda **pendiente** (máximo 30 pendientes a la vez);
se aprueba o bloquea a mano. Se guarda por el `sub` de Google (ID fijo de la cuenta), no por email. Bloquear
cierra sus sesiones al momento.

**Qué sabemos de cada uno** (solo el permiso básico "perfil y email" de Google; es lo que enseña la pantalla
de Google al entrar):

| Dato | Para qué |
|---|---|
| `sub` (ID de la cuenta de Google) | Identificarla; no cambia aunque cambie el email |
| Email | Verla en el panel y aprobarla. Sin email verificado no se entra |
| Nombre | El saludo de la app |
| Foto (enlace a la de Google) | El avatar de la app |
| Estado (`pendiente` / `aprobado` / `bloqueado`), `since` (primera vez), `seen` (último login) | Acceso y panel |

De cada **sesión** solo se guarda su hash, de quién es y cuándo caduca (90 días). **No** hay contraseñas ni
acceso a Gmail, Drive, contactos, etc.: Google da un justificante firmado de quién eres, se comprueba y se tira;
no se guarda ningún token que sirva para entrar en la cuenta de Google. Lo demás que trae el justificante
(nombre y apellido por separado, idioma…) no se guarda.

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
`~/Yoneapolis/` (por ahora solo redirige a `https://musica.yoneapolis.com/`) cuyo contenedor se une a la red `musicapp_default` solo
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
- **Cookies de YouTube:** `server/data/youtube-cookies.txt` (dueño 1000, permisos 600); yt-dlp las usa si
  existen. Son de una cuenta desechable (si se filtran, se cierra la sesión de esa cuenta en Google). Cómo
  renovarlas sin que YouTube las rote: `~/MusicBot/README.md`, sección 6.
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
desde móviles fuera de casa. Una canción (~134 kbps, ver "Calidad del audio") ocupa ~1/90 de esa subida.

**Respaldo: Tailscale Funnel** (contenedor `musicapp-tailscale`, `https://musicapp.tail66213e.ts.net`).
Gratis y sin dominio, pero más lento (tabla de arriba) y sin la IP real del cliente. Necesita el permiso
`funnel` en la política de Tailscale (`nodeAttrs` para `autogroup:member`, cuenta `yonisrubiocl@gmail.com`).
Se apaga cuando el dominio esté probado desde móviles.

El servidor en sí va sobrado (4 núcleos, 15 GB de RAM): el posible cuello de botella es el túnel.

## 3. Actualizaciones de la app

La app **se actualiza desde dentro**, sin Play Store:

1. Al abrirse pregunta al servidor `GET /app/version` (con su sesión) y compara el `build` con el suyo.
2. Si hay uno mayor: aviso "Hay una versión nueva · Actualizar". Un toque pide `/app/enlace`, baja el `.apk`
   desde nuestro servidor y Android pregunta "¿Instalar?". La primera vez, Android pide permitir instalar apps
   de esta fuente. Se instala encima: no se pierde nada.
3. **Publicar** una versión: desde el PC, `tools/publicar.ps1` del proyecto de la app sube el APK y escribe
   `version.json` en `/var/lib/musicapp/app/` (ver "Repartir la app"). Sin reiniciar el servidor.
4. **Todas las versiones se firman con la misma llave.** Si se pierde, Android no deja actualizar y todos
   tendrían que desinstalar e instalar de nuevo: la llave va con copia de seguridad, fuera de git.

Lo que vive en el servidor (búsqueda, letras, descargas) mejora para todos al instante sin actualizar la
app, así que se pone en el servidor todo lo que se pueda. Más adelante, si molestan los toques, se puede
añadir **Shorebird** (cambios de código Dart aplicados solos al abrir la app, sin APK nuevo).

## 3b. Calidad del audio

Se baja **lo mejor que YouTube da sin Premium**: Opus en `.webm`, 48 kHz, estéreo, **~134 kbps** de mediana
(el 80 % entre 126 y 144; medido el 29-10-2026 sobre las ~1.900 canciones). Quedan 16 antiguas en AAC `.m4a`
~128 kbps. Opus a ~130 suena más o menos como un MP3 de 192–256: comparable a Spotify "Alta" (160), por
debajo de "Muy alta" (320) y del sin pérdida.

- **App:** el archivo llega tal cual, sin recomprimir.
- **Discord:** el bot recomprime a 128 kbps y Discord limita el canal de voz (64–96 kbps normalmente): ahí el
  tope lo pone Discord, no la descarga.

**¿Más calidad?** YouTube Music da 256 kbps (Opus) solo a cuentas **Premium**. Con la cuenta Premium personal
**no**: sus cookies caducan al seguir usándola en el móvil (YouTube las rota) y, si YouTube lo detecta, se
arriesga la cuenta de Google entera. El ritmo no sería el problema (1 canción cada 10 min parece uso normal; las
~1.900 se rehacen en ~2 semanas). Si compensa, la opción buena es una **cuenta nueva solo para el servidor como
miembro del plan Familiar** de Premium (solo con plan Familiar). **Antes, prueba a ciegas:** bajar una canción en
el PC en las dos calidades (`yt-dlp`, con `--cookies-from-browser` para la de 256) y ver si se distingue. Si no
se distingue, no vale la pena.

## 4. Plan por fases

Cada fase funciona por sí sola.

| Fase | Qué | Estado |
|---|---|---|
| 1 | **Servidor mínimo:** buscar una canción y escucharla (probado sin app) + publicarlo y **medir la velocidad del túnel** | Hecho |
| 1b | **Login con Google** en el servidor (aprobación manual con panel, sesiones de 90 días) | Hecho (falta en la app y el bloqueo automático) |
| 1c | **Biblioteca única:** la API dueña de la música, el bot cliente suyo (ver "Canciones") | Hecho |
| 2 | **App mínima:** login con Google, búsqueda, play y que suene + actualizador propio. Al tenerla, quitar `API_TOKEN` | En marcha (1.0.2 publicada, actualizador hecho) |
| 3 | **Reproductor de verdad:** cola, siguiente/anterior, segundo plano y pantalla de bloqueo (`just_audio`, `audio_service`) | Pendiente |
| 4 | Listas, favoritos, historial, letras y portadas | Pendiente |
| 5 | Descargas para escuchar sin conexión, ver qué escuchan los amigos, escuchar juntos | Pendiente |

## 5. Pendiente

- Con la app: crear en Google Cloud (proyecto `musicapp`) el **cliente OAuth Android** si la app lo necesita
  (nombre de paquete + SHA-1 de la llave de firma, con copia de seguridad).
- Probar `musica.yoneapolis.com` desde el móvil con datos; si va bien, apagar Funnel (`musicapp-tailscale`).
- **Bloqueo automático** (sección 2) antes de repartir la app a todos.
- Quitar `API_TOKEN` cuando la app no lo use (ni `/prueba-login`).
- Decidir si la sesión se renueva sola con el uso (ahora caduca a los 90 días y la app tendría que volver a
  pedir el login a Google, sin que yo apruebe de nuevo).
- **Prueba a ciegas de calidad** (sección 3b) antes de pensar en Premium.
- Repositorio remoto (GitHub) para este repo: hoy solo está en el servidor.
- Borrar los restos de antes de la biblioteca única (sección "Canciones").
- La búsqueda tolerante (`Library.find`) aún no está en el bot de Discord.
- El contenedor `musicapp-prueba` (imagen de la API con `data/` en solo lectura) sigue encendido sin uso aparente.
- `/home` tiene poco sitio (2,8 GB libres de 20 el 29-10-2026; `ProjectV1` ocupa 11 GB): lo que crece
  (música, APK) ya está en `/var`.

## 6. Carpetas

```
/home/lainer/MusicApp/
├── server/
│   ├── app.py              la API (FastAPI): puerto 8000 para la app, 8001 para el bot; también reparte el APK
│   ├── library.py          la biblioteca única (carpeta + catálogo, búsqueda, tope de espacio); la música está en /var/lib/music
│   ├── users.py            usuarios y sesiones (login con Google, aprobar/bloquear por comando)
│   ├── web/                página principal (acceso.html) y logo.png; colores de la app: fondo #080A12,
│   │                       tarjetas #151725, violeta #9B5CFF, rosa #F04DBB, azul #5268FF, texto #FFFFFF / #A3A5B5
│   ├── panel.py            panel de terminal para aprobar/bloquear usuarios (se ejecuta en el servidor, no en Docker)
│   ├── Dockerfile
│   ├── docker-compose.yml  contenedores musicapp-api, musicapp-cloudflared y musicapp-tailscale (red propia musicapp_default)
│   ├── funnel.json         qué publica Funnel (respaldo): https://musicapp.<tailnet>.ts.net -> api:8000
│   ├── .env                API_TOKEN, BOT_API_KEY, CF_TUNNEL_TOKEN y TS_AUTHKEY (fuera de git; plantilla en .env.example)
│   └── data/               users.json, sessions.json, youtube-cookies.txt y estado de Tailscale (fuera de git)
├── README.md     este documento
(/var/lib/musicapp/app/musica.apk   la app para repartir, fuera de git; ver "Repartir la app")
└── .gitignore    ignora .env, data/ y __pycache__/
```
