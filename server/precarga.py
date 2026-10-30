"""Precarga: baja poco a poco los álbumes de estudio de los artistas que más se escuchan (los que tienen
MIN_SONGS canciones o más guardadas), para que estén en el servidor antes de que alguien los pida.

Va muy despacio para no llamar la atención de YouTube (el bloqueo del 25-10-2026 fue por una importación de golpe):
de madrugada una operación cada NIGHT_GAP s; de día una cada DAY_GAP s y solo si nadie ha usado YouTube en los
últimos IDLE s. Si YouTube da cualquier aviso de bloqueo, se para BLOCK_PAUSE. Todo pasa además por el ritmo
general (yt_turn). Se salta: directos, instrumentales, karaokes, recopilatorios y ediciones repetidas (por el
título del álbum), y las canciones que ya están guardadas, también si es otra versión del mismo artista y título.

Estado (lo hecho, la cola y las cuentas) en /data/precarga.json: sobrevive a los reinicios. Ver README.md,
"Precarga de álbumes".
"""
import datetime
import json
import logging
import os
import re
import threading
import time

log = logging.getLogger("musicapp.precarga")

FILE = "/data/precarga.json"
MIN_SONGS = 5                           # artistas con al menos tantas canciones guardadas
NIGHT_UTC = (6, 11)                     # 03:00-08:00 en Chile
NIGHT_GAP = 90                          # segundos entre operaciones de madrugada
DAY_GAP = 240                           # de día
IDLE = 600                              # de día, solo si nadie usó YouTube en estos segundos
BLOCK_PAUSE = 24 * 3600                 # tras un aviso de bloqueo
SKIP_ALBUM = re.compile(r"\b(live|en vivo|ao vivo|en directo|unplugged|instrumental|karaoke|greatest hits|grandes "
                        r"[eé]xitos|[eé]xitos|best of|the best|essential|collection|colecci[oó]n|antolog|remaster|"
                        r"anniversary|aniversario|deluxe|expanded|edition|edici[oó]n|mixtape|sessions?|acoustic|"
                        r"ac[uú]stico|remixes|cercle|tribute|tributo)\b", re.I)
NOISE = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]|\s+(?:ft\.?|feat\.?|featuring)\s.*$|\s+-\s+.*$", re.I)


