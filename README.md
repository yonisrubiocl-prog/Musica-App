# MusicApp: app de música propia

> **Regla de este documento:** describe **cómo está el proyecto ahora**, no su historia. Al cambiar algo,
> se **reescribe la parte afectada y se borra lo viejo o ya realizado**; no se añaden notas sueltas al
> final ni "actualizaciones" encima de texto desfasado. Debe poder leerse de arriba abajo sin
> contradicciones. Lo histórico está en git, no aquí.

App de música propia, tipo Spotify: buscas una canción, le das a play y **suena en el móvil o el PC**.
No tiene nada que ver con Discord (el bot `MusicBot` es otro proyecto y no se toca).

Es un proyecto **por diversión y para aprender**: privado, solo para mí y mis amigos (unas 6 personas),
sin publicarlo ni cobrar nada.

**Estado actual:** solo está la carpeta y este documento. Todavía no hay código.

---

## 1. Cómo funciona (diseño)

```
 PC / móvil                               Este servidor
 ──────────                               ─────────────────────────────────────────
  App Flutter  ◄──── Tailscale Funnel ────►  API de música (contenedor Docker propio)
                     (https://….ts.net)        ├─ login + lista de permitidos + bloqueos
                                               ├─ buscar en YouTube (yt-dlp)
                                               ├─ descargar y guardar en caché
                                               └─ enviar el audio a la app
```

| Pieza | Dónde | Qué es |
|---|---|---|
| **Servidor** (`server/`) | Este servidor, en Docker | API de música. Servicio aparte del bot de Discord: si se rompe, el bot sigue |
| **App** | PC del usuario | Flutter (Android y PC; iPhone algún día). Se desarrolla allí porque este servidor no tiene pantalla para el emulador |
| **Túnel** | Contenedor `tailscale` aquí + servidores de Tailscale | Da una dirección pública fija con HTTPS sin abrir puertos ni comprar dominio |
| **Canciones** | `/var/lib/musicapp/cache` | Fuera del proyecto: `/home` tiene poco espacio, `/var` tiene de sobra |

Del bot (`MusicBot/bot.py`) se aprovechan como **idea/código** la búsqueda, la descarga con yt-dlp, la
caché y las letras; no se comparte el programa.

## 2. Acceso y seguridad

**Túnel: Tailscale Funnel** (gratis, sin dominio). El contenedor `tailscale` abre una conexión **de salida**
hacia Tailscale; quien entra a la dirección `.ts.net` llega por ahí hasta la API. Los amigos no instalan
nada más que la app.

Tailscale **solo reenvía, no filtra**: toda petición llega a la API, así que la API se protege sola:

- **Solo se expone la API**, no el servidor: desde esa dirección no se llega a nada más (otros proyectos,
  bases de datos, SSH). El contenedor de Tailscale va aislado.
- **Login con lista de permitidos** por ID (no por nombre, que se puede cambiar). Una cuenta cualquiera
  entra al login pero recibe "no autorizado". Opción por defecto: login con **Discord** (todos lo tienen,
  no hay contraseñas que guardar); se puede cambiar por usuario/contraseña propios si apetece hacerlo.
- **Bloqueo automático** a quien insista: demasiados fallos o peticiones seguidas → bloqueado un tiempo,
  cada vez más largo. Queda en el registro. (Pendiente comprobar si Funnel pasa la IP real.)
- La API solo hace cosas de música: no ejecuta comandos ni toca archivos fuera de su caché.

**Plan B — túnel de Cloudflare:** el túnel que ya corre en este servidor (`finops-tunnel-1`) es de la
cuenta de **mi hermano**; no sirve con otra cuenta. Si un día se usa Cloudflare (un subdominio en su
cuenta, o un dominio propio `.com` en Cloudflare Registrar, ~10 $/año sin subidas al renovar), se cambia
el contenedor `tailscale` por un `cloudflared` y la dirección en los ajustes de la app. La API no cambia.

**Rendimiento esperado:** con 6 personas escuchando a la vez, ~1 Mbps de subida (128–160 kbps cada una)
y muy poca CPU/RAM. El servidor tiene 4 núcleos y 15 GB de RAM.

## 3. Plan por fases

Cada fase funciona por sí sola.

| Fase | Qué | Estado |
|---|---|---|
| 1 | **Servidor mínimo:** buscar una canción y escucharla (probado sin app) | Pendiente |
| 2 | **App mínima:** pantalla de búsqueda, play y que suene | Pendiente |
| 3 | **Reproductor de verdad:** cola, siguiente/anterior, segundo plano y pantalla de bloqueo (`just_audio`, `audio_service`) | Pendiente |
| 4 | Listas, favoritos, historial, letras y portadas | Pendiente |
| 5 | Descargas para escuchar sin conexión, ver qué escuchan los amigos, escuchar juntos | Pendiente |

## 4. Pendiente de mi parte

- Crear la cuenta gratis en **tailscale.com** (Google/GitHub/Microsoft) para activar Funnel. No hace
  falta para la fase 1.
- Instalar en el PC **Flutter** y **Android Studio** (con su emulador, o usar el móvil por USB).
- Crear la carpeta de canciones (necesita `sudo`, se hará en la fase 1).

## 5. Carpetas

```
/home/lainer/MusicApp/
├── server/       API de música (vacío todavía)
├── README.md     este documento
└── .gitignore    ignora .env, data/ y __pycache__/
```
