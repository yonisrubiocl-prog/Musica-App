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

**Estado actual** (30-10-2026):
- **Servidor** hecho y publicado en `https://musica.yoneapolis.com` (túnel de Cloudflare, dominio propio;
  `https://yoneapolis.com` lleva aquí). Tailscale Funnel (`https://musicapp.tail66213e.ts.net`) sigue encendido
  como respaldo. 7 usuarios. ~2.300 canciones (8,1 GB; tope 50 GB).
- **Biblioteca única** hecha: la API es la dueña de la música (`/var/lib/music`) y el bot de Discord es cliente suyo.
- **Buscar:** lo guardado tolera faltas y palabras a medio escribir; lo de internet sale de **YouTube Music**
  (20 canciones nuevas siempre, álbumes en orden), con memoria de 7 días y un ritmo máximo con YouTube.
- **Por usuario:** favoritas, historial y playlists (iguales en la app y la web), máximo 3 dispositivos por cuenta.
- **Catálogo:** artistas → álbumes → canciones, género por artista (MusicBrainz y correcciones a mano), y de
  fondo: fichas de las canciones viejas y **precarga** de los álbumes de estudio de los artistas más escuchados.
- **App Android** (fase 2) en marcha, la lleva otra sesión: **1.0.17 (build 18) publicada**, con aviso de
  actualización propio. **App web** (hecha en el servidor) en `/web/`, a la que lleva la página principal tras entrar.

