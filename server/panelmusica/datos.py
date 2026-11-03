"""Lo que enseña el panel, leído de los archivos de la API, del bot y de Docker. Nada de aquí cambia datos salvo las
acciones del final (aprobar, bloquear, precarga, reiniciar), que usan la misma lógica que los comandos a mano.

Los archivos son del grupo `musicapp` (la API corre como el usuario 10001): `lainer` los lee por estar en ese grupo.
"""
import collections
import json
import os
import re
import shutil
import subprocess
import time
import unicodedata
import urllib.request
from datetime import datetime, timezone

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # ~/MusicApp/server
DATA = os.path.join(D, "data")
USERS = os.path.join(DATA, "users.json")
SESSIONS = os.path.join(DATA, "sessions.json")
USERDATA = os.path.join(DATA, "userdata.json")
PRECARGA = os.path.join(DATA, "precarga.json")
PRIMERO = os.path.join(DATA, "precarga-primero.txt")   # artistas que la precarga baja antes (:A)
SALTAR = os.path.join(DATA, "precarga-saltar.txt")     # álbumes o artistas enteros ("X | *") que no baja (:X)
YT_ESTADO = os.path.join(DATA, "youtube-estado.json")  # lo escribe la API cada 30 s y al bloquearnos
YT_BLOQUEOS = os.path.join(DATA, "youtube-bloqueos.jsonl")
GENEROS = os.path.join(DATA, "generos.json")
INDEX = "/var/lib/music/index.json"
MUSIC_DIR = "/var/lib/music"
RECOMENDAR = "/var/lib/musicapp/recomendar"
OPINIONES = os.path.join(RECOMENDAR, "opiniones.jsonl")
BOT_DATA = os.path.expanduser("~/MusicBot/data")
COMPOSE = os.path.join(D, "docker-compose.yml")
API = "http://127.0.0.1:8090"
API_CONT, BOT_CONT = "musicapp-api", "musicbot"
CONTENEDORES = {   # los de la música, en el orden en que salen
    API_CONT: "API de música", BOT_CONT: "Bot de Discord",
    "musicapp-cloudflared": "Túnel Cloudflare", "musicapp-tailscale": "Tailscale Funnel",
}
ORDEN = {"pendiente": 0, "aprobado": 1, "bloqueado": 2}
CONTEXTOS = {"radio": "radio", "para_ti": "Para ti", "vuelve": "Vuelve a escuchar", "busqueda": "búsqueda",
             "biblioteca": "biblioteca", "playlist": "playlist", "favoritas": "favoritas", "desconocido": ""}


# ---------- lectura con memoria: solo se vuelve a leer un archivo si cambió ----------

_cache = {}


def cargar(path, default=None, lineas=False):
    """JSON (o JSON por líneas) de 'path'; si no cambió desde la última vez, lo de memoria."""
    try:
        st = os.stat(path)
    except OSError:
        return default
    marca = (st.st_mtime_ns, st.st_size)
    hit = _cache.get(path)
    if hit and hit[0] == marca:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as f:
            data = [json.loads(x) for x in f if x.strip()] if lineas else json.load(f)
    except (OSError, ValueError):
        return hit[1] if hit else default   # a medio escribir: lo de antes
    _cache[path] = (marca, data)
    return data


