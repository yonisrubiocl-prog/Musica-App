"""API de MusicApp: buscar una canción y escucharla, con login de Google.

Canciones: se leen de la caché propia (/cache, escribible) y de la del bot (/bot-cache, solo lectura).
Si no está en ninguna, se baja de YouTube a la propia. Ver README.md, sección "Canciones".
"""
import hmac
import json
import logging
import os
import re
import shutil
import threading
import time
import unicodedata

import yt_dlp
from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token

import users

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("musicapp")

CACHE_DIR = "/cache"                    # propias (en el servidor: /var/lib/musicapp/cache)
CACHE_INDEX = "/data/index.json"        # su catálogo (en ~/MusicApp/server/data), mismo formato que el del bot
BOT_CACHE_DIR = "/bot-cache"            # del bot, solo lectura (/var/lib/musicbot/cache)
BOT_INDEX = "/bot-data/index.json"      # catálogo del bot, solo lectura (~/MusicBot/data)
TMP = "/tmp/musicapp"
TOKEN = os.environ.get("API_TOKEN", "")          # clave compartida provisional, hasta que la app tenga login
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")   # cliente OAuth "Aplicación web" (no es secreto)
YT_RESULTS = 5
YT_PAUSE = 15 * 60                      # tras un bloqueo de YouTube no se le pide nada durante este tiempo
VIDEO_ID = re.compile(r"[\w-]{11}")

# Palabras que no ayudan a distinguir canciones (las mismas que usa el bot).
NOISE = {"official", "oficial", "video", "videoclip", "clip", "lyrics", "lyric", "letra", "audio", "hd", "hq",
         "4k", "remaster", "remastered", "visualizer", "music", "musical", "ft", "feat", "featuring",
         "the", "a", "an", "of", "de", "del", "la", "el", "los", "las", "en", "y", "con", "and", "n"}


def words(text):
    """'Neutro Shorty - Soy Yo [Official Video]' -> {'neutro', 'shorty', 'soy', 'yo'} (sin tildes ni relleno)."""
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return {w for w in re.findall(r"[a-z0-9]+", t) if w not in NOISE}


def artist_of(info):
    """Artista según YouTube (misma regla que el bot): ficha musical, o el canal si es '… - Topic' / '…VEVO'."""
    names = [x.strip() for x in (info.get("artists") or (info.get("artist") or "").split(",")) if x and x.strip()]
    raw = info.get("uploader") or info.get("channel") or ""
    ch = re.sub(r"(?i)\s*(?:-\s*topic|vevo)$", "", raw).strip()
    if names:
        own = [n for n in names if n.lower() == ch.lower()]
        return (own or names)[0]
    if ch and re.search(r"(?i)-\s*topic$|vevo$", raw):
        return ch
    return ""


def music_meta(info):
    """Ficha de la canción con los mismos campos que guarda el bot (sale de la misma respuesta de la descarga)."""
    date = info.get("release_date") or info.get("upload_date") or ""
    cats = info.get("categories") or []
    m = re.search(r"℗\s*(?:\d{4}\s*)?([^\n]+)", info.get("description") or "")
    return {"artist": artist_of(info), "album": (info.get("album") or "").strip(),
            "track": (info.get("track") or "").strip(),
            "year": info.get("release_year") or (int(date[:4]) if date[:4].isdigit() else None),
            "date": date or None, "channel": info.get("channel") or info.get("uploader") or "",
            "credits": [x for x in (info.get("artists") or []) if x][:10],
            "label": m.group(1).strip() if m else "", "category": cats[0] if cats else "",
            "tags": (info.get("tags") or [])[:10], "views": info.get("view_count"), "likes": info.get("like_count"),
            "language": info.get("language") or "", "age": info.get("age_limit") or 0}


class Catalog:
    """Un index.json con formato del bot: 'yt-<id>' -> {file, title, duration, thumb, artist, album…}.
    El del bot se relee solo cuando cambia en disco; el propio se escribe aquí."""

    def __init__(self, root, index_file, name):
        self.root, self.file, self.name = root, index_file, name
        self.lock = threading.Lock()
        self.index, self.mtime = {}, None
        self.reload()

    def reload(self):
        try:
            mtime = os.path.getmtime(self.file)
        except OSError:
            return
        if mtime == self.mtime:
            return
        try:
            with open(self.file) as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            log.warning("%s: no pude leer %s: %s", self.name, self.file, e)   # se queda con lo que tenía
            return
        if isinstance(data, dict):
            with self.lock:
                self.index, self.mtime = data, mtime
            log.info("%s: %d canciones en el catálogo", self.name, len(data))

    def path(self, key):
        """Ruta del audio si la canción está en el catálogo y el archivo sigue ahí."""
        e = self.index.get(key)
        if e:
            p = os.path.join(self.root, e["file"])
            if os.path.exists(p):
                return p
        return None

    def search(self, q, limit):
        """Canciones con TODAS las palabras buscadas en título, artista o álbum. Mejor primero: la que menos
        palabras tiene de más; luego la más puesta."""
        self.reload()
        hits = []
        for k, e in list(self.index.items()):
            ws = words(f"{e.get('title') or ''} {e.get('artist') or ''} {e.get('album') or ''}")
            if q <= ws:
                hits.append((len(q) / max(1, len(ws)), e.get("plays", 0), k, e))
        hits.sort(key=lambda h: h[:2], reverse=True)
        return [(k, e) for *_, k, e in hits[:limit]]

    def add(self, key, path, info):
        with self.lock:
            old = self.index.get(key) or {}
            self.index[key] = {"file": os.path.basename(path), "url": info.get("webpage_url"),
                               "title": info.get("title"), "duration": info.get("duration"),
                               "thumb": info.get("thumbnail"), "size": os.path.getsize(path), "used": time.time(),
                               "plays": old.get("plays", 0), "by": old.get("by", 0), **music_meta(info)}
            self._save()

    def played(self, key):
        with self.lock:
            e = self.index.get(key)
            if e:
                e["used"], e["plays"] = time.time(), e.get("plays", 0) + 1
                self._save()

    def _save(self):
        tmp = self.file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.index, f, ensure_ascii=False)
        os.replace(tmp, self.file)
        self.mtime = os.path.getmtime(self.file)


