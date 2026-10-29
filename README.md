# MusicApp: app de música propia

> **Regla de este documento:** describe **cómo está el proyecto ahora**, no su historia. Al cambiar algo,
> se **reescribe la parte afectada y se borra lo viejo o ya realizado**; no se añaden notas sueltas al
> final ni "actualizaciones" encima de texto desfasado. Debe poder leerse de arriba abajo sin
> contradicciones. Lo histórico está en git, no aquí.

App de música propia, tipo Spotify: buscas una canción, le das a play y **suena en el móvil o el PC**.
No tiene nada que ver con Discord (el bot `MusicBot` es otro proyecto y no se toca).

Es un proyecto **por diversión y para aprender**: privado, solo para mí y mis amigos (unas 6 personas),
sin publicarlo ni cobrar nada.

**Estado actual:** fase 1 hecha. El servidor busca y sirve canciones y está publicado en
`https://musica.yoneapolis.com` (túnel de Cloudflare, dominio propio), probado con `curl` desde fuera.
Tailscale Funnel (`https://musicapp.tail66213e.ts.net`) sigue encendido como respaldo mientras se prueba
el dominio desde móviles. Lo siguiente es la app (fase 2).

---

## 1. Cómo funciona (diseño)

```
 PC / móvil                               Este servidor
 ──────────                               ─────────────────────────────────────────
  App Flutter  ◄── túnel de Cloudflare ──►  API de música (contenedor Docker propio)
              (https://musica.yoneapolis.com)  ├─ login + lista de permitidos + bloqueos
                                               ├─ buscar en YouTube (yt-dlp)
                                               ├─ descargar y guardar en caché
                                               └─ enviar el audio a la app
```

| Pieza | Dónde | Qué es |
|---|---|---|
| **Servidor** (`server/`) | Este servidor, en Docker | API de música. Servicio aparte del bot de Discord: si se rompe, el bot sigue |
| **App** | PC del usuario | Flutter (Android y PC; iPhone algún día). Se desarrolla allí porque este servidor no tiene pantalla para el emulador |
| **Túnel** | Contenedor `cloudflared` aquí + Cloudflare | Da la dirección pública con HTTPS sin abrir puertos. Dominio `yoneapolis.com` (mío, en Cloudflare), pensado para todos mis proyectos con un subdominio cada uno |
| **Canciones** | `/var/lib/musicapp/cache` (propias) + `/var/lib/musicbot/cache` (del bot, solo lectura) | Fuera del proyecto: `/home` tiene poco espacio, `/var` tiene de sobra. Ver "Canciones" abajo |

### Canciones

El bot y la app **leen las dos carpetas y cada uno escribe solo en la suya**:

```
            lee ┌──────────────────────┐ lee
   Bot ────────►│ /var/lib/musicbot    │◄──────── App
    │  escribe  └──────────────────────┘           │
    │           ┌──────────────────────┐           │
    └──────────►│ /var/lib/musicapp    │◄──────────┘
          lee   └──────────────────────┘  escribe
```

- La carpeta del otro se monta **solo lectura**: ninguno puede borrar ni estropear lo del otro.
- Los dos descargan igual (yt-dlp, `.webm` con audio **Opus**, archivo nombrado por el ID de YouTube:
  `yt-<id>.webm`), así que una canción se reconoce en cualquiera de las dos carpetas.
- **El catálogo de la app usa el mismo formato que el del bot** (`index.json`: título, artista, álbum…), para que
  cada uno pueda buscar por nombre también en el del otro. Catálogo del bot: `~/MusicBot/data/index.json`.

Al pedir una canción: si está en cualquiera de las dos carpetas se usa de ahí; si no, se baja a la propia.
Si desaparece del otro lado (el bot, al pasar de 15 GB, borra las menos usadas recientemente), se vuelve a
bajar a la propia. Así casi no hay duplicados (de media ~3,6 MB por canción).

**Nunca se escribe en la carpeta ni en el catálogo del otro:** se pisarían el `index.json`, y el bot borraría lo
de la app al llenarse (no lo cuenta como usado).

