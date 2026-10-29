"""La biblioteca única: una carpeta de canciones y un catálogo, que solo escribe la API.

Es la clase Cache del bot (~/MusicBot/bot.py) traída aquí, con la misma lógica de búsqueda (índice de palabras,
autocompletado, faltas de ortografía) y el mismo tope de espacio. El bot pasará a usarla por la red interna.
Ver README.md, sección "Canciones".
"""
import bisect
import difflib
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
import unicodedata

log = logging.getLogger("musicapp.library")

FLUSH = 30                      # segundos como mucho entre guardados del catálogo por lo que cambia al sonar
SONG_FILE = re.compile(r"(yt-[\w-]{11}|u-[0-9a-f]{16})\.\w+")   # nombre de una canción guardada
KEY = re.compile(r"yt-[\w-]{11}|u-[0-9a-f]{16}")
YT_ID = re.compile(r"(?:youtu\.be/|youtu.*?(?:[?&]v=|/shorts/|/live/))([\w-]{11})")

# Palabras que no ayudan a distinguir canciones (las mismas que usa el bot).
NOISE = {"official", "oficial", "video", "videoclip", "clip", "lyrics", "lyric", "letra", "audio", "hd", "hq",
         "4k", "remaster", "remastered", "visualizer", "music", "musical", "ft", "feat", "featuring",
         "the", "a", "an", "of", "de", "del", "la", "el", "los", "las", "en", "y", "con", "and", "n"}


def words(text):
    """'Neutro Shorty - Soy Yo [Official Video]' -> ['neutro', 'shorty', 'soy', 'yo'] (sin tildes ni relleno)."""
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return [w for w in re.findall(r"[a-z0-9]+", t) if w not in NOISE]


def key_of(url, info=None):
    """Mismo nombre para la misma canción (igual que el bot): id de YouTube, o un resumen del enlace."""
    if info is not None and info.get("extractor_key") == "Youtube" and info.get("id"):
        return "yt-" + info["id"]
    m = YT_ID.search(url)
    if m:
        return "yt-" + m.group(1)
    return "u-" + hashlib.sha1(url.encode()).hexdigest()[:16]


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


