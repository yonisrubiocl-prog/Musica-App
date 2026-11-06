# MusicApp: app de música propia

> **Regla de este documento:** describe **cómo está el proyecto ahora**, no su historia. Al cambiar algo,
> se **reescribe la parte afectada y se borra lo viejo o ya realizado**; no se añaden notas sueltas al
> final ni "actualizaciones" encima de texto desfasado. Debe poder leerse de arriba abajo sin
> contradicciones. Lo histórico está en git, no aquí.

App de música propia, tipo Spotify: buscas una canción, le das a play y **suena en el móvil o el PC**.
El bot de Discord (`MusicBot`, otro proyecto) es aparte: comparten la música guardada, que es de esta API, y la
app además puede controlarlo desde su pestaña **DC** cuando estás en un canal de voz con él (ver "Pestaña DC").

Es un proyecto **por diversión y para aprender**: privado, solo para mí y mis amigos (unas 6 personas),
sin publicarlo ni cobrar nada.

**Estado actual** (03-11-2026):
- **Servidor** hecho y publicado en `https://musica.yoneapolis.com` (túnel de Cloudflare, dominio propio;
  `https://yoneapolis.com` lleva aquí). Tailscale Funnel (`https://musicapp.tail66213e.ts.net`) sigue encendido
  como respaldo. 13 usuarios aprobados. ~3.160 canciones (11 GB; tope 50 GB).
- **Pestaña DC** hecha en el servidor y probada con música real: "Entrar con Discord" y controlar el bot desde la
  app (cola, pedir sin repetidas, saltar, anterior, pausa, quitar, mover y volver a poner una de las anteriores).
  La app la está terminando la otra sesión; la web no la tiene.
- **Biblioteca única** hecha: la API es la dueña de la música (`/var/lib/music`) y el bot de Discord es cliente suyo.
- **Buscar:** lo guardado tolera faltas y palabras a medio escribir; lo de internet sale de **YouTube Music**
  (sus 20 primeras canciones tal cual, álbumes en orden), con memoria de 7 días y un ritmo máximo con YouTube.
- **Por usuario:** favoritas, historial y playlists (iguales en la app y la web), máximo 3 dispositivos por cuenta.
- **Catálogo:** artistas → álbumes → canciones, género por artista (MusicBrainz y correcciones a mano), y de
  fondo: fichas de las canciones viejas y **precarga** de los álbumes de estudio de los artistas más escuchados.
- **App Android** (fase 2) en marcha, la lleva otra sesión: **1.0.44 (build 45) publicada** (06-11-2026: ya con
  Canvas, su iconito de estado, títulos limpios y 🔀 Aleatorio), con aviso de actualización propio; pide el audio con la sesión en la cabecera. La 1.0.38 y anteriores no suenan (usaban
  `?token=`): la app avisa de la nueva al abrirla. **App web** (hecha en el servidor) en `/web/`, a la que lleva la página principal tras entrar;
  es la referencia de cómo debe comportarse la app (`docs/app-paridad.md`).
- **Seguridad:** la auditoría del servidor del 02-11-2026 está aplicada en lo de este proyecto (sección 2): API y bot
  sin root ni `lainer`, FFmpeg solo con los formatos que usamos, sesión solo en la cabecera, cabeceras de seguridad
  y CSP, imágenes al día. Falta el parche de FFmpeg de Debian (ver Pendientes). Tras el barrido de la app
  (06-11-2026): HSTS con `includeSubDomains`; una IP que manda **10 sesiones (o enlaces de audio) falsas distintas en
  10 min** recibe 429 en todo lo que pide sesión durante 15 min (una sesión caducada repetida no cuenta; la IP es la
  de `CF-Connecting-IP`); y `/app/version` y `/app/enlace` dan el `sha256` del APK para que la app lo compruebe antes
  de instalar. Descartado a propósito: fijar el certificado (Cloudflare lo cambia solo), ofuscar la app y Frida.

**Repositorio:** GitHub privado **yonisrubiocl-prog/Musica-App** (solo el servidor; la app Flutter tiene el suyo).
El servidor sube con su propia llave de despliegue, que solo vale para ese repo (`~/.ssh/github_musicapp`, alias
`github-musicapp` en `~/.ssh/config`): `git push` desde `~/MusicApp`. Al terminar cada cambio: commit y push.

**Para igualar la app con la web y el servidor:** `docs/app-paridad.md` (rutas que debe usar y comportamientos a
copiar: cola, radio, sugerencias, recomendaciones, portada viva…). Es lo que hay que pasarle a la sesión de la app.

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
                 ◄── pestaña DC de la app ──    (la API le pasa las órdenes al puerto 8100 del bot)
```

| Pieza | Dónde | Qué es |
|---|---|---|
| **Servidor** (`server/`) | Este servidor, en Docker | API de música, dueña de la biblioteca. Si se cae, el bot sigue tocando lo guardado pero no puede bajar nada nuevo |
| **App** | PC del usuario | Flutter, para Android. Se desarrolla allí porque este servidor no tiene pantalla para el emulador. La **app web** es aparte y vive en el servidor (`server/web/web.html`) |
| **Túnel** | Contenedor `cloudflared` aquí + Cloudflare | Da la dirección pública con HTTPS sin abrir puertos. Dominio `yoneapolis.com` (mío, en Cloudflare), pensado para todos mis proyectos con un subdominio cada uno |
| **Canciones** | `/var/lib/music` (la biblioteca única) | Fuera del proyecto: `/home` tiene poco espacio, `/var` tiene de sobra. Ver "Canciones" abajo |

### Canciones

La **API es la dueña de la música**: una carpeta `/var/lib/music` (~2.300 canciones, 8,2 GB el 30-10-2026) con su catálogo
`index.json` dentro (y `index.json.bak`, la versión anterior). Solo la API escribe ahí y solo ella habla con
YouTube: buscar y bajar (yt-dlp, `.webm` con audio **Opus**, archivo `yt-<id de YouTube>.webm`; otras webs
`u-<resumen del enlace>`). Lo bajado se comprueba con FFmpeg antes de guardarlo: solo entran los formatos de
`FORMATS` en `app.py` (WebM, MP4/M4A, MP3, Ogg, AAC, FLAC, HLS); el resto, como ADX/AAX, que tienen fallos conocidos
en FFmpeg, se rechaza con 415 aunque cambie la extensión. **Tope de 50 GB** (`MUSIC_GB` en `docker-compose.yml`; era 15, se subió a 40 y luego a 50 para la precarga de álbumes, que añade ~6.000 canciones / ~26 GB): al pasarlo borra lo que hace
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

**Títulos** (`server/titulos.py`, desde el 06-11-2026): la API enseña el título **sin lo que pone YouTube**:
"Alexis y Fido - Rompe La Cintura // Letra" → "Rompe La Cintura", "Aqua - Barbie Girl (Official Music Video)" →
"Barbie Girl", "A Besitos, Los Diablitos - Video Oficial" → "A Besitos". Quita las etiquetas de vídeo/letra
(entre paréntesis, tras `|`, `//` o ` - `), el canal al final y el artista delante o detrás (solo si de verdad es
uno de sus artistas). Lo que cambia la canción se queda: "(En Vivo)", "(Remix)", "(Cover Audio)", "ft. X". **Solo
para enseñar:** `index.json` guarda el título de YouTube tal cual (con él se buscan repetidas y versiones de vídeo,
y el bot lo sigue viendo así). Cambia ~275 de 3.750. Las portadas de álbum y de artista prefieren la portada de
YouTube Music (cuadrada) a un fotograma de vídeo; ~1.250 álbumes de 1–2 canciones no tienen ninguna.

### Repartir la app y versión web

**Flujo de la página principal** (`https://musica.yoneapolis.com/`; `https://yoneapolis.com` lleva aquí):
entrar con Google → si está **aprobado**, se abre la **app web** (`/web/`); si no, queda pendiente o sin acceso. La
sesión se guarda en el navegador (`localStorage`): la próxima vez entra directo. Cuenta como uno de los 3
dispositivos; si la cierran (4.º dispositivo), vuelve a la página con el aviso "se cerró tu sesión".

**App web** (`server/web/web.html`, hecha en el servidor con el estilo de la app; la sesión que guarda la
página principal está en `localStorage` con la clave `musica_sesion`). Toda la lógica vive en la API y la web solo
la enseña. (Se probó la app Flutter compilada para web y se descartó: dibuja la app del móvil en un lienzo, ~10 MB.)
Probada en Chromium (móvil y PC); **sin probar en iPhone/Safari** (el audio es Opus en `.webm`). Para probar
cambios en un navegador de verdad sin pantalla: `tools/probar-web.sh` (Playwright en Docker, imagen
`mcr.microsoft.com/playwright:v1.48.2-jammy`, ~1,5 GB; usa el `web.html` del disco sin reiniciar la API).

- **Pestañas** (abajo, como en la app):
  - **Inicio:** saludo con nombre y foto, "Escuchado recientemente" (`/history`), Para ti y Vuelve a escuchar
    (`/home`), álbumes recientes, "Tus favoritas", géneros, **"Tus artistas"** y "Lo más puesto".
  - **Buscar:** al escribir, un **cuadro flotante de sugerencias** como Spotify ("Buscar «…»", artistas, álbumes y
    canciones con foto; flechas y Enter; la lista de abajo no cambia mientras se escribe). Los resultados completos
    salen con Enter (botón aparte "Buscar en YouTube"). Sin texto, toda la biblioteca con scroll infinito
    (`/library`: Recientes, Populares, A–Z, Por artista) y chips de género.
  - **Biblioteca:** Playlists, Me gusta, Historial y Artistas. ♡ en cada canción y en el reproductor
    (`/favorites`, igual en la app).
    Botón 🔗 **Importar playlist** de YouTube / YouTube Music (playlist o Mix, ver `/import/youtube`): resumen
    "N canciones · ✓ ya estaban · ☁ de internet" y Descartar / Guardar playlist, como la app 1.0.40.