**Repositorio:** GitHub privado **yonisrubiocl-prog/Musica-App** (solo el servidor; la app Flutter tiene el suyo).
El servidor sube con su propia llave de despliegue, que solo vale para ese repo (`~/.ssh/github_musicapp`, alias
`github-musicapp` en `~/.ssh/config`): `git push` desde `~/MusicApp`. Al terminar cada cambio: commit y push.

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
  App web       (https://musica.yoneapolis.com)  ├─ login con Google + aprobación manual
  (navegador)                                    ├─ buscar: lo guardado y YouTube Music
                                                 ├─ bajar con yt-dlp y guardar en la biblioteca
                                                 ├─ enviar el audio a la app
                                                 └─ favoritas, historial, artistas, álbumes, géneros
  Bot de Discord ── red interna de Docker ──►   (rutas /interno, puerto 8001)
```

| Pieza | Dónde | Qué es |
|---|---|---|
| **Servidor** (`server/`) | Este servidor, en Docker | API de música, dueña de la biblioteca. Si se cae, el bot sigue tocando lo guardado pero no puede bajar nada nuevo |
| **App** | PC del usuario | Flutter, para Android. Se desarrolla allí porque este servidor no tiene pantalla para el emulador. La **app web** es aparte y vive en el servidor (`server/web/web.html`) |
| **Túnel** | Contenedor `cloudflared` aquí + Cloudflare | Da la dirección pública con HTTPS sin abrir puertos. Dominio `yoneapolis.com` (mío, en Cloudflare), pensado para todos mis proyectos con un subdominio cada uno |
| **Canciones** | `/var/lib/music` (la biblioteca única) | Fuera del proyecto: `/home` tiene poco espacio, `/var` tiene de sobra. Ver "Canciones" abajo |

### Canciones

La **API es la dueña de la música**: una carpeta `/var/lib/music` (~2.200 canciones, 8,4 GB el 30-10-2026) con su catálogo
`index.json` dentro (y `index.json.bak`, la versión anterior). Solo la API escribe ahí y solo ella habla con
YouTube: buscar y bajar (yt-dlp, `.webm` con audio **Opus**, archivo `yt-<id de YouTube>.webm`; otras webs
`u-<resumen del enlace>`). **Tope de 50 GB** (`MUSIC_GB` en `docker-compose.yml`; era 15, se subió a 40 y luego a 50 para la precarga de álbumes, que añade ~6.000 canciones / ~26 GB): al pasarlo borra lo que hace
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

### Repartir la app y versión web

**Flujo de la página principal** (`https://musica.yoneapolis.com/`; `https://yoneapolis.com` lleva aquí):
entrar con Google → si está **aprobado**, se abre la **app web** (`/web/`); si no, queda pendiente o sin acceso. La
sesión se guarda en el navegador (`localStorage`): la próxima vez entra directo. Cuenta como uno de los 3
dispositivos; si la cierran (4.º dispositivo), vuelve a la página con el aviso "se cerró tu sesión".

**App web** (`server/web/web.html`, hecha en el servidor con el estilo de la app; la sesión que guarda la
página principal está en `localStorage` con la clave `musica_sesion`). Se probó también la app Flutter compilada
para web (30-10-2026) y se descartó y borró: Flutter en el navegador dibuja la app del móvil en un lienzo (se ve
como un emulador, ~10 MB, no se comporta como una web). Para el navegador, mejor una web propia: toda la lógica
vive en la API y la web solo la enseña. Idea pendiente: diseño de escritorio (menú lateral, cuadrícula,
reproductor a lo ancho abajo). Tiene tres pestañas
abajo como en la app. **Inicio**: saludo con nombre y foto, "Escuchado recientemente" (el mío, `/history`), "Tus
favoritas", artistas y "Lo más puesto". **En pantallas anchas (≥1100 px, PC):** el contenido a la izquierda y el **reproductor grande fijo a la
derecha** (portada viva, controles, volumen, cola y letra), como Spotify en el ordenador, en una **tarjeta flotante
redondeada** con aire alrededor, brillo violeta y un **ecualizador animado** junto a "Reproduciendo" (se mueve solo
mientras suena); sin canción enseña "Aquí
sonará tu música". La barra pequeña de abajo se oculta ahí (el panel tiene los controles). Márgenes simétricos (sin
hueco entre el contenido y el panel). **En pantallas muy anchas (≥1500 px)**, tres tarjetas iguales: **la cola
("Siguiente") a la izquierda**, siempre a la vista, el contenido en medio y el reproductor a la derecha (que
entonces solo tiene la letra, con un interruptor "Letra · ocultar" / "Mostrar letra" que se recuerda). **Cómo se
llena la cola:** tocar una canción suelta (Lo más puesto, búsqueda, biblioteca, género) es **modo radio**: esa
canción y detrás recomendadas, que se van añadiendo solas (~10, y más cuando quedan 2–3); tocar algo que es una
lista es **modo lista**, primero la elegida y luego: **con aleatorio**, todas las demás mezcladas; **sin
aleatorio**, depende de dónde: en las **filas del Inicio** (Escuchado recientemente, Tus favoritas, Para ti, Vuelve
a escuchar) suena **la lista entera** aunque la fila enseñe solo 20 (en orden desde ahí y al final las de antes);
en la **Biblioteca** (Me gusta, una playlist, un álbum) desde ahí hacia abajo, sin volver al principio. La cola solo enseña lo que
viene desde la canción actual, así que el número cambia según suena. En el móvil, como
siempre. **Buscar**: al escribir sale un **cuadro flotante de sugerencias** (como Spotify:
"Buscar «…»", artistas, álbumes y canciones con foto; flechas y Enter; la lista de abajo no cambia mientras se
escribe); los resultados completos salen con Enter (botón aparte "Buscar en YouTube") y, sin texto, toda la biblioteca con scroll infinito (`/library`: Recientes, Populares, A–Z, Por
artista). **Biblioteca**: Favoritas, Historial y Artistas → álbumes → canciones. ♡ en cada canción y en el
reproductor (`/favorites`, sincronizado con la app). Cristal (fondo translúcido con desenfoque) en tarjetas,
reproductor y barra de pestañas; el fondo toma los colores de la portada de lo que suena. Barras de scroll finas y discretas (y sin scroll horizontal). Minirreproductor con
barra violeta, anterior/siguiente, **volumen** (en la barra en pantallas anchas y en el reproductor grande; flechas
arriba/abajo; se recuerda; en el móvil manda el volumen del teléfono) y controles en la pantalla de bloqueo (Media
Session). En Android enseña arriba
"Instala la app" y en el menú del avatar está **"Descargar app Android"** (`/app/enlace`). Probado en Chromium
(móvil y PC): carga, reproduce y pasa de canción. **Sin probar en iPhone/Safari** (el audio es Opus en `.webm`).


**Portada viva** (reproductor grande de la web; la app debería hacer lo mismo): la portada se acerca y se mueve muy
despacio dentro de su marco (Ken Burns, 24 s, ida y vuelta) y sus colores desenfocados del fondo "respiran"; **solo
mientras suena** (en pausa, quieta) y nada si el sistema pide reducir movimiento. Es solo CSS: el servidor no hace
nada (la portada ya va en `thumb`), sin vídeo, sin espacio ni peticiones. Se probó también un **Canvas** como el de
Spotify (7 s del videoclip, vertical, en bucle, ~400 KB por canción, 3–4 peticiones a YouTube cada una): precioso,
pero se descartó por ser demasiado (30-10-2026). Si algún día se quiere, está en el commit `c3f3a23` (página
`/demo-canvas` y ruta `/canvas/<id>`; yt-dlp con `download_ranges` + ffmpeg con `cropdetect`).

