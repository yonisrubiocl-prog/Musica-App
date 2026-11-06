"""Canvas como el de Spotify: un trozo de SECS s del videoclip de cada canción, vertical (9:16), sin sonido y en
bucle, que el reproductor grande pone de fondo mientras suena. ~300-500 KB por canción, en DIR/<id>.mp4.

De dónde sale el vídeo:
- Si la canción se bajó de un vídeo de verdad (miniatura de vídeo y sin "Letra", "Lyrics", "Audio"…), de ese mismo.
- Si no (pistas de álbum de YouTube Music, que son la portada quieta, o vídeos con letra), se busca su videoclip en
  YouTube Music (1 búsqueda) y se coge el primero que sea de verdad el suyo (artista, título y duración parecidos).
Al acabar se mira si el trozo se mueve: si casi no se mueve (una imagen fija), no vale y se queda la portada viva.
Cada canción se intenta **una sola vez**: lo que sale mal para siempre (sin videoclip, quieto) queda apuntado en
"no" y no se vuelve a pedir; un fallo de red se reintenta (RETRY, como mucho MAX_ERRORS veces).

Orden: 1) las que alguien está poniendo (GET /canvas/<id>/estado), a cualquier hora; 2) las que acaba de bajar la
precarga; 3) todas las demás, las más puestas primero, de madrugada (NIGHT_UTC) o de día si nadie usa YouTube
(IDLE), con pausas al azar (GAP) como la precarga. Todo pasa por el ritmo general con YouTube (yt_turn) y, si
YouTube avisa de bloqueo, se para BLOCK_PAUSE. Estado en /data/canvas.json. Ver README.md, "Canvas".
"""
import collections
import difflib
import json
import logging
import os
import random
import re
import subprocess
import threading
import time

import titulos

log = logging.getLogger("musicapp.canvas")

DIR = "/canvas"                         # en el servidor: /var/lib/musicapp/canvas
FILE = "/data/canvas.json"
TMP = "/tmp/musicapp/canvas"
SECS = 7                                # lo que dura el trozo
SIZE = (540, 960)                       # vertical; de fondo en un móvil no hace falta más
NIGHT_UTC = (4, 12)                     # 01:00-09:00 en Chile, como la precarga
GAP = (90, 300)                         # entre las de fondo (segundos, al azar): ~18 por hora, ~70 peticiones
DAY_SLOWER = 1.5
IDLE = 600                              # de día, las de fondo solo si nadie usó YouTube en estos segundos
BLOCK_PAUSE = 24 * 3600
RETRY, MAX_ERRORS = 6 * 3600, 3         # otros fallos: se reintenta pasado RETRY, como mucho MAX_ERRORS veces
NET_PAUSE = 30 * 60                     # sin conexión con los servidores de vídeo: todo quieto este rato, sin contarlo
NETWORK = re.compile(r"unreachable|timed out|connection|ffmpeg exited|temporary failure|name resolution", re.I)
WAIT_SAVED = 15 * 60                    # una pedida que aún no está guardada (se está bajando) espera hasta esto
FROZEN = 0.6                            # si más de esta parte del trozo está quieta, es una imagen fija
# un vídeo propio que no es un videoclip: se busca el videoclip
NOT_OWN = re.compile(r"lyric|letra|karaoke|\baudio\b|visuali[sz]er|\b8d\b|sped up|slowed", re.I)
OFFICIAL = re.compile(r"official|oficial|vevo", re.I)
# resultados de la búsqueda que no son el videoclip (salvo que la canción también lo sea: "(En Vivo)")
NOT_CLIP = re.compile(r"lyric|letra|karaoke|reacci[oó]n|reaction|cover|tutorial|en vivo|\blive\b|concierto|concert|"
                      r"\b8d\b|sped up|slowed|instrumental|remix|acoustic|ac[uú]stic", re.I)