- **Temas y color de acento** (menú del avatar → Ajustes, como la app 1.0.38): **Oscuro** (por defecto), **Gris** y
  **Claro**, y debajo 8 acentos; cada tema recuerda el suyo y todo cambia al momento. Se guarda solo en el navegador
  (`localStorage`: `tema` y `acentos`), no en el servidor: cada dispositivo el suyo. El CSS no tiene colores fijos:
  todo sale de variables (`--fondo`, `--acento`, `--cristal`, `--hoja`, `--barra`, `--elevado`, `--texto`…) y un tema
  es solo otro bloque de variables. En Claro, los acentos muy luminosos (luminancia ≥ 0,3) pierden un 18 % de
  luminosidad para leerse; sobre un botón de acento el texto es negro si el acento es claro (> 0,45). El reproductor
  grande y la barra de lo que suena (van sobre la portada difuminada) son oscuros también en Claro.
- **Rendimiento** (Ajustes, debajo del tema; se recuerda en cada navegador): interruptores para **Canvas** (apagado no
  pregunta ni baja vídeos), **escuchar en varios dispositivos** (apagado deja de esperar al servidor: no se ve desde
  los otros ni los maneja) y **animaciones** (portada viva, fondo que respira, ecualizador). "🔋 Modo ahorro" apaga
  los tres. Para gastar menos datos y batería en el celular.
- **Artistas como en Spotify:**
  - Biblioteca → Artistas enseña **solo los tuyos** (los que escuchas o tienes en Me gusta o playlists, los que
    más primero), con "Ver todos los artistas" al final; quien no tiene ninguno ve todos.
  - **Página de un artista:** "Tus canciones" (las suyas en tus Me gusta o playlists), luego "Populares" (las más
    puestas, sin repetir las tuyas: 10 y "Ver todas") y al final los álbumes.
  - Suena con **su propio aleatorio**, aparte del general (empieza apagado y cada uno se recuerda por separado;
    el botón 🔀 cambia el de lo que suena). "▶ Reproducir": primero las tuyas y luego las populares.
- **Cómo se llena la cola:**
  - **Canción suelta** (búsqueda, Lo más puesto, un género) → **modo radio**: esa y detrás recomendadas, que se
    añaden solas al final (~10 cuando quedan 2–3).
  - **Una lista** (filas del Inicio, Me gusta, playlist, álbum, artista) → la elegida pasa al primer puesto y detrás
    **la lista entera en su orden desde el principio**, sin repetirla, aunque la fila enseñe solo 20 (tocar la 7.ª:
    7, 1, 2, 3, 4, 5, 6, 8, 9…). Con aleatorio: la elegida y el resto mezclado.
  - **Si ya suena esa misma lista**, no se rehace: la tocada se adelanta y suena ya, y lo que venía detrás sigue
    igual (no vuelven las que ya sonaron). "▶ Reproducir" sí empieza de cero.
  - **"🔀 Aleatorio"** al lado de "▶ Reproducir" (Me gusta, playlists, álbumes, géneros; si hay 2 o más): enciende el
    aleatorio general y pone la lista entera mezclada empezando por una cualquiera.
  - **"⏭ Reproducir a continuación"** (menú ⋮ de cualquier canción): entra justo detrás de la que suena **solo en la
    cola de ahora** (no toca la playlist, Me gusta ni la lista de origen); varias, en el orden en que se añadieron;
    si ya estaba más adelante, se mueve. Sale marcada "Añadida" en la cola. Sin nada sonando, suena ya.
  - Al acabarse una lista, interruptor **"Seguir con canciones parecidas"** (radio de la última). Nunca entra una
    canción dos veces.
- **La cola en pantalla es una lista fija:** enseña como máximo las **2 últimas reproducidas en gris**, la actual y
  todas las siguientes. Las más antiguas se ocultan; el botón Anterior sigue permitiendo volver a ellas. Al pasar de canción no se repinta: solo cambia la resaltada (baja lo justo si
  queda fuera de la vista). Tocar una anterior la vuelve a poner. **Se reordena arrastrando:** desde el asa ≡
  (al momento, ratón o dedo) o manteniendo pulsada la fila (en el móvil ~0,35 s quieto, vibra); una línea marca el
  sitio y cerca del borde la lista se desplaza sola. Solo las que faltan, siempre después de la que suena.
- **En el PC:**
  - **≥1100 px:** contenido a la izquierda y el **reproductor grande fijo a la derecha** (portada viva, controles,
    volumen, cola y letra) en una tarjeta flotante con un ecualizador animado mientras suena; sin canción, "Aquí
    sonará tu música". La barra pequeña de abajo se oculta.
  - **≥1500 px:** tres tarjetas iguales: **la cola ("Siguiente") a la izquierda**, siempre a la vista, el contenido
    en medio y a la derecha solo la letra, con "Letra · ocultar" / "Mostrar letra" (se recuerda) y su barra pegada
    arriba al bajar.
- **Lo demás:** cristal (fondo translúcido con desenfoque) en tarjetas, reproductor y barras; el fondo toma los
  colores de la portada. Barras de scroll finas, sin scroll horizontal. Minirreproductor con anterior/siguiente y
  **volumen** (flechas arriba/abajo; se recuerda; en el móvil manda el del teléfono). Controles en la pantalla de
  bloqueo (Media Session). En Android, arriba "Instala la app" y en el menú del avatar "Descargar app Android"
  (`/app/enlace`).

**Portada viva** (reproductor grande de la web; la app debería hacer lo mismo): la portada se acerca y se mueve muy
despacio dentro de su marco (Ken Burns, 24 s, ida y vuelta) y sus colores desenfocados del fondo "respiran"; **solo
mientras suena** (en pausa, quieta) y nada si el sistema pide reducir movimiento. Es solo CSS: el servidor no hace
nada (la portada ya va en `thumb`), sin vídeo, sin espacio ni peticiones. Es lo que se ve si la canción no tiene Canvas.

**Canvas** (desde el 06-11-2026, `server/canvas.py`; el 30-10 se probó y se dejó para más adelante): como en Spotify,
**7 s del videoclip de fondo** en el reproductor grande, vertical (540×960, H.264), sin sonido y en bucle, ~100–500
KB por canción en `/var/lib/musicapp/canvas/<id>.mp4`. La portada deja su sitio al vídeo, y se para con la música.
- **De dónde sale:** si la canción se bajó de un vídeo de verdad (miniatura de vídeo y sin "Letra/Lyrics/Audio" en el
  título), de ese mismo vídeo. Si no (las pistas de álbum de YouTube Music, que son la portada quieta, o los vídeos con
  letra), **busca su videoclip** en YouTube Music (1 búsqueda), mejor del canal del artista o "Official Video", con
  artista, título y duración parecidos. Baja solo ese trozo (yt-dlp `download_ranges`, hacia el 35 % de la canción),
  quita las franjas negras (`cropdetect`) y lo recorta en vertical. Si el trozo casi no se mueve (una foto fija), no vale.
- **Una sola vez por canción:** lo que no tiene arreglo (sin videoclip, imagen quieta) queda en "no" para siempre y se
  queda la portada viva. Un fallo de otro tipo se reintenta a las 6 h (3 veces como mucho); si se cae la red con los
  servidores de vídeo, todo espera 30 min sin contarlo.
- **Orden:** 1) la que alguien pone (la web pregunta `GET /canvas/<id>/estado` al empezar cada canción; si no lo
  tiene, se hace ya, ~1 min, y la web vuelve a preguntar cada 20 s); 2) las que acaba de bajar la precarga (cada
  canción nueva de la precarga pide su Canvas); 3) todas las demás, las más puestas primero, de madrugada o de día si
  nadie usa YouTube, con 1,5–5 min al azar entre una y otra (~18 por hora). Todo por el ritmo general con YouTube;
  con aviso de bloqueo, 24 h quieto. Los de canciones que el tope de espacio borra se borran una vez al día.
- **Freno:** cada Canvas cuesta ~4 peticiones a YouTube (hasta ~9 si su vídeo sale quieto y hay que buscar otro). El
  06-11 llegó a 265 de 300 por hora. Con más de **150 en la última hora** (`BUSY`), solo se hacen las que alguien está
  poniendo; las de fondo y las de la precarga esperan. La cuenta de la última hora (y un bloqueo de YouTube) se guarda en
  `data/youtube-estado.json` (`recientes`) y **sobrevive a los reinicios** (antes volvía a 0 al reiniciar la API).
- **Estado** en `/data/canvas.json` (`ok`, `no` con el motivo, `err`); resumen en `GET /interno/canvas`. En el panel
  (`./panel.py`): pestaña **5 Precarga** (listos, sin videoclip, cuánto ocupan, el último y si está en espera) y una
  línea en la tarjeta de la precarga del Resumen.
- **Nodo de vídeo de respaldo** (`use_fallback` en `app.py`, para el Canvas y para todas las descargas): si el nodo
  que da YouTube no responde, se usa el de respaldo que trae el propio enlace (`mn=principal,respaldo`, `fvip`), como
  hace su reproductor. El 06-11-2026 de madrugada se cayó la caché de YouTube del proveedor de internet
  (`sn-xouxa…`, 181.42.62.81) y no bajaba nada, ni la precarga; **no era un bloqueo** (YouTube contestaba normal).
- **Iconito en la esquina de la portada** cuando no se ve el Canvas (para probar y saber que no es un fallo): tachado =
  no tiene (al tocarlo dice el motivo), latiendo = se está haciendo, reloj = en espera, aviso = error. Con Canvas no sale.
