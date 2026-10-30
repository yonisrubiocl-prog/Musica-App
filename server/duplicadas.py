"""Canciones repetidas en la biblioteca: la misma canción guardada varias veces con otro título ("Numb", "Linkin Park -
Numb (Official Music Video) [4K]", "Numb (Lyrics)"…). Se queda una y las demás se borran.

Es la misma canción si es del mismo artista, con el mismo título limpio (sin "Artista - ", etiquetas ni "ft."), sin
que una sea directo, remix, acústica… y la otra no, y con duración parecida (o la de vídeo algo más larga, por la
intro). Se queda **la del disco** (sin etiquetas de vídeo/letra, con álbum y número de pista) y, si no hay, la más
puesta. Antes de borrar las otras, las favoritas, playlists e historial de todos pasan a la que se queda (en el mismo
sitio) y se le suman sus reproducciones. Cada cambio queda en /data/duplicadas.jsonl.

Se hace cada noche (y a mano: GET /interno/duplicadas para ver, POST para hacerlo). También sirve para no enseñar
en "Buscar en YouTube" canciones que ya están guardadas con otro título (`Duplicadas.saved`). Ver README.md.
"""
import collections
import json
import logging
import os
import re
import threading
import time
import unicodedata

from versiones import LIVE, OTHER, TAGS, VIDEO

log = logging.getLogger("musicapp.duplicadas")

LOG = "/data/duplicadas.jsonl"
ALIAS = "/data/alias.json"              # vídeo pedido -> la canción guardada que es la misma (no se bajó)
HOUR_UTC = 8                            # cada noche, a las 05:00 de Chile
# etiquetas de vídeo/letra entre paréntesis o tras "|": "(Lyrics)", "[4K]", "(Vídeo Animación)", "| Un Verano Sin Ti"
TAG_VIDEO = re.compile(r"video|v[ií]deo|lyric|letra|\b4k\b|\bhd\b|\bhq\b|clip|visuali[sz]er|animaci[oó]n|official|"
                       r"oficial|audio", re.I)
# lo único que puede llevar una etiqueta de un vídeo de otro canal para ser la misma canción ("(Lyrics)", "[4K UPGRADE]",
# "(Remastered 2023)"): lo demás ("(Metal)", "| Naruto AMV", "(Reaction Video)") puede ser otra interpretación
SAME_WORDS = set("official oficial music musica musical video videoclip clip audio lyric lyrics letra con with hd hq "
                 "4k uhd upgrade remaster remastered remasterizado remasterizada visualizer visualiser animacion "
                 "sub subtitulado subtitulada subtitulos en espanol traducida".split())
CHANNEL_WORDS = {"official", "oficial", "music", "musica", "tv", "channel", "canal", "topic", "band", "banda"}
# títulos que se repiten entre discos sin ser la misma canción
GENERIC = re.compile(r"^(intro|outro|interlude|interludio|skit|prelude|preludio|bonus( track)?|untitled|sin titulo|"
                     r"hidden track|instrumental|reprise|\d+)$")