**Publicar la app Android:** lo hace la sesión de la app desde el PC (`tools/publicar.ps1` del proyecto Flutter):
sube el APK firmado a `/var/lib/musicapp/app/musica.apk` y escribe al lado `version.json` (`build` y `version`).
La carpeta está montada solo lectura en la API como `/app-dist`. Sin reiniciar nada. La app instalada lo ve en
`/app/version` y avisa. El enlace de descarga (`/app/enlace`) sirve 10 min y no lleva la sesión dentro; no es
de un solo uso a propósito (los navegadores de Android a veces piden el archivo dos veces). Lo que protege la
música es el login: un APK pasado por WhatsApp no reproduce nada sin una cuenta aprobada. **No hacer pruebas en
esa carpeta** (una prueba ya borró un APK publicado): probar con otro nombre de archivo. Solo Android: en iPhone
no se pueden instalar apps fuera de la tienda (para ellos, la app web). En Samsung, el "Bloqueo automático"
(Ajustes → Seguridad y privacidad) impide instalar fuera de la tienda: hay que apagarlo.

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
| `POST /auth/google` | Cuerpo `{"id_token": "…"}` (con `"web": true`: sesión de 10 min que no cuenta como dispositivo, para algo que solo baje la app; hoy no se usa) (el que da Google a la app). Aprobado → `{"session": …, "user": …}` (sesión de 90 días); nuevo o pendiente → 403 `pendiente`; bloqueado → 403 `bloqueado`. Sin clave |
| `GET /me` | Quién es el dueño de la sesión |
| `POST /auth/logout` | Cierra la sesión usada |
| `GET /` y `GET /acceso` | **La página principal** (`server/web/acceso.html`, estilo Dark Premium y logo del perrito): entrar con Google; al aprobado le abre la app web, a los demás les dice si quedaron pendientes (ver "Repartir la app y versión web"). Sin clave |
| `GET /web/…` | **La app en el navegador** (`server/web/web.html`): Inicio, Buscar, Biblioteca, favoritas y reproductor. Cualquier ruta bajo `/web/` da la misma página. Usa la sesión que guardó la página principal; sin ella, vuelve a `/`. Sin clave (la página en sí no tiene datos) |
| `GET /logo.png`, `/logo-480.webp`, `/logo-96.webp` | El logo: original PNG 512×512 (505 KB) y las versiones ligeras que usa la página (WebP 25 KB y 3 KB; el de 96 también es el icono de la pestaña). Solo nombres `logo…png/webp` de `server/web/`. Sin clave |
| `POST /app/enlace` | Para aprobados: enlace de descarga de la app que sirve 10 min (`{url, minutes, size, date}`); 404 si aún no hay APK |
| `GET /app/version` | Versión publicada de la app (`version.json` junto al APK, p. ej. `{"build": 18, "version": "1.0.17"}`); la app avisa si `build` es mayor que el suyo y se actualiza con `/app/enlace`. 404 si no hay. Pide sesión |
| `GET /app/descargar/<enlace>` | El APK (`musica.apk`). Enlace caducado o inventado → 404. Sin clave: el enlace ya lo es |
| `GET /prueba-login` | Página para probar el login de Google en el navegador (buscar y escuchar con la sesión). Sin clave |
| `GET /search?q=…` | Primero lo guardado (de 20 en 20 con `&offset=&limit=` hasta 200; `total` dice cuántas guardadas hay en total: "rawayana" → 78; todas las palabras en título/artista/álbum, pero cada una vale exacta, a medio escribir o en plural/singular: "one pilot" encuentra la banda, "hope" encuentra Hope y Hopeless. **Las faltas** ("chayane", "stresed out") solo cuentan en palabras de 5 letras o más y **solo si sin ellas no sale nada**. Ver `Library.find`). Con `&yt=1` (por defecto, solo en la primera página) añade **20 canciones de internet que no estén en el servidor**, de **YouTube Music** (oficiales, con artista, álbum y duración): pide 20; si muchas ya están guardadas, pide más (hasta 100) para juntar 20 nuevas, salvo que YouTube no tenga más. Cada resultado: `id`, `title`, `artist`, `album`, `duration`, `thumb`, `where` (`guardada`/`youtube`). `&yt=0` = solo lo guardado (sin tocar YouTube) |
| `GET /suggest?q=…&n=8` | **Sugerencias mientras se escribe**, de lo guardado (sin YouTube, ~45 ms): artistas (con su nº de canciones), álbumes y canciones cuyas palabras empiezan por lo escrito ("raw" → Rawayana · 78, RawayanaLand…): `{sugerencias: [{tipo: artista\|album\|cancion, texto, artista, id, canciones, thumb}]}` |
| `GET /search/albums?q=…` | Álbumes de internet (YouTube Music): `{albums: [{id, title, artist, year, type, thumb}]}`. 1 petición la primera vez; luego de memoria. Pide sesión |
| `GET /search/album/<id>` | Un álbum de internet con sus canciones **en orden** (`track`) y `where` (cuáles ya están guardadas). 1 petición la primera vez. Poner una canción baja solo esa. Pide sesión |
| `GET /library?sort=…&offset=0&limit=50` | **Toda la música guardada por páginas**, para ir cargando según se baja (scroll infinito): `{total, offset, songs}`. `sort`: `recientes` (la última que sonó primero, por defecto), `populares`, `nombre` (A-Z) o `artista` (A-Z). `&genre=…` filtra por género. `limit` hasta 200. No hay más cuando `offset + len(songs)` llega a `total`. Pide sesión |
| `GET /favorites` | **Mis favoritas** (las mismas en la app y en la web), la última marcada primero: canciones como en `/search` más `added`. Las que ya no están guardadas salen con `where: youtube` (al ponerlas se vuelven a bajar). Pide sesión de un usuario (la clave compartida no tiene: 400) |
| `PUT /favorites/<id>` | Marcar como favorita. Si está guardada, la ficha sale de la biblioteca; si es un resultado de YouTube, mandar en el cuerpo `{title, artist, album, duration, thumb}` |
| `DELETE /favorites/<id>` | Quitar de favoritas |
| `GET /playlists` | **Mis playlists** (iguales en la app, la web y otros móviles), la última cambiada primero: `{playlists: [{id, name, songs: [canciones como en /search], created, updated}]}` |
| `POST /playlists` | `{name}` → `{id}`. Como mucho 200 playlists |
| `PUT /playlists/<id>` | `{name, songs: [ids en orden]}`: **guarda la playlist entera** (quitar, añadir y reordenar son el mismo cambio; lo hecho sin conexión se sube igual, gana el último en guardar). Una canción que el servidor no conoce (ni guardada, ni en favoritas o playlists, ni en búsquedas recientes) va como ficha `{id, title, artist, album, duration, thumb}`; si falta, 400 con `{detail: {error, ids}}`. Hasta 2.000 canciones |
| `DELETE /playlists/<id>` | Borrar una playlist |
| `GET /home` | Secciones del Inicio recomendadas: `{secciones: [{id: recientes\|para_ti\|vuelve, titulo, tipo, items}]}` (ver `docs/recomendaciones.md`) |
| `GET /radio?desde=cancion:<id>\|artista:<nombre>&ya=<ids>&n=20` | Radio infinita: las siguientes `n`, sin repetir lo de `ya` |
| `POST /eventos` | `{eventos: [{tipo: entera\|salto\|no_me_gusta\|ya_no_me_gusta, id, segundo, duracion, contexto, causa, cuando}]}` en lote ("empezó a sonar" lo apunta `/stream`) |
| `POST /recomendaciones/opinion`, `GET /recomendaciones/preguntar?contexto=` | "¿Qué te parecieron?" y si toca preguntarlo (una vez por semana) |
| `GET /history?limit=50` | **Lo último que puse yo** (no lo de todos), lo más reciente primero, con `played`. Se apunta solo al empezar a sonar una canción por `/stream` (los saltos dentro de la canción no cuentan); hasta 200 |
| `GET /genres` | Géneros de lo guardado: `{genres: [{name, songs}]}`, los que más tienen primero (ver "Género y fichas"). Para filtrar: `/library?genre=…`. Pide sesión |
| `GET /artists` | Todos los artistas guardados: `{artists: [{name, songs, albums, thumb}]}`, los que más canciones tienen primero. Agrupa sin mayúsculas ni tildes ("Milo j" = "Milo J"); a las canciones sin artista en su ficha pero con título "Artista - Canción" les toma lo de antes del guion. Pide sesión |
| `GET /artist?name=…` | Un artista: `{name, songs, albums: [{name, year, songs, thumb}], loose: [canciones sin álbum]}`; álbumes del más nuevo al más viejo. 404 si no hay. Pide sesión |
| `GET /album?artist=…&name=…` | Las canciones guardadas de un álbum: `{name, artist, year, songs}`, por fecha y título (YouTube no da el número de pista; las bajadas por la precarga sí lo traen, `track_no`). 404 si no hay. Pide sesión |
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
| `GET /interno/precarga` | Cómo va la precarga de álbumes: artistas hechos, cola, bajadas, saltadas, fallidas |
| `GET /interno/stats` | `{songs, bytes, max_bytes}` |
| `POST /interno/resolve` | `{"query": …, "limit": n}`: buscar un nombre (`ytsearch5:…` o el nombre a secas: **YouTube Music**; con `yt:` delante o si no hay nada, YouTube normal) o leer un enlace (video, lista, SoundCloud…) sin bajar nada. Título, duración, miniatura, artista y `entries` si es lista o búsqueda |
| `GET /interno/song/<clave>` | Ficha sin contarla como puesta |
| `POST /interno/played/<clave>` | Sonó: suma una vez puesta y actualiza el último uso |
| `POST /interno/fetch` | `{"url": …, "by": <id de Discord>}`: "dame esta canción". Guardada → `source: local`; si no, la baja → `online`; directos → `live`, sin archivo y con `info.url` para escucharlo |
| `POST /interno/ficha/<clave>` | Completa artista/álbum preguntándole a YouTube; 503 si está bloqueado |
| `DELETE /interno/song/<clave>` | Olvidar: borra archivo y ficha |