Estado: la app ya lee la caché del bot (~1.900 canciones) y baja a la suya lo que falta. Que **el bot lea la de la app**
requiere un cambio pequeño en `MusicBot` (montar solo lectura `/var/lib/musicapp/cache` y el catálogo
`~/MusicApp/server/data/index.json`, y buscar también ahí); se hace en una sesión de `MusicBot` aparte y probado.
La caché propia aún no tiene tope de tamaño (`/var` tiene ~88 GB libres); se le pondrá como el del bot si crece.

Del bot (`MusicBot/bot.py`) se aprovechan como **idea/código** la búsqueda, la descarga con yt-dlp, la
caché y las letras; no se comparte el programa.

### Servidor (`server/`)

Python con **FastAPI** + **yt-dlp** en el contenedor `musicapp-api` (usuario 1000, no root; actualiza yt-dlp
en cada arranque, como el bot). Escucha en `127.0.0.1:8090` solo para pruebas desde este servidor.

| Ruta | Qué hace |
|---|---|
| `GET /health` | `{"ok": true}`, sin clave |
| `GET /search?q=…` | Primero lo guardado (propio y del bot, todas las palabras en título/artista/álbum), luego 5 de YouTube, sin repetir. Cada resultado: `id`, `title`, `artist`, `album`, `duration`, `thumb`, `where` (`app`/`bot`/`youtube`). `&yt=0` = solo lo guardado |
| `GET /stream/<id>` | El audio (`audio/webm`, Opus) por ID de YouTube. Lo saca de la caché propia o de la del bot; si no está, lo baja a la propia (una sola vez aunque lo pidan varios a la vez). Admite `Range` (saltar dentro de la canción). Cabecera `X-Source` dice de dónde salió |

Si YouTube pide "confirmar que no eres un bot", el servidor deja de preguntarle 15 min (insistir alarga el
bloqueo); lo guardado sigue sonando.

**Clave de la fase 1:** todo menos `/health` pide `API_TOKEN` (en `server/.env`, fuera de git) como
`Authorization: Bearer …` o `?token=…`. Es provisional hasta el login con lista de permitidos.

```bash
cd ~/MusicApp/server
docker compose up -d --build api        # arrancar / actualizar tras cambiar app.py
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
- **Login con lista de permitidos** por ID (no por nombre, que se puede cambiar). Una cuenta cualquiera
  entra al login pero recibe "no autorizado". Opción por defecto: login con **Discord** (todos lo tienen,
  no hay contraseñas que guardar); se puede cambiar por Google o usuario/contraseña propios.
- **Bloqueo automático** a quien insista: demasiados fallos o peticiones seguidas → bloqueado un tiempo,
  cada vez más largo. Queda en el registro. Cloudflare pasa la IP real en la cabecera `CF-Connecting-IP`.
- La API solo hace cosas de música: no ejecuta comandos ni toca archivos fuera de su caché. El ID de canción
  se valida (11 caracteres de YouTube) antes de buscar archivos. Corre sin root, así que tampoco puede leer
  las cookies del bot aunque su carpeta `data/` esté montada (solo lectura, para su `index.json`).

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
| 2 | **App mínima:** pantalla de búsqueda, play y que suene + actualizador propio | Pendiente |
| 3 | **Reproductor de verdad:** cola, siguiente/anterior, segundo plano y pantalla de bloqueo (`just_audio`, `audio_service`) | Pendiente |
| 4 | Listas, favoritos, historial, letras y portadas | Pendiente |
| 5 | Descargas para escuchar sin conexión, ver qué escuchan los amigos, escuchar juntos | Pendiente |

## 5. Pendiente de mi parte

- Instalar en el PC **Flutter** y **Android Studio** (con su emulador, o usar el móvil por USB).

## 6. Carpetas

```
/home/lainer/MusicApp/
├── server/
│   ├── app.py              la API (FastAPI)
│   ├── Dockerfile
│   ├── docker-compose.yml  contenedores musicapp-api, musicapp-cloudflared y musicapp-tailscale (red propia musicapp_default)
│   ├── funnel.json         qué publica Funnel (respaldo): https://musicapp.<tailnet>.ts.net -> api:8000
│   ├── .env                API_TOKEN, CF_TUNNEL_TOKEN y TS_AUTHKEY (fuera de git; plantilla en .env.example)
│   └── data/               catálogo propio index.json y estado de Tailscale (fuera de git)
├── README.md     este documento
└── .gitignore    ignora .env, data/ y __pycache__/
```