class Duplicadas:
    def __init__(self, lib, ud):
        self.lib, self.ud = lib, ud
        self.lock = threading.Lock()
        self._saved = (None, {})
        try:
            with open(ALIAS) as f:
                self.aliases = json.load(f)
        except (OSError, ValueError):
            self.aliases = {}
        threading.Thread(target=self._run, daemon=True, name="duplicadas").start()

    # ---------- qué es igual a qué ----------

    def clean(self, title, artist_n):
        """'Linkin Park - Numb (Official Music Video) [4K]' -> 'numb'."""
        t = title or ""
        if self.lib.DASH.search(t):
            a, b = self.lib.DASH.split(t, 1)
            na = self.lib._norm(a)
            # solo si lo de delante EMPIEZA por el artista ('Rawayana, Akapellah - Veneka'); si no, lo de detrás puede
            # ser el canal ('Difícil De Igualar, Binomio De Oro, Video Letra - Sentir Vallenato')
            nb = self.lib._norm(b)
            if artist_n and (na == artist_n or na.startswith(artist_n + " ") or artist_n.startswith(na + " ")):
                t = b
            elif artist_n and (nb == artist_n or nb.startswith(artist_n + " ")):   # "Numb (Official Video) – Linkin Park"
                t = a
        return self.lib._norm(TAGS.sub("", t))

    def kind(self, title, artist_n):
        """Clave de "la misma canción": (artista, título limpio, ¿directo?, ¿remix/acústica/…?)."""
        t = title or ""
        return artist_n, self.clean(t, artist_n), bool(LIVE.search(t)), bool(OTHER.search(t))

    @staticmethod
    def tagged(title):
        """¿Lleva etiquetas de vídeo o letra? ("(Official Video)", "(Lyrics)", "[4K]", "| álbum")."""
        t = unicodedata.normalize("NFKD", title or "")   # "ᴴᴰ" -> "HD"
        return bool(VIDEO.search(t)) or "|" in t or bool(re.search(r"\b(hd|hq|4k)\s*$", t, re.I)) or any(TAG_VIDEO.search(x) for x in re.findall(r"[\(\[]([^\)\]]*)[\)\]]", t))

    def collabs(self, e, artist_n):
        """Con quién canta, sin el artista principal: los "feat." del título, el "Artista, Otro - …" y la ficha."""
        t, out = e.get("title") or "", set()
        parts = self.lib.DASH.split(t, 1) if self.lib.DASH.search(t) else []
        chunks = [f for f in self.lib.FEAT.findall(t)] + [e.get("artist") or ""]
        chunks += [p for p in parts if artist_n and self.lib._norm(p).startswith(artist_n)]
        for c in chunks:
            for m in self.lib.JOINT.split(TAGS.sub("", c)):
                n = self.lib._norm(m)
                if n and n != artist_n and artist_n not in n:
                    out.add(n)
        return out

    def genuine(self, title, channel, artists):
        """¿Es de verdad esa grabación y no otra persona cantándola? Sí si la subió el propio artista; de otro canal,
        solo si lo único que añade el título son etiquetas de vídeo o letra (ante la duda, no: mejor una copia de más
        que sonar otra canción). Sin canal conocido (fichas viejas) no se sabe nada: sí."""
        words = [w for w in self.lib._norm(channel).split() if w not in CHANNEL_WORDS]
        if not channel:
            return True
        who = re.sub(r"^(?:oficial|official)|(?:vevo|oficial|official|musica|music)$", "", "".join(words))   # OficialMana, LassoMusica
        if any(who == "".join(self.lib._norm(a).split()) for a in artists):
            return True
        t = unicodedata.normalize("NFKD", title or "")
        tags = re.findall(r"[\(\[]([^\)\]]*)[\)\]]", t) + t.split("|")[1:]
        tags += re.findall(r"\s((?:official|video oficial|videoclip|lyric).*)$", re.sub(r"[\(\[][^\)\]]*[\)\]]", "", t), re.I)
        words = [self.lib._norm(x).split() for x in tags]
        return bool(words) and all(w and all(x in SAME_WORDS or x.isdigit() or re.fullmatch(r"\d+p", x) for x in w) for w in words)

    def _genuine(self, e, artist_n):
        name = self.lib.artist_name(e)
        return self.genuine(e.get("title"), e.get("channel"), [artist_n, name, *self.lib.JOINT.split(name)])

    def _best(self, items):
        return max(items, key=lambda ke: (not self.tagged(ke[1].get("title")), bool(ke[1].get("track_no")),
                                          bool(ke[1].get("album")), ke[1].get("plays", 0)))

    @staticmethod
    def _close(e, best):
        d0, d = best.get("duration") or 0, e.get("duration") or 0
        if not d0 or not d:
            return True
        # duración parecida, o la de vídeo más larga (intro, escenas) pero no el doble y pico
        return abs(d - d0) <= max(25, 0.15 * d0) or (d > d0 and d <= 2.2 * d0 and Duplicadas.tagged(e.get("title")))

    def find(self):
        """[(la que se queda (clave, ficha), [(clave, ficha) que sobran])]."""
        with self.lib.lock:
            groups = collections.defaultdict(list)
            artist_of = {}
            for n, (_, items) in self.lib._by_artist().items():
                for k, e in items:
                    if k.startswith("yt-"):
                        key = self.kind(e.get("title") or e.get("track"), n)
                        if key[1] and not GENERIC.match(key[1]):
                            groups[key].append((k, dict(e)))
                            artist_of[k] = n
        best_n = lambda items: artist_of[items[0][0]]
        out = []
        for items in groups.values():
            if len(items) > 1:
                best = self._best(items)
                bc = self.collabs(best[1], items_n := best_n(items))
                # con colaboradores distintos son otra canción ("Sin Ti" con Willy Rodríguez / con La Vida Bohème)
                rest = [(k, e) for k, e in items if k != best[0] and self._close(e, best[1])
                        and self._genuine(e, items_n) and self._genuine(best[1], items_n)
                        and not (bc and (oc := self.collabs(e, items_n)) and not bc & oc)]
                if rest:
                    out.append((best, rest))
        return out

    def saved(self):
        """{(artista, título limpio, directo, remix…): clave} de lo guardado, para no ofrecer de internet otra copia."""
        stamp = (self.lib._ver, len(self.lib.index))
        if self._saved[0] != stamp:
            with self.lib.lock:
                out = {}
                for n, (_, items) in self.lib._by_artist().items():
                    for k, e in items:
                        out.setdefault(self.kind(e.get("title") or e.get("track"), n), k)
            self._saved = (stamp, out)
        return self._saved[1]

    def is_saved(self, title, artists):
        """¿Esta canción de internet (título y artistas) ya está guardada con otro título? Su clave o None."""
        saved, groups = self.saved(), self.lib._by_artist()
        for a in artists:
            n = self.lib._norm(a)
            if n in groups:
                k = saved.get(self.kind(title, n))
                if k:
                    return k
        return None

    # ---------- no bajar lo que ya está ----------

    def real_key(self, key):
        """La canción guardada que es `key` (si se apodó al pedirla), o la misma `key`."""
        k = self.aliases.get(key)
        return k if k and self.lib.peek(k) else key

    def _save_aliases(self):
        tmp = ALIAS + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.aliases, f)
        os.replace(tmp, ALIAS)

    def same_as_saved(self, key, info):
        """Antes de bajar `key` (con la ficha de yt-dlp `info`): la clave de la guardada que es la misma canción, o
        None. Si lo pedido es la versión del disco y lo guardado un vídeo, None (mejor bajar la buena; la noche junta).
        Si la hay, se apunta el apodo para la próxima vez."""
        title = info.get("title") or ""
        artists = [info.get("artist"), info.get("creator"),
                   re.sub(r"\s*-\s*topic$", "", self.lib.CHANNEL.sub("", info.get("channel") or info.get("uploader") or ""), flags=re.I)]
        if self.lib.DASH.search(title):
            artists += self.lib.DASH.split(title, 1)
        artists = [x for a in artists if a for x in self.lib.JOINT.split(a) if x.strip()]
        saved = self.is_saved(title, artists) or (info.get("track") and self.is_saved(info["track"], artists))
        e = self.lib.peek(saved) if saved else None
        if not e:
            return None
        asked = {"title": title, "duration": info.get("duration")}
        if not (self._close(asked, e) or self._close(e, asked)):
            return None
        if not self.tagged(title) and self.tagged(e.get("title")):
            return None
        name = self.lib.artist_name(e)
        if not self.genuine(title, info.get("channel") or info.get("uploader"), [name, *self.lib.JOINT.split(name)]):
            return None
        with self.lock:
            self.aliases[key] = saved
            self._save_aliases()
        log.info("duplicadas: %s ya está guardada como %s (%s): no se baja", title, e.get("title"), saved)
        return saved

    # ---------- juntar ----------

    def merge(self):
        """Junta todas las repetidas. Devuelve cuántas canciones sobraban y se borraron."""
        with self.lock:
            done = 0
            for (bk, be), rest in self.find():
                if not self.lib.peek(bk):
                    continue
                info = {k: be.get(k) for k in ("title", "artist", "album", "duration", "thumb")}
                plays = be.get("plays", 0)
                for k, e in rest:
                    self.ud.replace_everywhere(k[3:], bk[3:], info)
                    plays += e.get("plays", 0)
                    for a, t in self.aliases.items():
                        if t == k:
                            self.aliases[a] = bk
                    if self.lib.remove(k):
                        done += 1
                        with open(LOG, "a") as f:
                            f.write(json.dumps({"cuando": int(time.time()), "borrada": k, "titulo": e.get("title"),
                                                "queda": bk, "queda_titulo": be.get("title")}, ensure_ascii=False) + "\n")
                self.lib.set_fields(bk, {"plays": plays})
            for a, t in list(self.aliases.items()):   # lo que alguien guardó con el vídeo apodado
                e = self.lib.peek(t)
                if e:
                    self.ud.replace_everywhere(a[3:], t[3:], {k: e.get(k) for k in ("title", "artist", "album", "duration", "thumb")})
            self._save_aliases()
            if done:
                log.info("duplicadas: %d copias de canciones repetidas juntadas", done)
            return done

    def _run(self):
        last = None
        while True:
            time.sleep(600)
            t = time.gmtime()
            if t.tm_hour == HOUR_UTC and last != t.tm_yday:
                last = t.tm_yday
                try:
                    self.merge()
                except Exception as ex:
                    log.warning("duplicadas: %s", ex)
