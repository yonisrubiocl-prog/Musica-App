"""API de MusicApp: la dueña de la música. La app la usa por internet (login de Google) y el bot por la red
interna de Docker (rutas /interno, en otro puerto al que los túneles no llegan).

Canciones: una sola biblioteca en /music con su catálogo (ver library.py). El bot lee el catálogo y los archivos
directo del disco (solo lectura); todo lo que escribe o habla con YouTube lo pide aquí. Ver README.md, "Canciones".
"""
import asyncio
import hmac
import logging
import os
import re
import threading
import time

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
TMP = "/tmp/musicapp"
TOKEN = os.environ.get("API_TOKEN", "")          # clave compartida provisional, hasta que la app tenga login
BOT_KEY = os.environ.get("BOT_API_KEY", "")      # clave del bot para /interno
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")   # cliente OAuth "Aplicación web" (no es secreto)
PUBLIC_PORT, INTERNAL_PORT = 8000, 8001
YT_RESULTS = 5
MAX_PLAYLIST = 5000                     # tope de canciones al leer una lista (el bot pide menos para la cola)
YT_PAUSE = 15 * 60                      # tras un bloqueo de YouTube no se le pide nada durante este tiempo
VIDEO_ID = re.compile(r"[\w-]{11}")
# Lo que el bot necesita de la respuesta de yt-dlp (el resto, como la lista de formatos, pesa mucho).
INFO_FIELDS = ("id", "title", "webpage_url", "duration", "thumbnail", "is_live", "url", "http_headers",
               "extractor_key", "ie_key", "uploader", "channel", "artist", "artists")

LIB = Library(MUSIC_DIR, MUSIC_GB * 1024 ** 3, MUSIC_INDEX)

_yt_blocked_until = 0.0
_downloads = {}                         # clave -> lock: dos peticiones de la misma canción la bajan una vez
_downloads_lock = threading.Lock()


def ydl(**extra):
    o = {"quiet": True, "no_warnings": True, "noprogress": True}
    if os.path.exists(COOKIES):
        o["cookiefile"] = COOKIES
    return yt_dlp.YoutubeDL({**o, **extra})


def is_yt(url):
    return "youtu" in url


def youtube(fn, yt=True):
    """Llama a YouTube salvo que nos tenga bloqueados (pide 'confirmar que no eres un bot'): insistir lo alarga.
    yt=False: es otra web (SoundCloud, una radio…), no cuenta el bloqueo."""
    global _yt_blocked_until
    left = _yt_blocked_until - time.time()
    if yt and left > 0:
        raise HTTPException(503, f"YouTube nos bloqueó un rato; vuelvo a probar en ~{max(1, round(left / 60))} min")
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
        raise HTTPException(401, "no autorizado")
    return found


app = FastAPI(title="MusicApp", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/auth/google")
def auth_google(token: str = Body(embed=True, alias="id_token", max_length=4096)):
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
        user, session = users.login(claims)
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


@app.get("/acceso", response_class=HTMLResponse)
def access_page():
    """Página para pasar a los amigos: entran con Google y quedan pendientes de aprobar. No reproduce nada."""
    return ACCESS_HTML.replace("{CLIENT_ID}", GOOGLE_CLIENT_ID)


@app.get("/search", dependencies=[Depends(check_token)])
def search(q: str = Query(min_length=1, max_length=200), youtube_too: bool = Query(True, alias="yt")):
    """Primero lo guardado; luego, si se pide, YouTube. Sin repetir canciones."""
    out, seen = [], set()
    for k, e in LIB.matches(q, 10):
        if k.startswith("yt-"):   # /stream solo acepta canciones de YouTube
            seen.add(k)
            out.append(entry(k, e, "guardada"))
    if youtube_too:
        def run():
            with ydl(extract_flat="in_playlist") as y:
                return y.extract_info(f"ytsearch{YT_RESULTS}:{q}", download=False)
        for e in youtube(run).get("entries") or []:
            if e and e.get("id") and f"yt-{e['id']}" not in seen:
                seen.add(f"yt-{e['id']}")
                thumbs = e.get("thumbnails") or []
                out.append({"id": e["id"], "title": e.get("title"), "artist": artist_of(e), "album": "",
                            "duration": e.get("duration"), "thumb": thumbs[-1]["url"] if thumbs else None,
                            "where": "youtube"})
    return {"results": out}


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
    título, duración, miniatura y, si es lista o búsqueda, sus 'entries'."""
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


ACCESS_HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Música · pedir acceso</title>
<style>
  :root{--bg:#0d0d0f;--card:#18181c;--fg:#f2f2f2;--sub:#a0a0a8;--ok:#3ddc84;--wait:#ffd23f;--no:#ff5c5c}
  *{box-sizing:border-box;margin:0}
  body{min-height:100vh;display:grid;place-items:center;padding:16px;background:var(--bg);color:var(--fg);
       font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
  .card{width:100%;max-width:380px;background:var(--card);border-radius:20px;padding:32px 24px;text-align:center}
  h1{font-size:1.6rem;margin-bottom:.5rem} p{color:var(--sub);line-height:1.5}
  .g{display:flex;justify-content:center;margin:24px 0 8px;min-height:44px}
  #estado{margin-top:16px;padding:14px;border-radius:12px;display:none;color:var(--fg);line-height:1.5}
  #estado.ok{display:block;background:#3ddc8422;border:1px solid var(--ok)}
  #estado.wait{display:block;background:#ffd23f1f;border:1px solid var(--wait)}
  #estado.no{display:block;background:#ff5c5c1f;border:1px solid var(--no)}
</style>
<script src="https://accounts.google.com/gsi/client" async></script></head><body>
<main class="card">
  <h1>🎵 Música</h1>
  <p>Entra con tu cuenta de Google para pedir acceso. Cuando te aprueben podrás usar la app.</p>
  <div id="g_id_onload" data-client_id="{CLIENT_ID}" data-callback="entrar" data-auto_prompt="false"></div>
  <div class="g"><div class="g_id_signin" data-type="standard" data-theme="filled_black" data-shape="pill"
       data-text="continue_with" data-locale="es"></div></div>
  <div id="estado" role="status"></div>
</main>
<script>
const estado = (cls, html) => { const e = document.getElementById('estado'); e.className = cls; e.innerHTML = html; };
async function entrar(r) {
  estado('wait', 'Comprobando…');
  try {
    const res = await fetch('/auth/google', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                             body: JSON.stringify({id_token: r.credential})});
    const j = await res.json();
    const d = j.detail && typeof j.detail === 'object' ? j.detail : j;
    const nombre = (d.user && (d.user.name || d.user.email)) || '';
    if (j.session) {   // aquí no se usa la sesión: se cierra al momento
      fetch('/auth/logout', {method: 'POST', headers: {Authorization: 'Bearer ' + j.session}});
      estado('ok', '✅ <b>' + nombre + '</b>, ya estás aprobado. Cuando tengas la app, entra con esta misma cuenta.');
    } else if (d.status === 'pendiente') {
      estado('wait', '⏳ Listo, <b>' + nombre + '</b>. Tu solicitud quedó enviada: avisa para que te aprueben.');
    } else if (d.status === 'bloqueado') {
      estado('no', 'Esta cuenta no tiene acceso.');
    } else {
      estado('no', 'No se pudo comprobar (' + res.status + '). Prueba otra vez en un rato.');
    }
  } catch (e) { estado('no', 'Sin conexión con el servidor. Prueba otra vez.'); }
}
</script></body></html>"""


if __name__ == "__main__":
    asyncio.run(serve())