**Pocas peticiones a YouTube** (para YouTube buscar y bajar son lo mismo: peticiones desde nuestra IP, y muchas
seguidas parecen un bot):

- La app lista **solo lo guardado** (`/search?…&yt=0`, al instante) y tiene un botón aparte "buscar en YouTube".
- **YouTube Music para buscar** (`ytmusicapi`): 20 canciones = 2 peticiones, igual que la búsqueda normal, pero
  trae las oficiales con sus datos; álbumes = 1 petición; abrir un álbum = 1. Medido el 30-10-2026: con yt-dlp,
  pedir 5 o 20 resultados cuesta lo mismo (2 peticiones) y 40 cuesta 3; YouTube da ~20 por página. Quitar las
  que ya están en el servidor es gratis (se mira el catálogo). Lo que sí cuesta más: juntar 20 nuevas de un
  artista del que ya hay mucho guardado (hay que pedir más resultados: ~5 peticiones en vez de 2). Si
  `ytmusicapi` falla (no es oficial; YouTube cambia), `/search` vuelve sola a la búsqueda de yt-dlp. **El bot
  también busca los nombres en YouTube Music** (`/interno/resolve`, misma búsqueda y memoria que la app); si no hay
  nada, o el texto empieza por `yt:`, en YouTube normal (remixes, memes, "sped up", directos que no están en
  YouTube Music). Los enlaces (un vídeo o una playlist) se respetan tal cual. **YouTube Music no tiene archivos
  propios**: cada canción es un vídeo de YouTube con el mismo id y el mismo audio; lo que cambia es qué vídeo se
  elige (la pista oficial del disco en vez de un videoclip con intro, un directo o un cover).
