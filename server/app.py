"""API de MusicApp: la dueña de la música. La app la usa por internet (login de Google) y el bot por la red
interna de Docker (rutas /interno, en otro puerto al que los túneles no llegan).

Canciones: una sola biblioteca en /music con su catálogo (ver library.py). El bot lee el catálogo y los archivos
directo del disco (solo lectura); todo lo que escribe o habla con YouTube lo pide aquí. Ver README.md, "Canciones".
"""
import asyncio
import collections
import hmac
import secrets
import json
import logging
import os
import re
import threading
import time
import unicodedata

import uvicorn
import yt_dlp
from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token

import users
from library import KEY, Library, artist_of, key_of, music_meta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("musicapp")

MUSIC_DIR = "/music"                    # la biblioteca (en el servidor: /var/lib/music)
MUSIC_INDEX = "/music/index.json"       # su catálogo, junto a la música: el bot lo lee de su montaje
MUSIC_GB = float(os.environ.get("MUSIC_GB", "15"))
COOKIES = "/data/youtube-cookies.txt"   # cookies de YouTube (las del bot); solo las lee el usuario 1000
APK = "/app-dist/musica.apk"            # la app para Android (en el servidor: /var/lib/musicapp/app/musica.apk)
APK_LINK_TTL = 10 * 60                  # cuánto sirve un enlace de descarga de la app
SEARCHES = "/data/youtube-searches.json"   # búsquedas a YouTube ya hechas (ver YouTubeSearches)
SEARCH_DAYS = 7                         # cuánto se recuerda una búsqueda
SEARCH_MAX = 3000                       # búsquedas recordadas como mucho (se olvidan primero las más viejas)
WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")   # página principal y logo
TMP = "/tmp/musicapp"
TOKEN = os.environ.get("API_TOKEN", "")          # clave compartida provisional, hasta que la app tenga login
BOT_KEY = os.environ.get("BOT_API_KEY", "")      # clave del bot para /interno
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")   # cliente OAuth "Aplicación web" (no es secreto)
PUBLIC_PORT, INTERNAL_PORT = 8000, 8001
YT_RESULTS = 5
MAX_PLAYLIST = 5000                     # tope de canciones al leer una lista (el bot pide menos para la cola)
YT_PAUSE = 15 * 60                      # tras un bloqueo de YouTube no se le pide nada durante este tiempo
# Ritmo con YouTube (ver yt_turn): lo que hace saltar su "no eres un bot" son las ráfagas, no el uso normal.
YT_GAP = 4                              # segundos como mínimo entre dos peticiones a YouTube
YT_PER_HOUR = 120                       # peticiones como mucho en una hora
YT_MAX_WAIT = 45                        # si el turno tarda más que esto, se contesta "espera" (429) en vez de colgar
VIDEO_ID = re.compile(r"[\w-]{11}")
# Lo que el bot necesita de la respuesta de yt-dlp (el resto, como la lista de formatos, pesa mucho).
INFO_FIELDS = ("id", "title", "webpage_url", "duration", "thumbnail", "is_live", "url", "http_headers",
               "extractor_key", "ie_key", "uploader", "channel", "artist", "artists")

LIB = Library(MUSIC_DIR, MUSIC_GB * 1024 ** 3, MUSIC_INDEX)

_yt_blocked_until = 0.0
_downloads = {}                         # clave -> lock: dos peticiones de la misma canción la bajan una vez
_downloads_lock = threading.Lock()
_apk_links = {}                         # enlace de descarga de la app -> hasta cuándo sirve


def ydl(**extra):
    o = {"quiet": True, "no_warnings": True, "noprogress": True}
    if os.path.exists(COOKIES):
        o["cookiefile"] = COOKIES
    return yt_dlp.YoutubeDL({**o, **extra})


def is_yt(url):
    return "youtu" in url


_yt_turns = threading.Lock()
_yt_next = 0.0                          # cuándo puede salir la siguiente petición
_yt_recent = collections.deque()        # cuándo salieron las de la última hora