class Library:
    """Canciones en root (en el servidor: /var/lib/music) con su catálogo index_file. Con tope de tamaño: al
    pasarlo se borran las que hace más tiempo que nadie pide."""

    def __init__(self, root, max_bytes, index_file):
        self.root, self.max, self.file = root, max_bytes, index_file
        self.lock = threading.Lock()
        self.index = {}   # clave -> {file, url, title, duration, thumb, size, used, plays, by, artist, album…}
        self.wix, self.tw, self.vocab = {}, {}, []
        self.dirty = False   # cambios sin guardar (ver flush)
        self.index = self._load()
        files = {n for n in os.listdir(root) if SONG_FILE.fullmatch(n)}
        for n in os.listdir(root):   # restos de descargas o copias cortadas
            if n.endswith((".part", ".tmp")):
                os.remove(os.path.join(root, n))
        if self.index and not files:
            # Carpeta vacía con un catálogo lleno: casi seguro que /music no se montó. No se toca el catálogo.
            log.warning("biblioteca: %s está vacía pero el catálogo tiene %d canciones; no toco nada",
                        root, len(self.index))
        else:
            for k, e in list(self.index.items()):   # canciones cuyo archivo ya no está (o entradas rotas)
                if not isinstance(e, dict) or e.get("file") not in files:
                    del self.index[k]
            # Archivos que el catálogo no conoce: se vuelven a apuntar, nunca se borran. La ficha se completa
            # la primera vez que alguien la pida (ver /interno/ficha).
            known = {e["file"] for e in self.index.values()}
            lost = sorted(files - known)
            for n in lost:
                key, path = os.path.splitext(n)[0], os.path.join(root, n)
                self.index[key] = {"file": n, "title": None, "duration": None, "thumb": None, "plays": 0,
                                   "url": "https://www.youtube.com/watch?v=" + key[3:] if key.startswith("yt-") else None,
                                   "size": os.path.getsize(path), "used": os.path.getmtime(path)}
            if lost:
                log.warning("biblioteca: %d canciones no estaban en el catálogo; apuntadas de nuevo", len(lost))
        for k, e in self.index.items():
            e.setdefault("size", 0)
            e.setdefault("used", 0)
            self._index_add(k, self._text(e))
        self.save()
        n, size, _ = self.stats()
        log.info("biblioteca: %d canciones, %.2f GB", n, size / 1024 ** 3)
        threading.Thread(target=self._flusher, daemon=True).start()

    def _load(self):
        """El catálogo, o su copia de antes (.bak) si está roto. Uno roto se guarda como .roto para mirarlo."""
        for path in (self.file, self.file + ".bak"):
            try:
                with open(path) as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("no es un diccionario")
            except FileNotFoundError:
                continue
            except (OSError, ValueError) as ex:
                log.warning("biblioteca: no pude leer %s: %s", path, ex)
                if path == self.file:
                    shutil.copy(path, path + ".roto")
                continue
            if path != self.file:
                log.warning("biblioteca: uso la copia anterior del catálogo (%s)", path)
            return data
        return {}

    @staticmethod
    def _text(e):
        """Lo que se indexa de una canción: título, artista y álbum ('nf paralyzed' encuentra 'Paralyzed · NF')."""
        return f"{e.get('title') or ''} {e.get('artist') or ''} {e.get('album') or ''}"

    # ---------- índice de palabras (buscar por nombre sin recorrer todas las canciones) ----------
    # self.wix: palabra -> claves de las canciones que la tienen. Buscar varias palabras es cruzar esos
    # conjuntos (del más pequeño al más grande). self.vocab: las palabras ordenadas, para el autocompletado
    # por trozos ("neut" -> "neutro") con bisect. self.tw: clave -> sus palabras.

    def _index_add(self, key, title):
        self._index_del(key)
        ws = set(words(title))
        self.tw[key] = ws
        for w in ws:
            if w not in self.wix:
                self.wix[w] = set()
                bisect.insort(self.vocab, w)
            self.wix[w].add(key)

    def _index_del(self, key):
        for w in self.tw.pop(key, ()):
            s = self.wix.get(w)
            if s is not None:
                s.discard(key)
                if not s:
                    del self.wix[w]
                    i = bisect.bisect_left(self.vocab, w)
                    if i < len(self.vocab) and self.vocab[i] == w:
                        self.vocab.pop(i)

    def _with_prefix(self, prefix):
        """Claves de canciones con alguna palabra que empieza por 'prefix'."""
        out = set()
        i = bisect.bisect_left(self.vocab, prefix)
        while i < len(self.vocab) and self.vocab[i].startswith(prefix):
            out |= self.wix[self.vocab[i]]
            i += 1
        return out

    def _exists(self, k):
        return os.path.exists(os.path.join(self.root, self.index[k]["file"]))

    def _rank(self, keys, q):
        """Mejor primero: la que menos palabras tiene de más; luego la más puesta y la más reciente."""
        def score(k):
            e = self.index[k]
            return (len(q) / max(1, len(self.tw.get(k) or ())), e.get("plays", 0), e.get("used", 0))
        return sorted(keys, key=score, reverse=True)

    def match(self, query, fuzzy=False):
        """Canción guardada que contiene TODAS las palabras buscadas. fuzzy: acepta faltas en las palabras
        que no existan tal cual ('huawae' -> 'hawaii'). Devuelve ((clave, datos), cuántas más coinciden)."""
        q = set(words(query))
        if not q or not self.wix:
            return None
        with self.lock:
            sets = []
            for w in q:
                s = self.wix.get(w)
                if s is None and fuzzy:
                    close = difflib.get_close_matches(w, self.vocab, n=3, cutoff=0.75)
                    s = set().union(*(self.wix[c] for c in close)) if close else None
                if not s:
                    return None
                sets.append(s)
            sets.sort(key=len)
            cand = [k for k in set(sets[0]).intersection(*sets[1:]) if self._exists(k)]
            if not cand:
                return None
            best = self._rank(cand, q)
            return (best[0], dict(self.index[best[0]])), len(best) - 1

    def matches(self, query, limit=10):
        """Todas las guardadas con todas las palabras buscadas (mejor primero)."""
        q = set(words(query))
        if not q or not self.wix:
            return []
        with self.lock:
            sets = sorted((self.wix.get(w, set()) for w in q), key=len)
            cand = [k for k in set(sets[0]).intersection(*sets[1:]) if self._exists(k)]
            return [(k, dict(self.index[k])) for k in self._rank(cand, q)[:limit]]

    def suggest(self, text, limit=25):
        """Autocompletado: canciones cuyas palabras empiezan por lo escrito ('neut sh' -> Neutro Shorty). Una
        palabra que no empiece así en ninguna se cambia por la más parecida ('chayane' -> 'chayanne'). Sin
        texto: las más puestas."""
        if not self.wix:
            return []
        q = words(text)
        with self.lock:
            if not q:
                cand = self.index
            else:
                sets = []
                for w in q:
                    hit = self._with_prefix(w)
                    if not hit:
                        close = difflib.get_close_matches(w, self.vocab, n=3, cutoff=0.75)
                        hit = set().union(*(self.wix[c] for c in close)) if close else set()
                    sets.append(hit)
                sets.sort(key=len)
                cand = set(sets[0]).intersection(*sets[1:])
            keys = sorted(cand, key=lambda k: (self.index[k].get("plays", 0), self.index[k]["used"]), reverse=True)
            return [(k, dict(self.index[k])) for k in keys[:limit]]

    def search(self, text, limit=25):
        """Canciones cuyo título, artista o álbum contiene el texto tal cual (las más recientes primero)."""
        text = text.lower()
        with self.lock:
            hits = [(k, dict(e)) for k, e in self.index.items()
                    if text in self._text(e).lower() and self._exists(k)]
        hits.sort(key=lambda h: -h[1]["used"])
        return hits[:limit]

    def albums(self):
        """Álbumes guardados: [(nombre, artista, canciones)], los que más canciones tienen primero."""
        with self.lock:
            acc = {}
            for e in self.index.values():
                a = e.get("album")
                if a:
                    k = " ".join(words(a))
                    name, artist, n = acc.get(k, (a, e.get("artist") or "", 0))
                    acc[k] = (name, artist, n + 1)
        return sorted(acc.values(), key=lambda x: (-x[2], x[0].lower()))

    def album_tracks(self, query):
        """Guardadas de un álbum (todas las palabras escritas están en su nombre), por título."""
        q = set(words(query))
        if not q:
            return []
        with self.lock:
            hits = [(k, dict(e)) for k, e in self.index.items()
                    if q <= set(words(e.get("album") or "")) and self._exists(k)]
        return sorted(hits, key=lambda h: (h[1].get("title") or "").lower())

    def stats(self):
        with self.lock:
            return len(self.index), sum(e["size"] for e in self.index.values()), self.max

    def peek(self, key):
        """Datos de una canción guardada, sin marcarla como usada."""
        with self.lock:
            e = self.index.get(key)
            if e and self._exists(key):
                return dict(e)
        return None

    def get(self, key):
        """Datos y ruta de una canción guardada, y la marca como puesta (cuenta para el tope y 'las más puestas')."""
        with self.lock:
            e = self.index.get(key)
            if not e:
                return None
            path = os.path.join(self.root, e["file"])
            if not os.path.exists(path):
                del self.index[key]
                self._index_del(key)
                return None
            e["used"] = time.time()
            e["plays"] = e.get("plays", 0) + 1
            self.dirty = True   # solo cambian "veces puesta" y "último uso": se guarda en el siguiente flush
            return dict(e, path=path)

    def path(self, key):
        """Ruta del audio si está guardada (sin contarla como puesta)."""
        with self.lock:
            e = self.index.get(key)
            if e and self._exists(key):
                return os.path.join(self.root, e["file"])
        return None

    def set_meta(self, key, meta, info=None):
        """Apunta la ficha de una guardada de antes. meta=None: la consulta falló; se permite UN reintento y luego
        se da por preguntada ("artist" vacío). info: la respuesta de YouTube, para rellenar título, duración, etc.
        si faltan."""
        with self.lock:
            e = self.index.get(key)
            if e is None:
                return None
            if meta is None:
                e["tries"] = e.get("tries", 0) + 1
                if e["tries"] < 2:
                    self.dirty = True
                    return dict(e)
                meta = music_meta({})
            e.pop("tries", None)
            e.update(meta)
            for f, src in (("title", "title"), ("duration", "duration"), ("thumb", "thumbnail"), ("url", "webpage_url")):
                if not e.get(f) and (info or {}).get(src):
                    e[f] = info[src]
            self._index_add(key, self._text(e))
            self.save()
            return dict(e)

    def remove(self, key):
        """Borra una canción. Devuelve sus datos o None si no estaba."""
        with self.lock:
            e = self.index.pop(key, None)
            if not e:
                return None
            self._index_del(key)
            try:
                os.remove(os.path.join(self.root, e["file"]))
            except OSError:
                pass
            self.save()
        return e

    def put(self, key, src, info, by=None, copy=False, entry=None):
        """Guarda un audio (lo mueve, o lo copia si copy) y devuelve su ruta. entry: la ficha ya hecha (al traer
        una del catálogo viejo del bot); si no, se arma con info, la respuesta de YouTube."""
        name = key + os.path.splitext(src)[1]
        dest = os.path.join(self.root, name)
        (shutil.copy2 if copy else shutil.move)(src, dest + ".part")   # si se corta queda un .part, nunca una a medias
        os.replace(dest + ".part", dest)
        with self.lock:
            old = self.index.get(key) or {}
            if entry is not None:
                e = dict(entry, file=name, size=os.path.getsize(dest))
            else:
                e = {"file": name, "url": info.get("webpage_url"), "title": info.get("title"),
                     "duration": info.get("duration"), "thumb": info.get("thumbnail"), "size": os.path.getsize(dest),
                     "used": time.time(), "plays": old.get("plays", 0), "by": old.get("by", by), **music_meta(info)}
            self.index[key] = e
            self._index_add(key, self._text(e))
            total = sum(x["size"] for x in self.index.values())
            for k in sorted(self.index, key=lambda k: self.index[k]["used"]):
                if total <= self.max or k == key:
                    break
                gone = self.index.pop(k)
                self._index_del(k)
                total -= gone["size"]
                log.info("tope de espacio: borro %s (%s)", gone.get("title"), k)
                try:
                    os.remove(os.path.join(self.root, gone["file"]))
                except OSError:
                    pass
            self.save()
        return dest

    def save(self):
        """Se escribe aparte y se fuerza al disco antes de cambiarlo (un apagón no deja un catálogo vacío). La
        versión anterior queda como .bak. Llamar con self.lock tomado (o al arrancar)."""
        tmp = self.file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.index, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(self.file):
            os.replace(self.file, self.file + ".bak")
        os.replace(tmp, self.file)
        self.dirty = False

    def flush(self):
        """Guarda lo pendiente (lo que cambia al sonar una canción). Cada FLUSH s."""
        with self.lock:
            if self.dirty:
                self.save()

    def _flusher(self):
        while True:
            time.sleep(FLUSH)
            try:
                self.flush()
            except OSError as e:
                log.warning("biblioteca: no pude guardar el catálogo: %s", e)