def texto(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().splitlines()
    except OSError:
        return []


def escribir(path, rows):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    os.replace(tmp, path)


def norm(t):
    """Igual que Library._norm: sin mayúsculas, tildes ni signos ("Maná" == "mana")."""
    t = unicodedata.normalize("NFKD", (t or "").lower())
    return " ".join("".join(c if c.isalnum() else " " for c in t if not unicodedata.combining(c)).split())


def hace(t, ahora=None):
    """'ahora', 'hace 12 min', 'hace 3 h', 'ayer', 'hace 5 días'."""
    if not t:
        return "nunca"
    s = (ahora or time.time()) - t
    if s < 90:
        return "ahora"
    if s < 3600:
        return f"hace {int(s // 60)} min"
    if s < 86400:
        return f"hace {int(s // 3600)} h"
    return "ayer" if s < 2 * 86400 else f"hace {int(s // 86400)} días"


def fecha(t, formato="%d/%m %H:%M"):
    return datetime.fromtimestamp(t).strftime(formato) if t else "—"


def tamano(b):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024 or u == "TB":
            return f"{b:.1f} {u}" if u in ("GB", "TB") else f"{b:.0f} {u}"
        b /= 1024


# ---------- canciones ----------

def indice():
    return cargar(INDEX, {})


def cancion(vid, corto=False):
    """'Título · Artista' de una canción guardada (por su id de YouTube); el id si no está."""
    e = indice().get(f"yt-{vid}") or {}
    if not e:
        return vid
    t, a = e.get("title") or vid, e.get("artist") or ""
    return t if corto or not a else f"{t} · {a}"


def music_gb():
    """El tope de la biblioteca, el de docker-compose.yml (MUSIC_GB)."""
    m = re.search(r'MUSIC_GB:\s*"?([\d.]+)', "\n".join(texto(COMPOSE)))
    return float(m.group(1)) if m else 50.0


# ---------- usuarios ----------

def usuarios():
    """Todos, en orden fijo (pendientes primero, los más antiguos arriba; luego aprobados y bloqueados), con lo que
    hace cada uno: dispositivos, última canción, cuántas en 24 h, favoritas y playlists."""
    users, ses, ud = cargar(USERS, {}), cargar(SESSIONS, {}), cargar(USERDATA, {})
    ahora = time.time()
    app, web = collections.Counter(), collections.Counter()
    for s in ses.values():
        if s.get("until", 0) > ahora:
            (web if s.get("web") else app)[s.get("sub")] += 1
    out = []
    for sub, u in sorted(users.items(), key=lambda kv: (ORDEN.get(kv[1].get("status"), 9), kv[1].get("since", 0))):
        d = ud.get(sub) or {}
        h = d.get("history") or []
        out.append({
            "sub": sub, "email": u.get("email", ""), "nombre": u.get("name") or "", "estado": u.get("status", "?"),
            "pidio": u.get("since"), "visto": u.get("seen"), "admin": bool(u.get("admin")),
            "discord": (u.get("discord") or {}).get("name"),
            "dispositivos": app[sub], "web": web[sub],
            "ultima": h[0][1] if h else 0, "ultima_cancion": cancion(h[0][0]) if h else "",
            "dia": sum(1 for _, t in h if ahora - t < 86400),
            "favoritas": len(d.get("favorites") or []), "playlists": len(d.get("playlists") or []),
            "historial": [(vid, t) for vid, t in h[:15]],
        })
    return out


def nombres():
    """sub -> nombre corto (el nombre de Google o el principio del email)."""
    return {sub: (u.get("name") or u.get("email", "?").split("@")[0]).split()[0]
            for sub, u in cargar(USERS, {}).items()}


# ---------- actividad: app y web (eventos), Discord (registro del bot), API (registro de Docker) ----------

def eventos(horas=48):
    """Los eventos de las recomendaciones de las últimas 'horas' (este mes y el anterior)."""
    ahora, out = time.time(), []
    meses = {time.strftime("%Y-%m", time.gmtime(ahora - d * 86400)) for d in (0, horas / 24)}
    for m in sorted(meses):
        for e in cargar(os.path.join(RECOMENDAR, f"eventos-{m}.jsonl"), [], lineas=True):
            if ahora - e.get("cuando", 0) < horas * 3600:
                out.append(e)
    return out


BOT_LINEA = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) UTC \[([^\]]*)\] (\S+) (.*)$")