def yt_turn():
    """Espera su turno para pedirle algo a YouTube: una cada YT_GAP s y como mucho YT_PER_HOUR por hora, venga
    de la app, del bot o de una importación. Lo recordado (búsquedas, canciones guardadas) no pasa por aquí."""
    global _yt_next
    with _yt_turns:
        now = time.time()
        while _yt_recent and _yt_recent[0] < now - 3600:
            _yt_recent.popleft()
        start = max(now, _yt_next)
        if len(_yt_recent) >= YT_PER_HOUR:
            start = max(start, _yt_recent[-YT_PER_HOUR] + 3600)
        wait = start - now
        if wait > YT_MAX_WAIT:
            log.warning("ritmo con YouTube: %d en la última hora; la siguiente tendría que esperar %d s", len(_yt_recent), wait)
            raise HTTPException(429, f"muchas peticiones a YouTube seguidas; prueba en ~{max(1, round(wait / 60))} min")
        _yt_next = start + YT_GAP
        _yt_recent.append(start)
    if wait > 0:
        if wait > 10:
            log.info("ritmo con YouTube: espero %d s", wait)
        time.sleep(wait)


def youtube(fn, yt=True):
    """Llama a YouTube salvo que nos tenga bloqueados (pide 'confirmar que no eres un bot'): insistir lo alarga.
    yt=False: es otra web (SoundCloud, una radio…), no cuenta el bloqueo."""
    global _yt_blocked_until
    left = _yt_blocked_until - time.time()
    if yt and left > 0:
        raise HTTPException(503, f"YouTube nos bloqueó un rato; vuelvo a probar en ~{max(1, round(left / 60))} min")
    if yt:
        yt_turn()
    try:
        return fn()
    except yt_dlp.utils.DownloadError as e:
        t = str(e).lower()
        if yt and ("not a bot" in t or ("429" in t and "too many requests" in t)):
            _yt_blocked_until = time.time() + YT_PAUSE
            log.warning("YouTube nos bloqueó: no le pido nada durante %d min", YT_PAUSE // 60)
        log.warning("descarga: %s", e)
        raise HTTPException(502, str(e).replace("ERROR: ", "")[:200])


def download(url, by=None):
    """Baja el audio (webm/Opus si hay) a la biblioteca, una sola vez aunque la pidan varios a la vez.
    Devuelve (info, ruta); los directos no se guardan: ruta None y en info["url"] el enlace para escucharlo."""
    key = key_of(url)
    with _downloads_lock:
        lock = _downloads.setdefault(key, threading.Lock())
    with lock:
        p = LIB.path(key)
        if p:
            return LIB.peek(key), p

        def run():
            os.makedirs(TMP, exist_ok=True)
            with ydl(format="bestaudio[ext=webm]/bestaudio/best", noplaylist=True,
                     outtmpl=f"{TMP}/%(id)s.%(ext)s") as y:
                info = y.extract_info(url, download=False)
                if info.get("entries"):
                    info = next(e for e in info["entries"] if e)
                if info.get("is_live") or not info.get("duration"):
                    return info, None
                y.process_info(info)
                return info, y.prepare_filename(info)

        info, src = youtube(run, is_yt(url))
        if not src:
            return info, None
        dest = LIB.put(key_of(url, info), src, info, by)
        log.info("bajada: %s (%s)", info.get("title"), key_of(url, info))
        return info, dest


class YouTubeSearches:
    """Búsquedas a YouTube ya hechas -> sus resultados, durante SEARCH_DAYS: la misma búsqueda (de la app o del
    bot) no vuelve a preguntarle a YouTube. 'Karol G' = 'karol g' = 'karol  g'. Se guarda en disco para que un
    reinicio no la vacíe."""

    def __init__(self, file):
        self.file, self.lock = file, threading.Lock()
        try:
            with open(file) as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}
        self.hits = self.misses = 0

    @staticmethod
    def key(text, n):
        t = unicodedata.normalize("NFKD", text.lower())
        t = "".join(c for c in t if not unicodedata.combining(c))
        return f"{n}:{' '.join(re.findall(r'[a-z0-9]+', t))}"

    def get(self, text, n):
        """Resultados de buscar 'text' en YouTube (n como mucho), de memoria si se buscó hace poco."""
        k = self.key(text, n)
        with self.lock:
            hit = self.data.get(k)
            if hit and hit["until"] > time.time():
                self.hits += 1
                return hit["info"]

        def run():
            with ydl(extract_flat="in_playlist") as y:
                return y.extract_info(f"ytsearch{n}:{text}", download=False)
        info = small_info(youtube(run))
        with self.lock:
            self.misses += 1
            self.data.pop(k, None)   # al final = la más reciente
            self.data[k] = {"until": time.time() + SEARCH_DAYS * 86400, "info": info}
            now = time.time()
            for old in [x for x, v in self.data.items() if v["until"] < now]:
                del self.data[old]
            for old in list(self.data)[:max(0, len(self.data) - SEARCH_MAX)]:
                del self.data[old]
            try:
                with open(self.file + ".tmp", "w") as f:
                    json.dump(self.data, f, ensure_ascii=False)
                os.replace(self.file + ".tmp", self.file)
            except OSError as e:
                log.warning("no pude guardar las búsquedas: %s", e)
            log.info("búsqueda en YouTube: %r (de memoria %d, a YouTube %d desde que arrancó)",
                     text, self.hits, self.misses)
        return info