- **Búsquedas recordadas 7 días** (`YouTubeSearches` en `app.py`, en `server/data/youtube-searches.json`, hasta
  3.000): la misma búsqueda, desde la app o desde el bot, no vuelve a preguntarle a YouTube. Sin distinguir
  mayúsculas, tildes ni espacios ("Karol G" = "karol g"). El registro dice cuántas salieron de memoria.
- Una canción se baja **una sola vez** para todos (biblioteca única) y su ficha se pide una sola vez.
- **Ritmo con YouTube** (`yt_turn` en `app.py`): lo que hace saltar el bloqueo son las ráfagas (el del 25-10-2026
  fue una importación de 1.236 canciones seguidas), no el uso normal. Toda petición a YouTube (búsqueda, descarga
  o ficha; de la app, del bot o de una importación) espera su turno: **una operación cada 4 s y como mucho 300
  peticiones reales por hora**. Cada operación cuenta lo que de verdad cuesta (medido el 30-10-2026): descarga 4,
  búsqueda 2 (más si pide más de 20 resultados), ficha 2, álbumes o abrir un álbum 1; una lista larga, una más
  por cada 100 canciones.
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

**Clave:** todas las rutas que no dicen "Sin clave" piden una **sesión** de un usuario aprobado como
`Authorization: Bearer …` o `?token=…`. También vale la clave compartida `API_TOKEN` (en `server/.env`, fuera de
git) para pruebas desde el servidor, salvo en lo que es de cada usuario (favoritas, historial: 400); se quitará
cuando nada la use.

**Género** (`genres.py`): **por artista** (todas sus canciones el mismo), de una lista corta en español
(Vallenato, Salsa, Bachata, Merengue, Cumbia, Reguetón, Regional mexicano, Trap, Urbano latino, Rock en español,
Baladas, Pop latino, Metal, Rap, R&B, Reggae, Electrónica, Alternativo, Rock, Pop…). De dónde sale, por orden:
1. **A mano**: `docker exec musicapp-api python genres.py "Rawayana" "Pop latino"` (sin argumentos lista todos con
   su género y de dónde salió; `-` como género quita la corrección). Manda siempre.
