"""Cambiar en favoritas y playlists las versiones de vídeo ("Official Music Video", "Video Oficial", "(Letra)"…) por la
canción del disco, que no trae intros, escenas habladas ni finales distintos.

Por cada una: si la versión de disco ya está guardada (la precarga baja álbumes), se cambia sin tocar YouTube; si
no, se busca en YouTube Music como canción (la pista del disco, no el vídeo) y se baja, despacio y a ritmo de
persona como la precarga. Al cambiarla se conserva su fecha en Me gusta y su sitio en las playlists. Los directos
no se tocan (son otra grabación). Se apunta cada cambio en /data/versiones.json para poder deshacerlo.

Se pide por cuenta: POST /interno/versiones {"email": …} (o {"email": …, "deshacer": true}); cómo va: GET
/interno/versiones. Ver README.md, "Versiones de disco".
"""
import json
import logging
import os
import random
import re
import threading
import time

log = logging.getLogger("musicapp.versiones")

FILE = "/data/versiones.json"
NIGHT_UTC = (4, 12)                     # 01:00-09:00 en Chile, como la precarga
GAP = (60, 200)                         # entre canciones que hay que buscar y bajar (segundos, al azar)
DAY_SLOWER = 1.5
IDLE = 600                              # de día, solo si nadie usó YouTube en estos segundos
BLOCK_PAUSE = 24 * 3600

VIDEO = re.compile(r"official\s*(music\s*)?video|video\s*oficial|v[ií]deo\s*clip|videoclip|\(video\)|\[video\]|"
                   r"lyric\s*video|v[ií]deo\s*lyric|con\s*letra|\(letra\)|\[letra\]|official\s*visuali[sz]er|\bmv\b|"
                   r"\(clip\)", re.I)
LIVE = re.compile(r"en\s*vivo|ao\s*vivo|\blive\b|en\s*directo|unplugged", re.I)
OTHER = re.compile(r"\b(remix|rmx|acoustic|ac[uú]stic[oa]|live|en vivo|version|versi[oó]n|edit|mix|cover|"
                   r"karaoke|instrumental|sped up|slowed|demo)\b", re.I)   # otra canción si solo la tiene una
TAGS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]|\s+(?:ft\.?|feat\.?|featuring)\s.*$|\s*\|.*$|"
                  r"\s+(?:official|video oficial|videoclip|lyric).*$", re.I)