def bot_lineas(horas=48):
    """[(cuándo, servidor, texto)] del registro del bot de las últimas 'horas'."""
    ahora, out = time.time(), []
    meses = {time.strftime("%Y-%m", time.gmtime(ahora - d * 86400)) for d in (0, horas / 24)}
    for m in sorted(meses):
        for x in texto(os.path.join(BOT_DATA, f"registro-{m}.log")):
            r = BOT_LINEA.match(x)
            if not r:
                continue
            t = datetime.strptime(r.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
            if ahora - t < horas * 3600:
                out.append((t, r.group(2), r.group(4)))
    return out


API_LINEA = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ (\w+) ([\w.]+): (.*)$")


def registro_api(horas=48):
    """Del registro de la API (docker logs): bajadas, rechazadas y avisos/errores. Tarda ~0,3 s: va en segundo plano."""
    try:
        r = subprocess.run(["docker", "logs", "--since", f"{horas}h", API_CONT], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return {"bajadas": [], "avisos": [], "ok": False}
    bajadas, avisos = [], []
    for x in (r.stdout + r.stderr).splitlines():
        m = API_LINEA.match(x)
        if not m:
            if avisos and (x.startswith(" ") or x.startswith("Traceback")):   # lo que sigue a un error
                continue
            continue
        t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        nivel, msg = m.group(2), m.group(4)
        if msg.startswith("bajada: "):
            b = re.match(r"bajada: (.*) \((yt-[\w-]+|u-[\w-]+)\)$", msg)
            bajadas.append((t, b.group(1) if b else msg[8:], b.group(2) if b else ""))
        elif nivel in ("WARNING", "ERROR", "CRITICAL"):
            avisos.append((t, nivel, m.group(3), msg))
    return {"bajadas": bajadas, "avisos": avisos, "ok": r.returncode == 0}


def actividad(api_log, horas=48, n=300):
    """Lo que ha pasado, lo más nuevo primero: [(cuándo, de dónde, quién, qué, tipo)]."""
    who, out = nombres(), []
    for e in eventos(horas):
        tipo = e.get("tipo")
        if tipo == "inicio":
            ctx = CONTEXTOS.get(e.get("contexto") or "", e.get("contexto") or "")
            out.append((e["cuando"], "app", who.get(e.get("sub"), "?"), cancion(e.get("id")) + (f"  ({ctx})" if ctx else ""), "suena"))
        elif tipo in ("no_me_gusta", "ya_no_me_gusta"):
            out.append((e["cuando"], "app", who.get(e.get("sub"), "?"),
                        ("👎 " if tipo == "no_me_gusta" else "↩ ya le gusta: ") + cancion(e.get("id")), "opina"))
    for t, srv, msg in bot_lineas(horas):
        if "Sonando:" in msg:
            m = re.search(r"Sonando: (.*?)(?: · (?:💾|🌐)[^·]*)?(?: · pedida por (.*))?$", msg)
            out.append((t, "discord", (m.group(2) or "") if m else "", m.group(1) if m else msg, "suena"))
        elif any(k in msg for k in ("se salió", "paró", "⛔", "⚠️", "se unió", "entró")):
            out.append((t, "discord", "", re.sub(r"^\S+ ", "", msg), "aviso" if ("⛔" in msg or "⚠️" in msg) else "bot"))
    for t, titulo, _ in api_log.get("bajadas", []):
        out.append((t, "api", "", "⬇ guardada: " + titulo, "bajada"))
    for sub, u in cargar(USERS, {}).items():
        if time.time() - u.get("since", 0) < horas * 3600:
            out.append((u["since"], "api", who.get(sub, "?"), f"pidió acceso ({u.get('email')})", "acceso"))
    out.sort(key=lambda x: -x[0])
    return out[:n]


def por_hora(horas=24):
    """Reproducciones por hora en las últimas 'horas' (app/web y Discord), de la más vieja a la de ahora."""
    ahora = time.time()
    app, dc = [0] * horas, [0] * horas
    for e in eventos(horas):
        if e.get("tipo") == "inicio":
            i = int((ahora - e["cuando"]) // 3600)
            if 0 <= i < horas:
                app[horas - 1 - i] += 1
    for t, _, msg in bot_lineas(horas):
        if "Sonando:" in msg:
            i = int((ahora - t) // 3600)
            if 0 <= i < horas:
                dc[horas - 1 - i] += 1
    return app, dc


def escuchando(minutos=15):
    """Quién está escuchando ahora: [(quién, dónde, canción, cuándo)] (última canción hace menos de 'minutos')."""
    ahora, who = time.time(), nombres()
    ultimo = {}
    for e in eventos(1):
        if e.get("tipo") == "inicio" and ahora - e["cuando"] < minutos * 60:
            if e["cuando"] > ultimo.get(e.get("sub"), (0,))[0]:
                ultimo[e.get("sub")] = (e["cuando"], e.get("id"))
    out = [(who.get(sub, "?"), "app", cancion(vid), t) for sub, (t, vid) in ultimo.items()]
    por_srv = {}
    for t, srv, msg in bot_lineas(2):   # Discord: lo último de cada servidor, si no paró ni se salió después
        if "Sonando:" in msg or "se salió" in msg or "paró" in msg:
            por_srv[srv] = (t, msg)
    for srv, (t, msg) in por_srv.items():
        if "Sonando:" in msg and ahora - t < 30 * 60:
            m = re.search(r"Sonando: (.*?)(?: · (?:💾|🌐)[^·]*)?(?: · pedida por (.*))?$", msg)
            out.append((m.group(2) or srv if m else srv, "discord", m.group(1) if m else msg, t))
    return sorted(out, key=lambda x: -x[3])


# ---------- biblioteca ----------

def biblioteca():
    idx = indice()
    gen = {k: v.get("genre") for k, v in cargar(GENEROS, {}).items() if isinstance(v, dict)}
    canciones = [(k, e) for k, e in idx.items() if e.get("file")]
    usado = sum(e.get("size") or 0 for _, e in canciones)
    artistas, generos = collections.Counter(), collections.Counter()
    canciones_de = collections.Counter()
    for _, e in canciones:
        a = e.get("artist") or ""
        artistas[a] += e.get("plays") or 0
        canciones_de[a] += 1
        g = gen.get(norm(a)) or gen.get(norm(re.split(r",|&| feat\.| ft\.| x ", a)[0]))
        generos[g or "sin género"] += 1
    top = sorted(canciones, key=lambda kv: (-(kv[1].get("plays") or 0), -(kv[1].get("used") or 0)))[:40]
    disco = shutil.disk_usage(MUSIC_DIR)
    return {
        "canciones": len(canciones), "usado": usado, "tope": music_gb() * 1024 ** 3,
        "artistas": len([a for a in canciones_de if a]),
        "duracion": sum(e.get("duration") or 0 for _, e in canciones),
        "top": [(e.get("title") or k, e.get("artist") or "", e.get("plays") or 0) for k, e in top],
        "top_artistas": [(a, p, canciones_de[a]) for a, p in artistas.most_common(40) if a],
        "generos": generos.most_common(),
        "disco_libre": disco.free, "disco_total": disco.total,
    }


# ---------- precarga ----------

def precarga():
    """(texto, tipo) de cómo va la precarga de álbumes; tipo: parada, esperando, bajando o nada."""
    s = cargar(PRECARGA)
    if not s:
        return "sin empezar", "nada", {}
    now = s.get("now") or {}
    hechos = sum(1 for a in s.get("artists", {}).values() if a.get("done"))
    cuentas = {"bajadas": s.get("done", 0), "cola": len(s.get("queue", [])), "fallidas": s.get("failed", 0),
               "artistas_hechos": hechos, "artistas": now.get("artists_total") or len(s.get("lista") or [])}
    if s.get("paused_until", 0) > time.time():
        return f"PARADA hasta {fecha(s['paused_until'])} (YouTube avisó)", "parada", cuentas
    if now.get("mode") == "esperando":
        return "esperando: de día solo baja si nadie usa YouTube", "esperando", cuentas
    falta = max(0, (now.get("next_at") or 0) - time.time())
    sig = "ahora" if falta < 60 else f"en {int(falta // 60)} min"
    donde = f"{now.get('artist', '')} – {now.get('album', '')}" if now.get("artist") else "buscando álbumes"
    return f"{donde} · siguiente {sig}", "bajando", cuentas


def primeros():
    return [norm(x) for x in texto(PRIMERO) if x.strip() and not x.lstrip().startswith("#")]


def saltados():
    """{(artista, álbum)} normalizados de SALTAR; el artista entero ("Artista | *") queda como (artista, "")."""
    return {(norm(a), norm(b)) for a, _, b in (x.partition("|") for x in texto(SALTAR)
                                               if "|" in x and not x.lstrip().startswith("#"))}


def artistas_precarga():
    """Los artistas de la precarga en el orden en que irán: [(nombre, canciones, estado, álbumes)]."""
    st = cargar(PRECARGA)
    if not st:
        return []
    plan, now = st.get("artists", {}), st.get("now") or {}
    lista = st.get("lista") or [[n, "?"] for n in plan]
    first, skip = primeros(), saltados()
    rows = []
    for name, songs in lista:
        a, n = plan.get(name), norm(name)
        albums = [x for x in (a or {}).get("albums", []) if x.get("opened") or (n, norm(x["title"])) not in skip]
        abiertos = sum(1 for x in albums if x.get("opened"))
        albumes = "sin mirar" if a is None else f"{abiertos}/{len(albums)}"
        bajando = now.get("artist") == name and st.get("queue")
        acabado = a and (a.get("done") or abiertos == len(albums)) and not bajando
        estado = ("quitado" if (n, "") in skip else "hecho" if acabado else "bajando" if bajando else
                  "adelantado" if n in first else "pendiente")
        rows.append((name, songs, estado, albumes))
    turno = {"bajando": 0, "adelantado": 1, "pendiente": 2, "hecho": 3, "quitado": 4}
    return sorted(rows, key=lambda r: (turno[r[2]], first.index(norm(r[0])) if r[2] == "adelantado" else 0))


def adelantar(name):
    """Lo pone el primero de PRIMERO (sin repetirlo); los comentarios se quedan arriba."""
    rows = texto(PRIMERO)
    com = [x for x in rows if x.lstrip().startswith("#")] or [
        "# Un artista por línea: la precarga baja sus álbumes antes que los de los demás (en este orden)"]
    resto = [x for x in rows if x.strip() and not x.lstrip().startswith("#") and norm(x) != norm(name)]
    escribir(PRIMERO, com + [name] + resto)


def quitar(name, fuera=True):
    """Añade "Artista | *" a SALTAR (o lo borra si fuera=False) y lo saca de PRIMERO."""
    rows = [x for x in texto(SALTAR) if not ("|" in x and not x.lstrip().startswith("#")
                                             and norm(x.partition("|")[0]) == norm(name) and not norm(x.partition("|")[2]))]
    escribir(SALTAR, rows + ([f"{name} | *"] if fuera else []))
    if fuera and norm(name) in primeros():   # quitado ya no se adelanta
        escribir(PRIMERO, [x for x in texto(PRIMERO) if x.lstrip().startswith("#") or norm(x) != norm(name)])


# ---------- YouTube y opiniones ----------

def youtube():
    s = cargar(YT_ESTADO) or {}
    viejo = time.time() - s.get("cuando", 0) > 120
    return {"peticiones": s.get("peticiones_hora", 0), "tope": s.get("tope_hora", 300),
            "bloqueado_hasta": s.get("bloqueado_hasta") or 0, "ultimo": s.get("ultimo_bloqueo"),
            "sin_datos": not s or viejo,
            "bloqueos": list(reversed(cargar(YT_BLOQUEOS, [], lineas=True)[-20:]))}


def opiniones(dias=7):
    rows = [r for r in cargar(OPINIONES, [], lineas=True) if time.time() - r.get("cuando", 0) < dias * 86400]
    ops = collections.Counter(o for r in rows for o in r.get("opciones") or [])
    return {"si": sum(r.get("gusto") == "si" for r in rows), "no": sum(r.get("gusto") == "no" for r in rows),
            "top": ops.most_common(3), "textos": [(r.get("cuando"), r.get("texto")) for r in rows if r.get("texto")]}


# ---------- servicios ----------

def salud_api():
    """(funciona, milisegundos)."""
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(API + "/health", timeout=3) as r:
            return r.status == 200, (time.perf_counter() - t) * 1000
    except OSError:
        return False, 0


def contenedores():
    """Los de la música: {nombre: {estado, desde, reinicios, cpu, ram, ram_pct, imagen}}. Tarda ~2 s (docker stats)."""
    nombres_ = list(CONTENEDORES)
    out = {n: {"estado": "no existe"} for n in nombres_}
    try:
        r = subprocess.run(["docker", "inspect", "-f",
                            "{{.Name}}|{{.State.Status}}|{{.State.StartedAt}}|{{.RestartCount}}|{{.Config.Image}}|"
                            "{{if .State.Health}}{{.State.Health.Status}}{{end}}", *nombres_],
                           capture_output=True, text=True, timeout=15)
        for x in r.stdout.splitlines():
            n, estado, desde, reinicios, imagen, salud = x.split("|")
            n = n.lstrip("/")
            try:
                t = datetime.fromisoformat(desde[:26].rstrip("Z") + "+00:00").timestamp()
            except ValueError:
                t = 0
            out[n] = {"estado": estado, "desde": t, "reinicios": int(reinicios or 0), "imagen": imagen, "salud": salud}
        r = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}", *nombres_],
                           capture_output=True, text=True, timeout=20)
        for x in r.stdout.splitlines():
            s = json.loads(x)
            n = s.get("Name")
            if n in out:
                out[n].update(cpu=s.get("CPUPerc", "").rstrip("%"), ram=s.get("MemUsage", "").split(" / ")[0],
                              ram_pct=s.get("MemPerc", "").rstrip("%"))
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return out


def sistema():
    """Disco y carga del servidor."""
    raiz = shutil.disk_usage("/")
    try:
        carga = os.getloadavg()
    except OSError:
        carga = (0, 0, 0)
    try:
        mem = dict(x.split(":", 1) for x in texto("/proc/meminfo"))
        total = int(mem["MemTotal"].split()[0]) * 1024
        libre = int(mem["MemAvailable"].split()[0]) * 1024
    except (KeyError, ValueError):
        total = libre = 0
    return {"carga": carga, "cpus": os.cpu_count() or 1, "ram_total": total, "ram_libre": libre,
            "raiz_total": raiz.total, "raiz_libre": raiz.free}


# ---------- acciones ----------

def users_py(*args):
    """Lo mismo que `docker exec musicapp-api python users.py …` a mano: (bien, última línea de lo que dijo)."""
    try:
        r = subprocess.run(["docker", "exec", API_CONT, "python", "users.py", *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    lineas = (r.stdout or r.stderr).strip().splitlines()
    return r.returncode == 0, lineas[-1] if lineas else ""


def reiniciar(contenedor):
    try:
        r = subprocess.run(["docker", "restart", contenedor], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return r.returncode == 0, (r.stderr or r.stdout).strip()