class Precarga:
    def __init__(self, lib, ytm, download, blocked, user_idle):
        self.lib, self.ytm, self.download = lib, ytm, download
        self.blocked, self.user_idle = blocked, user_idle   # blocked(): ¿YouTube nos tiene bloqueados?
        self.lock = threading.Lock()
        try:
            with open(FILE) as f:
                self.state = json.load(f)
        except (OSError, ValueError):
            self.state = {}
        for k, v in (("artists", {}), ("queue", []), ("done", 0), ("skipped", 0), ("failed", 0), ("paused_until", 0)):
            self.state.setdefault(k, v)
        threading.Thread(target=self._run, daemon=True, name="precarga").start()

    def _save(self):
        with self.lock:
            tmp = FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.state, f, ensure_ascii=False)
            os.replace(tmp, FILE)

    def status(self):
        s = self.state
        return {"artists_done": sum(1 for a in s["artists"].values() if a.get("done")),
                "artists_total": len(self._artists()), "queue": len(s["queue"]), "done": s["done"],
                "skipped": s["skipped"], "failed": s["failed"], "paused_until": s["paused_until"]}

    # ---------- qué bajar ----------

    def _artists(self):
        return [a["name"] for a in self.lib.artists() if a["songs"] >= MIN_SONGS]

    def _have(self, artist, title):
        """¿Ya hay una canción de este artista con este título (cualquier versión)?"""
        n_title = self.lib._norm(NOISE.sub("", title or ""))
        a = self.lib.artist(artist)
        if not a or not n_title:
            return False
        songs = [e for _, e in a["loose"]]
        for al in a["albums"]:
            found = self.lib.album(artist, al["name"])
            songs += [e for _, e in (found or {}).get("songs", [])]
        return any(self.lib._norm(NOISE.sub("", e.get("track") or e.get("title") or "")) == n_title for e in songs)

    def _plan_artist(self, name):
        """Busca al artista en YouTube Music y apunta sus álbumes de estudio (sin abrirlos todavía)."""
        found = self.ytm(lambda y: y.search(name, filter="artists", limit=5))
        match = next((x for x in found if self.lib._norm(x.get("artist")) == self.lib._norm(name)), None)
        if not match:
            log.info("precarga: no encuentro a %s en YouTube Music", name)
            return {"done": True, "albums": []}
        art = self.ytm(lambda y: y.get_artist(match["browseId"]))
        al = art.get("albums") or {}
        lst = al.get("results") or []
        if al.get("browseId") and al.get("params"):
            lst = self.ytm(lambda y: y.get_artist_albums(al["browseId"], al["params"])) or lst
        seen, albums = set(), []
        for a in lst:
            t = a.get("title") or ""
            base = self.lib._norm(NOISE.sub("", t))
            if not a.get("browseId") or SKIP_ALBUM.search(t) or base in seen:
                continue
            seen.add(base)
            albums.append({"id": a["browseId"], "title": t, "year": a.get("year")})
        log.info("precarga: %s, %d álbumes de estudio", name, len(albums))
        return {"done": False, "albums": albums}

    def _plan_album(self, artist, album):
        """Abre un álbum y pone en la cola sus canciones que no estén ya."""
        a = self.ytm(lambda y: y.get_album(album["id"]))
        added = 0
        for t in a.get("tracks") or []:
            vid = t.get("videoId")
            if not vid or self.lib.peek(f"yt-{vid}") or self._have(artist, t.get("title")):
                self.state["skipped"] += 1
                continue
            self.state["queue"].append({"id": vid, "title": t.get("title"), "artist": artist, "album": a.get("title"),
                                        "year": int(a["year"]) if str(a.get("year") or "").isdigit() else None,
                                        "track": t.get("trackNumber")})
            added += 1
        return added

    # ---------- una operación cada vez ----------

    def _step(self):
        """Hace UNA cosa (abrir un artista, abrir un álbum o bajar una canción). False si no queda nada."""
        s = self.state
        if s["queue"]:
            item = s["queue"].pop(0)
            if self.lib.peek(f"yt-{item['id']}"):
                s["skipped"] += 1
            else:
                try:
                    _, path = self.download(f"https://www.youtube.com/watch?v={item['id']}")
                    if path:
                        self.lib.fill(f"yt-{item['id']}", {"album": item["album"], "year": item["year"],
                                                           "track_no": item["track"], "artist": item["artist"]}, "precarga")
                        s["done"] += 1
                except Exception as ex:
                    if getattr(ex, "status_code", 0) in (503, 429):
                        s["queue"].insert(0, item)
                        raise
                    s["failed"] += 1
                    log.info("precarga: no pude bajar %s: %s", item["title"], ex)
            return True
        for name in self._artists():
            a = s["artists"].get(name)
            if a is None:
                s["artists"][name] = self._plan_artist(name)
                return True
            if not a.get("done"):
                pend = [al for al in a["albums"] if not al.get("opened")]
                if not pend:
                    a["done"] = True
                    continue
                pend[0]["opened"] = True
                self._plan_album(name, pend[0])
                return True
        return False

    def _night(self):
        return NIGHT_UTC[0] <= datetime.datetime.now(datetime.timezone.utc).hour < NIGHT_UTC[1]

    def _run(self):
        time.sleep(120)
        n = 0
        while True:
            try:
                now = time.time()
                if self.blocked():
                    self.state["paused_until"] = now + BLOCK_PAUSE
                    self._save()
                    log.warning("precarga: YouTube avisó de bloqueo; paro 24 h")
                if now < self.state["paused_until"]:
                    time.sleep(600)
                    continue
                night = self._night()
                if not night and not self.user_idle(IDLE):
                    time.sleep(60)
                    continue
                more = self._step()
                self._save()
                n += 1
                if n % 25 == 0:
                    log.info("precarga: %s", self.status())
                time.sleep((NIGHT_GAP if night else DAY_GAP) if more else 3600)
            except Exception as ex:
                code = getattr(ex, "status_code", 0)
                if code == 503:   # aviso de bloqueo de YouTube
                    self.state["paused_until"] = time.time() + BLOCK_PAUSE
                    log.warning("precarga: YouTube frenó (%s); paro 24 h", ex)
                elif code != 429:   # 429: nuestro propio ritmo dice que espere; se reintenta en 10 min
                    log.exception("precarga")
                self._save()
                time.sleep(600)