class Versiones:
    def __init__(self, lib, ytm, download, ud, blocked, user_idle):
        self.lib, self.ytm, self.download, self.ud = lib, ytm, download, ud
        self.blocked, self.user_idle = blocked, user_idle
        self.lock = threading.Lock()
        try:
            with open(FILE) as f:
                self.state = json.load(f)
        except (OSError, ValueError):
            self.state = {"jobs": {}, "paused_until": 0}
        threading.Thread(target=self._run, daemon=True, name="versiones").start()

    def _save(self):
        tmp = FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f, ensure_ascii=False)
        os.replace(tmp, FILE)

    # ---------- qué es igual a qué ----------

    def _clean(self, title, artist_n):
        """Título sin "Artista - ", etiquetas, "ft." ni "(Official Video)": 'soy yo'."""
        t = title or ""
        if self.lib.DASH.search(t):
            a, b = self.lib.DASH.split(t, 1)
            na = self.lib._norm(a)
            if artist_n and (na == artist_n or artist_n in na or na in artist_n):
                t = b
        return self.lib._norm(TAGS.sub("", t))

    def _same(self, orig, title, artists_n, duration, artist_n):
        """¿Es la misma canción (de disco) que la favorita 'orig' en versión vídeo?"""
        if not artist_n or not any(a == artist_n or artist_n in a or a in artist_n for a in artists_n):
            return False
        if self._clean(title, artist_n) != self._clean(orig["title"], artist_n) or VIDEO.search(title or ""):
            return False
        if bool(OTHER.search(title or "")) != bool(OTHER.search(orig["title"] or "")):
            return False   # remix, acústica, directo… solo en una de las dos
        d0 = orig.get("duration")
        return not (d0 and duration and not 0.45 * d0 <= duration <= d0 + 15)   # el vídeo suele durar más (intro)

    def candidates(self, sub):
        """Favoritas y canciones de playlists en versión vídeo (sin directos): [ficha con id]."""
        seen, out = set(), []
        songs = list(self.ud.favorites(sub)) + [s for p in self.ud.playlists(sub) for s in p["songs"]]
        for s in songs:
            t = s.get("title") or ""
            if s["id"] not in seen and VIDEO.search(t) and not LIVE.search(t):
                seen.add(s["id"])
                out.append(s)
        return out

    def _local(self, orig, artist_n):
        """La versión de disco si ya está guardada: (clave, ficha) o None."""
        found = self.lib.artist(self.lib._by_artist().get(artist_n, (None,))[0] or "") if artist_n else None
        if not found:
            return None
        pairs = list(found["loose"])
        for al in found["albums"]:
            pairs += (self.lib.album(found["name"], al["name"]) or {}).get("songs", [])
        hits = [(k, e) for k, e in pairs if k.startswith("yt-") and k != "yt-" + orig["id"]
                and self._same(orig, e.get("track") or e.get("title"), [artist_n], e.get("duration"), artist_n)]
        return max(hits, key=lambda h: (bool(h[1].get("track_no")), bool(h[1].get("album")))) if hits else None

    def _artist_of(self, orig):
        groups = self.lib._by_artist()
        key = "yt-" + orig["id"]
        for n, (_, items) in groups.items():
            if any(k == key for k, _ in items):
                return n
        a = self.lib.artist_name(orig)   # ya no está guardada: por su ficha
        n = self.lib._norm(self.lib.JOINT.split(a, 1)[0]) if a else ""
        return n if n in groups else None

    # ---------- el trabajo ----------

    def start(self, sub, email):
        with self.lock:
            job = self.state["jobs"].setdefault(sub, {"email": email, "done": [], "skip": []})
            done = {d["old"] for d in job["done"]} | {d["old"] for d in job["skip"]}
            job["pend"] = [s["id"] for s in self.candidates(sub) if s["id"] not in done]
            job["started"] = int(time.time())
            self._save()
            return len(job["pend"])

    def undo(self, sub):
        """Vuelve a poner las versiones de antes (las de vídeo) donde se cambiaron."""
        with self.lock:
            job = self.state["jobs"].get(sub)
            if not job:
                return 0
            n = 0
            for d in reversed(job["done"]):
                old = self.lib.peek("yt-" + d["old"]) or {}
                self.ud.replace_song(sub, d["new"], d["old"], {**d.get("old_info", {}), **{k: old.get(k) for k in
                                     ("title", "artist", "album", "duration", "thumb") if old.get(k)}})
                n += 1
            job["done"], job["pend"] = [], []
            self._save()
            return n

    def status(self):
        with self.lock:
            return {"paused_until": self.state.get("paused_until", 0),
                    "jobs": {j.get("email", s): {"pendientes": len(j.get("pend", [])), "cambiadas": len(j["done"]),
                                                 "sin_version": len(j["skip"]),
                                                 "ultimas": j["done"][-5:], "saltadas": j["skip"][-5:]}
                             for s, j in self.state["jobs"].items()}}

    def _next(self):
        for sub, job in self.state["jobs"].items():
            if job.get("pend"):
                return sub, job
        return None, None

    def _one(self, sub, job):
        """Una canción: devuelve cuánto esperar (0 si no hizo falta YouTube)."""
        vid = job["pend"][0]
        orig = next((s for s in self.ud.favorites(sub) + [x for p in self.ud.playlists(sub) for x in p["songs"]]
                     if s["id"] == vid), None)
        if not orig:   # ya no la tiene
            job["pend"].pop(0)
            return 0
        artist_n = self._artist_of(orig)
        info = {k: orig.get(k) for k in ("title", "artist", "album", "duration", "thumb")}
        hit = self._local(orig, artist_n)
        waited = 0
        if hit:
            new_key, e = hit
            how = "guardada"
        else:
            name = self.lib._by_artist().get(artist_n, (orig.get("artist") or "",))[0] if artist_n else orig.get("artist") or ""
            query = f"{name} {self._clean(orig['title'], artist_n)}".strip()
            res = self.ytm(lambda y: y.search(query, filter="songs", limit=8)) or []
            waited = 1
            pick = next((r for r in res if r.get("videoId") and self._same(
                orig, r.get("title"), [self.lib._norm(a.get("name")) for a in r.get("artists") or []],
                r.get("duration_seconds"), artist_n)), None)
            if not pick:
                job["pend"].pop(0)
                job["skip"].append({"old": vid, "title": orig["title"], "why": f"sin versión de disco en YouTube Music ({query})"})
                log.info("versiones: sin versión de disco para %s", orig["title"])
                return waited
            new_key = "yt-" + pick["videoId"]
            if not self.lib.peek(new_key):
                _, path = self.download(f"https://www.youtube.com/watch?v={pick['videoId']}")
                if not path:
                    raise RuntimeError("no se pudo bajar")
            thumbs = pick.get("thumbnails") or []
            album = (pick.get("album") or {}).get("name")
            self.lib.fill(new_key, {"album": album, "artist": ", ".join(a["name"] for a in pick.get("artists") or [])},
                          "versiones")
            self.lib.set_fields(new_key, {"title": pick.get("title"), "thumb": thumbs[-1]["url"] if thumbs else None})
            e = self.lib.peek(new_key) or {}
            how = "youtube"
        new_info = {k: e.get(k) for k in ("title", "artist", "album", "duration", "thumb")}
        self.ud.replace_song(sub, vid, new_key[3:], new_info)
        job["pend"].pop(0)
        job["done"].append({"old": vid, "new": new_key[3:], "title": orig["title"], "now": new_info.get("title"),
                            "how": how, "old_info": info})
        log.info("versiones: %s -> %s (%s)", orig["title"], new_info.get("title"), how)
        return waited

    def _run(self):
        time.sleep(30)
        while True:
            try:
                now = time.time()
                if self.blocked():
                    with self.lock:
                        self.state["paused_until"] = now + BLOCK_PAUSE
                        self._save()
                if now < self.state.get("paused_until", 0):
                    time.sleep(600)
                    continue
                with self.lock:
                    sub, job = self._next()
                if not job:
                    time.sleep(60)
                    continue
                night = NIGHT_UTC[0] <= time.gmtime().tm_hour < NIGHT_UTC[1]
                if not night and not self.user_idle(IDLE):
                    time.sleep(60)
                    continue
                with self.lock:
                    used_yt = self._one(sub, job)
                    self._save()
                if used_yt:
                    time.sleep(random.uniform(*GAP) * (1 if night else DAY_SLOWER))
            except Exception as ex:
                log.info("versiones: %s", ex)
                with self.lock:
                    if getattr(ex, "status_code", 0) == 503:   # YouTube nos bloqueó: 24 h quieto
                        self.state["paused_until"] = time.time() + BLOCK_PAUSE
                    else:                                      # otra cosa: esa canción se salta, no se reintenta
                        sub, job = self._next()
                        if job:
                            vid = job["pend"].pop(0)
                            job["skip"].append({"old": vid, "why": f"error: {str(ex)[:120]}"})
                    self._save()
                time.sleep(300)