- **Con Canvas**, el vídeo se ve limpio (solo una capa leve y sombra en el texto, que va en blanco) y Siguiente / Letra
  van en una cajita de cristal flotante como la barra de Inicio / Buscar / Biblioteca.
- En la web, el vídeo solo se baja con el reproductor grande a la vista (en el PC siempre; en el móvil al abrirlo), y
  con "reducir movimiento" no sale.

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

Python con **FastAPI** + **yt-dlp** en el contenedor `musicapp-api` (usuario 10001, que no existe en el servidor:
ni root ni `lainer`; actualiza yt-dlp en cada arranque, como el bot). Sus datos (`server/data/`, `/var/lib/music`,
`/var/lib/musicapp/recomendar`) son del 10001 y del grupo **`musicapp`**, en el que está `lainer`: así el panel y
las listas de precarga se tocan sin `sudo` (carpetas con setgid, para que lo nuevo herede el grupo). Para pruebas desde este servidor: `127.0.0.1:8090` (app) y `127.0.0.1:8091` (bot).

| Ruta | Qué hace |
|---|---|
| `GET /health` | `{"ok": true}`, sin clave |
| `POST /auth/google` | Cuerpo `{"id_token": "…"}` (con `"web": true`: sesión de 10 min que no cuenta como dispositivo, para algo que solo baje la app; hoy no se usa) (el que da Google a la app). Aprobado → `{"session": …, "user": …}` (sesión de 90 días); nuevo o pendiente → 403 `pendiente`; bloqueado → 403 `bloqueado`. Sin clave |
| `GET /me` | Quién es el dueño de la sesión |
| `POST /auth/logout` | Cierra la sesión usada |
| `GET /` y `GET /acceso` | **La página principal** (`server/web/acceso.html`, estilo Dark Premium y logo del perrito): entrar con Google; al aprobado le abre la app web, a los demás les dice si quedaron pendientes (ver "Repartir la app y versión web"). Sin clave |
| `GET /web/…` | **La app en el navegador** (`server/web/web.html`): Inicio, Buscar, Biblioteca, favoritas y reproductor. Cualquier ruta bajo `/web/` da la misma página. Usa la sesión que guardó la página principal; sin ella, vuelve a `/`. Sin clave (la página en sí no tiene datos) |
| `GET /logo.png`, `/logo-480.webp`, `/logo-96.webp` | El logo: original PNG 512×512 (505 KB) y las versiones ligeras que usa la página (WebP 25 KB y 3 KB; el de 96 también es el icono de la pestaña). Solo nombres `logo…png/webp` de `server/web/`. Sin clave |
| `POST /app/enlace` | Para aprobados: enlace de descarga de la app que sirve 10 min (`{url, minutes, size, date, sha256}`); 404 si aún no hay APK |
| `GET /app/version` | Versión publicada de la app (`version.json` junto al APK, p. ej. `{"build": 18, "version": "1.0.17"}`, más `sha256`: la huella del APK que se sirve, calculada por la API); la app avisa si `build` es mayor que el suyo y se actualiza con `/app/enlace`. 404 si no hay. Pide sesión |
| `GET /app/descargar/<enlace>` | El APK (`musica.apk`). Enlace caducado o inventado → 404. Sin clave: el enlace ya lo es |
| `GET /search?q=…` | Primero lo guardado (de 20 en 20 con `&offset=&limit=` hasta 200; `total` dice cuántas guardadas hay en total: "rawayana" → 78; `artists`: los artistas que encajan, también con faltas ("cancerbero" → Canserbero), en la primera página; todas las palabras en título/artista/álbum, pero cada una vale exacta, a medio escribir o en plural/singular: "one pilot" encuentra la banda, "hope" encuentra Hope y Hopeless. **Las faltas** ("chayane", "stresed out") solo cuentan en palabras de 5 letras o más, y **las faltas y los plurales** ("pilots" → "pilot") **solo si sin ellos no sale nada** (si no, "juanes" traía a Juan Luis Guerra y Juan Magán como plural de "juan"). Ver `Library.find`). Con `&yt=1` (por defecto, solo en la primera página) trae en `internet` hasta **20 canciones de YouTube Music** **tal cual las da su buscador**: las mismas, en el mismo orden, sin añadir, quitar ni reordenar (con artista, álbum y duración). Lo guardado sigue en su fila marcado como `guardada` (y con el `id` de la copia del servidor si está con otro título) y `results` lleva detrás solo las de `youtube`, para versiones viejas de la app. Cada resultado: `id`, `title`, `artist`, `album`, `duration`, `thumb`, `where` (`guardada`/`youtube`). `&yt=0` = solo lo guardado (sin tocar YouTube) |
| `GET /suggest?q=…&n=8` | **Sugerencias mientras se escribe**, de lo guardado (sin YouTube, ~45 ms): artistas (con su nº de canciones), álbumes y canciones cuyas palabras empiezan por lo escrito ("raw" → Rawayana · 78, RawayanaLand…): `{sugerencias: [{tipo: artista\|album\|cancion, texto, artista, id, canciones, thumb}]}` |
| `GET /search/albums?q=…` | Álbumes de internet (YouTube Music): `{albums: [{id, title, artist, year, type, thumb}], artista}`. Si lo escrito es un artista, aunque tenga faltas ("guns ando rose" → Guns N' Roses, por la biblioteca o por las canciones ya buscadas), busca **los suyos** y solo enseña los suyos (`artista`; la búsqueda de álbumes de YouTube Music no corrige faltas y traía de Anuel). 1 petición la primera vez; luego de memoria. Pide sesión |
| `GET /search/album/<id>` | Un álbum de internet con sus canciones **en orden** (`track`) y `where` (cuáles ya están guardadas). 1 petición la primera vez. Poner una canción baja solo esa. Pide sesión |
| `GET /library?sort=…&offset=0&limit=50` | **Toda la música guardada por páginas**, para ir cargando según se baja (scroll infinito): `{total, offset, songs}`. `sort`: `recientes` (la última que sonó primero, por defecto), `populares`, `nombre` (A-Z) o `artista` (A-Z). `&genre=…` filtra por género. `limit` hasta 200. No hay más cuando `offset + len(songs)` llega a `total`. Pide sesión |
| `GET /favorites` | **Mis favoritas** (las mismas en la app y en la web), la última marcada primero: canciones como en `/search` más `added`. Las que ya no están guardadas salen con `where: youtube` (al ponerlas se vuelven a bajar). Pide sesión de un usuario (la clave compartida no tiene: 400) |
| `PUT /favorites/<id>` | Marcar como favorita. Si está guardada, la ficha sale de la biblioteca; si es un resultado de YouTube, mandar en el cuerpo `{title, artist, album, duration, thumb}` |
| `DELETE /favorites/<id>` | Quitar de favoritas |
| `GET /playlists` | **Mis playlists** (iguales en la app, la web y otros móviles), la última cambiada primero: `{playlists: [{id, name, songs: [canciones como en /search], created, updated}]}` |
| `POST /playlists` | `{name}` → `{id}`. Como mucho 200 playlists |
| `PUT /playlists/<id>` | `{name, songs: [ids en orden]}`: **guarda la playlist entera** (quitar, añadir y reordenar son el mismo cambio; lo hecho sin conexión se sube igual, gana el último en guardar). Una canción que el servidor no conoce (ni guardada, ni en favoritas o playlists, ni en búsquedas recientes) va como ficha `{id, title, artist, album, duration, thumb}`; si falta, 400 con `{detail: {error, ids}}`. Hasta 2.000 canciones |
| `DELETE /playlists/<id>` | Borrar una playlist |
| `GET /import/youtube?url=…` | **Leer una playlist o un Mix de YouTube / YouTube Music para importarlo** (no guarda nada): `{name, songs: [canciones como en /search], total, truncated}`. Playlist normal (`PL…`, `OLAK…`, `RDCLAK…`): todas, hasta 500 (100 por petición). Mix (`RD…`): la primera tanda (~50; la siguiente no acaba nunca), empezando por el `v=` del enlace, sin lo de más de 15 min y sin "(Official Video)" en los títulos; nombre "Mix: <primera canción>". Cada canción va marcada `guardada` (también si es otra copia: lleva el `id` de la del servidor) o `youtube` (se baja al sonar). Enlace sin `list=`, de otra web o lista privada (`LM`, `LL`, `WL`): 400 con el motivo; lista que no se puede leer: 404. 1–6 peticiones a YouTube Music y solo cuando alguien lo pide. La web (botón 🔗 en Tu biblioteca) y la app crean después la playlist con `POST` + `PUT /playlists` |
| `GET /home` | Secciones del Inicio recomendadas: `{secciones: [{id: recientes\|para_ti\|vuelve\|artistas, titulo, tipo, items}]}`; `tipo: canciones` o, en `artistas` ("Tus artistas", hasta 20), `tipo: artistas` con items como `/artists` (ver `docs/recomendaciones.md`) |
| `GET /radio?desde=cancion:<id>\|artista:<nombre>&ya=<ids>&n=20` | Radio infinita: las siguientes `n`, sin repetir lo de `ya` |
| `POST /eventos` | `{eventos: [{tipo: entera\|salto\|no_me_gusta\|ya_no_me_gusta, id, segundo, duracion, contexto, causa, cuando}]}` en lote ("empezó a sonar" lo apunta `/stream`) |
| `POST /recomendaciones/opinion`, `GET /recomendaciones/preguntar?contexto=` | "¿Qué te parecieron?" y si toca preguntarlo (una vez por semana) |
| `GET /history?limit=50` | **Lo último que puse yo** (no lo de todos), lo más reciente primero, con `played`. Se apunta solo al empezar a sonar una canción por `/stream` (los saltos dentro de la canción no cuentan); hasta 200 |
| `GET /genres` | Géneros de lo guardado: `{genres: [{name, songs}]}`, los que más tienen primero (ver "Género y fichas"). Para filtrar: `/library?genre=…`. Pide sesión |
| `GET /artists` | Todos los artistas guardados: `{artists: [{name, songs, albums, thumb}]}`, los que más canciones tienen primero; con `?orden=tuyos`, primero **los que más escuchas** (`tuyo: true`; cada vez que pusiste una canción suya cuenta, la mitad a los 45 días, y suman un poco favoritas y playlists: `Recomendar.top_artists`). Agrupa sin mayúsculas ni tildes ("Milo j" = "Milo J"); a las canciones sin artista en su ficha pero con título "Artista - Canción" les toma lo de antes del guion. Pide sesión |
| `GET /artist?name=…` | Un artista: `{name, songs, albums: [{name, year, songs, thumb}], loose: [canciones sin álbum y colaboraciones]}`; álbumes del más nuevo al más viejo. Con sesión de usuario, además **`tuyas`** (las suyas en tus favoritas, la última marcada primero, y luego en tus playlists) y **`todas`** (la cola de "Reproducir": las tuyas y luego las demás, las más puestas primero). 404 si no hay. Pide sesión |
| `GET /album?artist=…&name=…` | Las canciones guardadas de un álbum: `{name, artist, year, thumb, songs}` (`thumb`: la portada del álbum), por fecha y título (YouTube no da el número de pista; las bajadas por la precarga sí lo traen, `track_no`). 404 si no hay. Pide sesión |
| `GET /canvas/{id}/estado` | ¿Tiene Canvas? `{estado: listo \| haciendo \| no, motivo?, espera?}` (`motivo`: por qué no tiene; `espera`: por qué no se puede hacer ahora, p. ej. sin red con YouTube). Preguntarlo al empezar cada canción: si no lo tiene ni se intentó, se hace ya (~1 min). `no` es para siempre (portada viva). Pide sesión |
| `GET /canvas/{id}` | El Canvas: `video/mp4` (H.264, 540×960, 7 s, sin sonido) para poner en bucle; 404 si no tiene. Pide sesión o el `?t=` del enlace de esa canción (la TV) |
| `GET /lyrics/{id}` | La letra: `{synced (LRC con tiempos) o null, plain o null}`, de lrclib.net con el artista, el título limpio y la duración (si no, buscando). Se recuerda (las que no tienen, un día). Sesión o el `?t=` de esa canción |
| `GET /tv/` | La pantalla de la TV (receptor de Google Cast, App ID `25E4DFA9`): sin login, ver "Pantalla de la TV" |
| `GET /conectar?disp=&nombre=&desde=` | Escuchar en varios dispositivos: `{v, activo, activo_vivo, este, dispositivos: [{id, nombre, vivo}], sonando: {cancion, pos (el segundo de ahora), pausa, cola, qi, radio, repetir, aleatorio, duracion}, ordenes}` (`ordenes`, solo al que suena). Si `v` sigue siendo `desde`, espera un cambio (25 s). `disp`: 6–40 letras, números, `_` o `-`. Pide sesión |
| `POST /conectar/estado` | `{disp, nombre, datos, tomar?, hecho?}`: el que suena cuenta lo que pasa (`datos` como `sonando`; `cola` solo si cambió). 409 si suena en otro dispositivo vivo, salvo `tomar`. `hecho`: la última orden ya hecha |
| `POST /conectar/salir` | `{disp}`: ese dispositivo se cierra (la TV al apagarse): los demás dejan de verlo al momento, sin esperar los 45 s de `VIVO`; si sonaba ahí, queda en pausa en su segundo |
| `POST /conectar/orden` | `{disp, tipo, datos}` para el que suena: `pausa {pausar}`, `siguiente`, `anterior`, `ir {pos}`, `cola {cola, qi, nueva?, radio?, repetir?, aleatorio?}`, `transferir {a}` (que suene en el dispositivo `a`, en el mismo segundo), `desconectar {a}` (cerrar la TV `a` (id `tv…`), la conectara quien la conectara: la TV lo ve en `desconectar: true` de su `GET /conectar` y se cierra; si sonaba allí, lo de allí queda en el que la cierra, en pausa). 409 con el motivo |
| `GET /stream/<id>` | El audio (`audio/webm`, Opus) por ID de YouTube. Si no está guardado lo baja (una sola vez aunque lo pidan varios a la vez). Admite `Range` (saltar dentro de la canción). Cabecera `X-Source` dice de dónde salió. Con la sesión en la cabecera, o con `?t=` de un enlace de la ruta siguiente |
| `POST /stream/<id>/enlace` | `{url}`: enlace a `/stream/<id>?t=…` firmado (`server/data/stream.key`, se crea sola) que vale solo para esa canción y esa cuenta durante 6 h, sin la sesión dentro. Lo usa la web, porque `<audio>` no puede mandar la cabecera; si se copia, no da acceso a la cuenta. Borrar `stream.key` caduca todos |

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
| `GET /interno/youtube` | Cómo está YouTube: `{bloqueado_hasta (0 si no), peticiones_hora, tope_hora, ultimo_bloqueo}`. El bot lo usa para avisar en el canal de registro |
| `GET /interno/precarga` | Cómo va la precarga de álbumes: artistas hechos, cola, bajadas, saltadas, fallidas |
| `GET /interno/stats` | `{songs, bytes, max_bytes}` |
| `POST /interno/resolve` | `{"query": …, "limit": n}`: buscar un nombre (`ytsearch5:…` o el nombre a secas: **YouTube Music**; con `yt:` delante o si no hay nada, YouTube normal) o leer un enlace (video, lista, SoundCloud…) sin bajar nada. Título, duración, miniatura, artista y `entries` si es lista o búsqueda |
| `GET /interno/song/<clave>` | Ficha sin contarla como puesta |
| `POST /interno/played/<clave>` | Sonó: suma una vez puesta y actualiza el último uso |
| `POST /interno/fetch` | `{"url": …, "by": <id de Discord>}`: "dame esta canción". Guardada → `source: local`; si no, la baja → `online`; directos → `live`, sin archivo y con `info.url` para escucharlo |
| `POST /interno/cambiar` | `{viejo, nuevo, olvidar?}` (ids de YouTube): cambia una canción por otra versión en todas las cuentas (favoritas con su fecha, playlists en su sitio, historial), bajando `nuevo` aunque parezca la misma; desde entonces pedir `viejo` da `nuevo`; `olvidar` (por defecto) borra la vieja. Se usó el 06-11-2026 con *Frijolero*: el videoclip de MolotovVEVO viene **censurado**, la del disco *Dance And Dense Denso* no |
| `POST /interno/ficha/<clave>` | Completa artista/álbum preguntándole a YouTube; 503 si está bloqueado |
| `DELETE /interno/song/<clave>` | Olvidar: borra archivo y ficha |

### Escuchar en varios dispositivos (como Spotify Connect)

Desde el 06-11-2026 (`server/conectar.py`; en la web; la app, pendiente). Cada cuenta tiene **una reproducción**: la
que suena en un dispositivo (la web del PC, la app del celular…), y los demás de la misma cuenta **la ven y la
manejan**. No toca YouTube.
- **Cada dispositivo** se da un id (la web lo guarda en el navegador) y un nombre ("PC · Chrome", "Celular · Chrome").
- **El que suena** cuenta lo que pasa (`POST /conectar/estado`): canción, segundo, cola entera, aleatorio, repetir,
  pausa. Lo hace al cambiar algo y cada 15 s mientras suena. Si otro dispositivo vivo está sonando, 409; con `tomar`
  (darle play aquí), la música pasa a este y el otro se pausa solo.
- **Todos esperan cambios** con `GET /conectar` (espera larga de 25 s, `async`: no ocupa hilos). Un dispositivo está
  vivo si preguntó hace menos de 45 s.
- **Si suena en otro**, el mini reproductor y el grande enseñan eso ("🔊 En PC · Chrome" / "Sonando en PC · Chrome")
  y sus botones son un mando (`POST /conectar/orden`): pausa, siguiente, anterior, ir a un segundo, y cualquier cambio
  de la cola (poner una lista o una canción, "a continuación", mover, quitar, aleatorio, repetir) se hace en la copia
  de la cola y se manda entera (`cola`). El volumen se esconde (es el de allí).
- **🔊 Dónde suena** (botón debajo de los controles del reproductor grande): la lista de dispositivos abiertos; al
  elegir otro (`transferir`), el de antes se pausa y el nuevo sigue **en el mismo segundo**. Con un solo dispositivo abierto es
  solo el icono, sin texto; con otro abierto dice "Este dispositivo".
- Si el que sonaba se cierra, lo de allí queda en los demás **en pausa, en su segundo**, para seguir donde se dejó.
- El que suena cuenta play, pausa, fin de canción y cada orden **al momento** (no espera al intervalo: con la pestaña
  en segundo plano Chrome lo frena a una vez por minuto; lo avisó la sesión de la app el 06-11-2026).
- **Google Cast (app, próxima versión):** el celular manda a la TV los enlaces de `POST /stream/<id>/enlace` (la TV
  pide `/stream/<id>?t=…` con Range; firmados, sin sesión en la cabecera, 6 h); en `/conectar` sigue de activo el
  celular, con el nombre "Celular · App → <TV>". La API no necesitó nada nuevo (comprobado: 206 con Range por el túnel).
- Se guarda en `/data/conectar.json` cada 20 s. Prueba con dos navegadores sin tocar cuentas reales:
  `tools/probar-conectar.sh` (servidor de mentira con la lógica real y audio de mentira).

### Pantalla de la TV (Google Cast)

Desde el 06-11-2026: `server/web/tv.html` + `tv.js`, en `https://musica.yoneapolis.com/tv/`, registrada en la consola
de Cast como receptor propio (App ID `25E4DFA9`, inédito: solo en la TV registrada del dueño; modo invitado apagado).
La app (sender) manda la cola por Cast (la que suena y las siguientes, mejor 6 para llenar "A continuación": `contentUrl` = enlace firmado de
`POST /stream/<id>/enlace`, `audio/webm`, metadata de música con portada, `customData.id`) y maneja pausa, siguiente,
etc. La página suena en su `<audio>` con el reproductor de CAF y enseña, para mirarla de lejos en 16:9: el **Canvas**
(vertical) o la portada que se mueve, el fondo difuminado que respira, título y artista grandes, la **letra** (línea
actual y siguiente), la barra y **"A continuación"**. El vídeo se para con la música. En un parlante Cast (sin
pantalla) solo suena: no pide Canvas ni letra.
- **El reproductor es el `<audio>`**, el único elemento de medios al arrancar; el `<video>` del Canvas lo crea `tv.js`
  después, cuando hace falta (con `disableRemotePlayback`). En la primera prueba (06-11-2026, Google TV iFFalcon, app
  1.0.46) el vídeo estaba en el HTML antes que el audio y Cast lo cogió a él: no sonaba, se pausaba y cada canción
  duraba 7 s. En `chrome://inspect` salen avisos `[tv] …` (qué se cargó, cuánto dura según Cast, si el audio tiene el
  `/stream` y cuántos vídeos hay).
- **Seguridad:** pública y sin login, pero sin datos: nunca la sesión. El `?t=` del enlace vale solo para esa canción y
  esa cuenta (audio, `/canvas/<id>` y `/lyrics/<id>`; nunca favoritas, playlists ni historial). Como cualquiera con el
  App ID podría lanzarla, solo acepta audio de `/stream/…` de este dominio e imágenes de aquí, `i.ytimg.com` y
  `*.googleusercontent.com` (portadas de YouTube Music); lo demás lo ignora (también al cargar o añadir a la cola).
  CSP: `script-src 'self' https://www.gstatic.com` (el código va en `tv.js`), media y connect solo de aquí (+ gstatic),
  sin fuentes de fuera; `X-Robots-Tag: noindex`.
- **Botones en la TV:** −10 s · ⏮ · ⏯ · ⏭ · +10 s debajo de la barra; con el control remoto, ← → eligen (el elegido,
  iluminado; al abrir, ⏯) y OK pulsa; ↑ también pausa/sigue (por si el OK de algún mando no llega a la página). Las
  teclas multimedia del mando (⏯, ⏭, ⏮, ⏩, ⏪) también valen. Sale un aviso grande un momento; Cast avisa del cambio
  a la app o la web que mandó la música. Las teclas que no se usan quedan en el registro ("tecla: …"). Las flechas se
  interceptan antes que Cast (que en Google TV las usaba para adelantar/atrasar al navegar entre botones); si aun así
  la canción salta con una flecha, queda en el registro ("saltó sola con la flecha"). El marco del Canvas es siempre
  vertical (9:16): sin Canvas, la portada cuadrada en medio sobre ella misma difuminada, para que no cambie de tamaño.
- **Desde la web también** (Chrome en PC o Android, con el SDK de Cast): botón 📺 junto a 🔊 en el reproductor grande
  (sale si hay una TV con Cast en la red). Al conectar, la web le da a la TV su llave y **la cola entera** (hasta 300,
  `TV_COLA`; por el canal propio, `{tipo: "cola", cola, qi, pos, radio}`) y la TV la pone y suena ella, igual que al
  elegir algo en sus menús: cuenta lo que suena en "varios dispositivos" y la web pasa a ser **un mando** de la TV
  (play, siguiente, la barra, cambiar la cola… van como órdenes; el volumen, por Cast). Si es radio, el mando le busca
  más cuando quedan 2. Si a los 5 s de tener la llave nadie le ha pasado la cola (la pantalla puede tardar ~20 s en cargar y el
  mensaje perderse), la TV pregunta a `/conectar` qué suena en la cuenta y lo pone ella. Al recargar la página, la TV sigue con lo suyo; al desconectar, lo de la TV queda en la página
  en pausa. **Cambiar dónde suena con la TV conectada:** elegir este navegador en "Dónde suena" lo hace sonar
  aquí (la TV queda abierta, en pausa); elegir la TV la vuelve a poner (la TV retoma la cola y el segundo del
  servidor). Cualquier dispositivo que se quede la música pausa la TV, sea de quien sea la cola. Mientras suena en
  otro, la TV hace de **espejo**: enseña esa canción, su barra y "Sonando en PC · Chrome", y sus botones la manejan
  a distancia (órdenes de `/conectar`). (Hasta el 06-11-2026 la web le pasaba unas pocas canciones por Cast y se descuadraban: dos maneras de
  sonar a la vez.) La app aún manda por Cast la cola a trozos: debería hacer lo mismo que la web.
- **La llave de la TV** (`POST /tv/llave`, solo con una sesión de verdad): al conectar, la web (y la app, pendiente) le
  pide una y se la manda a la TV por un canal propio de Cast (`urn:x-cast:com.yoneapolis.musica`, `{tipo: "llave",
  llave, caduca}`); al desconectar la anula (`DELETE /tv/llave`). Empieza por `tv.`, dura 24 h, no cuenta como
  dispositivo y **solo vale para mirar y escuchar** (`TV_ALLOWED` en `app.py`: Inicio, biblioteca, playlists, artistas,
  buscar, el enlace del audio, Canvas, letra, varios dispositivos, eventos); en lo demás (Me gusta, playlists, cuenta,
  Discord…) 403 "la TV solo puede mirar y escuchar". Huellas en `/data/tv-llaves.json`. Es la base de los menús en la TV.
  **Si otra persona conecta la misma TV con su cuenta**, gana la última (como en Spotify): la TV se despide de la
  cuenta de antes (`/conectar/salir` con la llave vieja; sus dispositivos lo ven al momento), recarga los menús con lo
  de la nueva y avisa "Ahora la usa <nombre>". Ojo: "Dejar de enviar" del menú de Cast de Chrome cierra la TV para
  todos (es de Google).
- **Menús en la TV** (con la llave): pestañas **Ahora · Inicio · Biblioteca · Buscar** arriba. Inicio: las filas de
  `/home` (recientes, Para ti, Vuelve a escuchar, Tus artistas), Tus Me gusta y Tus playlists; Biblioteca: Me gusta,
  playlists y tus artistas; dentro, playlist, álbum o artista con ▶ Reproducir / 🔀 Aleatorio y sus canciones; Buscar:
  teclado en pantalla y resultados de lo guardado (`/search?yt=0`). Se recorre con las flechas (van al elemento más
  cercano en esa dirección; todo lo elegible lleva la clase `f`) y OK; "← Volver" en pantalla; Atrás del mando también
  vuelve (la TV sí deja ver la tecla: `BrowserBack`). **⏻ Salir** al final de las pestañas cierra la pantalla (pide
  un segundo OK en 4 s); la web o el celular ven que se desconectó y se quedan la música en pausa. Al elegir algo, **la TV pone su propia cola** (enlaces de `POST /stream/enlaces`, de una vez) y
  suena sola, sin depender del celular; en "varios dispositivos" es el dispositivo "TV" (id que empieza por `tv`): la
  web pasa a mando sin pausarla, y la TV hace las órdenes de los otros. Si nada suena ni se toca el control en 30 min,
  se cierra sola (`disableIdleTimeout`: Cast ya no la cierra a los 5). En un navegador: `/tv/?demo&llave=x`.
- **Cómo se ve:** en Ahora, "A continuación" es una fila con las 6 próximas (↓ para llegar, OK salta a esa) y al
  final **☰ Lista completa**: toda la cola de la TV, con la que suena elegida; OK salta a esa y vuelve a Ahora. La letra,
  en un cuadrito de cristal. En los
  menús, lo que suena queda **a la izquierda** en un panel solo de información (portada o Canvas, título, artista,
  barra), como el panel del reproductor de la web en el PC; llegando a él con ← y OK se va a Ahora, donde están los
  botones. Inicio empieza con un saludo ("Buenas tardes, Yoni") y accesos rápidos (Me gusta y 5 playlists); las filas
  van de borde a borde, alineadas con los títulos. En las listas, cada canción con su número y la que suena marcada.
  Las flechas: de lado gana lo que está a la misma altura; arriba/abajo, lo de la misma columna.
- **Registro de la TV:** la página manda sus avisos `[tv] …` y errores a `POST /tv/registro` (solo con la firma de la
  canción que suena, o con la llave si aún no suena nada) y salen en el registro de la API: `docker logs -f musicapp-api 2>&1 | grep "TV de"`.
  Lo que hace la web con la TV (cuántas le manda, a qué canción pasó) va a `POST /web/registro`: `grep "Web de"`.
- **Probarla en un navegador:** `/tv/?demo&id=<id>&titulo=…&artista=…&img=…&sig=…` (sin TV; el Canvas y la letra
  necesitan un `t` válido). En la TV registrada se depura desde `chrome://inspect` del PC.

### Pestaña DC (controlar el bot desde la app)

La cuenta de la app (Google) se une una vez a la de Discord con "Entrar con Discord" (OAuth, permiso `identify`:
solo id, nombre y foto; se guarda en `users.json`). Con eso, quien está en un canal de voz con el bot ve la cola y la
maneja. **La cola no se copia aquí:** vive en el bot, que abre un servidor interno (`musicbot:8100`, solo en la red de
Docker, con `BOT_API_KEY`); la API comprueba la sesión y le pasa la petición (`server/discord_dc.py`).

| Ruta | Qué hace |
|---|---|
| `POST /discord/inicio` | `{url}`: el enlace para abrir en el navegador, de un solo uso, 10 min |
| `GET /auth/discord/callback` | Adonde vuelve Discord. Guarda el vínculo y enseña "Listo, vuelve a la app". Un Discord solo puede estar en una cuenta |
| `DELETE /discord` | Desvincula |
| `GET /dc/estado?desde=<version>` | **Espera larga:** si la versión sigue siendo `desde`, contesta al cambiar algo o a los 25 s. `estado`: `sin_vincular` (contesta al momento), `fuera_de_voz`, `sin_bot`, `ocupado` (los bots están en otros canales) o `con_bot`. Con bot: `canal`, `bot`, `actual` (con `posicion`), `pausada`, `cargando`, `repetir`, `acciones` (las 5 últimas), `anteriores` (las 2 últimas que sonaron, la más reciente al final, nunca la que suena aunque ya sonara antes; el bot recuerda 20) y `cola`. Canciones: `{qid, id, titulo, artista, duracion, miniatura, pedida_por}`; `id` es `null` si no son de YouTube |
| `POST /dc/pedir` | `{id, siguiente?}`, el `id` de `/search`. Si no hay bot en tu canal, entra. 409 "Ya está en la cola" si esa canción ya suena o espera (la misma regla vale al pedir una suelta por Discord; listas, álbumes y aleatorio no la miran) |
| `POST /dc/saltar` | `{qid}`: salta esa canción solo si sigue sonando |
| `POST /dc/anterior` | `{qid}` de la que se ve (`null` si no suena nada): vuelve a la anterior, como el botón del panel, y la que sonaba queda justo detrás. Hay anterior si `anteriores` no está vacío |
| `POST /dc/pausa` | `{pausar}`: pausa o reanuda; no alterna |
| `POST /dc/quitar` | `{qid}`, también la que suena |
| `POST /dc/mover` | `{qid, antes_de}`; `antes_de: null` la manda al final. El `qid` también puede ser de `anteriores`: sale del historial (ya no está para ⏮️) y vuelve a la cola con el mismo `qid` ("↩️ volvió a poner"); al sonar otra vez, vuelve a `anteriores` como cualquiera. Si no sonaba nada, empieza a sonar |

Errores en `detail`: 403 (no estás en el canal del bot o sin vincular), 404 (esa canción ya no está), 409 (bots
ocupados, o la cola cambió mientras movías), 422 (no se pudo añadir), 503 (el bot no contesta).

**Varios a la vez:** las órdenes de la app y de Discord se aplican de una en una en el bot y van por `qid`, no por
posición: dos saltos a la vez saltan una sola, y mover algo que ya no está da error en vez de dejarlo en otro sitio.
Con dos arrastres seguidos gana el último. Quien está en el canal puede hacer todo, igual que con el panel, y
`acciones` enseña quién hizo qué.

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
  bloqueo); lo guardado sigue sonando. **Cómo enterarse:** el panel tiene una línea fija "YouTube: ✅ normal · N de
  300 peticiones en la última hora" que pasa a **🔴 BLOQUEADO hasta las HH:MM**; el bot de Discord escribe en el canal
  de registro "⛔ YouTube nos bloqueó…" y "✅ YouTube vuelve a responder" (consulta `GET /interno/youtube` cada
  minuto); y cada bloqueo queda en `server/data/youtube-bloqueos.jsonl` (cuándo, hasta cuándo, de dónde y cuántas
  peticiones llevábamos esa hora). El estado actual, en `server/data/youtube-estado.json` (se reescribe cada 30 s).

