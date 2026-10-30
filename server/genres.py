"""Género de cada artista (todas sus canciones tienen el mismo): una lista corta en español.

De dónde sale, por orden:
1. A mano (lo que se corrija con `python genres.py "Artista" "Género"`): manda siempre.
2. MusicBrainz (enciclopedia musical libre: conoce vallenato, bachata, salsa, corridos…), traducido a la lista.
3. iTunes, por mayoría entre las canciones del artista (enrich.py lo apunta como 'itunes_genre'), traducido.
4. Si nada sirve, sin género (mejor que uno falso).

Se guarda en /data/generos.json: artista normalizado -> {"name", "genre", "src": manual|musicbrainz|itunes|ninguno}.
Ver README.md, "Género y fichas".

Desde el servidor:
  docker exec musicapp-api python genres.py                      # lista: artista, género y de dónde salió
  docker exec musicapp-api python genres.py "Rawayana" "Pop latino"
  docker exec musicapp-api python genres.py "Rawayana" -         # quitar la corrección (vuelve a calcularse)
"""
import collections
import json
import logging
import os
import re
import sys
import threading
import time
import unicodedata

log = logging.getLogger("musicapp.genres")

FILE = "/data/generos.json"
MB = "https://musicbrainz.org/ws/2/artist/"
MB_HEADERS = {"User-Agent": "MusicApp/1.0 (https://musica.yoneapolis.com)"}
MB_GAP = 1.2                            # MusicBrainz pide como mucho 1 consulta por segundo

# Etiqueta (de MusicBrainz o iTunes, en minúsculas) -> género de la lista. Gana la primera regla que encaje con
# la etiqueta más votada; por eso las más concretas van antes ("latin rock" antes que "rock").
RULES = [
    (r"vallenato", "Vallenato"), (r"bachata", "Bachata"), (r"merengue", "Merengue"), (r"salsa", "Salsa"),
    (r"cumbia", "Cumbia"), (r"champeta", "Champeta"), (r"reggaet[oó]n|dembow|perreo", "Reguetón"),
    (r"corrido|regional mexican|mexicana|norteñ|banda|mariachi|ranchera|grupero", "Regional mexicano"),
    (r"latin trap|trap latino|trap", "Trap"), (r"urbano|latin urban|latin hip hop", "Urbano latino"),
    (r"latin rock|rock en espa|rock latino|alternativa y rock en espa", "Rock en español"),
    (r"bolero|balada|ballad", "Baladas"), (r"tropical", "Tropical"),
    (r"latin pop|pop latino|pop en espa", "Pop latino"),
    (r"metal|djent|metalcore", "Metal"), (r"punk", "Punk"),
    (r"hip hop|hip-hop|rap", "Rap"), (r"r&b|rnb|soul|funk", "R&B"),
    (r"reggae|ska|dancehall", "Reggae"),
    (r"electr|edm|house|techno|dance|dubstep|trance|drum and bass", "Electrónica"),
    (r"lo-?fi|chill", "Lo-Fi"), (r"jazz|blues", "Jazz y blues"), (r"classical|cl[aá]sica|soundtrack|banda sonora", "Clásica y bandas sonoras"),
    (r"alternative|indie|alternativ", "Alternativo"), (r"rock", "Rock"),
    (r"pop", "Pop"), (r"latin|latina", "Latino"),
]
LIST = list(dict.fromkeys(g for _, g in RULES))


def norm(text):
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", t))


def translate(tags):
    """[(etiqueta, votos)] -> género de la lista o None."""
    for tag, _ in sorted(tags, key=lambda t: -t[1]):
        for rx, genre in RULES:
            if re.search(rx, tag.lower()):
                return genre
    return None


class Genres:
    def __init__(self, lib=None):
        self.lib, self.lock = lib, threading.Lock()
        self.data, self.mtime = {}, None
        self.reload()
        if lib is not None:
            threading.Thread(target=self._run, daemon=True, name="enrich").start()

    def reload(self):
        try:
            m = os.path.getmtime(FILE)
            if m != self.mtime:
                with open(FILE) as f:
                    self.data, self.mtime = json.load(f), m
        except (OSError, ValueError):
            pass

    def save(self):
        with self.lock:
            with open(FILE + ".tmp", "w") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(FILE + ".tmp", FILE)
            self.mtime = os.path.getmtime(FILE)

    def stamp(self):
        self.reload()
        return self.mtime

    def of(self, artist):
        """Género del artista ('' si no hay)."""
        self.reload()
        return (self.data.get(norm(artist)) or {}).get("genre") or ""

    # ---------- de dónde sale ----------

    def _musicbrainz(self, name):
        import requests
        try:
            r = requests.get(MB, params={"query": name, "fmt": "json", "limit": 5}, headers=MB_HEADERS, timeout=15)
            time.sleep(MB_GAP)
            found = next((a for a in (r.json().get("artists") or []) if norm(a.get("name")) == norm(name)
                          or any(norm(x.get("name")) == norm(name) for x in a.get("aliases") or [])), None)
            if not found:
                return None
            d = requests.get(MB + found["id"], params={"inc": "genres tags", "fmt": "json"}, headers=MB_HEADERS,
                             timeout=15).json()
            time.sleep(MB_GAP)
        except Exception as e:
            log.info("MusicBrainz, %s: %s", name, e)
            return "error"
        tags = ([(x["name"], x.get("count", 0)) for x in d.get("genres") or []]
                or [(t["name"], t.get("count", 0)) for t in d.get("tags") or []])
        return translate(tags)

    def _itunes(self, songs):
        c = collections.Counter(e.get("itunes_genre") for e in songs if e.get("itunes_genre"))
        return translate([(g, n) for g, n in c.items()])

    def _run(self):
        time.sleep(60)
        while True:
            try:
                arts = self.lib._by_artist()
                todo = sorted(((n, a) for n, a in arts.items() if n not in self.data), key=lambda x: -len(x[1][1]))
                for n, (shown, songs) in todo:
                    g, src = self._musicbrainz(shown), "musicbrainz"
                    if g == "error":
                        break   # MusicBrainz no responde: se sigue en la próxima vuelta
                    if not g:
                        g, src = self._itunes([e for _, e in songs]), "itunes"
                    with self.lock:
                        self.reload()
                        if n not in self.data:   # por si se corrigió a mano mientras tanto
                            self.data[n] = {"name": shown, "genre": g or "", "src": src if g else "ninguno"}
                    self.save()
                time.sleep(1800)
            except Exception:
                log.exception("géneros")
                time.sleep(1800)


def _cli(args):
    g = Genres()
    if not args:
        for n, x in sorted(g.data.items(), key=lambda kv: (kv[1]["genre"] == "", kv[1]["genre"], kv[1]["name"].lower())):
            print(f"{x['genre'] or '—':24} {x['name'][:40]:40} ({x['src']})")
        print(f"{len(g.data)} artistas. Géneros posibles: {', '.join(LIST)}")
        return 0
    if len(args) != 2:
        print(__doc__)
        return 1
    name, genre = args
    if genre == "-":
        g.data.pop(norm(name), None)
        print(f"{name}: sin corrección (se volverá a calcular)")
    else:
        if genre not in LIST:
            print(f"Ojo: «{genre}» no está en la lista ({', '.join(LIST)}); se usa igual.")
        g.data[norm(name)] = {"name": name, "genre": genre, "src": "manual"}
        print(f"{name}: {genre}")
    g.save()
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