2. **MusicBrainz** (enciclopedia libre, ~1 consulta/s, sin tocar YouTube): conoce vallenato, bachata, salsa,
   corridos… (Diomedes Díaz → Vallenato, Romeo Santos → Bachata, Peso Pluma → Regional mexicano). No conoce a
   todos (Rawayana, Neutro Shorty, Chayanne no tienen géneros allí).
3. **iTunes** por mayoría entre las canciones del artista. Es lo peor: iTunes pone el género por disco según la
   distribuidora y no tiene "vallenato" (el 30-10-2026 puso a Diomedes Díaz como "Salsa y tropical", "Pop" y
   "Música mexicana" a la vez); por eso solo es el último recurso.
4. Si nada sirve, sin género.

Se guarda en `server/data/generos.json`. Los artistas nuevos se calculan solos cada 30 min.

**Fichas de las canciones viejas** (`enrich.py`, de fondo): rellena **artista, álbum y año** de las canciones que
no los tenían, con iTunes (solo si artista y título coinciden de verdad; títulos al revés, "Beat It - Michael
Jackson", se prueban dados la vuelta) y, las que sigan sin artista, con **YouTube Music** por el vídeo exacto (1
petición cada 2 min, de 03:00 a 08:00 de Chile). Nunca cambia el título ni pisa un dato que ya esté. El género
que da iTunes se guarda aparte (`itunes_genre`) solo como pista para el paso 3.

**Artistas con colaboraciones**: "Diomedes Díaz & Juancho Rois" cuenta para Diomedes Díaz si él tiene canciones a
su nombre (un dúo de verdad, "Simon & Garfunkel", no se parte).

**Precarga de álbumes** (`precarga.py`): baja poco a poco los **álbumes de estudio** de los artistas con **5 o más
canciones guardadas**, **como mucho los 6 más escuchados de cada uno** (`MAX_ALBUMS`;
sin gastar peticiones: primero los que tienen los éxitos del artista según YouTube Music, luego los que ya tienen
canciones guardadas aquí, luego los más nuevos; AC/DC: *Back In Black*, *The Razors Edge*, *Highway to Hell*…) (~107 el 30-10-2026; ~6.000 canciones, ~27 GB). **A ritmo de persona, no de robot** (una
descarga cada X segundos exactos durante horas es el patrón de un robot): entre canciones de un álbum espera más o
menos lo que dura la canción (40–110 %, al azar, como quien la escucha o se la salta); entre álbumes, una pausa de
5 a 30 min y, 1 de cada 7 veces, una larga de 30 a 90 min; el siguiente artista se elige al azar entre los 3 más
escuchados que falten. De madrugada (**01:00–09:00 de Chile**) siempre; de día un 50 % más lento y solo si nadie ha
usado YouTube en los últimos 10 min. Si YouTube avisa de bloqueo, para 24 h. Unas 15–20 canciones por hora mientras
trabaja: los artistas más escuchados en pocos días, el total en unas 5–6 semanas. Se salta directos,
instrumentales, karaokes, recopilatorios ("Greatest Hits", "Uniquehits", "Lo Mejor De…", "Vol. 1") y ediciones
repetidas (por el título del álbum) y las canciones que ya
están, también si es otra versión del mismo artista y título (ensayo con Rawayana: 7 álbumes de estudio, 78 nuevas,
28 que ya estaban). **Baja las pistas del disco, no los videoclips:** en algunos álbumes YouTube Music enlaza cada
pista a su videoclip (el 30-10-2026, "City Walls" de *Breach* bajó como el vídeo de 9:55 con intro en vez de la
canción de 5:23); por eso usa la **lista de audio** del álbum (`audioPlaylistId`, 1 petición más por álbum). Las
bajadas quedan con **título limpio** ("City Walls", no "Twenty One Pilots - City Walls (Official Video)"), la
**portada del álbum** como foto, artista, álbum, año y número de pista (`track_no`). Estado en
`server/data/precarga.json`; cómo va: `curl -H "Authorization: Bearer $BOT_API_KEY" 127.0.0.1:8091/interno/precarga`.
Para pararla: quitar la línea `PRECARGA = …` de `app.py`. **Saltar un álbum** (o uno que ya
esté bajando): añadir una línea `Artista | Álbum` a `server/data/precarga-saltar.txt` (sin distinguir mayúsculas
ni tildes); se lee en cada paso, sin reiniciar, y lo que ya estaba en cola de ese álbum sale al momento. Lo que ya
se bajó de él se borra a mano (p. ej. `DELETE /interno/song/<clave>`). Saltado el 30-10-2026: Rawayana |
ASTROPICAL.

