"""Usuarios y sesiones de MusicApp: login con Google y aprobación manual.

Quien entra con Google por primera vez queda "pendiente"; hasta que se aprueba no recibe sesión.
Las sesiones son claves aleatorias; en disco solo se guarda su hash. Ver README.md, "Acceso y seguridad".

Desde el servidor:
  docker exec musicapp-api python users.py                    # lista de usuarios
  docker exec musicapp-api python users.py aprobar <email>
  docker exec musicapp-api python users.py bloquear <email>    # también cierra sus sesiones
"""
import hashlib
import json
import os
import secrets
import sys
import threading
import time

USERS_FILE = "/data/users.json"         # sub de Google -> {email, name, picture, status, since, seen}
SESSIONS_FILE = "/data/sessions.json"   # sha256(sesión) -> {sub, until}
SESSION_DAYS = 90
MAX_PENDING = 30                        # tope de solicitudes sin revisar, para que nadie llene el archivo
STATUSES = ("pendiente", "aprobado", "bloqueado")


class JsonStore:
    """Un dict guardado en un .json. Se relee si otro proceso lo cambió (el comando de aprobar)."""

    def __init__(self, file):
        self.file = file
        self.lock = threading.RLock()
        self.data, self.mtime = {}, None
        self.reload()

    def reload(self):
        try:
            mtime = os.path.getmtime(self.file)
        except OSError:
            return
        if mtime != self.mtime:
            with self.lock, open(self.file) as f:
                self.data, self.mtime = json.load(f), mtime

    def save(self):
        tmp = self.file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.file)
        self.mtime = os.path.getmtime(self.file)


USERS = JsonStore(USERS_FILE)
SESSIONS = JsonStore(SESSIONS_FILE)


def _hash(session):
    return hashlib.sha256(session.encode()).hexdigest()


def public(sub, u):
    return {"id": sub, "email": u["email"], "name": u.get("name") or "", "picture": u.get("picture") or "",
            "status": u["status"]}


def login(claims):
    """Datos ya verificados del token de Google -> (usuario, sesión o None si no está aprobado).
    Lanza OverflowError si hay demasiadas solicitudes pendientes."""
    sub = claims["sub"]
    with USERS.lock:
        USERS.reload()
        u = USERS.data.get(sub)
        if u is None:
            if sum(x["status"] == "pendiente" for x in USERS.data.values()) >= MAX_PENDING:
                raise OverflowError
            u = USERS.data[sub] = {"status": "pendiente", "since": int(time.time())}
        u.update(email=claims["email"], name=claims.get("name") or "", picture=claims.get("picture") or "",
                 seen=int(time.time()))
        USERS.save()
    if u["status"] != "aprobado":
        return public(sub, u), None
    session = secrets.token_urlsafe(32)
    with SESSIONS.lock:
        SESSIONS.reload()
        now = time.time()
        SESSIONS.data = {k: s for k, s in SESSIONS.data.items() if s["until"] > now}   # de paso, limpia caducadas
        SESSIONS.data[_hash(session)] = {"sub": sub, "until": int(now + SESSION_DAYS * 86400)}
        SESSIONS.save()
    return public(sub, u), session


def user_of(session):
    """Sesión -> (sub, usuario) si es válida y el usuario sigue aprobado; si no, None."""
    s = SESSIONS.data.get(_hash(session))
    if not s or s["until"] < time.time():
        return None
    USERS.reload()
    u = USERS.data.get(s["sub"])
    return (s["sub"], u) if u and u["status"] == "aprobado" else None


def logout(session):
    with SESSIONS.lock:
        SESSIONS.reload()
        if SESSIONS.data.pop(_hash(session), None):
            SESSIONS.save()


def _cli(args):
    if not args:
        rows = sorted(USERS.data.items(), key=lambda kv: (STATUSES.index(kv[1]["status"]), kv[1]["since"]))
        for sub, u in rows:
            print(f"{u['status']:<10} {u['email']:<35} {u.get('name') or '':<25} "
                  f"desde {time.strftime('%Y-%m-%d', time.localtime(u['since']))}")
        print(f"{len(rows)} usuarios" if rows else "Nadie ha entrado todavía.")
        return 0
    action, who = (args + [""])[:2]
    status = {"aprobar": "aprobado", "bloquear": "bloqueado"}.get(action)
    if not status or not who:
        print(__doc__)
        return 1
    found = [sub for sub, u in USERS.data.items() if who in (sub, u["email"])]
    if not found:
        print(f"No hay nadie con '{who}'. Tiene que entrar con Google primero.")
        return 1
    for sub in found:
        USERS.data[sub]["status"] = status
    USERS.save()
    if status == "bloqueado":
        SESSIONS.data = {k: s for k, s in SESSIONS.data.items() if s["sub"] not in found}
        SESSIONS.save()
    print(f"{who}: {status}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