class Canvas:
    def __init__(self, lib, ytm, fetch, blocked, user_idle):
        """fetch(id, desde, segundos, base) -> ruta del trozo de vídeo bajado (pasa por el ritmo con YouTube)."""
        self.lib, self.ytm, self.fetch = lib, ytm, fetch
        self.blocked, self.user_idle = blocked, user_idle
        self.lock = threading.Lock()
        try:
            with open(FILE) as f:
                self.state = json.load(f)
        except (OSError, ValueError):
            self.state = {}
        for k in ("ok", "no", "err"):
            self.state.setdefault(k, {})
        self.state.setdefault("paused_until", 0)
        self.urgent = collections.OrderedDict()   # id -> cuándo se pidió (alguien la está poniendo)
        self.soon = collections.OrderedDict()     # id -> recién bajada por la precarga
        os.makedirs(DIR, exist_ok=True)
        threading.Thread(target=self._run, daemon=True, name="canvas").start()

    def _save(self):
        tmp = FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f, ensure_ascii=False)
        os.replace(tmp, FILE)

    # ---------- lo que usa la API ----------

    def path(self, vid):
        p = os.path.join(DIR, vid + ".mp4")
        return p if vid in self.state["ok"] and os.path.isfile(p) else None

    def status(self, vid):
        if self.path(vid):
            return "listo"
        return "no" if vid in self.state["no"] or self._dead(vid) else "haciendo"

    def ask(self, vid):
        """Alguien la está poniendo: si no tiene Canvas ni se intentó ya, va la primera de la cola."""
        with self.lock:
            st = self.status(vid)
            if st == "haciendo":
                self.urgent.setdefault(vid, time.time())
            return st

    def want(self, vid):
        """La precarga acaba de bajarla: va antes que las de fondo."""
        with self.lock:
            if self.status(vid) == "haciendo":
                self.soon.setdefault(vid, time.time())

    def summary(self):
        with self.lock:
            return {"listos": len(self.state["ok"]), "sin_canvas": len(self.state["no"]),
                    "con_error": len(self.state["err"]), "pedidos": len(self.urgent), "de_la_precarga": len(self.soon),
                    "kb": sum(x.get("kb", 0) for x in self.state["ok"].values()),
                    "pausado_hasta": int(self.state["paused_until"]) or None}

    # ---------- qué toca ----------

    def _dead(self, vid):
        return self.state["err"].get(vid, {}).get("n", 0) >= MAX_ERRORS

    def _waiting(self, vid):
        e = self.state["err"].get(vid)
        return bool(e) and time.time() - e["t"] < RETRY

    def _todo(self, vid):
        return vid not in self.state["ok"] and vid not in self.state["no"] and not self._dead(vid)

    def _next(self, background):
        """(id, de dónde) de la siguiente, o (None, None)."""
        now = time.time()
        for vid, asked in list(self.urgent.items()):
            if not self._todo(vid):
                self.urgent.pop(vid)
            elif self.lib.peek("yt-" + vid):
                return vid, "urgent"
            elif now - asked > WAIT_SAVED:   # no se llegó a guardar: no se hace
                self.urgent.pop(vid)
        for vid in list(self.soon):
            if not self._todo(vid) or not self.lib.peek("yt-" + vid):
                self.soon.pop(vid)
            elif not self._waiting(vid):
                return vid, "soon"
        if not background:
            return None, None
        with self.lib.lock:
            items = [(k[3:], e.get("plays", 0), e.get("used", 0)) for k, e in self.lib.index.items() if k.startswith("yt-")]
        items = [x for x in items if self._todo(x[0]) and not self._waiting(x[0])]
        if not items:
            return None, None
        return max(items, key=lambda x: (x[1], x[2]))[0], "fondo"

    # ---------- hacer uno ----------

    def _one(self, vid):
        """Hace el Canvas de una canción y lo apunta (en "ok" o en "no"). Las excepciones las trata _run."""
        e = self.lib.peek("yt-" + vid) or {}
        title, artist = e.get("title") or "", e.get("artist") or self.lib.artist_name(e)
        own = "ytimg.com" in (e.get("thumb") or "") and not NOT_OWN.search(title)
        why = "sin videoclip en YouTube"
        if own and self._cut(vid, e.get("duration"), vid):
            return self._done(vid, vid)
        if own:
            why = "su vídeo es una imagen fija y no hay otro videoclip"
        src = self._search(e, title, artist)
        if src and src[0] != vid:
            if self._cut(src[0], src[1], vid):
                return self._done(vid, src[0])
            why = "el videoclip que encontré casi no se mueve"
        with self.lock:
            self.state["no"][vid] = {"why": why, "t": int(time.time())}
            self.state["err"].pop(vid, None)
            self._save()
        log.info("canvas: %s, sin canvas (%s)", title, why)

    def _done(self, vid, src):
        with self.lock:
            self.state["ok"][vid] = {"src": src, "kb": os.path.getsize(os.path.join(DIR, vid + ".mp4")) // 1024,
                                     "t": int(time.time())}
            self.state["err"].pop(vid, None)
            self._save()
        log.info("canvas: listo %s (de %s)", vid, src)

    def _search(self, e, title, artist):
        """El videoclip de la canción en YouTube Music: (id, duración) o None. 1 petición."""
        name = titulos.nice(title, artist, tuple(e.get("credits") or ()), e.get("channel") or "")
        query = f"{artist} {name}".strip()
        res = self.ytm(lambda y: y.search(query, filter="videos", limit=8)) or []
        mine = {a for x in (artist, *(e.get("credits") or ())) for a in titulos.names(x)}
        want_n, dur = titulos.norm(name), e.get("duration")
        best = None   # (nota, id, duración): mejor el canal del artista u "Official Video" que la subida de un fan
        for i, r in enumerate(res):
            if not r.get("videoId"):
                continue
            rt = r.get("title") or ""
            names = [a.get("name") or "" for a in r.get("artists") or []]
            if NOT_CLIP.search(rt) and not NOT_CLIP.search(title):
                continue
            by_artist = any(titulos.is_artist(n, mine) for n in names)
            if not (by_artist or any(a in titulos.norm(rt) for a in mine)):
                continue
            got_n = titulos.norm(titulos.nice(rt, ", ".join(names)))
            if not (want_n and got_n and (want_n in got_n or got_n in want_n or
                                          difflib.SequenceMatcher(None, want_n, got_n).ratio() >= .75)):
                continue
            rd = r.get("duration_seconds")
            if dur and rd and not (0.75 * dur <= rd <= 1.6 * dur + 20):   # los videoclips traen intro y final
                continue
            score = (by_artist + bool(OFFICIAL.search(rt + " " + " ".join(names))), -i)
            if not best or score > best[0]:
                best = (score, r["videoId"], rd or dur)
        return best and best[1:]

    def _cut(self, src, duration, vid):
        """Baja SECS s del vídeo src (hacia el 35 %, donde suele ir el estribillo), lo deja vertical, sin franjas
        negras ni sonido, y lo guarda como el Canvas de vid. False si es una imagen fija."""
        os.makedirs(TMP, exist_ok=True)
        d = duration or 200
        start = max(5, min(d * 0.35, d - SECS - 5))
        raw = self.fetch(src, start, SECS, f"{TMP}/{src}")
        out = f"{TMP}/{vid}.out.mp4"
        try:
            probe = subprocess.run(["ffmpeg", "-hide_banner", "-i", raw, "-t", str(SECS), "-vf", "cropdetect=24:2:0",
                                    "-f", "null", "-"], capture_output=True, text=True, timeout=120).stderr
            crops = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", probe)
            size = re.search(r"Video:.*?, (\d{2,5})x(\d{2,5})", probe)
            if crops:
                w, h, x, y = map(int, crops[-1])
            elif size:
                w, h, x, y = int(size.group(1)), int(size.group(2)), 0, 0
            else:
                raise RuntimeError("el trozo de vídeo no se pudo leer")
            cw = min(w, h * 9 // 16) // 2 * 2
            ch = min(h, cw * 16 // 9) // 2 * 2
            vf = (f"crop={cw}:{ch}:{x + (w - cw) // 2}:{y + (h - ch) // 2},scale={SIZE[0]}:{SIZE[1]}:flags=lanczos,"
                  "fps=30,format=yuv420p")
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", raw, "-t", str(SECS), "-vf", vf,
                            "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "27", "-profile:v", "main",
                            "-movflags", "+faststart", out], check=True, timeout=300)
            fr = subprocess.run(["ffmpeg", "-hide_banner", "-i", out, "-vf", "freezedetect=n=0.003:d=1", "-f", "null",
                                 "-"], capture_output=True, text=True, timeout=120).stderr
            starts = [float(s) for s in re.findall(r"freeze_start: ([\d.]+)", fr)]
            frozen = sum(float(s) for s in re.findall(r"freeze_duration: ([\d.]+)", fr))
            if len(starts) > len(re.findall(r"freeze_end:", fr)):   # quieto hasta el final: ffmpeg no da la duración
                frozen += SECS - starts[-1]
            if frozen > FROZEN * SECS:
                log.info("canvas: %s está quieto (%.1f de %d s)", src, frozen, SECS)
                return False
            os.replace(out, os.path.join(DIR, vid + ".mp4"))
            return True
        finally:
            for p in (raw, out):
                try:
                    os.remove(p)
                except OSError:
                    pass

    # ---------- de fondo ----------

    def _clean(self):
        """Fuera los Canvas de canciones que ya no están guardadas (el tope de espacio las borró)."""
        with self.lock:
            gone = [v for v in self.state["ok"] if not self.lib.peek("yt-" + v)]
            for v in gone:
                self.state["ok"].pop(v)
                try:
                    os.remove(os.path.join(DIR, v + ".mp4"))
                except OSError:
                    pass
            if gone:
                self._save()
                log.info("canvas: %d borrados (sus canciones ya no están)", len(gone))

    def _run(self):
        time.sleep(30)
        cleaned = 0
        while True:
            vid = None
            try:
                now = time.time()
                if now - cleaned > 24 * 3600:
                    self._clean()
                    cleaned = now
                if self.blocked():
                    with self.lock:
                        self.state["paused_until"] = max(self.state["paused_until"], now + BLOCK_PAUSE)
                        self._save()
                if now < self.state["paused_until"]:
                    time.sleep(300)
                    continue
                night = NIGHT_UTC[0] <= time.gmtime().tm_hour < NIGHT_UTC[1]
                with self.lock:
                    vid, kind = self._next(night or self.user_idle(IDLE))
                if not vid:
                    time.sleep(5)
                    continue
                self._one(vid)
                with self.lock:
                    self.urgent.pop(vid, None)
                    self.soon.pop(vid, None)
                if kind == "fondo":
                    time.sleep(random.uniform(*GAP) * (1 if night else DAY_SLOWER))
            except Exception as ex:
                code = getattr(ex, "status_code", 0)
                log.info("canvas: %s %s", vid, ex)
                with self.lock:
                    if code == 503:     # YouTube nos bloqueó: quieto un día
                        self.state["paused_until"] = time.time() + BLOCK_PAUSE
                    elif NETWORK.search(str(ex)):   # se cortó la red: la canción no tiene la culpa
                        self.state["paused_until"] = time.time() + NET_PAUSE
                    elif code != 429:   # 429 = toca esperar el turno: se reintenta sin contarlo
                        er = self.state["err"].setdefault(vid, {"n": 0})
                        er.update(n=er["n"] + 1, t=int(time.time()), why=str(ex)[:150])
                        self.urgent.pop(vid, None)
                        self.soon.pop(vid, None)
                    self._save()
                time.sleep(60)