**Favoritas, historial y playlists** (`userdata.py`; en `server/data/userdata.json`, fuera de git, permisos
600): por cuenta, para que la app, la web y otros móviles se vean igual. De cada canción se guarda su ficha (título,
artista, portada…), así sigue saliendo aunque la canción se borre del servidor (al ponerla se vuelve a bajar).
**Las canciones en favoritas o playlists de cualquiera no se borran por el tope de espacio** (`Library.keep`).

**Usuarios** (`users.py`; datos en `server/data/users.json` y `sessions.json`, fuera de git, permisos 600): quien entra con Google por primera vez queda **pendiente** (máximo 30 pendientes a la vez);
se aprueba o bloquea a mano. Se guarda por el `sub` de Google (ID fijo de la cuenta), no por email. Bloquear
cierra sus sesiones al momento.

**Máximo 3 dispositivos por cuenta** (`MAX_DEVICES` en `users.py`), para que nadie reparta su cuenta: entrar en
un 4.º cierra la sesión **más antigua** (ese dispositivo recibe 401 y tiene que volver a entrar con Google). No se
rechaza el 4.º porque al reinstalar la app la sesión del móvil viejo sigue "viva" 90 días y dejaría fuera al
dueño. Quien comparta su cuenta se irá echando con los demás, y el registro de la API lo dice ("entró en otro
dispositivo; cierro el más antiguo"). La app web cuenta como un dispositivo más. (`"web": true` en `/auth/google` da una sesión de 10 min que no
cuenta; hoy no la usa nadie.) `docker exec musicapp-api python users.py` enseña los dispositivos de cada uno. **Los administradores no tienen
límite** (el dueño prueba en el móvil, el emulador, la web y el PC a la vez; el 30-10-2026 el límite le cerró la
sesión del móvil): `users.py admin <email>` / `noadmin <email>`. Hoy son `yonisrubiocl@gmail.com` y
`lainerrubio@gmail.com`.

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
`:H` ayuda, `:Q` sale. Los números no se mueven mientras escribes. Además de cuándo pidió acceso y su último
login, enseña **cuándo pidió su última canción** ("hace 12 min", verde si hace menos de 1 h) y **cuántas en las
últimas 24 h**, para ver quién está activo. Arriba, una línea con **la precarga de álbumes**: qué artista y álbum
está bajando, cuándo baja la siguiente, cuántas lleva, cola y artistas hechos (cian si trabaja, gris si espera a que
nadie use YouTube, rojo si YouTube avisó y está parada). Abajo, **las opiniones sobre las recomendaciones** de los
últimos 7 días (👍/👎 y lo que más se marca). Sale del historial (`userdata.json`): cuenta la app y la web, no
Discord, y empezó a apuntarse el 30-10-2026 (antes de eso sale "nunca"). Por debajo usa `users.py`:

```bash
docker exec musicapp-api python users.py                       # lista
docker exec musicapp-api python users.py aprobar amigo@gmail.com
docker exec musicapp-api python users.py bloquear amigo@gmail.com
docker exec musicapp-api python users.py admin yo@gmail.com     # sin límite de dispositivos
```

Arrancar y probar desde el servidor:

