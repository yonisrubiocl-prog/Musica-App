"""Recomendaciones (fase 1 del plan: docs/recomendaciones.md): Radio, Para ti, Vuelve a escuchar, eventos y
opiniones. Todo el cálculo vive aquí; las apps solo enseñan lo que devuelve y mandan lo que hace el usuario.

Datos (en /recomendar, en el servidor /var/lib/musicapp/recomendar):
  eventos-AAAA-MM.jsonl   lo que hace cada uno (empezó, entera, saltó, no me gusta…), una línea por evento
  opiniones.jsonl         "¿qué te parecieron?" con lo que se había recomendado
  estado.json             no me gusta, saltos en recomendaciones, cuándo se preguntó, ajustes de cada uno

Se apaga con RECOMENDAR=0 (docker-compose.yml): las rutas dan 404 y las apps enseñan lo de siempre. Para quitarlo:
borrar este archivo, sus rutas en app.py y la carpeta de datos. Los números para ajustar están aquí arriba.
"""
import collections
import json
import logging
import os
import random
import re
import threading
import time
import unicodedata

log = logging.getLogger("musicapp.recomendar")


def _year(y):
    """Año como número (algunas fichas lo traen como texto, "1998" o "1998-05-01"); None si no hay."""
    m = re.match(r"\d{4}", str(y or ""))
    return int(m.group()) if m else None

DIR = "/recomendar"
KEEP_DAYS = 180                         # eventos que se leen al arrancar (los archivos viejos se pueden borrar)

# ---- señales (sección 2 del plan) ----
W_FAV, W_PLAYLIST, W_REPEAT, W_FULL = 4.0, 3.0, 2.0, 1.0
W_PLAY = 0.5                            # haberla puesto (una vez por día y canción)
W_SKIP_OWN, W_SKIP_REPEATED = -0.3, -2.0
SKIP_EARLY = 0.15                       # saltar antes de este % de la canción
SKIP_DAYS_FOR_DISLIKE = 3               # saltos (tempranos) en días distintos para contar como "no me gusta"
RECO_SKIP_PAUSE = 5 * 86400             # saltada estando recomendada: no recomendarla en estos segundos
# ---- perfil doble (sección 3) ----
HALF_HISTORIC, HALF_RECENT = 180 * 86400, 10 * 86400
MIX_HISTORIC = 0.6                      # el resto, lo reciente
# ---- radio y Para ti (secciones 5 y 6) ----
SESSION_GAP = 30 * 60                   # dos escuchas más separadas que esto no son "una detrás de otra"
S_NEXT, S_ARTIST, S_GENRE, S_YEAR, S_ALBUM = 3.0, 1.0, 0.6, 0.2, 0.1
S_TASTE = 0.5                           # cuánto pesa el gusto de la persona al ordenar
NO_REPEAT = 24 * 3600                   # lo escuchado hace menos de esto no se recomienda
EXPLORE = 0.15                          # parte de sorpresa
MAX_PER_ARTIST, ARTIST_WINDOW = 2, 10   # como mucho 2 del mismo artista cada 10
# ---- opiniones (sección 7) ----
ASK_EVERY = 7 * 86400                   # preguntar como mucho una vez por semana
ASK_MIN_SONGS = 10
CONTEXTS = ("radio", "para_ti", "mix", "vuelve", "busqueda", "biblioteca", "playlist", "favoritas", "album",
            "artista", "desconocido")
TYPES = ("inicio", "entera", "salto", "no_me_gusta", "ya_no_me_gusta")
CAUSES = ("usuario", "error", "dispositivo", "interrupcion")
OPTIONS = ("repetitivas", "no_me_gustaron", "quiero_nuevas", "muy_raras", "generos_no_pegan", "mas_reciente",
           "versiones_raras")
RECOMMENDED = {"radio", "para_ti", "mix", "vuelve"}

TAGS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]|\s+(?:ft\.?|feat\.?|featuring|prod\.?)\s.*$", re.I)
LIVE = re.compile(r"\b(live|en vivo|ao vivo|directo|unplugged|ac[uú]stic|acoustic|remix|sped up|slowed|karaoke|cover)\b", re.I)


def norm(text):
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", t))


