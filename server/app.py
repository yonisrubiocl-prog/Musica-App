"""API de MusicApp: la dueña de la música. La app la usa por internet (login de Google) y el bot por la red
interna de Docker (rutas /interno, en otro puerto al que los túneles no llegan).

Canciones: una sola biblioteca en /music con su catálogo (ver library.py). El bot lee el catálogo y los archivos
directo del disco (solo lectura); todo lo que escribe o habla con YouTube lo pide aquí. Ver README.md, "Canciones".
"""
import asyncio
import collections
import difflib
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

import userdata
from enrich import Enricher
from genres import Genres
from precarga import Precarga
from versiones import Versiones
from duplicadas import Duplicadas
from recomendar import Recomendar
import users
from library import KEY, YT_ID, Library, artist_of, key_of, music_meta

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
YT_GAP = 4                              # segundos como mínimo entre dos operaciones con YouTube
YT_PER_HOUR = 300                       # peticiones REALES como mucho en una hora (cada operación cuenta lo que cuesta)
# Lo que cuesta cada operación en peticiones reales (medido el 30-10-2026)
COST_DOWNLOAD, COST_SEARCH, COST_INFO, COST_ALBUM = 4, 2, 2, 1
YT_MAX_WAIT = 45                        # si el turno tarda más que esto, se contesta "espera" (429) en vez de colgar
VIDEO_ID = re.compile(r"[\w-]{11}")
# Lo que el bot necesita de la respuesta de yt-dlp (el resto, como la lista de formatos, pesa mucho).
INFO_FIELDS = ("id", "title", "webpage_url", "duration", "thumbnail", "is_live", "url", "http_headers",
               "extractor_key", "ie_key", "uploader", "channel", "artist", "artists")

LIB = Library(MUSIC_DIR, MUSIC_GB * 1024 ** 3, MUSIC_INDEX)
LIB.keep = lambda: {"yt-" + i for i in userdata.favorite_ids()}   # favoritas y playlists de alguien: no se borran por espacio

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
_yt_last_user = 0.0                     # última vez que alguien (no la precarga ni las fichas) usó YouTube
BACKGROUND = {"precarga", "enrich"}     # hilos de fondo: no cuentan como uso de alguien


YT_STATE = "/data/youtube-estado.json"      # cómo está YouTube ahora (lo lee panel.py)
YT_BLOCKS = "/data/youtube-bloqueos.jsonl"  # historial de bloqueos


