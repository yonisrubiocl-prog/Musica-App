"""Lo de cada usuario que tiene que verse igual en la app, la web y otros móviles: favoritas, historial y
playlists.

Se guarda por cuenta (el `sub` de Google) en /data/userdata.json:
  sub -> {"favorites": {id: {title, artist, album, duration, thumb, added}}, "history": [[id, cuándo], …],
          "playlists": {pid: {name, songs: [{id, title, artist, album, duration, thumb}], created, updated}}}
De cada canción guardada aquí se guarda su ficha, así se sigue viendo aunque la canción se borre del servidor (al
ponerla se vuelve a bajar). Ver README.md, "Favoritas, historial y playlists".
"""
import json
import os
import secrets
import threading
import time

FILE = "/data/userdata.json"
HISTORY_MAX = 200                       # canciones del historial de cada uno
PLAYLISTS_MAX = 200                     # playlists de cada uno
PLAYLIST_SONGS_MAX = 2000               # canciones de una playlist
FIELDS = ("title", "artist", "album", "duration", "thumb")

_lock = threading.Lock()
try:
    with open(FILE) as f:
        _data = json.load(f)
except (OSError, ValueError):
    _data = {}


def _save():
    tmp = FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(_data, f, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    os.replace(tmp, FILE)


def _user(sub):
    u = _data.setdefault(sub, {"favorites": {}, "history": []})
    u.setdefault("playlists", {})
    return u


def favorites(sub):
    """Favoritas, la última marcada primero: [{id, title, artist, album, duration, thumb, added}]."""
    with _lock:
        favs = (_data.get(sub) or {}).get("favorites", {})
        return sorted(({"id": i, **f} for i, f in favs.items()), key=lambda f: -f.get("added", 0))


def favorite_ids():
    """Las canciones que alguien tiene de favorita o en una playlist (no se borran al llenarse el espacio)."""
    with _lock:
        return ({i for u in _data.values() for i in u.get("favorites", {})}
                | {s["id"] for u in _data.values() for p in u.get("playlists", {}).values() for s in p["songs"]})


def known(vid):
    """La ficha de una canción que alguien ya tenga apuntada (favorita o en una playlist), o None."""
    with _lock:
        for u in _data.values():
            if vid in u.get("favorites", {}):
                return u["favorites"][vid]
            for p in u.get("playlists", {}).values():
                for s in p["songs"]:
                    if s["id"] == vid:
                        return s
    return None


def playlists(sub):
    """Las playlists del usuario, la última cambiada primero: [{id, name, songs: [fichas], created, updated}]."""
    with _lock:
        pl = (_data.get(sub) or {}).get("playlists", {})
        return sorted(({"id": i, **p, "songs": list(p["songs"])} for i, p in pl.items()), key=lambda p: -p["updated"])


def create_playlist(sub, name):
    with _lock:
        pl = _user(sub)["playlists"]
        if len(pl) >= PLAYLISTS_MAX:
            raise OverflowError
        pid = secrets.token_urlsafe(8)
        now = int(time.time())
        pl[pid] = {"name": name, "songs": [], "created": now, "updated": now}
        _save()
        return pid


def save_playlist(sub, pid, name, songs):
    """Guarda la playlist entera (nombre y canciones en orden; songs = fichas con id). False si no existe."""
    with _lock:
        p = _user(sub)["playlists"].get(pid)
        if p is None:
            return False
        p.update(name=name, songs=[{"id": s["id"], **{k: s.get(k) for k in FIELDS}} for s in songs][:PLAYLIST_SONGS_MAX],
                 updated=int(time.time()))
        _save()
        return True


def delete_playlist(sub, pid):
    with _lock:
        if _user(sub)["playlists"].pop(pid, None) is not None:
            _save()
            return True
    return False


def add_favorite(sub, vid, info):
    with _lock:
        favs = _user(sub)["favorites"]
        favs[vid] = {**{k: info.get(k) for k in FIELDS}, "added": favs.get(vid, {}).get("added") or int(time.time())}
        _save()


def remove_favorite(sub, vid):
    with _lock:
        if _user(sub)["favorites"].pop(vid, None) is not None:
            _save()
            return True
    return False


def _replace_in(u, old, new, info):
    """Cambia la canción `old` por `new` en las favoritas, playlists e historial de un usuario (sin cerrojo)."""
    favs = u["favorites"]
    if old in favs:   # la nueva, en el sitio exacto de la vieja (hay muchas con la misma fecha: importadas)
        was, dup = favs[old], new in favs and new != old
        entry = {**{k: info.get(k) for k in FIELDS}, "added": was.get("added") or int(time.time())}
        u["favorites"] = {(new if k == old else k): (entry if k == old else v)
                          for k, v in favs.items() if not (dup and k == new)}
    for p in u["playlists"].values():
        if not any(s["id"] == old for s in p["songs"]):
            continue
        out, seen = [], set()
        for s in p["songs"]:
            s = {"id": new, **{k: info.get(k) for k in FIELDS}} if s["id"] == old else s
            if s["id"] not in seen:
                seen.add(s["id"])
                out.append(s)
        p["songs"] = out
    if any(h[0] == old for h in u.get("history", [])):
        out, seen = [], set()
        for vid, when in u["history"]:
            vid = new if vid == old else vid
            if vid not in seen:
                seen.add(vid)
                out.append([vid, when])
        u["history"] = out


def replace_song(sub, old, new, info):
    """Cambia la canción `old` por `new` (con su ficha `info`) en las favoritas, playlists e historial de un usuario:
    en favoritas conserva cuándo se marcó y su sitio; en cada playlist, su posición. Si `new` ya estaba, no se repite
    (se queda en el sitio de la vieja). Ver versiones.py."""
    with _lock:
        _user(sub)
        _replace_in(_data[sub], old, new, info)
        _save()


def replace_everywhere(old, new, info):
    """Lo mismo en todas las cuentas (duplicadas.py: al juntar dos copias de la misma canción)."""
    with _lock:
        for sub in list(_data):
            _user(sub)
            _replace_in(_data[sub], old, new, info)
        _save()


def played(sub, vid):
    """Apunta que este usuario puso esta canción (la más reciente al principio, sin repetir)."""
    with _lock:
        h = [x for x in _user(sub)["history"] if x[0] != vid]
        _user(sub)["history"] = [[vid, int(time.time())]] + h[:HISTORY_MAX - 1]
        _save()


def history(sub, limit=50):
    """[(id, cuándo)] de lo último que puso, lo más reciente primero."""
    with _lock:
        return [tuple(x) for x in (_data.get(sub) or {}).get("history", [])[:limit]]