```bash
cd ~/MusicApp/server
docker compose up -d --build api        # arrancar / actualizar tras cambiar cualquier .py o web/ (corta unos segundos)
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
- La API solo hace cosas de música: no ejecuta comandos ni toca archivos fuera de `/var/lib/music`, su `data/`
  y el APK (solo lectura). El ID o la clave de canción se validan antes de buscar archivos. Corre sin root.
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
| 1b | **Login con Google** (aprobación manual con panel, sesiones de 90 días, máximo 3 dispositivos) | Hecho (falta el bloqueo automático) |
| 1c | **Biblioteca única:** la API dueña de la música, el bot cliente suyo (ver "Canciones") | Hecho |
| 2 | **App mínima:** login con Google, búsqueda, play y que suene + actualizador propio. Al tenerla, quitar `API_TOKEN` | En marcha (1.0.17 publicada, actualizador hecho) |
| 3 | **Reproductor de verdad:** cola, siguiente/anterior, segundo plano y pantalla de bloqueo (`just_audio`, `audio_service`) | Pendiente |
| 4 | Listas, favoritos, historial, letras y portadas | Favoritas, historial, playlists, artistas/álbumes y géneros hechos en el servidor; faltan letras |
| 5 | Descargas para escuchar sin conexión, ver qué escuchan los amigos, escuchar juntos | Pendiente |
| 6 | **Recomendaciones:** Radio, Para ti, mixes, descubrir (plan y estado en `docs/recomendaciones.md`) | Fase 1 hecha en servidor y web; falta en la app |

## 5. Pendiente

**Del servidor:**
- **Recomendaciones** (fase 6, `docs/recomendaciones.md`): fase 1 hecha en el servidor y la web; falta que la app
  Android mande eventos, use `/home` y `/radio`, y tenga "No me gusta" y la tarjeta de opinión. Siguientes fases:
  afinar con datos y que las opiniones ajusten (3), mixes (4), lo de todos opcional (5), Descubre (6).
- **Bloqueo automático** (sección 2) antes de repartir la app a todos.
- Revisar los géneros (`docker exec musicapp-api python genres.py`) y corregir a mano los que no cuadren.
- Ruta de sincronización para favoritas hechas **sin conexión** en la app (cada cambio con su hora; gana el más
  reciente). Propuesta, sin hacer.
- Que la web se actualice sola si cambian las favoritas en otro dispositivo (ahora: al cambiar de pestaña o
  recargar).
- Quitar `API_TOKEN` cuando nada lo use (ni `/prueba-login`).
- Decidir si la sesión se renueva sola con el uso (ahora caduca a los 90 días y la app tendría que volver a
  pedir el login a Google, sin que yo apruebe de nuevo).
- Borrar los restos de antes de la biblioteca única (sección "Canciones") y el contenedor `musicapp-prueba`
  (imagen de la API con `data/` en solo lectura, encendido sin uso aparente).
- **Prueba a ciegas de calidad** (sección 3b) antes de pensar en Premium.
- Ideas sin hacer: generador de PO tokens, Cloudflare WARP o el móvil con datos (Tailscale como nodo de salida)
  como salida de reserva hacia YouTube.

**Del bot de Discord** (`~/MusicBot`): la búsqueda tolerante (`Library.find`) aún no está allí; si la API no
responde un momento, una importación da esa canción por fallida (debería esperar y reintentar).

**Del servidor en general:** `/home` tiene poco sitio (2,8 GB libres de 20 el 30-10-2026; `ProjectV1` ocupa
11 GB): lo que crece (música, APK) ya está en `/var` (71 GB libres).

## 6. Carpetas

```
/home/lainer/MusicApp/
├── server/
│   ├── app.py              la API (FastAPI): puerto 8000 para la app, 8001 para el bot; también reparte el APK
│   ├── enrich.py           completa de fondo artista/álbum/año de las canciones viejas (iTunes, YouTube Music)
│   ├── genres.py           género por artista (a mano, MusicBrainz, iTunes); también comando para corregir
│   ├── precarga.py         baja despacio los álbumes de estudio de los artistas más escuchados
│   ├── recomendar.py       recomendaciones: radio, Para ti, Vuelve a escuchar, eventos, opiniones (docs/recomendaciones.md)
│   ├── library.py          la biblioteca única (carpeta + catálogo, búsqueda, tope de espacio); la música está en /var/lib/music
│   ├── users.py            usuarios y sesiones (login con Google, aprobar/bloquear por comando, 3 dispositivos)
│   ├── userdata.py         favoritas e historial de cada usuario
│   ├── web/                página principal (acceso.html), app web (web.html) y el logo (logo.png original; logo-480.webp y
│   │                       logo-96.webp, los ligeros: rehacerlos si cambia el logo); colores de la app: fondo #080A12,
│   │                       tarjetas #151725, violeta #9B5CFF, rosa #F04DBB, azul #5268FF, texto #FFFFFF / #A3A5B5
│   ├── panel.py            panel de terminal para aprobar/bloquear usuarios (se ejecuta en el servidor, no en Docker)
│   ├── Dockerfile
│   ├── docker-compose.yml  contenedores musicapp-api, musicapp-cloudflared y musicapp-tailscale (red propia musicapp_default)
│   ├── funnel.json         qué publica Funnel (respaldo): https://musicapp.<tailnet>.ts.net -> api:8000
│   ├── .env                API_TOKEN, BOT_API_KEY, CF_TUNNEL_TOKEN y TS_AUTHKEY (fuera de git; plantilla en .env.example)
│   └── data/               users.json, sessions.json, userdata.json (favoritas/historial), generos.json,
│                           precarga.json, precarga-saltar.txt (álbumes que no se bajan), youtube-searches.json, youtube-cookies.txt y estado de Tailscale (fuera de git)
├── docs/
│   └── recomendaciones.md   plan y estado del recomendador
├── README.md     este documento
(/var/lib/music/                   la biblioteca: canciones + index.json, fuera de git)
(/var/lib/musicapp/app/            musica.apk + version.json, lo publica la sesión de la app; fuera de git)
(/var/lib/musicapp/recomendar/     eventos, opiniones y estado de las recomendaciones; fuera de git)
└── .gitignore    ignora .env, data/ y __pycache__/
```