**Clave:** todas las rutas que no dicen "Sin clave" piden una **sesión** de un usuario aprobado como
`Authorization: Bearer …`, **solo en la cabecera**: `?token=` en la dirección se quitó el 03-11-2026 (una sesión en la
dirección se queda en historiales y registros). Para el audio en el navegador, `POST /stream/<id>/enlace`. La app
1.0.38 y anteriores pedían el audio con `?token=`: no suenan hasta actualizar a la 1.0.39. También vale la clave compartida
`API_TOKEN` (en `server/.env`, fuera de git) para pruebas desde el servidor, salvo en lo que es de cada usuario (favoritas, historial: 400); se quitará
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

**Sin artista en la ficha** (vídeos subidos sin datos de música): se toma del título. "Artista – Canción" es lo
normal, pero si lo de **detrás** del guion es un artista que existe o el canal que lo subió ("Numb (Official Music
Video) [4K] – Linkin Park"), manda ese lado. **Artistas con colaboraciones**: "Diomedes Díaz & Juancho Rois" cuenta para Diomedes Díaz si él tiene canciones a
su nombre (un dúo de verdad, "Simon & Garfunkel", no se parte), y **sale también en la página de los demás**
(Juancho Rois, si tiene canciones propias), igual que quien va en un **"feat./ft." del título** ("HIGH feat.
Apache" sale en Apache; cada canción una vez aunque el nombre esté en el artista y en el "ft."). **Nombres de
canal**: "Canserbero Music", "X VEVO", "X Official", "X TV" cuentan como el artista X si existe; si la ficha trae
el canal que la subió ("DOBLE S") y el título es "Canserbero – …", manda el título. **Sin artista**: si el título
empieza o acaba por un artista que ya existe ("SHAKIRA || BZRP…", "Qué tengo que hacer. Daddy Yankee"), es suya.
Así la página de un artista y su búsqueda dan lo mismo; la búsqueda solo trae de más canciones que **se llaman**
como él ("Apache" de The Sugarhill Gang). **Buscar artistas tolera faltas** (`Library.find_artists`):
primero por cómo empieza cada palabra ("raw" → Rawayana); si no hay ninguno, el más parecido ("cancerbero" →
Canserbero, "chayane" → Chayanne).

**Precarga de álbumes** (`precarga.py`, dentro de la API): baja poco a poco los **álbumes de estudio** de los
artistas con **5 o más canciones guardadas** (120 el 30-10-2026; en total ~6.000 canciones, ~27 GB, unas 5–6
semanas).

- **Qué baja:** como mucho **6 álbumes por artista** (`MAX_ALBUMS`), los más escuchados, sin gastar peticiones:
  primero los que tienen los éxitos del artista según YouTube Music, luego los que ya tienen canciones aquí, luego
  los más nuevos. Se salta directos, instrumentales, karaokes, recopilatorios ("Greatest Hits", "Uniquehits", "Lo
  Mejor De…", "Vol. 1") y ediciones repetidas, y las canciones que ya están (también otra versión del mismo título).
- **Pistas del disco, no videoclips:** usa la **lista de audio** del álbum (`audioPlaylistId`; si no, "City Walls"
  de *Breach* bajaba como el vídeo de 9:55). Quedan con **título limpio** ("City Walls"), la **portada del álbum**,
  artista, álbum, año y número de pista (`track_no`).
- **A ritmo de persona, no de robot:** entre canciones espera el 40–110 % de lo que dura la canción (al azar); entre
  álbumes, 5–30 min y, 1 de cada 7 veces, 30–90 min. De madrugada (**01:00–09:00 de Chile**) siempre; de día un 50 %
  más lento y solo si nadie usó YouTube en 10 min. Si YouTube avisa de bloqueo, para 24 h. Unas 15–20 canciones/hora.
- **Orden:** primero los adelantados (`server/data/precarga-primero.txt`, un artista por línea, en ese orden; el
  30-10-2026: Maná) y luego uno al azar entre los 3 más escuchados que falten. Se adelanta en cuanto acabe el álbum
  que esté bajando.
- **Saltar:** una línea `Artista | Álbum` en `server/data/precarga-saltar.txt` (sin distinguir mayúsculas ni
  tildes), o `Artista | *` para el artista entero. Lo que ya estaba en cola sale al momento; lo ya bajado se borra a
  mano (`DELETE /interno/song/<clave>`). Saltados el 30-10-2026: Rawayana | ASTROPICAL, Milo j | 166 y Milo j | 111.
- Los dos archivos se leen en cada paso, **sin reiniciar**, y se manejan también desde el panel (`:P`, `:A`, `:X`).
- **Estado:** `server/data/precarga.json` (con `now` = lo que hace ahora y `lista` = los artistas, para el panel);
  `curl -H "Authorization: Bearer $BOT_API_KEY" 127.0.0.1:8091/interno/precarga`. Para pararla: quitar la línea
  `PRECARGA = …` de `app.py`.

**Canciones repetidas** (`duplicadas.py`, dentro de la API): la misma canción guardada varias veces con otro
título ("Numb", "Numb (Official Music Video) [4K]", "Numb (Lyrics)", la remasterizada, la del single…) se junta en
una sola.

- **Es la misma** si coincide el artista y el título limpio (quitando "Artista - " solo si lo de delante empieza
  por el artista; si no, lo de detrás puede ser el canal), ninguna es directo, remix, acústica, orquestal,
  "stripped"… sin serlo la otra, la duración se parece (o la de vídeo es algo más larga por la intro) y, si las
  dos nombran colaboradores, comparten alguno. Si solo una los nombra, tienen que durar casi lo mismo: "Dutty Love"
  y "Dutty Love ft. Natti Natasha" son la misma, pero "No Ha Parado De Llover" de Maná (5:22) y la de Sebastián
  Yatra (4:06) no. Vale también "Canción – Artista" ("Numb (Official Music Video) [4K] –
  Linkin Park"). Títulos genéricos ("Intro", "Interlude", "Skit") nunca se juntan.
- **Se queda la del disco** (sin etiquetas de vídeo o letra, con álbum y pista) o, si no hay, la más puesta. Antes de
  borrar las demás, las favoritas, playlists e historial de **todos** pasan a la que queda (mismo sitio, sin
  repetirse) y se le suman sus reproducciones. Cada borrado queda en `server/data/duplicadas.jsonl`.
- **Para que no entren:** "Buscar en internet" enseña lo ya guardado **marcado como guardada**, también si es otra
  copia (`Duplicadas.is_saved` en `internet_songs`): la fila sigue siendo la de YouTube Music, pero suena la del servidor. Y **antes de bajar nada** (`download`,
  para la app, la web y el bot, también con enlaces y `yt:`) se mira la ficha del vídeo: si es la misma canción que una guardada, **no se baja**, suena la guardada y se apunta
  el apodo en `server/data/alias.json`. Al bot se lo dice ya `/interno/resolve`: un enlace con apodo responde al
  momento con la guardada, sin preguntar a YouTube, y uno nuevo solo le pregunta una vez. **Ante la duda, es otra
  canción** (`Duplicadas.genuine`, también para juntar de noche): de un canal que no es del artista solo cuenta como
  la misma si el título añade únicamente etiquetas de vídeo o letra ("(Lyrics)", "[HD]"); covers, anime, nightcore,
  "(Metal)" o "| Naruto AMV" se bajan aparte, aunque no digan "cover". Excepción: si lo pedido es la
  versión del disco y lo guardado un vídeo, se baja (es mejor; la noche junta). La precarga y `versiones.py` bajan
  siempre lo que eligen (`dedupe=False`).
- **Cada noche** (05:00 de Chile) se juntan las que se hayan colado, y las favoritas, playlists e historial que
  apunten a un vídeo apodado pasan a la canción guardada.
- A mano: `GET /interno/duplicadas` (ver, sin tocar) y `POST /interno/duplicadas` (juntar ya), con `BOT_API_KEY`
  en el puerto 8091. El 30-10-2026 se juntaron 190 copias (~700 MB); respaldos de antes en
  `server/data/index.antes-duplicadas.json` y `userdata.antes-duplicadas.json`.

**Versiones de disco** (`versiones.py`, dentro de la API): cambia en las favoritas y playlists de una cuenta las
versiones de **vídeo o de letra** ("Official Music Video", "Video Oficial", "(Letra)"…) por **la canción del disco**,
sin intros ni escenas habladas. Los directos no se tocan.

- **Cómo:** si la versión de disco ya está guardada (la precarga baja álbumes), se cambia al momento sin YouTube; si
  no, se busca en YouTube Music como canción y se baja, con el mismo freno y horario que la precarga (60–200 s
  entre canciones; de día, solo si nadie usa YouTube; 24 h quieto si hay bloqueo).
- **Es la misma canción** solo si coincide el artista y el título limpio, no es remix, acústica ni directo si la
  otra no lo es, y dura como el vídeo o menos (no menos del 45 %). Si no hay ninguna, se queda la de vídeo.
- **No se pierde nada:** la nueva ocupa el sitio exacto de la vieja en Me gusta (misma fecha y orden) y en cada
  playlist; no se duplica. Cada cambio queda en `server/data/versiones.json` para deshacerlo.
- **Uso** (con `BOT_API_KEY`, puerto 8091): empezar `curl -X POST -H "Authorization: Bearer $BOT_API_KEY" -H
  "Content-Type: application/json" -d '{"email":"…"}' 127.0.0.1:8091/interno/versiones`; deshacer, lo mismo con
  `"deshacer": true`; cómo va, `GET /interno/versiones`. El 30-10-2026, para yonisrubiocl: 172 de 500 favoritas
  (55 ya tenían versión de disco guardada); respaldo de antes en `server/data/userdata.antes-versiones.json`.

**Favoritas, historial y playlists** (`userdata.py`; en `server/data/userdata.json`, fuera de git, permisos
660, solo el grupo `musicapp`): por cuenta, para que la app, la web y otros móviles se vean igual. De cada canción se guarda su ficha (título,
artista, portada…), así sigue saliendo aunque la canción se borre del servidor (al ponerla se vuelve a bajar).
**Las canciones en favoritas o playlists de cualquiera no se borran por el tope de espacio** (`Library.keep`).

**Usuarios** (`users.py`; datos en `server/data/users.json` y `sessions.json`, fuera de git, permisos 660, solo el grupo `musicapp`): quien entra con Google por primera vez queda **pendiente** (máximo 30 pendientes a la vez);
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

**Panel**: `~/MusicApp/server/panel.py` (atajo **`panelm`**, en `~/.bashrc`), en el servidor (no en Docker), hecho con **Textual** (`server/panelmusica/`:
`datos.py` lee, `app.py` dibuja, `panel.tcss` la disposición). Tres paletas: **suave** (la de siempre, tonos apagados),
**app** (los colores vivos de la app) y **sobria** (casi sin color); `:T` pasa a la siguiente y se recuerda en
`~/.config/panel-musica.json`. Pide color real de 24 bits (`COLORTERM=truecolor`, que por SSH no suele llegar y sin él
los colores salen más chillones); en una terminal vieja que se vea rara: `COLORTERM=256 ./panel.py`. Arranca con su propio entorno `.venv-panel`
(fuera de git; si falta, lo crea solo con `panelmusica/requisitos.txt`). Lee los datos por el grupo `musicapp`; si la
sesión SSH aún no lo tiene, se relanza sola con `sg musicapp`. Se adapta al ancho: por debajo de 120 columnas (el
móvil por SSH) pasa a una o dos columnas.

Se manda como siempre: **`:` abre la línea de comandos** (Enter la manda, Esc la cierra; mientras escribes, los
números no se mueven). Las teclas sueltas solo mueven: **1–6 cambian de pestaña**, flechas y ratón recorren las tablas;
nada se aprueba ni se bloquea por accidente. Todo se refresca solo (archivos cada 2 s, Docker cada 10 s).

| Pestaña | Qué enseña |
|---|---|
| **1 Resumen** | Usuarios (aviso en amarillo si hay pendientes), canciones y espacio, YouTube (peticiones/h, bloqueos), servicios (API, bot, túnel, Funnel), **quién está escuchando ahora** (app, web y Discord), la precarga, las **reproducciones por hora de las últimas 24 h** (app/web y Discord por separado) y lo último que pasó |
| **2 Usuarios** | Todos (pendientes primero) con dispositivos, cuándo escuchó, canciones en 24 h, favoritas, playlists y última canción; ★ = administrador. A la derecha (abajo si es estrecho), el elegido: fechas, dispositivos, Discord y sus 15 últimas canciones |
| **3 Actividad** | 48 h de lo que pasa: canciones en la app y la web (eventos), en Discord (registro del bot), bajadas (registro de la API) y solicitudes de acceso |
| **4 Biblioteca** | Canciones, artistas y horas; espacio frente al tope y disco libre; lo más puesto, los artistas que más suenan y los géneros |
| **5 Precarga** | Los artistas en el orden en que irán, con estado (bajando, adelantado, pendiente, hecho, quitado) y álbumes abiertos/elegidos |
| **6 Sistema** | Contenedores (estado, desde cuándo, reinicios, CPU, RAM, imagen), carga, RAM y disco del servidor, avisos y errores del registro de la API y bloqueos de YouTube |

**Con el ratón:** clic en un usuario (Usuarios) y, en su detalle, **Aprobar / Desbloquear**, **Bloquear** y **Hacer o
quitar administrador** (salen solo los que tocan según su estado); clic en un artista (Precarga) y **Adelantar** y
**Quitar / Devolver**; en Sistema, **Reiniciar API** y **Reiniciar bot**. Todos los botones piden confirmar (también
aprobar) y no se quedan el foco, así 1–6 siguen cambiando de pestaña.

**Con comandos**, cada pestaña tiene los suyos (abajo se ven los de la pestaña abierta; escritos en otra, el panel dice
adónde ir):
**Usuarios**: `:1` aprueba al 1 (`:1 3 4` a varios; si estaba bloqueado, pide confirmar), `:B 2` bloquea (pide
confirmar; cierra sus sesiones), `:ADM 2` le da o quita el administrador (sin límite de dispositivos). **Precarga**:
`:A 5` adelanta al 5 (primero en `precarga-primero.txt`), `:X 5` lo quita (`Artista | *` en `precarga-saltar.txt`) y
otra vez `:X` lo devuelve. **Sistema**: `:R API` y `:R BOT` reinician (piden confirmar). **En todas**: `:T` cambia de
paleta, `:H` ayuda, `:Q` sale (la API sigue igual).

Por debajo usa `users.py`:

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
`cloudflared` (imagen con versión fija, `cloudflare/cloudflared:2026.10.7` en `docker-compose.yml`: "latest" no se
actualiza solo, así que se sube a mano de vez en cuando) abre una conexión **de salida** hacia Cloudflare; quien entra a `musica.yoneapolis.com` llega
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
- **Cabeceras de seguridad** en todas las respuestas: HSTS (siempre https, sin `includeSubDomains`), `X-Frame-Options:
  DENY` (nadie nos mete en un marco), `nosniff` y `Referrer-Policy: strict-origin-when-cross-origin`. Las páginas
  (`/`, `/web/`, las de Discord) llevan además **CSP** (`CSP` y `page()` en `app.py`): solo corre el código de sus
  propias etiquetas `<script>` (marcadas con un número de un solo uso por respuesta) y el botón de Google; nada de
  `onclick="…"` en el HTML. Si se añade algo de fuera (otra fuente, otra web a la que llamar), hay que sumarlo a `CSP`
  o el navegador lo bloquea. Probado en Chromium el 03-11-2026: sin bloqueos en la entrada ni en la web.
- **Cookies de YouTube:** `server/data/youtube-cookies.txt` (dueño 10001, permisos 600); yt-dlp las usa si
  existen. Son de una cuenta desechable (si se filtran, se cierra la sesión de esa cuenta en Google). Cómo
  renovarlas sin que YouTube las rote: `~/MusicBot/README.md`, sección 6.
- **Rutas del bot** (`/interno`): puerto 8001 al que los túneles no reenvían, más su propia clave. Dentro de la
  red `musicapp_default` sí se alcanza (el bot lo necesita), pero sin la clave da 401.
- **Entrar con Discord:** aplicación del bot 1 en el portal de Discord (`DISCORD_CLIENT_ID`, no es secreto), con
  `https://musica.yoneapolis.com/auth/discord/callback` como Redirect. Su *client secret* es el único secreto de OAuth
  que usa la API: va en `server/.env` (`DISCORD_CLIENT_SECRET`) y, si se filtra, se rota en ese portal. El `state` de
  cada enlace evita que alguien una su Discord a una cuenta ajena. El servidor interno del bot (8100) no se publica.

**Velocidad (medida el 06-11-2026):** el servidor va **por cable** (`enp1s0`, 1 Gbps dúplex completo; el wifi
`wlp2s0` queda conectado de respaldo, con menos prioridad). Internet de casa contra Cloudflare (Santiago): **~700
Mbps de bajada y 230–620 de subida**. A través del túnel (del servidor a su propia dirección pública, ida y vuelta):

| Prueba | Cloudflare | Tailscale Funnel (29-10) |
|---|---|---|
| Hasta el primer byte del audio | ~0,4–0,7 s | ~1,4 s |
| 1 descarga (canción de 7,8 MB) | **50–80 Mbps** | 150–225 KB/s |
| 6 descargas a la vez | ~30 Mbps cada una, **~150 Mbps en total** | 63–107 KB/s cada una, ~3 Mbps en total |
| APK al actualizar (~30–50 MB) | unos segundos | ~3–5 min |

Una canción va a ~134 kbps (ver "Calidad del audio"): sobra para cientos a la vez. El 29-10 el túnel daba ~12 Mbps
en total y se creyó que era la subida de casa; no lo era (la subida es de cientos de Mbps). Para los que escuchan
lejos (p. ej. Venezuela) cuenta sobre todo la distancia (~100–250 ms más por cada clic) y su propia conexión.

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
- **Igualar la app Android** con la web y el servidor: lista completa en `docs/app-paridad.md`.
- **Fichas con el artista mal** (visto el 06-11-2026): algunas canciones traen de YouTube un disco como artista
  ("En El Muelle De San Blas" con artista "Arde El Cielo", que es un disco en vivo de Maná). Sale mal en la web y el
  Canvas busca su videoclip con ese nombre. Falta detectarlas y corregirlas (por ejemplo, con iTunes o los créditos).
- **Canvas:** si el primer videoclip encontrado es una imagen quieta, probar con el segundo resultado antes de dejar
  la canción sin Canvas (~4 peticiones más, solo en esas). Las ya marcadas "casi no se mueve" habría que reintentarlas.
- **Recomendaciones** (fase 6, `docs/recomendaciones.md`): fase 1 hecha en el servidor y la web; falta en la app
  (ver `docs/app-paridad.md`). Siguientes fases:
  afinar con datos y que las opiniones ajusten (3), mixes (4), lo de todos opcional (5), Descubre (6).
- **Bloqueo automático** (sección 2) antes de repartir la app a todos.
- **Letras:** desde el 06-11-2026 la API tiene `/lyrics/<id>` (de lrclib.net, recordadas en memoria; la web la usa
  primero y la TV solo esa). Sigue dependiendo solo de lrclib.net, que el 31-10-2026 se cayó horas: falta guardarlas en
  disco, otra fuente y que la web distinga "servicio caído" de "no hay letra".
- Revisar los géneros (`docker exec musicapp-api python genres.py`) y corregir a mano los que no cuadren.
- Ruta de sincronización para favoritas hechas **sin conexión** en la app (cada cambio con su hora; gana el más
  reciente). Propuesta, sin hacer.
- Que la web se actualice sola si cambian las favoritas en otro dispositivo (ahora: al cambiar de pestaña o
  recargar).
- Quitar `API_TOKEN` cuando nada lo use.
- **FFmpeg** (CVE-2026-64835, ADX/AAX): cuando Debian publique el arreglo para trixie, reconstruir la API
  (`docker compose build --pull api`) y el bot. Mientras, los formatos raros no se abren (sección "Canciones").
- Decidir si la sesión se renueva sola con el uso (ahora caduca a los 90 días y la app tendría que volver a
  pedir el login a Google, sin que yo apruebe de nuevo).
- Borrar los restos de antes de la biblioteca única (sección "Canciones").
- **Prueba a ciegas de calidad** (sección 3b) antes de pensar en Premium.
- Ideas sin hacer: generador de PO tokens, Cloudflare WARP o el móvil con datos (Tailscale como nodo de salida)
  como salida de reserva hacia YouTube.

**Del bot de Discord** (`~/MusicBot`): la búsqueda tolerante (`Library.find`) aún no está allí; si la API no
responde un momento, una importación da esa canción por fallida (debería esperar y reintentar). Si Discord invalida
su sesión con música sonando, discord.py olvida la conexión de voz: la cola se para, el bot no se sale solo y la
pestaña DC enseña `sin_bot` con el bot dentro.

**Pestaña DC:** falta en la app (ver `docs/app-paridad.md`) y en la web. Tampoco hay parar, aleatorio, repetir,
álbumes ni playlists enteras desde la app.

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
│   ├── versiones.py        cambia en favoritas/playlists las versiones de vídeo por la canción del disco
│   ├── web/tv.html, tv.js  la pantalla de la TV (receptor de Google Cast; sección "Pantalla de la TV")
│   ├── conectar.py         escuchar en varios dispositivos: qué suena y dónde, órdenes entre ellos (sección propia)
│   ├── canvas.py           los Canvas: trozo de 7 s del videoclip de cada canción (sección "Portada viva" y "Canvas")
│   ├── titulos.py          el título que se enseña, sin "(Official Video)" ni el artista delante (sección "Canciones")
│   ├── duplicadas.py       junta la misma canción guardada varias veces (cada noche) y la quita de "Buscar en YouTube"
│   ├── recomendar.py       recomendaciones: radio, Para ti, Vuelve a escuchar, eventos, opiniones (docs/recomendaciones.md)
│   ├── library.py          la biblioteca única (carpeta + catálogo, búsqueda, tope de espacio); la música está en /var/lib/music
│   ├── users.py            usuarios y sesiones (login con Google, aprobar/bloquear por comando, 3 dispositivos)
│   ├── discord_dc.py       pestaña DC: "Entrar con Discord" y las peticiones al servidor interno del bot
│   ├── userdata.py         favoritas, historial y playlists de cada usuario
│   ├── web/                página principal (acceso.html), app web (web.html) y el logo (logo.png original; logo-480.webp y
│   │                       logo-96.webp, los ligeros: rehacerlos si cambia el logo); colores de la app: fondo #080A12,
│   │                       tarjetas #151725, violeta #9B5CFF, rosa #F04DBB, azul #5268FF, texto #FFFFFF / #A3A5B5
│   ├── panel.py            arranca el panel de terminal (fuera de Docker), con su entorno .venv-panel (fuera de git)
│   ├── panelmusica/        el panel (Textual): datos.py lee, app.py dibuja, panel.tcss colores, requisitos.txt
│   ├── Dockerfile          imagen de la API: Python 3.12 + FFmpeg + yt-dlp, usuario 10001
│   ├── docker-compose.yml  contenedores musicapp-api, musicapp-cloudflared y musicapp-tailscale (red propia musicapp_default)
│   ├── funnel.json         qué publica Funnel (respaldo): https://musicapp.<tailnet>.ts.net -> api:8000
│   ├── .env                API_TOKEN, BOT_API_KEY, CF_TUNNEL_TOKEN y TS_AUTHKEY (fuera de git; plantilla en .env.example)
│   └── data/               users.json, sessions.json, userdata.json (favoritas/historial), generos.json,
│                           precarga.json, precarga-saltar.txt (álbumes que no se bajan), precarga-primero.txt (artistas antes), youtube-searches.json, youtube-cookies.txt, stream.key (firma
│                           los enlaces del audio) y estado de Tailscale (fuera de git)
├── docs/
│   ├── recomendaciones.md   plan y estado del recomendador
│   └── app-paridad.md       lo que la app Android tiene que usar y copiar de la web (para igualarlas)
├── tools/
│   ├── probar-web.sh        prueba la web en un Chromium de verdad (Playwright en Docker, contra la API local)
│   ├── prueba-cola.js       la prueba de la cola: arrastrar con ratón y con dedo (PC y móvil)
│   ├── prueba-siguiente.js  la prueba de "Reproducir a continuación" (tools/probar-web.sh prueba-siguiente.js)
│   ├── prueba-aleatorio.js  la prueba del botón 🔀 Aleatorio de Me gusta y playlists
│   ├── probar-conectar.sh   la prueba de escuchar en varios dispositivos (con prueba-conectar.js y conectar-falso.py)
│   └── prueba-internet.js   la prueba de "Buscar en internet" (tools/probar-web.sh prueba-internet.js)
├── README.md     este documento
(/var/lib/music/                   la biblioteca: canciones + index.json, fuera de git)
(/var/lib/musicapp/app/            musica.apk + version.json, lo publica la sesión de la app; fuera de git)
(/var/lib/musicapp/recomendar/     eventos, opiniones y estado de las recomendaciones; fuera de git)
└── .gitignore    ignora .env, data/ y __pycache__/
```