class Recomendar:
    def __init__(self, lib, userdata):
        self.lib, self.ud = lib, userdata
        self.lock = threading.Lock()
        os.makedirs(DIR, exist_ok=True)
        self.state = self._load_json("estado.json", {})
        for k in ("no_me_gusta", "reco_skips", "asked", "shown"):
            self.state.setdefault(k, {})
        self.events = collections.defaultdict(list)   # sub -> [evento], el más viejo primero
        self._read_events()
        self._cat = (None, None)

    # ---------- archivos ----------

    def _load_json(self, name, default):
        try:
            with open(os.path.join(DIR, name)) as f:
                return json.load(f)
        except (OSError, ValueError):
            return default

    def _save_state(self):
        tmp = os.path.join(DIR, "estado.json.tmp")
        with open(tmp, "w") as f:
            json.dump(self.state, f, ensure_ascii=False)
        os.replace(tmp, os.path.join(DIR, "estado.json"))

    def _append(self, name, row):
        with open(os.path.join(DIR, name), "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _read_events(self):
        since, n = time.time() - KEEP_DAYS * 86400, 0
        for name in sorted(os.listdir(DIR)):
            if not (name.startswith("eventos-") and name.endswith(".jsonl")):
                continue
            with open(os.path.join(DIR, name)) as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if e.get("cuando", 0) >= since:
                        self.events[e["sub"]].append(e)
                        n += 1
        for evs in self.events.values():
            evs.sort(key=lambda e: e["cuando"])
        log.info("recomendaciones: %d eventos de %d usuarios", n, len(self.events))

    # ---------- eventos (los manda la app; "inicio" también lo apunta /stream) ----------

    def add_events(self, sub, items, source="app"):
        now = time.time()
        ok = 0
        with self.lock:
            for it in items:
                t, vid = it.get("tipo"), it.get("id")
                if t == "inicio" and source == "app":
                    continue   # "empezó a sonar" lo apunta el servidor solo (/stream): así no sale dos veces
                if t not in TYPES or not isinstance(vid, str) or not re.fullmatch(r"[\w-]{11}", vid):
                    continue
                when = it.get("cuando") if isinstance(it.get("cuando"), (int, float)) else now
                when = min(now, max(now - 30 * 86400, when))   # lo mandado sin conexión, como mucho de hace 30 días
                e = {"sub": sub, "tipo": t, "id": vid, "cuando": round(when, 1), "fuente": source,
                     "contexto": it.get("contexto") if it.get("contexto") in CONTEXTS else "desconocido"}
                for k in ("segundo", "duracion"):
                    if isinstance(it.get(k), (int, float)) and 0 <= it[k] < 6 * 3600:
                        e[k] = round(it[k], 1)
                if it.get("causa") in CAUSES:
                    e["causa"] = it["causa"]
                self._append(f"eventos-{time.strftime('%Y-%m', time.gmtime(when))}.jsonl", e)
                self.events[sub].append(e)
                self._apply(sub, e)
                ok += 1
            if ok:
                self.events[sub].sort(key=lambda e: e["cuando"])
                self._save_state()
        return ok

    def _apply(self, sub, e):
        """Lo que cambia al momento (el resto se calcula al recomendar)."""
        dis = self.state["no_me_gusta"].setdefault(sub, {})
        if e["tipo"] == "no_me_gusta":
            dis[e["id"]] = e["cuando"]
        elif e["tipo"] == "ya_no_me_gusta":
            dis.pop(e["id"], None)
        elif self._is_skip(e) and e["contexto"] in RECOMMENDED:
            self.state["reco_skips"].setdefault(sub, {})[e["id"]] = e["cuando"]

    @staticmethod
    def _is_skip(e):
        """Salto temprano hecho por la persona (no un error, un cambio de dispositivo ni un corte)."""
        if e["tipo"] != "salto" or e.get("causa", "usuario") != "usuario":
            return False
        d, s = e.get("duracion"), e.get("segundo")
        return s is not None and (s < 5 or (d and s / d < SKIP_EARLY))

    # ---------- catálogo y versiones (sección 4) ----------

    def catalog(self):
        """Canciones con lo que hace falta para recomendar: artista (agrupado), género, año, álbum y 'canon' (la
        misma canción en todas sus versiones). Se recalcula solo cuando cambia la biblioteca o los géneros."""
        stamp = (self.lib._ver, len(self.lib.index), self.lib.genre_stamp())
        if self._cat[0] == stamp:
            return self._cat[1]
        with self.lib.lock:
            groups = self.lib._by_artist()
            genres = self.lib._key_genres()
            songs = {}
            for n_artist, (shown, items) in groups.items():
                for k, e in items:
                    if not k.startswith("yt-"):
                        continue
                    title = e.get("title") or ""
                    if " - " in title and norm(title.split(" - ", 1)[0]) == n_artist:
                        title = title.split(" - ", 1)[1]
                    songs[k] = {"key": k, "id": k[3:], "artist": shown, "artist_n": n_artist,
                                "genre": genres.get(k, ""), "year": _year(e.get("year")), "album": norm(e.get("album")),
                                "canon": n_artist + "|" + norm(TAGS.sub("", title)), "live": bool(LIVE.search(title)),
                                "plays": e.get("plays", 0), "used": e.get("used", 0), "duration": e.get("duration")}
        by_artist, by_genre, by_canon = collections.defaultdict(list), collections.defaultdict(list), {}
        for s in songs.values():
            by_artist[s["artist_n"]].append(s["key"])
            if s["genre"]:
                by_genre[s["genre"]].append(s["key"])
            best = by_canon.get(s["canon"])   # la mejor versión: de estudio y la más puesta
            if best is None or (songs[best]["live"], -songs[best]["plays"]) > (s["live"], -s["plays"]):
                by_canon[s["canon"]] = s["key"]
        cat = {"songs": songs, "artist": by_artist, "genre": by_genre, "best": by_canon}
        self._cat = (stamp, cat)
        return cat

    # ---------- perfil (secciones 2 y 3) ----------

    def profile(self, sub):
        """Gusto de la persona: {'artist': {..}, 'genre': {..}, 'song': {..}} mezclando lo de siempre y lo reciente."""
        cat, now = self.catalog(), time.time()
        song_w = collections.defaultdict(float)

        def add(key, w, when):
            age = max(0, now - when)
            song_w[key] += w * (MIX_HISTORIC * 0.5 ** (age / HALF_HISTORIC) + (1 - MIX_HISTORIC) * 0.5 ** (age / HALF_RECENT))

        for f in self.ud.favorites(sub):
            add("yt-" + f["id"], W_FAV, f.get("added", now))
        for p in self.ud.playlists(sub):
            for s in p["songs"]:
                add("yt-" + s["id"], W_PLAYLIST, p.get("updated", now))
        days = collections.defaultdict(set)   # canción -> días en que se puso
        skip_days = collections.defaultdict(set)
        for e in self.events.get(sub, []):
            k, day = "yt-" + e["id"], int(e["cuando"] // 86400)
            if e["tipo"] == "inicio" and day not in days[k]:
                add(k, W_PLAY if not days[k] else W_REPEAT, e["cuando"])
                days[k].add(day)
            elif e["tipo"] == "entera":
                add(k, W_FULL, e["cuando"])
            elif self._is_skip(e) and e["contexto"] not in RECOMMENDED:
                add(k, W_SKIP_OWN, e["cuando"])
                skip_days[k].add(day)
        for k, ds in skip_days.items():
            if len(ds) >= SKIP_DAYS_FOR_DISLIKE:
                add(k, W_SKIP_REPEATED, now)
        artist, genre = collections.defaultdict(float), collections.defaultdict(float)
        for k, w in song_w.items():
            s = cat["songs"].get(k)
            if s:
                artist[s["artist_n"]] += w
                if s["genre"]:
                    genre[s["genre"]] += w
        return {"song": dict(song_w), "artist": dict(artist), "genre": dict(genre), "days": days}

    def _blocked(self, sub):
        """Lo que no se recomienda ahora: no me gusta, saltado estando recomendado hace poco, escuchado hace poco."""
        now = time.time()
        out = set("yt-" + i for i in self.state["no_me_gusta"].get(sub, {}))
        out |= {"yt-" + i for i, t in self.state["reco_skips"].get(sub, {}).items() if now - t < RECO_SKIP_PAUSE}
        out |= {"yt-" + e["id"] for e in self.events.get(sub, []) if e["tipo"] == "inicio" and now - e["cuando"] < NO_REPEAT}
        out |= {"yt-" + i for i, t in self.ud.history(sub, 200) if now - t < NO_REPEAT}
        return out

    def _next_counts(self, sub, seed):
        """Qué suele sonar justo después de 'seed' en las escuchas de la persona (misma sesión)."""
        out = collections.Counter()
        starts = [e for e in self.events.get(sub, []) if e["tipo"] == "inicio"]
        for a, b in zip(starts, starts[1:]):
            if a["id"] == seed[3:] and b["id"] != a["id"] and b["cuando"] - a["cuando"] < SESSION_GAP:
                out["yt-" + b["id"]] += 1
        return out

    # ---------- elegir con variedad ----------

    def _pick(self, scored, n, exclude_canon=(), explore_pool=()):
        """De [(puntos, clave)] elige n: mejor primero, sin dos versiones de lo mismo, como mucho MAX_PER_ARTIST del
        mismo artista cada ARTIST_WINDOW, y un EXPLORE de sorpresa sacado de explore_pool."""
        cat = self.catalog()
        seen_canon, out, recent = set(exclude_canon), [], collections.deque(maxlen=ARTIST_WINDOW)
        n_explore = int(round(n * EXPLORE))
        pool = [k for k in explore_pool if k in cat["songs"]]
        random.shuffle(pool)
        ranked = [k for _, k in sorted(scored, key=lambda x: -x[0])]

        def take(k, variety=True):
            s = cat["songs"][k]
            best = cat["best"].get(s["canon"], k)
            if best in cat["songs"]:
                k, s = best, cat["songs"][best]
            if s["canon"] in seen_canon or (variety and sum(1 for a in recent if a == s["artist_n"]) >= MAX_PER_ARTIST):
                return False
            seen_canon.add(s["canon"])
            recent.append(s["artist_n"])
            out.append(k)
            return True

        for k in ranked:
            if len(out) >= n - n_explore:
                break
            take(k)
        for k in pool:
            if len(out) >= n:
                break
            if k not in out:
                take(k)
        for k in ranked:   # si la sorpresa no llenó, con lo siguiente del ranking
            if len(out) >= n:
                break
            if k not in out:
                take(k)
        for k in ranked:   # y si aún falta (p. ej. el único artista de su género), sin la regla de variedad
            if len(out) >= n:
                break
            if k not in out:
                take(k, variety=False)
        if len(out) > n - n_explore:   # que la sorpresa no salga toda al final
            head, tail = out[:3], out[3:]
            random.shuffle(tail)
            out = head + tail
        return out

    # ---------- radio (sección 6) ----------

    def radio(self, sub, seed, exclude, n=20):
        """seed: ('cancion', clave) o ('artista', nombre). exclude: claves ya puestas. Devuelve claves."""
        cat, prof = self.catalog(), self.profile(sub)
        blocked = self._blocked(sub) | set(exclude)
        exclude_canon = {cat["songs"][k]["canon"] for k in exclude if k in cat["songs"]}
        if seed[0] == "artista":
            a = norm(seed[1])
            own = [k for k in cat["artist"].get(a, []) if k not in blocked]
            if not own:
                return []
            seed_song = max(own, key=lambda k: (prof["song"].get(k, 0), cat["songs"][k]["plays"]))
        else:
            seed_song = seed[1]
            if seed_song not in cat["songs"]:
                return []
            exclude_canon.add(cat["songs"][seed_song]["canon"])
        s0 = cat["songs"][seed_song]
        nxt = self._next_counts(sub, seed_song)
        cand = set(nxt) | set(cat["artist"].get(s0["artist_n"], [])) | set(cat["genre"].get(s0["genre"], []) if s0["genre"] else [])
        max_a = max(prof["artist"].values(), default=0) or 1
        scored = []
        for k in cand:
            if k in blocked or k == seed_song or k not in cat["songs"]:
                continue
            s = cat["songs"][k]
            p = S_NEXT * nxt.get(k, 0)
            p += S_ARTIST if s["artist_n"] == s0["artist_n"] else 0
            p += S_GENRE if s["genre"] and s["genre"] == s0["genre"] else 0
            p += S_YEAR if s["year"] and s0["year"] and abs(s["year"] - s0["year"]) <= 5 else 0
            p += S_ALBUM if s["album"] and s["album"] == s0["album"] else 0
            p += S_TASTE * prof["artist"].get(s["artist_n"], 0) / max_a + 0.2 * random.random()
            p -= 0.5 if s["live"] and not s0["live"] else 0
            scored.append((p, k))
        pool = [k for k in cat["genre"].get(s0["genre"], []) if k not in blocked and prof["artist"].get(cat["songs"][k]["artist_n"], 0) <= 0]
        picked = self._pick(scored, n, exclude_canon, pool)
        if seed[0] == "artista" and seed_song not in picked:
            picked = [seed_song] + picked[:n - 1]
        return picked

    # ---------- Para ti y Vuelve a escuchar (sección 6) ----------

    def para_ti(self, sub, n=20):
        """Guardadas que no ha escuchado, de sus artistas y géneros, y parecidas a lo que le gusta."""
        cat, prof = self.catalog(), self.profile(sub)
        heard = set(prof["days"]) | {"yt-" + i for i, _ in self.ud.history(sub, 200)}
        blocked = self._blocked(sub) | heard | set(prof["song"])
        top_a = sorted(prof["artist"].items(), key=lambda x: -x[1])[:15]
        top_g = sorted(prof["genre"].items(), key=lambda x: -x[1])[:5]
        if not top_a:   # usuario nuevo: lo más puesto en el servidor
            ranked = sorted((k for k in cat["songs"] if k not in blocked), key=lambda k: -cat["songs"][k]["plays"])
            return self._pick([(cat["songs"][k]["plays"], k) for k in ranked[:200]], n)
        max_a, max_g = top_a[0][1] or 1, (top_g[0][1] if top_g else 1) or 1
        scored = {}
        for a, w in top_a:
            for k in cat["artist"].get(a, []):
                if k not in blocked:
                    scored[k] = scored.get(k, 0) + 1.0 * w / max_a
        for g, w in top_g:
            for k in cat["genre"].get(g, []):
                if k not in blocked:
                    scored[k] = scored.get(k, 0) + 0.5 * w / max_g
        scored = [(p + 0.15 * random.random(), k) for k, p in scored.items()]
        pool = [k for g, _ in top_g for k in cat["genre"].get(g, []) if k not in blocked
                and prof["artist"].get(cat["songs"][k]["artist_n"], 0) <= 0]
        return self._pick(scored, n, (), pool)

    def vuelve(self, sub, n=15):
        """Lo que ponía mucho hace 1–3 meses y ya no."""
        now = time.time()
        old, recent = collections.Counter(), set()
        for e in self.events.get(sub, []):
            if e["tipo"] != "inicio":
                continue
            age = now - e["cuando"]
            if age < 30 * 86400:
                recent.add("yt-" + e["id"])
            elif age < 90 * 86400:
                old["yt-" + e["id"]] += 1
        blocked = self._blocked(sub) | recent
        return self._pick([(c, k) for k, c in old.items() if c >= 2 and k not in blocked], n)

    def recent(self, sub, n=15):
        out = []
        for vid, _ in self.ud.history(sub, 50):
            if "yt-" + vid in self.catalog()["songs"]:
                out.append("yt-" + vid)
            if len(out) >= n:
                break
        return out

    # ---------- opiniones (sección 7) ----------

    def should_ask(self, sub, context):
        """¿Enseñar ahora "¿Qué te parecieron?"? Como mucho una vez por semana y no dos seguidas del mismo tipo.
        Si dice que sí, cuenta como preguntado."""
        with self.lock:
            a = self.state["asked"].get(sub) or {}
            now = time.time()
            if now - a.get("cuando", 0) < ASK_EVERY or a.get("contexto") == context:
                return False
            self.state["asked"][sub] = {"cuando": now, "contexto": context}
            self._save_state()
            return True

    def add_opinion(self, sub, data):
        row = {"sub": sub, "cuando": time.time(), "contexto": data.get("contexto") if data.get("contexto") in CONTEXTS else "desconocido",
               "semilla": str(data.get("semilla") or "")[:100], "gusto": data.get("gusto") if data.get("gusto") in ("si", "no") else None,
               "opciones": [o for o in data.get("opciones") or [] if o in OPTIONS],
               "texto": str(data.get("texto") or "")[:1000],
               "canciones": [c for c in (data.get("canciones") or [])[:100] if isinstance(c, str) and len(c) == 11]}
        with self.lock:
            self._append("opiniones.jsonl", row)
        log.info("opinión de recomendaciones: %s %s %s", row["contexto"], row["gusto"], row["opciones"])
        return row
