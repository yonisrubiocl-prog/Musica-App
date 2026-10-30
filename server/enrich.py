"""Completa de fondo la ficha de las canciones guardadas: género (de todas) y artista/álbum/año (de las viejas,
guardadas antes de que se apuntaran fichas). Nunca cambia el título ni pisa un dato que ya esté.

1. iTunes (Apple), sin tocar YouTube: busca "artista canción" en la tienda de Chile (géneros en español) y, si no
   está, en la de EE. UU. Solo acepta el resultado si artista y título coinciden de verdad (iTunes a veces
   devuelve otra canción); sin artista conocido no se intenta. Una cada ITUNES_GAP s.
2. Las que sigan sin artista: YouTube Music (1 petición por canción, por el mismo ritmo que lo demás de
   YouTube), solo de madrugada y despacio (YTM_GAP).
3. Género por artista: a las que iTunes no conoce se les pone el género más común de su artista.

Lo que se apunta en la ficha: genre, y artist/album/year si faltaban; 'enriched' = qué pasos ya se intentaron
(para no repetirlos). Ver README.md, "Género y fichas".
"""
import collections
import datetime
import logging
import re
import threading
import time

import requests

log = logging.getLogger("musicapp.enrich")

ITUNES = "https://itunes.apple.com/search"
ITUNES_GAP = 4                          # segundos entre consultas a iTunes (permite ~20 por minuto)
YTM_GAP = 120                           # segundos entre consultas a YouTube Music para las que iTunes no conoce
NIGHT_UTC = (6, 11)                     # de madrugada en Chile (03:00-08:00): cuando YouTube Music se usa
NOISE = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]|\s+(?:ft\.?|feat\.?|featuring)\s.*$", re.I)


def clean(title):
    """'Hope (Official Video) [4K] ft. X' -> 'Hope'."""
    return NOISE.sub("", title or "").strip(" -–|")


class Enricher:
    def __init__(self, lib, ytm, yt_busy):
        self.lib, self.ytm, self.yt_busy = lib, ytm, yt_busy   # yt_busy(): peticiones a YouTube en la última hora
        self.done = collections.Counter()
        threading.Thread(target=self._run, daemon=True).start()

    # ---------- qué hace falta ----------

    def _pending(self, step):
        with self.lib.lock:
            items = list(self.lib.index.items())
        out = []
        for k, e in items:
            tried = e.get("enriched") or []
            if step in tried:
                continue
            if step == "itunes" and (not e.get("genre") or not e.get("artist")):
                out.append((k, e))
            elif step == "ytm" and k.startswith("yt-") and not e.get("artist"):
                out.append((k, e))
        return out

    def _mark(self, key, step, fields):
        self.lib.fill(key, fields, step)

    # ---------- 1. iTunes ----------

    def _query(self, e):
        """(artista, canción) a buscar: los de la ficha o, si no hay artista, 'Artista - Canción' del título."""
        artist, song = (e.get("artist") or "").strip(), clean(e.get("track") or e.get("title"))
        if not artist and " - " in (e.get("title") or ""):
            artist, song = e["title"].split(" - ", 1)
            artist, song = artist.strip(), clean(song)
        return artist, song

    def _same(self, a, b):
        a, b = self.lib._norm(a), self.lib._norm(b)
        return bool(a and b) and (a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a))))

    def _itunes(self, e):
        """El resultado de iTunes de esta canción, o None. Sin artista no se intenta: no habría cómo comprobar
        que es la misma (eso queda para YouTube Music, que va por el vídeo exacto). Con título 'A - B' se prueba
        también al revés ('Beat It - Michael Jackson')."""
        artist, song = self._query(e)
        if not song or not artist:
            return None
        x = self._itunes_try(artist, song)
        if x is None and not e.get("artist") and " - " in (e.get("title") or ""):
            x = self._itunes_try(clean(song), artist)
        return x

    def _itunes_try(self, artist, song):
        for country in ("CL", "US"):
            try:
                r = requests.get(ITUNES, params={"term": f"{artist} {song}".strip(), "entity": "song", "limit": 10,
                                                 "country": country}, timeout=10)
                results = (r.json().get("results") or []) if r.ok else []
            except (requests.RequestException, ValueError) as ex:
                log.info("iTunes no responde: %s", ex)
                return "error"
            time.sleep(ITUNES_GAP)
            for x in results:
                if not self._same(clean(x.get("trackName")), song):
                    continue
                names = [n.strip() for n in re.split(r",|&| y | and | x ", x.get("artistName") or "")]
                if not any(self._same(n, artist) or self._same(artist, n) for n in names) \
                        and not self._same(x.get("artistName"), artist):
                    continue
                return x
        return None

    def _itunes_step(self):
        for k, e in self._pending("itunes"):
            x = self._itunes(e)
            if x == "error":
                return False   # sin conexión con iTunes: se reintenta en la siguiente vuelta
            fields = {}
            if x:
                fields = {"genre": x.get("primaryGenreName") or "", "artist": x.get("artistName"),
                          "album": x.get("collectionName"), "year": int(x["releaseDate"][:4]) if x.get("releaseDate") else None}
                self.done["itunes"] += 1
            self._mark(k, "itunes", fields)
        return True

    # ---------- 2. YouTube Music (de madrugada) ----------

    def _night(self):
        h = datetime.datetime.now(datetime.timezone.utc).hour
        return NIGHT_UTC[0] <= h < NIGHT_UTC[1]

    def _ytm_step(self):
        for k, e in self._pending("ytm"):
            if not self._night() or self.yt_busy() > 60:   # de día, o si YouTube ya va cargado, se espera
                return
            try:
                t = (self.ytm(lambda y: y.get_watch_playlist(videoId=k[3:], limit=1)).get("tracks") or [{}])[0]
            except Exception as ex:
                log.info("YouTube Music, ficha de %s: %s", k, ex)
                if "503" in str(ex) or "bloque" in str(ex):
                    return
                t = {}
            artists = ", ".join(a["name"] for a in t.get("artists") or [] if a.get("name"))
            fields = {"artist": artists, "album": (t.get("album") or {}).get("name"), "year": t.get("year")} if artists else {}
            if artists:
                self.done["ytm"] += 1
            self._mark(k, "ytm", fields)
            time.sleep(YTM_GAP)

    # ---------- 3. género por artista ----------

    def _artist_genres(self):
        with self.lib.lock:
            items = list(self.lib.index.items())
        by = collections.defaultdict(collections.Counter)
        for k, e in items:
            if e.get("genre") and e.get("genre_src") != "artista":
                by[self.lib._norm(self.lib.artist_name(e))][e["genre"]] += 1
        n = 0
        for k, e in items:
            if not e.get("genre") and "itunes" in (e.get("enriched") or []):
                g = by.get(self.lib._norm(self.lib.artist_name(e)))
                if g:
                    self.lib.fill(k, {"genre": g.most_common(1)[0][0], "genre_src": "artista"})
                    n += 1
        if n:
            log.info("género por artista: %d canciones", n)

    def _run(self):
        time.sleep(30)   # que arranque todo antes
        while True:
            try:
                before = dict(self.done)
                ok = self._itunes_step()
                self._artist_genres()
                self._ytm_step()
                if dict(self.done) != before:
                    log.info("fichas completadas hasta ahora: %s", dict(self.done))
                time.sleep(300 if ok else 900)
            except Exception:
                log.exception("completando fichas")
                time.sleep(900)