def yt_blocked(source, err):
    """YouTube pidió "confirmar que no eres un bot" (o 429): no se le pide nada durante YT_PAUSE y queda apuntado en
    el historial y en el estado (el panel lo pone en rojo y el bot avisa en el canal de registro)."""
    global _yt_blocked_until
    now = time.time()
    _yt_blocked_until = now + YT_PAUSE
    log.warning("YouTube nos bloqueó (%s): no le pido nada durante %d min", source, YT_PAUSE // 60)
    try:
        with open(YT_BLOCKS, "a") as f:
            f.write(json.dumps({"cuando": int(now), "hasta": int(_yt_blocked_until), "fuente": source,
                                "peticiones_hora": len(_yt_recent), "error": str(err)[:200]}, ensure_ascii=False) + "\n")
    except OSError:
        pass
    yt_state()


def yt_state():
    """{bloqueado_hasta, peticiones_hora, tope_hora, ultimo_bloqueo, cuando}: lo que enseña el panel y consulta el bot."""
    last = None
    try:
        with open(YT_BLOCKS) as f:
            lines = f.read().splitlines()
        last = json.loads(lines[-1]) if lines else None
    except (OSError, ValueError):
        pass
    now = time.time()
    st = {"bloqueado_hasta": int(_yt_blocked_until) if _yt_blocked_until > now else 0,
          "peticiones_hora": sum(1 for t in _yt_recent if t > now - 3600), "tope_hora": YT_PER_HOUR,
          "ultimo_bloqueo": last, "cuando": int(now)}
    try:
        with open(YT_STATE + ".tmp", "w") as f:
            json.dump(st, f, ensure_ascii=False)
        os.replace(YT_STATE + ".tmp", YT_STATE)
    except OSError:
        pass
    return st


def _yt_state_loop():
    while True:
        time.sleep(30)
        yt_state()


threading.Thread(target=_yt_state_loop, daemon=True).start()


def yt_turn(cost=1):
    """Espera su turno para pedirle algo a YouTube: una operación cada YT_GAP s y como mucho YT_PER_HOUR peticiones
    reales por hora (cost = las que hace esta operación), venga de la app, del bot o de una importación. Lo
    recordado (búsquedas, canciones guardadas) no pasa por aquí."""
    global _yt_next, _yt_last_user
    if threading.current_thread().name not in BACKGROUND:
        _yt_last_user = time.time()
    with _yt_turns:
        now = time.time()
        while _yt_recent and _yt_recent[0] < now - 3600:
            _yt_recent.popleft()
        start = max(now, _yt_next)
        if len(_yt_recent) + cost > YT_PER_HOUR:
            start = max(start, _yt_recent[min(len(_yt_recent), YT_PER_HOUR) - YT_PER_HOUR + cost - 1] + 3600)
        wait = start - now
        if wait > YT_MAX_WAIT:
            log.warning("ritmo con YouTube: %d en la última hora; la siguiente tendría que esperar %d s", len(_yt_recent), wait)
            raise HTTPException(429, f"muchas peticiones a YouTube seguidas; prueba en ~{max(1, round(wait / 60))} min")
        _yt_next = start + YT_GAP
        _yt_recent.extend([start] * cost)
    if wait > 0:
        if wait > 10:
            log.info("ritmo con YouTube: espero %d s", wait)
        time.sleep(wait)


def youtube(fn, yt=True, cost=COST_INFO):
    """Llama a YouTube salvo que nos tenga bloqueados (pide 'confirmar que no eres un bot'): insistir lo alarga.
    yt=False: es otra web (SoundCloud, una radio…), no cuenta el bloqueo."""
    left = _yt_blocked_until - time.time()
    if yt and left > 0:
        raise HTTPException(503, f"YouTube nos bloqueó un rato; vuelvo a probar en ~{max(1, round(left / 60))} min")
    if yt:
        yt_turn(cost)
    try:
        return fn()
    except yt_dlp.utils.DownloadError as e:
        t = str(e).lower()
        if yt and ("not a bot" in t or ("429" in t and "too many requests" in t)):
            yt_blocked("yt-dlp", e)
        log.warning("descarga: %s", e)
        raise HTTPException(502, str(e).replace("ERROR: ", "")[:200])


def download(url, by=None, dedupe=True):
    """Baja el audio (webm/Opus si hay) a la biblioteca, una sola vez aunque la pidan varios a la vez.
    Devuelve (info, ruta); los directos no se guardan: ruta None y en info["url"] el enlace para escucharlo.
    dedupe: si ya está guardada la misma canción con otro título ("Numb (Official Video)" y "Numb"), no se baja: se
    da la guardada y se apunta el apodo (duplicadas.py). La precarga y versiones.py lo apagan: eligen a propósito."""
    key = key_of(url)
    with _downloads_lock:
        lock = _downloads.setdefault(key, threading.Lock())
    with lock:
        real = DUPLICADAS.real_key(key)
        p = LIB.path(real)
        if p:
            return LIB.peek(real), p
        same = []

        def run():
            os.makedirs(TMP, exist_ok=True)
            with ydl(format="bestaudio[ext=webm]/bestaudio/best", noplaylist=True,
                     outtmpl=f"{TMP}/%(id)s.%(ext)s") as y:
                info = y.extract_info(url, download=False)
                if info.get("entries"):
                    info = next(e for e in info["entries"] if e)
                if info.get("is_live") or not info.get("duration"):
                    return info, None
                if dedupe and (k := DUPLICADAS.same_as_saved(key, info)):   # ya está con otro título
                    same.append(k)
                    return info, None
                y.process_info(info)
                return info, y.prepare_filename(info)

        info, src = youtube(run, is_yt(url), COST_DOWNLOAD)
        if same:
            return LIB.peek(same[0]), LIB.path(same[0])
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

    def recall(self, k):
        with self.lock:
            hit = self.data.get(k)
            if hit and hit["until"] > time.time():
                self.hits += 1
                return hit["info"]
        return None

    def get(self, text, n):
        """Resultados de buscar 'text' en YouTube con yt-dlp (n como mucho), de memoria si se buscó hace poco.
        La usa el bot ('?' y nombres)."""
        k = self.key(text, n)
        hit = self.recall(k)
        if hit is not None:
            return hit

        def run():
            with ydl(extract_flat="in_playlist") as y:
                return y.extract_info(f"ytsearch{n}:{text}", download=False)
        info = small_info(youtube(run, cost=COST_SEARCH))
        self.store(k, info, text)
        return info

    def store(self, k, info, text):
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


SEARCHES_YT = YouTubeSearches(SEARCHES)


# ---------- YouTube Music (ytmusicapi): canciones oficiales con sus datos, álbumes y sus pistas ----------
# Cuesta lo mismo o menos que la búsqueda de yt-dlp (20 canciones = 2 peticiones; álbumes = 1; abrir uno = 1) y
# trae artista, álbum, duración y número de pista. Pasa por el mismo ritmo y bloqueo que yt-dlp, y se recuerda
# igual (SEARCHES_YT). Si falla por otra cosa que un bloqueo, /search vuelve a la búsqueda de yt-dlp.
YTM_NEW = 20                            # canciones de internet que /search?yt=1 enseña (que no estén guardadas)
YTM_MAX = 100                           # como mucho se le piden tantas a YouTube Music para juntar YTM_NEW nuevas
ALBUM_ID = re.compile(r"MPREb_[\w-]{5,40}")
_ytm = None


def ytm(fn, cost=COST_ALBUM):
    """Llama a YouTube Music con el mismo cuidado que a YouTube: bloqueo, turno (yt_turn) y errores."""
    global _ytm
    left = _yt_blocked_until - time.time()
    if left > 0:
        raise HTTPException(503, f"YouTube nos bloqueó un rato; vuelvo a probar en ~{max(1, round(left / 60))} min")
    yt_turn(cost)
    try:
        if _ytm is None:
            from ytmusicapi import YTMusic
            _ytm = YTMusic()
        return fn(_ytm)
    except Exception as e:
        t = str(e).lower()
        if "429" in t or "not a bot" in t:
            yt_blocked("YouTube Music", e)
            raise HTTPException(503, "YouTube nos bloqueó un rato")
        log.warning("YouTube Music: %s", e)
        raise HTTPException(502, f"YouTube Music: {str(e)[:150]}")


ENRICH = Enricher(LIB, ytm, lambda: len(_yt_recent))   # fichas de las viejas, de fondo (enrich.py)
GENRES = Genres(LIB)                                   # género por artista (genres.py)
LIB.genre_of_artist, LIB.genre_stamp = GENRES.of, GENRES.stamp
# Recomendaciones (recomendar.py, plan en docs/recomendaciones.md). RECOMENDAR=0 las apaga: rutas 404.
REC = Recomendar(LIB, userdata) if os.environ.get("RECOMENDAR", "1") == "1" else None
PRECARGA = Precarga(LIB, ytm, lambda u: download(u, dedupe=False), lambda: _yt_blocked_until > time.time(),   # álbumes de los artistas
                    lambda s: time.time() - _yt_last_user > s)                     # más escuchados (precarga.py)
DUPLICADAS = Duplicadas(LIB, userdata)   # la misma canción guardada varias veces: se juntan (duplicadas.py)
VERSIONES = Versiones(LIB, ytm, lambda u: download(u, dedupe=False), userdata, lambda: _yt_blocked_until > time.time(),   # vídeo -> disco
                      lambda s: time.time() - _yt_last_user > s)                               # (versiones.py)


def ytm_thumb(x):
    thumbs = x.get("thumbnails") or []
    return thumbs[-1]["url"] if thumbs else None


def ytm_song(s, album=None):
    """Una canción de YouTube Music con el formato de /search."""
    return {"id": s.get("videoId"), "title": s.get("title"),
            "artist": ", ".join(a["name"] for a in s.get("artists") or [] if a.get("name")),
            "album": ((s.get("album") or {}).get("name") if isinstance(s.get("album"), dict) else s.get("album"))
            or (album or {}).get("title") or "",   # en una búsqueda viene como {name}; dentro de un álbum, como texto
            "duration": s.get("duration_seconds"), "thumb": ytm_thumb(s) or (album or {}).get("thumb"),
            "track": s.get("trackNumber"), "where": "youtube"}


def ytm_songs(text, limit):
    """Las primeras 'limit' canciones de YouTube Music para 'text', de memoria si se buscaron hace poco."""
    k = "ytm-songs:" + YouTubeSearches.key(text, limit)
    hit = SEARCHES_YT.recall(k)
    if hit is None:
        hit = [ytm_song(s) for s in ytm(lambda y: y.search(text, filter="songs", limit=limit), 1 + -(-limit // 20))
               if s.get("videoId")]
        SEARCHES_YT.store(k, hit, f"{text} (YouTube Music, {limit})")
    return hit


def new_songs(text, skip):
    """YTM_NEW canciones de internet que no estén en 'skip' (las guardadas): si en las primeras 20 hay muchas
    guardadas, se piden más (40, 60…) hasta juntar YTM_NEW o llegar a YTM_MAX o a que YouTube no tenga más."""
    limit = YTM_NEW
    while True:
        songs = ytm_songs(text, limit)
        # ni las guardadas ni otra copia de una guardada ("Numb (Official Video)" si ya está "Numb")
        fresh = [s for s in songs if f"yt-{s['id']}" not in skip
                 and not DUPLICADAS.is_saved(s.get("title"), LIB.JOINT.split(s.get("artist") or ""))]
        if len(fresh) >= YTM_NEW or len(songs) < limit or limit >= YTM_MAX:
            return fresh[:YTM_NEW]
        limit = YTM_MAX   # el segundo intento ya pide el máximo: dos búsquedas como mucho (peor caso ~8 peticiones)


def youtube_info(vid):
    def run():
        with ydl() as y:
            return y.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
    return youtube(run)


# ---------- app (por internet) ----------

def entry(key, e, where):
    return {"id": key[3:], "title": e.get("title"), "artist": e.get("artist") or "", "album": e.get("album") or "",
            "duration": e.get("duration"), "thumb": e.get("thumb"), "genre": LIB.genre_of(key), "where": where}


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
@app.get("/web/{path:path}", response_class=HTMLResponse)
def web_app(path: str = ""):
    """La app en el navegador (web/web.html): Inicio, Buscar, Biblioteca, favoritas, reproductor y la descarga para
    Android. Usa la sesión que guarda la página principal al entrar. Cualquier ruta bajo /web/ da la misma página."""
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
def search(q: str = Query(min_length=1, max_length=200), youtube_too: bool = Query(True, alias="yt"),
           offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=200)):
    """Primero lo guardado (tolera palabras a medio escribir y faltas: ver Library.find), de 'limit' en 'limit' desde
    'offset'; 'total' dice cuántas guardadas hay en total (p. ej. "rawayana": 78); 'artists', los artistas que
    encajan (también con faltas: "cancerbero" -> Canserbero), solo en la primera página. Luego, si se pide y es la primera
    página, YouTube. Sin repetir canciones."""
    out, seen = [], set()
    saved = [(k, e) for k, e in LIB.find(q, 2000) if k.startswith("yt-")]   # /stream solo acepta canciones de YouTube
    seen.update(k for k, _ in saved)
    for k, e in saved[offset:offset + limit]:
        out.append(entry(k, e, "guardada"))
    if youtube_too and offset == 0:
        try:
            out += new_songs(q, seen)
        except HTTPException as ex:
            if ex.status_code in (503, 429):
                raise
            log.warning("YouTube Music falló; busco con yt-dlp")
            for e in SEARCHES_YT.get(q, YT_RESULTS).get("entries") or []:
                if e and e.get("id") and f"yt-{e['id']}" not in seen:
                    seen.add(f"yt-{e['id']}")
                    out.append({"id": e["id"], "title": e.get("title"), "artist": artist_of(e), "album": "",
                                "duration": e.get("duration"), "thumb": e.get("thumbnail"), "where": "youtube"})
    arts = [{"name": x["name"], "songs": x["songs"], "albums": x["albums"], "thumb": x["thumb"]}
            for x in LIB.find_artists(q, 10)] if offset == 0 else []
    return {"results": out, "total": len(saved), "offset": offset, "artists": arts}


@app.get("/suggest", dependencies=[Depends(check_token)])
def suggest(q: str = Query(min_length=1, max_length=100), n: int = Query(8, ge=1, le=20)):
    """Sugerencias mientras se escribe (de lo guardado, sin YouTube; pocos ms): artistas, álbumes y canciones cuyas
    palabras empiezan por lo escrito ("raw" -> Rawayana · 78 canciones). {sugerencias: [{tipo: artista|album|cancion,
    texto, artista, id, canciones, thumb}]}: al tocar una, buscar 'texto' (o abrir el artista / poner la canción)."""
    words = Library._norm(q).split()
    if not words:
        return {"sugerencias": []}
    def fits(text):
        tw = Library._norm(text).split()
        return all(any(t.startswith(w) for t in tw) for w in words)
    out = []
    arts = LIB.find_artists(q, 3)   # tolera faltas: "cancerbero" -> Canserbero
    out += [{"tipo": "artista", "texto": a["name"], "canciones": a["songs"], "thumb": a["thumb"]} for a in arts]
    albums, seen_al = [], set()
    with LIB.lock:
        for e in LIB.index.values():
            al = e.get("album")
            if al and Library._norm(al) not in seen_al and fits(al):
                seen_al.add(Library._norm(al))
                albums.append({"tipo": "album", "texto": al, "artista": LIB.artist_name(e), "thumb": e.get("thumb")})
                if len(albums) >= 3:
                    break
    out += albums
    for k, e in LIB.suggest(q, n):
        if len(out) >= n:
            break
        if k.startswith("yt-"):
            out.append({"tipo": "cancion", "texto": e.get("title"), "artista": LIB.artist_name(e), "id": k[3:],
                        "thumb": e.get("thumb")})
    return {"sugerencias": out[:n]}


def album_artist(q):
    """El artista del que se habla en 'q', aunque esté mal escrito ("guns ando rose" -> Guns N' Roses): el de la
    biblioteca (tolera faltas) o, si no está guardado, el que más sale en las canciones de internet que ya se
    buscaron con ese texto (de memoria, sin pedir nada). Solo si lo escrito se parece al nombre o lo contiene (si no,
    "amor" acabaría en un artista cualquiera). None si no se sabe."""
    nq = LIB._norm(q)
    names = [a["name"] if isinstance(a, dict) else a for a in LIB.find_artists(q)[:3]]
    songs = SEARCHES_YT.recall("ytm-songs:" + YouTubeSearches.key(q, YTM_NEW)) or []
    top = collections.Counter((s.get("artist") or "").split(", ")[0] for s in songs[:10] if s.get("artist")).most_common(1)
    if top and top[0][1] >= 5:
        names.append(top[0][0])
    for name in names:
        nn = LIB._norm(name)
        if nn and (nq in nn or nn in nq or difflib.SequenceMatcher(None, nq, nn).ratio() >= 0.6):
            return name
    return None


@app.get("/search/albums", dependencies=[Depends(check_token)])
def search_albums(q: str = Query(min_length=1, max_length=200)):
    """Álbumes de internet (YouTube Music) para 'q': {albums: [{id, title, artist, year, thumb, type}]}. Si 'q' es un
    artista (también con faltas, album_artist), se buscan los suyos y solo salen los suyos (si hay alguno). 1
    petición a YouTube la primera vez; después, de memoria. La app lo pide solo si se abre la pestaña de álbumes."""
    artist = album_artist(q)
    text = artist or q
    k = "ytm-albums:" + YouTubeSearches.key(text, 20)
    hit = SEARCHES_YT.recall(k)
    if hit is None:
        hit = [{"id": a.get("browseId"), "title": a.get("title"), "year": a.get("year"), "type": a.get("type"),
                "artist": ", ".join(x["name"] for x in a.get("artists") or [] if x.get("name")), "thumb": ytm_thumb(a)}
               for a in ytm(lambda y: y.search(text, filter="albums", limit=20)) if a.get("browseId")]
        SEARCHES_YT.store(k, hit, f"{text} (álbumes)")
    if artist:   # solo los de ese artista ("Real Hasta la Muerte" no es de Guns N' Roses)
        na = LIB._norm(artist)
        mine = [a for a in hit if na in LIB._norm(a.get("artist"))]
        hit = mine or hit
    return {"albums": hit, "artista": artist}


@app.get("/search/album/{album_id}", dependencies=[Depends(check_token)])
def search_album(album_id: str):
    """Un álbum de internet con sus canciones en orden (track) y cuáles ya están guardadas (where). 1 petición
    a YouTube la primera vez. Poner una canción baja solo esa."""
    if not ALBUM_ID.fullmatch(album_id):
        raise HTTPException(400, "id de álbum no válido")
    k = "ytm-album:" + album_id
    al = SEARCHES_YT.recall(k)
    if al is None:
        a = ytm(lambda y: y.get_album(album_id))
        al = {"id": album_id, "title": a.get("title"), "year": a.get("year"), "thumb": ytm_thumb(a),
              "artist": ", ".join(x["name"] for x in a.get("artists") or [] if x.get("name"))}
        al["songs"] = [ytm_song(t, al) for t in a.get("tracks") or [] if t.get("videoId")]
        SEARCHES_YT.store(k, al, f"álbum {al['title']}")
    songs = [dict(s, where="guardada") if LIB.peek(f"yt-{s['id']}") else s for s in al["songs"]]
    return {**al, "songs": songs}


def yt_entries(pairs):
    """Canciones para la app (solo las de YouTube: /stream solo acepta esas)."""
    return [entry(k, e, "guardada") for k, e in pairs if k.startswith("yt-")]


@app.get("/library", dependencies=[Depends(check_token)])
def library_page(sort: str = Query("recientes"), offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                 genre: str | None = Query(None, max_length=100)):
    """Toda la música guardada por páginas, para ir cargando según se baja: {total, offset, songs}. sort:
    recientes (la última que sonó primero), populares, nombre (A-Z) o artista (A-Z). Cuando offset + len(songs)
    llega a total, no hay más."""
    if sort not in LIB.SORTS:
        raise HTTPException(400, f"sort tiene que ser uno de: {', '.join(LIB.SORTS)}")
    total, songs = LIB.page(sort, offset, limit, genre)
    return {"total": total, "offset": offset, "songs": yt_entries(songs)}


@app.get("/genres", dependencies=[Depends(check_token)])
def genres():
    """Los géneros de lo guardado: {genres: [{name, songs}]}, los que más canciones tienen primero. Para filtrar,
    /library?genre=…. Se van completando solos (enrich.py)."""
    return {"genres": LIB.genres()}


def my_artists(sub):
    """{artista normalizado: puntos} de lo que más escucha esta cuenta ({} sin cuenta o sin recomendaciones)."""
    return REC.top_artists(sub) if REC and sub else {}


@app.get("/artists")
def artists(found=Depends(check_token), orden: str = Query("canciones", pattern="^(canciones|tuyos)$")):
    """Todos los artistas guardados: [{name, songs, albums, thumb}], los que más canciones tienen primero. Con
    orden=tuyos (y sesión), primero los que más escuchas (como "Tus artistas" de Spotify; esos traen `tuyo: true`)
    y detrás los demás."""
    out = LIB.artists()
    mine = my_artists(found[0] if found else None) if orden == "tuyos" else {}
    if mine:
        for a in out:
            a["tuyo"] = mine.get(LIB._norm(a["name"]), 0) > 0
        out.sort(key=lambda a: -mine.get(LIB._norm(a["name"]), 0))   # estable: los demás, por canciones
    return {"artists": out}


@app.get("/artist")
def artist(found=Depends(check_token), name: str = Query(min_length=1, max_length=200)):
    """Un artista: sus álbumes [{name, year, songs, thumb}] (más nuevos primero) y sus canciones sin álbum. Con
    sesión, además `tuyas` (las suyas que tienes en favoritas o en alguna playlist: favoritas primero, la última
    marcada arriba) y `todas` (la cola al darle a reproducir: las tuyas y luego las demás, las más puestas primero)."""
    a = LIB.artist(name)
    if not a:
        raise HTTPException(404, "no hay canciones de ese artista")
    out = {"name": a["name"], "songs": a["songs"], "albums": a["albums"], "loose": yt_entries(a["loose"])}
    if found:
        sub = found[0]
        songs = dict(a["loose"])
        for al in a["albums"]:
            songs.update((LIB.album(a["name"], al["name"]) or {}).get("songs", []))
        order = [f["id"] for f in userdata.favorites(sub)] + [x["id"] for p in userdata.playlists(sub) for x in p["songs"]]
        mine = list(dict.fromkeys(k for k in ("yt-" + i for i in order) if k in songs))
        rest = sorted((k for k in songs if k not in set(mine)),
                      key=lambda k: (-songs[k].get("plays", 0), (songs[k].get("title") or "").lower()))
        out["tuyas"] = yt_entries([(k, songs[k]) for k in mine])
        out["todas"] = yt_entries([(k, songs[k]) for k in mine + rest])
    return out


@app.get("/album", dependencies=[Depends(check_token)])
def album(artist: str = Query(min_length=1, max_length=200), name: str = Query(min_length=1, max_length=300)):
    """Las canciones guardadas de un álbum de un artista."""
    a = LIB.album(artist, name)
    if not a:
        raise HTTPException(404, "no hay canciones de ese álbum")
    return {"name": a["name"], "artist": a["artist"], "year": a["year"], "songs": yt_entries(a["songs"])}


def need_user(found):
    if not found:
        raise HTTPException(400, "esto es de cada usuario: entra con tu cuenta (la clave compartida no tiene)")
    return found[0]


def valid_vid(vid):
    if not VIDEO_ID.fullmatch(vid):
        raise HTTPException(400, "id de YouTube no válido")
    return vid


def song_of(vid, fallback=None):
    """Una canción para la app: de la biblioteca si está guardada; si no, la ficha que se tenga (fallback)."""
    e = LIB.peek(f"yt-{vid}")
    if e:
        return entry(f"yt-{vid}", e, "guardada")
    if fallback:
        return {"id": vid, **{k: fallback.get(k) for k in userdata.FIELDS}, "where": "youtube"}
    return None


@app.get("/favorites")
def favorites(found=Depends(check_token)):
    """Mis favoritas (iguales en la app y en la web), la última marcada primero. Las que ya no están guardadas
    salen con where=youtube: al ponerlas se vuelven a bajar."""
    return {"songs": [dict(song_of(f["id"], f), added=f["added"]) for f in userdata.favorites(need_user(found))]}


@app.put("/favorites/{vid}")
def add_favorite(vid: str, found=Depends(check_token), title: str | None = Body(None, embed=True, max_length=300),
                 artist: str | None = Body(None, embed=True, max_length=200),
                 album: str | None = Body(None, embed=True, max_length=300),
                 duration: float | None = Body(None, embed=True), thumb: str | None = Body(None, embed=True, max_length=500)):
    """Marca una canción como favorita. Si está guardada, su ficha sale de la biblioteca; si no (un resultado de
    YouTube), vale la que mande la app (title, artist, album, duration, thumb)."""
    sub = need_user(found)
    info = song_of(valid_vid(vid)) or {"title": title, "artist": artist, "album": album, "duration": duration, "thumb": thumb}
    if not info.get("title"):
        raise HTTPException(400, "falta el título (no está guardada en el servidor)")
    userdata.add_favorite(sub, vid, info)
    return {"ok": True}


@app.delete("/favorites/{vid}")
def remove_favorite(vid: str, found=Depends(check_token)):
    return {"ok": userdata.remove_favorite(need_user(found), valid_vid(vid))}


def known_song(vid):
    """La ficha de una canción aunque no esté guardada: de la biblioteca, de lo que alguien ya apuntó (favoritas,
    playlists) o de las búsquedas recientes en YouTube Music. None si no se sabe nada."""
    s = song_of(vid, userdata.known(vid))
    if s:
        return s
    with SEARCHES_YT.lock:
        for v in SEARCHES_YT.data.values():
            info = v["info"]
            for x in (info if isinstance(info, list) else info.get("songs", []) if isinstance(info, dict) else []):
                if isinstance(x, dict) and x.get("id") == vid and x.get("title"):
                    return {k: x.get(k) for k in ("id", "title", "artist", "album", "duration", "thumb")} | {"where": "youtube"}
    return None


@app.get("/playlists")
def get_playlists(found=Depends(check_token)):
    """Mis playlists (iguales en la app, la web y otros móviles), la última cambiada primero: {playlists: [{id,
    name, songs: [canciones como en /search], created, updated}]}. Las canciones que ya no están guardadas salen
    con where=youtube (al ponerlas se vuelven a bajar)."""
    out = []
    for p in userdata.playlists(need_user(found)):
        p["songs"] = [song_of(s["id"], s) for s in p["songs"]]
        out.append(p)
    return {"playlists": out}


@app.post("/playlists")
def create_playlist(found=Depends(check_token), name: str = Body(embed=True, min_length=1, max_length=100)):
    try:
        return {"id": userdata.create_playlist(need_user(found), name.strip())}
    except OverflowError:
        raise HTTPException(400, f"como mucho {userdata.PLAYLISTS_MAX} playlists")


@app.put("/playlists/{pid}")
def save_playlist(pid: str, found=Depends(check_token), name: str = Body(embed=True, min_length=1, max_length=100),
                  songs: list = Body(embed=True)):
    """Guarda la playlist entera de una vez: nombre y canciones en orden (ids; o fichas {id, title, artist…} si es
    algo que el servidor aún no conoce). Quitar, añadir y reordenar son el mismo cambio."""
    sub = need_user(found)
    if len(songs) > userdata.PLAYLIST_SONGS_MAX:
        raise HTTPException(400, f"como mucho {userdata.PLAYLIST_SONGS_MAX} canciones")
    fichas, unknown = [], []
    for s in songs:
        vid = s.get("id") if isinstance(s, dict) else s
        if not isinstance(vid, str) or not VIDEO_ID.fullmatch(vid):
            raise HTTPException(400, f"id de canción no válido: {str(vid)[:20]}")
        info = known_song(vid) or (s if isinstance(s, dict) and s.get("title") else None)
        if not info:
            unknown.append(vid)
        fichas.append({"id": vid, **(info or {})})
    if unknown:   # sin título no se podría enseñar: que la app mande la ficha de esas
        raise HTTPException(400, {"error": "faltan las fichas de estas canciones (mándalas como {id, title, artist…})",
                                  "ids": unknown})
    if not userdata.save_playlist(sub, pid, name.strip(), fichas):
        raise HTTPException(404, "no existe esa playlist")
    return {"ok": True}


@app.delete("/playlists/{pid}")
def delete_playlist(pid: str, found=Depends(check_token)):
    if not userdata.delete_playlist(need_user(found), pid):
        raise HTTPException(404, "no existe esa playlist")
    return {"ok": True}


def rec_on():
    if not REC:
        raise HTTPException(404, "recomendaciones apagadas")
    return REC


def rec_songs(keys):
    return [s for s in (song_of(k[3:]) for k in keys) if s]


@app.post("/eventos")
def eventos(found=Depends(check_token), items: list = Body(embed=True, alias="eventos", max_length=500)):
    """Lo que hace el usuario, en lote (también lo guardado sin conexión): [{tipo: entera|salto|no_me_gusta|
    ya_no_me_gusta, id, segundo, duracion, contexto, causa, cuando}]. "Empezó a sonar" no hace falta: lo apunta
    /stream. Ver docs/recomendaciones.md, secciones 2 y 9."""
    return {"guardados": rec_on().add_events(need_user(found), [x for x in items if isinstance(x, dict)])}


@app.get("/home")
def home(found=Depends(check_token)):
    """Las secciones del Inicio, en orden: {secciones: [{id, titulo, tipo: canciones, items}]}. Las que salen vacías
    no se mandan."""
    rec, sub = rec_on(), need_user(found)
    out = []
    for sid, title, keys in (("recientes", "Escuchado recientemente", rec.recent(sub)),
                             ("para_ti", "Para ti", rec.para_ti(sub)),
                             ("vuelve", "Vuelve a escuchar", rec.vuelve(sub))):
        items = rec_songs(keys)
        if items:
            out.append({"id": sid, "titulo": title, "tipo": "canciones", "items": items})
    mine = rec.top_artists(sub)
    tuyos = [a for a in LIB.artists() if mine.get(LIB._norm(a["name"]), 0) > 0]
    tuyos.sort(key=lambda a: -mine[LIB._norm(a["name"])])
    if tuyos:   # tipo artistas: items = [{name, songs, albums, thumb}], como /artists
        out.append({"id": "artistas", "titulo": "Tus artistas", "tipo": "artistas", "items": tuyos[:20]})
    return {"secciones": out}


@app.get("/radio")
def radio(found=Depends(check_token), desde: str = Query(max_length=200), ya: str = Query("", max_length=20000),
          n: int = Query(20, ge=1, le=50)):
    """Radio infinita: desde=cancion:<id> o artista:<nombre>; ya = ids ya puestos (separados por comas), para no
    repetir. Volver a pedir al acercarse al final."""
    rec, sub = rec_on(), need_user(found)
    kind, _, value = desde.partition(":")
    if kind == "cancion" and VIDEO_ID.fullmatch(value):
        seed = ("cancion", f"yt-{value}")
    elif kind == "artista" and value.strip():
        seed = ("artista", value.strip())
    else:
        raise HTTPException(400, "desde=cancion:<id> o desde=artista:<nombre>")
    exclude = [f"yt-{i}" for i in ya.split(",") if VIDEO_ID.fullmatch(i)]
    songs = rec_songs(rec.radio(sub, seed, exclude, n))
    if not songs and seed[0] == "cancion" and not LIB.peek(seed[1]):
        raise HTTPException(404, "esa canción no está guardada: ponla primero")
    return {"songs": songs}


@app.post("/recomendaciones/opinion")
def opinion(found=Depends(check_token), body: dict = Body(...)):
    """"¿Qué te parecieron?": {contexto, semilla, gusto: si|no, opciones: [...], texto, canciones}."""
    rec_on().add_opinion(need_user(found), body)
    return {"ok": True}


@app.get("/recomendaciones/preguntar")
def preguntar(found=Depends(check_token), contexto: str = Query(max_length=20)):
    """¿Toca enseñar ahora la tarjeta "¿Qué te parecieron?"? (como mucho una vez por semana). Si dice que sí, ya
    cuenta como preguntado."""
    return {"preguntar": rec_on().should_ask(need_user(found), contexto)}


@app.get("/history")
def history(found=Depends(check_token), limit: int = Query(50, ge=1, le=userdata.HISTORY_MAX)):
    """Lo último que puse yo (no lo de todos), lo más reciente primero: canciones con 'played' (cuándo)."""
    sub = need_user(found)
    favs = {f["id"]: f for f in userdata.favorites(sub)}
    out = []
    for vid, when in userdata.history(sub, limit):
        s = song_of(vid, favs.get(vid))
        if s:
            out.append(dict(s, played=when))
    return {"songs": out}


@app.get("/stream/{vid}")
def stream(vid: str, request: Request, found=Depends(check_token)):
    """El audio de la canción (webm/Opus). Admite Range, así el reproductor puede saltar dentro de la canción."""
    if not VIDEO_ID.fullmatch(vid):
        raise HTTPException(400, "id de YouTube no válido")
    key, where = DUPLICADAS.real_key(f"yt-{vid}"), "guardada"
    first = request.headers.get("range", "bytes=0-").startswith("bytes=0-")   # al empezar, no en cada trozo
    if first:
        hit = LIB.get(key)
        path = hit and hit["path"]
        if found:
            userdata.played(found[0], vid)   # mi historial
            if REC:
                REC.add_events(found[0], [{"tipo": "inicio", "id": vid}], source="servidor")
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


@internal.get("/interno/youtube")
def i_youtube():
    """Cómo está YouTube: {bloqueado_hasta (0 si no), peticiones_hora, tope_hora, ultimo_bloqueo}. El bot lo consulta
    para avisar en el canal de registro cuando nos bloquea y cuando se pasa."""
    return yt_state()


@internal.get("/interno/duplicadas")
def i_duplicadas():
    """Canciones repetidas en la biblioteca, sin tocar nada: [{queda, sobran: [títulos]}]."""
    found = DUPLICADAS.find()
    return {"repetidas": len(found), "sobran": sum(len(r) for _, r in found),
            "lista": [{"queda": b[1].get("title"), "sobran": [e.get("title") for _, e in r]} for b, r in found]}


@internal.post("/interno/duplicadas")
def i_duplicadas_merge():
    """Junta las repetidas ya (se hace sola cada noche): favoritas, playlists e historial pasan a la que se queda."""
    return {"borradas": DUPLICADAS.merge()}


@internal.get("/interno/versiones")
def i_versiones():
    """Cómo va el cambio de versiones de vídeo por las de disco (versiones.py), por cuenta."""
    return VERSIONES.status()


@internal.post("/interno/versiones")
def i_versiones_start(email: str = Body(embed=True, max_length=200), deshacer: bool = Body(False, embed=True)):
    """Empieza a cambiar las favoritas y playlists en versión vídeo de esa cuenta por la versión de disco (o, con
    deshacer, pone otra vez las de antes). Las que ya están guardadas, al momento; las demás, despacio."""
    users.USERS.reload()
    sub = next((s for s, u in users.USERS.data.items() if u.get("email") == email.strip().lower()), None)
    if not sub:
        raise HTTPException(404, "no hay ninguna cuenta con ese email")
    if deshacer:
        return {"deshechas": VERSIONES.undo(sub)}
    return {"pendientes": VERSIONES.start(sub, email)}


@internal.get("/interno/precarga")
def i_precarga():
    """Cómo va la precarga de álbumes (precarga.py)."""
    return PRECARGA.status()


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
    key = DUPLICADAS.real_key(key_of(url))
    hit = LIB.get(key)
    if hit:
        hit.pop("path")
        return {"key": key, "source": "local", "file": hit["file"], "song": hit, "info": None}
    info, path = download(url, by)
    small = {**small_info(info), **music_meta(info)}
    if not path:
        return {"key": key, "source": "live", "file": None, "song": None, "info": small}
    key = DUPLICADAS.real_key(key_of(url, info))
    # la misma canción ya guardada con otro título (no se bajó nada): para el bot es local
    source = "local" if key not in (key_of(url), key_of(url, info)) else "online"
    return {"key": key, "source": source, "file": os.path.basename(path), "song": LIB.peek(key), "info": small}


def saved_as_info(key):
    """Una guardada con la forma de una respuesta de yt-dlp, que es lo que entiende el bot."""
    e = LIB.peek(key)
    return {"id": key[3:], "title": e.get("title"), "webpage_url": f"https://www.youtube.com/watch?v={key[3:]}",
            "duration": e.get("duration"), "thumbnail": e.get("thumb"), "artist": LIB.artist_name(e)}


@internal.post("/interno/resolve")
def i_resolve(query: str = Body(embed=True, max_length=2000), limit: int = Body(100, embed=True, le=MAX_PLAYLIST)):
    """Buscar ('ytsearch5:…' o un nombre) o leer un enlace (video, lista, SoundCloud…) sin bajar nada: título,
    duración, miniatura y, si es lista o búsqueda, sus 'entries'. Los nombres se buscan en **YouTube Music**
    (canciones oficiales, sin directos ni covers; misma búsqueda y memoria que la app); si no hay nada, o el
    texto empieza por 'yt:', en YouTube normal (remixes, memes, directos…). Los enlaces se respetan tal cual."""
    m = re.fullmatch(r"ytsearch(\d*):(.+)", query, re.S)
    if m or not re.match(r"https?://", query):
        n, text = (int(m.group(1) or 1), m.group(2)) if m else (1, query)
        text, n = text.strip(), min(n, 50)
        if text.lower().startswith("yt:"):
            return SEARCHES_YT.get(text[3:].strip(), n)
        try:
            songs = ytm_songs(text, 20)[:n]
        except HTTPException as ex:
            if ex.status_code in (503, 429):
                raise
            songs = []
        if not songs:
            return SEARCHES_YT.get(text, n)
        # con la forma de una búsqueda de yt-dlp, que es lo que entiende el bot
        return {"title": text, "entries": [
            {"id": s["id"], "title": s["title"], "url": f"https://www.youtube.com/watch?v={s['id']}",
             "webpage_url": f"https://www.youtube.com/watch?v={s['id']}", "ie_key": "Youtube",
             "duration": s["duration"], "thumbnail": s["thumb"], "artist": s["artist"],
             "artists": [x for x in s["artist"].split(", ") if x], "channel": s["artist"], "album": s["album"]}
            for s in songs]}

    # un vídeo suelto que ya se sabe que es una guardada con otro título: suena la guardada sin preguntar a YouTube
    one = bool(YT_ID.search(query)) and "list=" not in query
    key = key_of(query)
    if one and (real := DUPLICADAS.real_key(key)) != key and real.startswith("yt-"):
        return saved_as_info(real)

    def run():
        with ydl(extract_flat="in_playlist", playlistend=limit, default_search="ytsearch") as y:
            return y.extract_info(query, download=False)
    # una lista larga son varias páginas (~100 por página)
    info = youtube(run, not re.match(r"https?://", query) or is_yt(query), COST_SEARCH + limit // 100)
    # la primera vez se reconoce aquí, para no volver a preguntar al bajarla
    if one and info.get("duration") and not info.get("is_live") and not LIB.peek(key):
        same = DUPLICADAS.same_as_saved(key, info)
        if same and same.startswith("yt-"):
            return saved_as_info(same)
    return small_info(info)


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