OWN = Catalog(CACHE_DIR, CACHE_INDEX, "propias")
BOT = Catalog(BOT_CACHE_DIR, BOT_INDEX, "bot")

_yt_blocked_until = 0.0
_downloads = {}                         # id -> lock: dos peticiones de la misma canción la bajan una vez
_downloads_lock = threading.Lock()


def ydl(**extra):
    return yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noprogress": True, **extra})


def youtube(fn):
    """Llama a YouTube salvo que nos tenga bloqueados (pide 'confirmar que no eres un bot'): insistir lo alarga."""
    global _yt_blocked_until
    left = _yt_blocked_until - time.time()
    if left > 0:
        raise HTTPException(503, f"YouTube nos bloqueó un rato; vuelvo a probar en ~{max(1, round(left / 60))} min")
    try:
        return fn()
    except yt_dlp.utils.DownloadError as e:
        t = str(e).lower()
        if "not a bot" in t or ("429" in t and "too many requests" in t):
            _yt_blocked_until = time.time() + YT_PAUSE
            log.warning("YouTube nos bloqueó: no le pido nada durante %d min", YT_PAUSE // 60)
        log.warning("YouTube: %s", e)
        raise HTTPException(502, str(e).replace("ERROR: ", "")[:200])


def download(vid):
    """Baja el audio (webm/Opus como el bot) a la caché propia y lo apunta en el catálogo."""
    def run():
        os.makedirs(TMP, exist_ok=True)
        with ydl(format="bestaudio[ext=webm]/bestaudio/best", noplaylist=True,
                 outtmpl=f"{TMP}/%(id)s.%(ext)s") as y:
            info = y.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
            if info.get("is_live") or not info.get("duration"):
                raise HTTPException(422, "es un directo: no se puede guardar")
            y.process_info(info)
            return info, y.prepare_filename(info)

    info, src = youtube(run)
    dest = os.path.join(CACHE_DIR, f"yt-{vid}{os.path.splitext(src)[1]}")
    shutil.move(src, dest + ".part")   # copia entre discos: si se corta queda un .part, nunca uno a medias
    os.replace(dest + ".part", dest)
    OWN.add(f"yt-{vid}", dest, info)
    log.info("bajada: %s (%s)", info.get("title"), vid)
    return dest


def audio_path(vid):
    """De la caché propia, de la del bot, o bajándola (una sola vez aunque la pidan varios a la vez)."""
    key = f"yt-{vid}"
    p = OWN.path(key)
    if p:
        return p, "app"
    BOT.reload()
    p = BOT.path(key)
    if p:
        return p, "bot"
    with _downloads_lock:
        lock = _downloads.setdefault(vid, threading.Lock())
    with lock:
        p = OWN.path(key)
        if p:
            return p, "app"
        return download(vid), "youtube"


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


@app.get("/search", dependencies=[Depends(check_token)])
def search(q: str = Query(min_length=1, max_length=200), youtube_too: bool = Query(True, alias="yt")):
    """Primero lo guardado (propio y del bot); luego, si se pide, YouTube. Sin repetir canciones."""
    ws = words(q)
    out, seen = [], set()
    if ws:
        for cat, where in ((OWN, "app"), (BOT, "bot")):
            for k, e in cat.search(ws, 10):
                if k not in seen and cat.path(k):
                    seen.add(k)
                    out.append(entry(k, e, where))
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
    path, where = audio_path(vid)
    if where == "app" and request.headers.get("range", "bytes=0-").startswith("bytes=0-"):
        OWN.played(f"yt-{vid}")   # cuenta al empezar, no en cada trozo que pide el reproductor
    media = "audio/webm" if path.endswith(".webm") else "audio/mp4" if path.endswith(".m4a") else "audio/mpeg"
    return FileResponse(path, media_type=media, headers={"X-Source": where, "Cache-Control": "private, max-age=86400"})


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