SEARCHES_YT = YouTubeSearches(SEARCHES)


def youtube_info(vid):
    def run():
        with ydl() as y:
            return y.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
    return youtube(run)


# ---------- app (por internet) ----------

def entry(key, e, where):
    return {"id": key[3:], "title": e.get("title"), "artist": e.get("artist") or "", "album": e.get("album") or "",
            "duration": e.get("duration"), "thumb": e.get("thumb"), "where": where}


def given_key(request: Request):
    """La clave que manda la app: 'Authorization: Bearer …' o '?token=…' (para el navegador o VLC)."""
    auth = request.headers.get("authorization", "")
    return auth[7:] if auth.lower().startswith("bearer ") else request.query_params.get("token", "")


def check_token(request: Request):
    """Sesión de un usuario aprobado, o la clave compartida API_TOKEN mientras no haya app."""
    key = given_key(request)
    if key and TOKEN and hmac.compare_digest(key.encode(), TOKEN.encode()):
        return None
    found = users.user_of(key) if key else None
    if not found:
        if request.url.path == "/app/version":
            log.info("versión de la app pedida sin sesión válida (%s)", "sin clave" if not key else "sesión caducada o no aprobada")
        raise HTTPException(401, "no autorizado")
    return found


app = FastAPI(title="MusicApp", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/auth/google")
def auth_google(token: str = Body(embed=True, alias="id_token", max_length=4096), web: bool = Body(False, embed=True)):
    """La app manda el ID token que le dio Google. Si el usuario está aprobado, recibe su sesión;
    si es nuevo, queda pendiente hasta que se apruebe en el servidor (ver users.py)."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(503, "login con Google sin configurar")
    try:
        claims = id_token.verify_oauth2_token(token, GoogleRequest(), GOOGLE_CLIENT_ID)
    except ValueError as e:
        log.info("token de Google rechazado: %s", e)
        raise HTTPException(401, "token de Google no válido")
    if not claims.get("email_verified"):
        raise HTTPException(401, "la cuenta de Google no tiene el email verificado")
    try:
        user, session = users.login(claims, web)
    except OverflowError:
        raise HTTPException(429, "demasiadas solicitudes pendientes; prueba más tarde")
    log.info("login: %s (%s)", user["email"], user["status"])
    if not session:
        raise HTTPException(403, {"status": user["status"], "user": user})
    return {"status": user["status"], "session": session, "days": users.SESSION_DAYS, "user": user}


@app.get("/me")
def me(found=Depends(check_token)):
    if not found:
        return {"user": None, "via": "clave compartida"}
    return {"user": users.public(*found)}


@app.post("/auth/logout")
def logout(request: Request, found=Depends(check_token)):
    if found:
        users.logout(given_key(request))
    return {"ok": True}


@app.get("/prueba-login", response_class=HTMLResponse)
def login_test_page():
    """Página para probar el login de Google en el navegador mientras no hay app."""
    return LOGIN_TEST_HTML.replace("{CLIENT_ID}", GOOGLE_CLIENT_ID)


@app.get("/", response_class=HTMLResponse)
@app.get("/acceso", response_class=HTMLResponse)
def access_page():
    """La página principal (web/acceso.html, con el estilo de la app): entran con Google; a los pendientes les
    dice que esperen y a los aprobados les baja la app. No reproduce nada."""
    with open(os.path.join(WEB, "acceso.html")) as f:
        return f.read().replace("{CLIENT_ID}", GOOGLE_CLIENT_ID)


@app.get("/web", response_class=HTMLResponse)
def web_app():
    """Prototipo de la app en el navegador (web/web.html): biblioteca, búsqueda, artistas, reproductor y la
    descarga para Android. Usa la sesión que guarda la página principal al entrar."""
    with open(os.path.join(WEB, "web.html")) as f:
        return HTMLResponse(f.read(), headers={"Cache-Control": "no-cache"})


@app.get("/logo{rest}", include_in_schema=False)
def logo(rest: str):
    """El logo: logo.png (original, 512 px) y logo-480.webp / logo-96.webp (los que usa la página: 25 KB y 3 KB)."""
    name = "logo" + rest
    if not re.fullmatch(r"logo(-\d+)?\.(png|webp)", name) or not os.path.isfile(os.path.join(WEB, name)):
        raise HTTPException(404, "no existe")
    return FileResponse(os.path.join(WEB, name), media_type="image/" + name.rsplit(".", 1)[1],
                        headers={"Cache-Control": "public, max-age=604800"})


@app.post("/app/enlace")
def apk_link(found=Depends(check_token)):
    """Enlace para bajar la app, solo para aprobados (lo usa /acceso). Sirve APK_LINK_TTL y no lleva la sesión
    dentro: pasarlo a otro no le da acceso a la música."""
    if not os.path.isfile(APK):
        raise HTTPException(404, "la app todavía no está lista")
    now = time.time()
    for k in [k for k, until in _apk_links.items() if until < now]:
        del _apk_links[k]
    link = secrets.token_urlsafe(24)
    _apk_links[link] = now + APK_LINK_TTL
    log.info("enlace de la app para %s", found[1]["email"] if found else "clave compartida")
    return {"url": f"/app/descargar/{link}", "minutes": APK_LINK_TTL // 60,
            "size": os.path.getsize(APK), "date": int(os.path.getmtime(APK))}


@app.get("/app/version")
def app_version(found=Depends(check_token)):
    """Versión publicada de la app (la escribe tools/publicar.ps1 de la app junto al APK, como version.json):
    la app avisa si es mayor que la suya y se actualiza con /app/enlace."""
    who = found[1]["email"] if found else "clave compartida"
    try:
        with open(os.path.join(os.path.dirname(APK), "version.json")) as f:
            v = json.load(f)
    except (FileNotFoundError, ValueError):   # ValueError: se está escribiendo justo ahora
        log.info("versión de la app pedida por %s: sin versión publicada", who)
        raise HTTPException(404, "sin versión publicada")
    log.info("versión de la app pedida por %s: publicada %s (build %s)", who, v.get("version"), v.get("build"))
    return v


@app.get("/app/descargar/{link}")
def apk_download(link: str):
    if _apk_links.get(link, 0) < time.time() or not os.path.isfile(APK):
        raise HTTPException(404, "enlace caducado: vuelve a entrar en /acceso")
    return FileResponse(APK, media_type="application/vnd.android.package-archive", filename="musica.apk")


@app.get("/search", dependencies=[Depends(check_token)])
def search(q: str = Query(min_length=1, max_length=200), youtube_too: bool = Query(True, alias="yt")):
    """Primero lo guardado (hasta 20, tolera palabras a medio escribir y faltas: ver Library.find); luego, si se
    pide, YouTube. Sin repetir canciones."""
    out, seen = [], set()
    for k, e in LIB.find(q, 20):
        if k.startswith("yt-"):   # /stream solo acepta canciones de YouTube
            seen.add(k)
            out.append(entry(k, e, "guardada"))
    if youtube_too:
        for e in SEARCHES_YT.get(q, YT_RESULTS).get("entries") or []:
            if e and e.get("id") and f"yt-{e['id']}" not in seen:
                seen.add(f"yt-{e['id']}")
                out.append({"id": e["id"], "title": e.get("title"), "artist": artist_of(e), "album": "",
                            "duration": e.get("duration"), "thumb": e.get("thumbnail"), "where": "youtube"})
    return {"results": out}


def yt_entries(pairs):
    """Canciones para la app (solo las de YouTube: /stream solo acepta esas)."""
    return [entry(k, e, "guardada") for k, e in pairs if k.startswith("yt-")]


@app.get("/library", dependencies=[Depends(check_token)])
def library_page(sort: str = Query("recientes"), offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    """Toda la música guardada por páginas, para ir cargando según se baja: {total, offset, songs}. sort:
    recientes (la última que sonó primero), populares, nombre (A-Z) o artista (A-Z). Cuando offset + len(songs)
    llega a total, no hay más."""
    if sort not in LIB.SORTS:
        raise HTTPException(400, f"sort tiene que ser uno de: {', '.join(LIB.SORTS)}")
    total, songs = LIB.page(sort, offset, limit)
    return {"total": total, "offset": offset, "songs": yt_entries(songs)}


@app.get("/artists", dependencies=[Depends(check_token)])
def artists():
    """Todos los artistas guardados: [{name, songs, albums, thumb}], los que más canciones tienen primero."""
    return {"artists": LIB.artists()}


@app.get("/artist", dependencies=[Depends(check_token)])
def artist(name: str = Query(min_length=1, max_length=200)):
    """Un artista: sus álbumes [{name, year, songs, thumb}] (más nuevos primero) y sus canciones sin álbum."""
    a = LIB.artist(name)
    if not a:
        raise HTTPException(404, "no hay canciones de ese artista")
    return {"name": a["name"], "songs": a["songs"], "albums": a["albums"], "loose": yt_entries(a["loose"])}


@app.get("/album", dependencies=[Depends(check_token)])
def album(artist: str = Query(min_length=1, max_length=200), name: str = Query(min_length=1, max_length=300)):
    """Las canciones guardadas de un álbum de un artista."""
    a = LIB.album(artist, name)
    if not a:
        raise HTTPException(404, "no hay canciones de ese álbum")
    return {"name": a["name"], "artist": a["artist"], "year": a["year"], "songs": yt_entries(a["songs"])}


@app.get("/stream/{vid}", dependencies=[Depends(check_token)])
def stream(vid: str, request: Request):
    """El audio de la canción (webm/Opus). Admite Range, así el reproductor puede saltar dentro de la canción."""
    if not VIDEO_ID.fullmatch(vid):
        raise HTTPException(400, "id de YouTube no válido")
    key, where = f"yt-{vid}", "guardada"
    if request.headers.get("range", "bytes=0-").startswith("bytes=0-"):
        hit = LIB.get(key)   # cuenta al empezar, no en cada trozo que pide el reproductor
        path = hit and hit["path"]
    else:
        path = LIB.path(key)
    if not path:
        _, path = download(f"https://www.youtube.com/watch?v={vid}")
        where = "youtube"
        if not path:
            raise HTTPException(422, "es un directo: no se puede guardar")
    media = "audio/webm" if path.endswith(".webm") else "audio/mp4" if path.endswith(".m4a") else "audio/mpeg"
    return FileResponse(path, media_type=media, headers={"X-Source": where, "Cache-Control": "private, max-age=86400"})


# ---------- bot (red interna de Docker, puerto 8001: los túneles solo llegan al 8000) ----------

def check_bot(request: Request):
    key = given_key(request)
    if not (BOT_KEY and key and hmac.compare_digest(key.encode(), BOT_KEY.encode())):
        raise HTTPException(401, "no autorizado")


def valid_key(key):
    if not KEY.fullmatch(key):
        raise HTTPException(400, "clave de canción no válida")
    return key


def small_info(info):
    """Lo que el bot usa de una respuesta de yt-dlp (con 'entries' si es una lista o una búsqueda)."""
    out = {k: info.get(k) for k in INFO_FIELDS if info.get(k) is not None}
    thumbs = info.get("thumbnails") or []
    if thumbs and "thumbnail" not in out:
        out["thumbnail"] = thumbs[-1].get("url")
    if "entries" in info:
        out["entries"] = [small_info(e) if e else None for e in info["entries"] or []]
    return out


def songs(pairs):
    return [{"key": k, **e} for k, e in pairs]


internal = FastAPI(title="MusicApp interno", docs_url=None, redoc_url=None, openapi_url=None,
                   dependencies=[Depends(check_bot)])


@internal.get("/interno/match")
def i_match(q: str = Query(max_length=300), fuzzy: bool = False):
    """La mejor guardada con todas las palabras (fuzzy: acepta faltas). {song, more} o {song: null}."""
    m = LIB.match(q, fuzzy)
    if not m:
        return {"song": None, "more": 0}
    (k, e), more = m
    return {"song": {"key": k, **e}, "more": more}


@internal.get("/interno/matches")
def i_matches(q: str = Query(max_length=300), limit: int = Query(10, le=100)):
    return {"songs": songs(LIB.matches(q, limit))}


@internal.get("/interno/suggest")
def i_suggest(q: str = Query("", max_length=300), limit: int = Query(25, le=100)):
    return {"songs": songs(LIB.suggest(q, limit))}


@internal.get("/interno/search")
def i_search(q: str = Query(max_length=300), limit: int = Query(25, le=500)):
    return {"songs": songs(LIB.search(q, limit))}


@internal.get("/interno/albums")
def i_albums():
    return {"albums": [{"name": n, "artist": a, "count": c} for n, a, c in LIB.albums()]}


@internal.get("/interno/album")
def i_album(q: str = Query(max_length=300)):
    return {"songs": songs(LIB.album_tracks(q))}


@internal.get("/interno/stats")
def i_stats():
    n, size, cap = LIB.stats()
    return {"songs": n, "bytes": size, "max_bytes": cap}


@internal.get("/interno/song/{key}")
def i_peek(key: str):
    """Datos de una guardada sin contarla como puesta."""
    e = LIB.peek(valid_key(key))
    if not e:
        raise HTTPException(404, "no está guardada")
    return {"key": key, **e}


@internal.post("/interno/played/{key}")
def i_played(key: str):
    """Sonó en Discord: cuenta para 'las más puestas' y para el tope de espacio."""
    e = LIB.get(valid_key(key))
    if not e:
        raise HTTPException(404, "no está guardada")
    e.pop("path")
    return {"key": key, **e}


@internal.post("/interno/fetch")
def i_fetch(url: str = Body(embed=True, max_length=2000), by: int | None = Body(None, embed=True)):
    """'Dame esta canción': si está guardada la cuenta como puesta; si no, la baja. Devuelve la ficha y el
    archivo (relativo a la biblioteca; el bot la lee de su montaje). Directos: file null e info.url para
    escucharlo. source: local / online / live."""
    if not re.match(r"https?://", url):
        raise HTTPException(400, "hace falta un enlace")
    key = key_of(url)
    hit = LIB.get(key)
    if hit:
        hit.pop("path")
        return {"key": key, "source": "local", "file": hit["file"], "song": hit, "info": None}
    info, path = download(url, by)
    small = {**small_info(info), **music_meta(info)}
    if not path:
        return {"key": key, "source": "live", "file": None, "song": None, "info": small}
    key = key_of(url, info)
    return {"key": key, "source": "online", "file": os.path.basename(path), "song": LIB.peek(key), "info": small}


@internal.post("/interno/resolve")
def i_resolve(query: str = Body(embed=True, max_length=2000), limit: int = Body(100, embed=True, le=MAX_PLAYLIST)):
    """Buscar en YouTube ('ytsearch5:…' o un nombre) o leer un enlace (video, lista, SoundCloud…) sin bajar nada:
    título, duración, miniatura y, si es lista o búsqueda, sus 'entries'. Las búsquedas se recuerdan
    (YouTubeSearches); los enlaces no."""
    m = re.fullmatch(r"ytsearch(\d*):(.+)", query, re.S)
    if m or not re.match(r"https?://", query):
        n, text = (int(m.group(1) or 1), m.group(2)) if m else (1, query)
        return SEARCHES_YT.get(text, min(n, 50))

    def run():
        with ydl(extract_flat="in_playlist", playlistend=limit, default_search="ytsearch") as y:
            return y.extract_info(query, download=False)
    return small_info(youtube(run, not re.match(r"https?://", query) or is_yt(query)))


@internal.post("/interno/ficha/{key}")
def i_learn(key: str):
    """Completa la ficha (artista, álbum…) de una guardada de antes preguntándole a YouTube. Si YouTube
    está bloqueado no gasta el reintento (503); si falla por otra cosa, se reintenta una vez más."""
    valid_key(key)
    if not key.startswith("yt-"):
        e = LIB.set_meta(key, music_meta({}))
    else:
        try:
            info = youtube_info(key[3:])
        except HTTPException as ex:
            if ex.status_code == 503 or _yt_blocked_until > time.time():
                raise
            e = LIB.set_meta(key, None)
        else:
            e = LIB.set_meta(key, music_meta(info), info)
    if e is None:
        raise HTTPException(404, "no está guardada")
    return {"key": key, **e}


@internal.delete("/interno/song/{key}")
def i_remove(key: str):
    """Olvidar una canción: se borra el archivo y su ficha."""
    e = LIB.remove(valid_key(key))
    if not e:
        raise HTTPException(404, "no está guardada")
    log.info("olvidada: %s (%s)", e.get("title"), key)
    return {"key": key, **e}


async def serve():
    """Los dos puertos en el mismo proceso (comparten biblioteca y candados). Si uno se para, se paran los dos."""
    servers = [uvicorn.Server(uvicorn.Config(a, host="0.0.0.0", port=p, access_log=False, log_config=None))
               for a, p in ((app, PUBLIC_PORT), (internal, INTERNAL_PORT))]
    tasks = [asyncio.create_task(s.serve()) for s in servers]
    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for s in servers:
        s.should_exit = True
    await asyncio.gather(*tasks, return_exceptions=True)


LOGIN_TEST_HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>MusicApp · prueba de login</title>
<style>body{font-family:system-ui,sans-serif;max-width:640px;margin:32px auto;padding:0 16px;background:#111;color:#eee}
pre{background:#222;padding:12px;border-radius:8px;white-space:pre-wrap;word-break:break-all}
input,button{font:inherit;padding:8px}audio{width:100%;margin-top:12px}</style>
<script src="https://accounts.google.com/gsi/client" async></script></head><body>
<h1>Prueba de login</h1>
<div id="g_id_onload" data-client_id="{CLIENT_ID}" data-callback="entrar" data-auto_prompt="false"></div>
<div class="g_id_signin" data-type="standard" data-theme="filled_black" data-text="signin_with"></div>
<pre id="out">Inicia sesión con Google.</pre>
<div id="musica" hidden><input id="q" placeholder="buscar…"> <button onclick="buscar()">Buscar</button>
<ul id="res"></ul><audio id="audio" controls></audio></div>
<script>
let sesion = null;
const out = t => document.getElementById('out').textContent = typeof t === 'string' ? t : JSON.stringify(t, null, 2);
async function entrar(r) {
  const res = await fetch('/auth/google', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                           body: JSON.stringify({id_token: r.credential})});
  const j = await res.json(); out({http: res.status, ...j});
  if (j.session) { sesion = j.session; document.getElementById('musica').hidden = false; }
}
async function buscar() {
  const q = encodeURIComponent(document.getElementById('q').value);
  const j = await (await fetch('/search?q=' + q, {headers: {Authorization: 'Bearer ' + sesion}})).json();
  const ul = document.getElementById('res'); ul.innerHTML = '';
  for (const c of j.results || []) {
    const li = document.createElement('li'), a = document.createElement('a');
    a.href = '#'; a.textContent = c.title + (c.artist ? ' · ' + c.artist : '');
    a.onclick = e => { e.preventDefault(); const au = document.getElementById('audio');
                       au.src = '/stream/' + c.id + '?token=' + encodeURIComponent(sesion); au.play(); };
    li.append(a); ul.append(li);
  }
}
</script></body></html>"""



if __name__ == "__main__":
    asyncio.run(serve())
