"""Lo de cada usuario que tiene que verse igual en la app y en la web: favoritas e historial.

Se guarda por cuenta (el `sub` de Google) en /data/userdata.json:
  sub -> {"favorites": {id: {title, artist, album, duration, thumb, added}}, "history": [[id, cuándo], …]}
De cada favorita se guarda su ficha, así se sigue viendo aunque la canción se borre del servidor (al ponerla
se vuelve a bajar). Ver README.md, "Favoritas e historial".
"""
import json
import os
import threading
import time

FILE = "/data/userdata.json"
HISTORY_MAX = 200                       # canciones del historial de cada uno
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
    return _data.setdefault(sub, {"favorites": {}, "history": []})


def favorites(sub):
    """Favoritas, la última marcada primero: [{id, title, artist, album, duration, thumb, added}]."""
    with _lock:
        favs = (_data.get(sub) or {}).get("favorites", {})
        return sorted(({"id": i, **f} for i, f in favs.items()), key=lambda f: -f.get("added", 0))


def favorite_ids():
    """Todas las canciones que alguien tiene de favorita (no se borran al llenarse el espacio)."""
    with _lock:
        return {i for u in _data.values() for i in u.get("favorites", {})}


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
