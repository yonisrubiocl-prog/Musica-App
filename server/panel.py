#!/usr/bin/env python3
"""Panel de usuarios de MusicApp (estilo htop, comandos estilo vim, como el de ProjectV1).

Uso: ~/MusicApp/server/panel.py     Todo se hace escribiendo un comando que empieza por ":" y Enter
(Esc cancela). :1 aprueba al número 1 de la lista, :H ayuda, :Q sale.
Lee data/users.json directamente; los cambios los hace `users.py` dentro del contenedor (misma lógica que
el comando a mano: bloquear también cierra sus sesiones).
"""
import curses
import curses.textpad
import json
import locale
import os
import subprocess
import threading
import time
import unicodedata
from datetime import datetime

D = os.path.dirname(os.path.abspath(__file__))
USERS = os.path.join(D, "data", "users.json")
USERDATA = os.path.join(D, "data", "userdata.json")   # historial de cada uno (última canción que pidió)
PRECARGA = os.path.join(D, "data", "precarga.json")   # cómo va la precarga de álbumes (precarga.py)
PRIMERO = os.path.join(D, "data", "precarga-primero.txt")   # artistas que la precarga baja antes (:A)
SALTAR = os.path.join(D, "data", "precarga-saltar.txt")     # álbumes o artistas enteros ("X | *") que no baja (:X)
OPINIONES = "/var/lib/musicapp/recomendar/opiniones.jsonl"
YT_ESTADO = os.path.join(D, "data", "youtube-estado.json")   # lo escribe la API cada 30 s y al bloquearnos   # "¿qué te parecieron las recomendaciones?"
CONT = "musicapp-api"
ORDEN = {"pendiente": 0, "aprobado": 1, "bloqueado": 2}
VERDE, AMARILLO, ROJO, CIAN, GRIS = 1, 2, 3, 4, 5
COLOR = {"pendiente": AMARILLO, "aprobado": VERDE, "bloqueado": ROJO}

AYUDA = [
    ("Cómo se usa", ""),
    ("", "Escribe ':' para empezar un comando, luego Enter. Esc cancela; las teclas sueltas no hacen nada."),
    ("", "Los números no cambian mientras escribes. Las solicitudes nuevas salen al final de las pendientes."),
    ("Comandos", ""),
    (":<n>", "Aprobar al número n.  Ej:  :1    Varios:  :1 3 4"),
    (":B <n>", "Bloquear al número n (pide confirmar). Cierra sus sesiones al momento."),
    (":P", "Ver los artistas de la precarga (y volver a usuarios). ↑↓ y RePág/AvPág para moverse."),
    (":A <n>", "En :P, adelantar al artista n: el siguiente en bajarse (si hay varios, el último adelantado primero)."),
    (":X <n>", "En :P, quitar al artista n de la precarga (pide confirmar). Otra vez :X lo devuelve."),
    (":H", "Esta ayuda."),
    (":Q", "Salir del panel (la API sigue igual)."),
    ("Para pedir acceso", ""),
    ("", "https://musica.yoneapolis.com/acceso  (entran con Google y quedan pendientes)"),
    ("Colores", ""),
    ("", "amarillo = pendiente · verde = aprobado · rojo = bloqueado"),
    ("Precarga", ""),
    ("", "Arriba: qué artista y álbum está bajando la precarga, cuándo baja la siguiente y cuántas lleva."),
    ("Abajo", ""),
    ("", "YouTube: normal (verde) o BLOQUEADO hasta… (rojo), y peticiones de la última hora."),
    ("", "Opiniones sobre las recomendaciones de los últimos 7 días: 👍/👎 y lo que más se marca."),
    ("Última canción", ""),
    ("", "Cuándo pidió su última canción en la app o la web (no cuenta Discord). Verde: hace menos de 1 h."),
]


def leer():
    """Usuarios en orden fijo: pendientes primero (los más antiguos arriba), luego aprobados y bloqueados."""
    try:
        with open(USERS, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return sorted(data.items(), key=lambda kv: (ORDEN.get(kv[1]["status"], 9), kv[1].get("since", 0)))


def ultimas():
    """sub -> (cuándo pidió su última canción, cuántas en las últimas 24 h)."""
    try:
        with open(USERDATA, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    ahora = time.time()
    return {sub: (h[0][1], sum(1 for _, t in h if ahora - t < 86400))
            for sub, d in data.items() if (h := d.get("history"))}


def precarga():
    """Una línea con cómo va la precarga de álbumes, y su color."""
    try:
        with open(PRECARGA, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        return "Precarga: sin empezar", GRIS
    now = s.get("now") or {}
    hechos = sum(1 for a in s.get("artists", {}).values() if a.get("done"))
    total = now.get("artists_total") or "?"
    cuentas = f"{s.get('done', 0)} bajadas · {len(s.get('queue', []))} en cola · artistas {hechos}/{total}"
    if s.get("failed"):
        cuentas += f" · {s['failed']} fallidas"
    if s.get("paused_until", 0) > time.time():
        return f"Precarga PARADA (YouTube avisó) hasta {fecha(s['paused_until'])} · {cuentas}", ROJO
    if now.get("mode") == "esperando":
        return f"Precarga esperando (de día solo si nadie usa YouTube) · {cuentas}", GRIS
    falta = max(0, (now.get("next_at") or 0) - time.time())
    sig = "ahora" if falta < 60 else f"en {int(falta // 60)} min"
    donde = f"{now.get('artist', '')} – {now.get('album', '')}" if now.get("artist") else "buscando álbumes"
    return f"Precarga ({now.get('mode', '?')}): {donde} · siguiente {sig} · {cuentas}", CIAN


def norm(t):
    """Igual que Library._norm: sin mayúsculas, tildes ni signos ("Maná" == "mana")."""
    t = unicodedata.normalize("NFKD", (t or "").lower())
    return " ".join("".join(c if c.isalnum() else " " for c in t if not unicodedata.combining(c)).split())


def lineas(path):
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


def primeros():
    return [norm(x) for x in lineas(PRIMERO) if x.strip() and not x.lstrip().startswith("#")]


def saltados():
    """{(artista, álbum)} normalizados de SALTAR; el artista entero ("Artista | *") queda como (artista, "")."""
    return {(norm(a), norm(b)) for a, _, b in (x.partition("|") for x in lineas(SALTAR)
                                               if "|" in x and not x.lstrip().startswith("#"))}


def artistas_precarga():
    """Los artistas de la precarga en el orden en que irán: [(nombre, canciones, estado, álbumes)]."""
    try:
        with open(PRECARGA, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        return []
    plan, now = st.get("artists", {}), st.get("now") or {}
    lista = st.get("lista") or [[n, "?"] for n in plan]
    first, skip = primeros(), saltados()
    rows = []
    for name, songs in lista:
        a, n = plan.get(name), norm(name)
        albums = [x for x in (a or {}).get("albums", []) if x.get("opened") or (n, norm(x["title"])) not in skip]
        abiertos = sum(1 for x in albums if x.get("opened"))
        albumes = "sin mirar" if a is None else f"{abiertos}/{len(albums)} álbumes"
        acabado = a and (a.get("done") or abiertos == len(albums)) and not (now.get("artist") == name and st.get("queue"))
        estado = ("quitado" if (n, "") in skip else "hecho" if acabado else
                  "bajando" if now.get("artist") == name and st.get("queue") else
                  "adelantado" if n in first else "pendiente")
        rows.append((name, songs, estado, albumes))
    turno = {"bajando": 0, "adelantado": 1, "pendiente": 2, "hecho": 3, "quitado": 4}
    return sorted(rows, key=lambda r: (turno[r[2]], first.index(norm(r[0])) if r[2] == "adelantado" else 0))


def adelantar(name):
    """Lo pone el primero de PRIMERO (sin repetirlo); los comentarios se quedan arriba."""
    rows = lineas(PRIMERO)
    com = [x for x in rows if x.lstrip().startswith("#")] or [
        "# Un artista por línea: la precarga baja sus álbumes antes que los de los demás (en este orden)"]
    resto = [x for x in rows if x.strip() and not x.lstrip().startswith("#") and norm(x) != norm(name)]
    escribir(PRIMERO, com + [name] + resto)


def quitar(name, fuera=True):
    """Añade "Artista | *" a SALTAR (o lo borra si fuera=False) y lo saca de PRIMERO."""
    rows = [x for x in lineas(SALTAR) if not ("|" in x and not x.lstrip().startswith("#")
                                              and norm(x.partition("|")[0]) == norm(name) and not norm(x.partition("|")[2]))]
    escribir(SALTAR, rows + ([f"{name} | *"] if fuera else []))
    if fuera and norm(name) in primeros():   # quitado ya no se adelanta
        escribir(PRIMERO, [x for x in lineas(PRIMERO) if x.lstrip().startswith("#") or norm(x) != norm(name)])


def youtube():
    """Una línea con cómo está YouTube (bloqueado o no, y peticiones en la última hora), y su color."""
    try:
        with open(YT_ESTADO, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        return "YouTube: sin datos (¿la API está encendida?)", GRIS
    if time.time() - s.get("cuando", 0) > 120:
        return "YouTube: sin datos recientes (¿la API está encendida?)", AMARILLO
    uso = f"{s.get('peticiones_hora', 0)} de {s.get('tope_hora', 300)} peticiones en la última hora"
    if s.get("bloqueado_hasta"):
        return f"YouTube: 🔴 BLOQUEADO hasta las {fecha(s['bloqueado_hasta'])[-5:]} (lo guardado suena igual) · {uso}", ROJO
    ult = s.get("ultimo_bloqueo")
    return f"YouTube: ✅ normal · {uso}" + (f" · último bloqueo: {fecha(ult['cuando'])}" if ult else " · nunca bloqueado"), VERDE


def opiniones():
    """Una línea con las opiniones sobre las recomendaciones de los últimos 7 días."""
    try:
        with open(OPINIONES, encoding="utf-8") as f:
            rows = [json.loads(x) for x in f if x.strip()]
    except (OSError, ValueError):
        rows = []
    rows = [r for r in rows if time.time() - r.get("cuando", 0) < 7 * 86400]
    if not rows:
        return "Recomendaciones: sin opiniones esta semana", GRIS
    si = sum(r.get("gusto") == "si" for r in rows)
    no = sum(r.get("gusto") == "no" for r in rows)
    ops = {}
    for r in rows:
        for o in r.get("opciones") or []:
            ops[o] = ops.get(o, 0) + 1
    top = " · ".join(f"{o.replace('_', ' ')} ×{n}" for o, n in sorted(ops.items(), key=lambda x: -x[1])[:3])
    textos = sum(1 for r in rows if r.get("texto"))
    return (f"Recomendaciones (7 días): 👍 {si}  👎 {no}" + (f" · {top}" if top else "")
            + (f" · {textos} comentario(s) en {OPINIONES}" if textos else "")), (VERDE if si >= no else AMARILLO)


def hace(t):
    """'ahora', 'hace 12 min', 'hace 3 h', 'ayer', 'hace 5 días'."""
    if not t:
        return "nunca"
    s = time.time() - t
    if s < 120:
        return "ahora"
    if s < 3600:
        return f"hace {int(s // 60)} min"
    if s < 86400:
        return f"hace {int(s // 3600)} h"
    return "ayer" if s < 2 * 86400 else f"hace {int(s // 86400)} días"


def fecha(t):
    return datetime.fromtimestamp(t).strftime("%d/%m %H:%M") if t else "—"


def users_py(*args):
    r = subprocess.run(["docker", "exec", CONT, "python", "users.py", *args],
                       capture_output=True, text=True, timeout=20)
    return r.returncode == 0, (r.stdout or r.stderr).strip().splitlines()[-1:] or [""]


class UI:
    def __init__(s, scr):
        s.scr = scr
        s.modo_cmd, s.buf = False, ""
        s.salir, s.ayuda = False, False
        s.msg, s.msg_color, s.msg_hora = "", 0, 0
        s.conf = None   # (texto, acción)
        s.lista = leer()
        s.vista, s.arts, s.desde = "usuarios", [], 0   # :P cambia a "precarga"; desde = primera fila que se ve

    def aviso(s, texto, color=0):
        s.msg, s.msg_color, s.msg_hora = texto, color, time.time()

    # -- dibujo
    def put(s, y, x, texto, color=0, bold=False):
        h, w = s.scr.getmaxyx()
        if y < 0 or y >= h or x >= w:
            return
        attr = curses.color_pair(color) | (curses.A_BOLD if bold else 0)
        try:
            s.scr.addstr(y, x, texto[: max(0, w - x - (1 if y == h - 1 else 0))], attr)
        except curses.error:
            pass

    def caja(s, y, x, h, w, titulo):
        try:
            curses.textpad.rectangle(s.scr, y, x, y + h - 1, x + w - 1)
        except curses.error:
            pass
        s.put(y, x + 2, f" {titulo} ", 0, True)

    def dibujar(s):
        s.scr.erase()
        H, W = s.scr.getmaxyx()
        if not s.modo_cmd and not s.conf:   # mientras se escribe, la lista (y sus números) no se mueve
            s.lista = leer()
        act = ultimas()
        n = {st: sum(u["status"] == st for _, u in s.lista) for st in ORDEN}
        s.put(0, 0, f" MusicApp · {s.vista}".ljust(W - 9) + time.strftime("%H:%M:%S"), 0, True)
        s.scr.chgat(0, 0, W, curses.A_REVERSE | curses.A_BOLD)
        s.put(1, 1, f"{n['pendiente']} pendientes", AMARILLO, True)
        s.put(1, 17, f"{n['aprobado']} aprobados", VERDE)
        s.put(1, 31, f"{n['bloqueado']} bloqueados", ROJO)
        texto, color = precarga()
        s.put(1, 46, "│ " + texto, color)

        texto, color = youtube()
        s.put(H - 3, 2, texto, color, color == ROJO)
        texto, color = opiniones()
        s.put(H - 2, 2, texto, color)
        if s.vista == "precarga":
            s.dibujar_precarga(H, W)
            if s.ayuda:
                s.dibujar_ayuda(H, W)
            return s.linea_cmd(H, W)
        s.caja(2, 0, H - 5, W, "USUARIOS")
        s.put(3, 2, f"{'#':>3}  {'estado':<10} {'email':<34} {'nombre':<22} {'pidió':<12} {'último login':<13} "
                    f"{'última canción':<14} {'24 h'}", GRIS, True)
        if not s.lista:
            s.put(5, 4, "Nadie ha pedido acceso todavía. Enlace: https://musica.yoneapolis.com/acceso", GRIS)
        for i, (sub, u) in enumerate(s.lista[: max(0, H - 9)], start=1):
            s.put(3 + i, 2, f"{i:>3}  ", 0, True)
            s.put(3 + i, 7, f"{u['status']:<10} ", COLOR.get(u["status"], 0), u["status"] == "pendiente")
            s.put(3 + i, 18, f"{u['email'][:33]:<34} {(u.get('name') or '')[:21]:<22} "
                             f"{fecha(u.get('since')):<12} {fecha(u.get('seen')):<13} ")
            t, dia = act.get(sub, (0, 0))
            reciente = t and time.time() - t < 3600
            s.put(3 + i, 104, f"{hace(t):<14} ", VERDE if reciente else (GRIS if not t or time.time() - t > 86400 else 0),
                  bool(reciente))
            s.put(3 + i, 119, f"{dia or '—'}", GRIS if not dia else 0)
        if len(s.lista) > H - 9:
            s.put(H - 5, 4, f"… y {len(s.lista) - (H - 9)} más (agranda la ventana)", GRIS)
        if s.ayuda:
            s.dibujar_ayuda(H, W)
        s.linea_cmd(H, W)

    def dibujar_precarga(s, H, W):
        if not s.modo_cmd and not s.conf:   # los números no se mueven mientras se escribe
            s.arts = artistas_precarga()
        filas = max(1, H - 9)
        s.desde = max(0, min(s.desde, len(s.arts) - filas))
        s.caja(2, 0, H - 5, W, f"PRECARGA · {len(s.arts)} ARTISTAS  (en orden; de los 3 primeros pendientes, uno al azar)")
        s.put(3, 2, f"{'#':>3}  {'estado':<11} {'artista':<36} {'canciones':>9}  {'álbumes'}", GRIS, True)
        color = {"bajando": CIAN, "adelantado": AMARILLO, "hecho": VERDE, "quitado": ROJO, "pendiente": 0}
        for i, (name, songs, estado, albumes) in enumerate(s.arts[s.desde: s.desde + filas], start=s.desde + 1):
            y = 3 + i - s.desde
            s.put(y, 2, f"{i:>3}  ", 0, True)
            s.put(y, 7, f"{estado:<11} ", color[estado], estado in ("bajando", "adelantado"))
            s.put(y, 19, f"{name[:35]:<36} {songs:>9}  {albumes}", GRIS if estado in ("hecho", "quitado") else 0)
        if len(s.arts) > filas:
            s.put(H - 5, 4, f" {s.desde + 1}–{min(len(s.arts), s.desde + filas)} de {len(s.arts)} · ↑↓ RePág AvPág ", GRIS)

    def linea_cmd(s, H, W):
        if s.conf:
            s.put(H - 1, 0, f"{s.conf[0]}   s = sí · n = no", AMARILLO, True)
        elif s.modo_cmd:
            s.put(H - 1, 0, ":" + s.buf, 0, True)
            try:
                curses.curs_set(1)
                s.scr.move(H - 1, min(W - 2, 1 + len(s.buf)))
            except curses.error:
                pass
            return
        elif s.msg and time.time() - s.msg_hora < 8:
            s.put(H - 1, 0, s.msg, s.msg_color, True)
        else:
            s.put(H - 1, 0, ":A 3 adelantar el 3  ·  :X 3 quitarlo  ·  :P volver a usuarios  ·  :H ayuda  ·  :Q salir"
                  if s.vista == "precarga" else
                  ":1 aprobar el 1  ·  :1 3 4 varios  ·  :B 2 bloquear  ·  :P precarga  ·  :H ayuda  ·  :Q salir", GRIS)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def dibujar_ayuda(s, H, W):
        w = min(W - 4, 100)
        h = min(H - 2, len(AYUDA) + 3)
        y, x = (H - h) // 2, (W - w) // 2
        for i in range(h):
            s.put(y + i, x, " " * w)
        s.caja(y, x, h, w, "AYUDA  (cualquier tecla para cerrar)")
        for i, (a, b) in enumerate(AYUDA[: h - 3]):
            if a and not b:
                s.put(y + 1 + i, x + 2, a, CIAN, True)
            else:
                s.put(y + 1 + i, x + 3, a, AMARILLO, True)
                s.put(y + 1 + i, x + 13, b[: w - 15])

    # -- comandos
    def elegir(s, texto):
        """'1 3 4' -> [(sub, usuario)] de la lista que se estaba viendo; None si algún número no existe."""
        try:
            nums = [int(t) for t in texto.split()]
        except ValueError:
            return None
        if not nums or any(not 1 <= k <= len(s.lista) for k in nums):
            return None
        return [s.lista[k - 1] for k in nums]

    def cambiar(s, accion, elegidos):
        hechos, fallos = [], []
        for sub, u in elegidos:
            ok, salida = users_py(accion, sub)
            (hechos if ok else fallos).append(u["email"] if ok else f"{u['email']} ({salida[0]})")
        palabra = "Aprobado" if accion == "aprobar" else "Bloqueado"
        if fallos:
            s.aviso(f"Falló: {', '.join(fallos)}", ROJO)
        else:
            s.aviso(f"{palabra}: {', '.join(hechos)}", VERDE if accion == "aprobar" else ROJO)

    def ejecutar(s, linea):
        linea = linea.strip()
        cmd = linea.upper()
        if cmd == "Q":
            s.salir = True
        elif cmd == "H":
            s.ayuda = True
        elif cmd == "P":
            s.vista = "usuarios" if s.vista == "precarga" else "precarga"
            s.desde = 0
        elif s.vista == "precarga":
            s.ejecutar_precarga(cmd, linea)
        elif cmd.startswith("B ") or cmd == "B":
            elegidos = s.elegir(linea[1:])
            if not elegidos:
                return s.aviso("Uso: :B <número de la lista>", ROJO)
            emails = ", ".join(u["email"] for _, u in elegidos)
            s.conf = (f"¿Bloquear a {emails}?", lambda: s.cambiar("bloquear", elegidos))
        elif linea[:1].isdigit():
            elegidos = s.elegir(linea)
            if not elegidos:
                return s.aviso(f"No hay número '{linea}' en la lista", ROJO)
            bloqueados = [u["email"] for _, u in elegidos if u["status"] == "bloqueado"]
            if bloqueados:   # desbloquear es raro: que no pase por un número mal puesto
                s.conf = (f"{', '.join(bloqueados)} está bloqueado. ¿Aprobar igual?",
                          lambda: s.cambiar("aprobar", elegidos))
            else:
                s.aviso("Aprobando…", GRIS)
                threading.Thread(target=s.cambiar, args=("aprobar", elegidos), daemon=True).start()
        elif linea:
            s.aviso(f"Comando desconocido: :{linea}   (:H ayuda)", ROJO)

    def ejecutar_precarga(s, cmd, linea):
        try:
            k = int(linea[1:].strip())
            assert k >= 1 and cmd[:1] in ("A", "X")
            name, _, estado, _ = s.arts[k - 1]
        except (ValueError, IndexError, AssertionError):
            return s.aviso("En :P:  :A <n> adelantar  ·  :X <n> quitar / devolver  ·  :P volver a usuarios", ROJO)
        if cmd[0] == "A":
            if estado == "quitado":
                return s.aviso(f"{name} está quitado: :X {k} para devolverlo antes", ROJO)
            adelantar(name)
            s.aviso(f"{name}: el siguiente en la precarga (cuando acabe el álbum que esté bajando)", VERDE)
        elif estado == "quitado":
            quitar(name, fuera=False)
            s.aviso(f"{name} vuelve a la precarga", VERDE)
        else:
            s.conf = (f"¿Quitar a {name} de la precarga? (lo ya bajado se queda)",
                      lambda: (quitar(name), s.aviso(f"{name} fuera de la precarga", ROJO)))

    # -- teclado
    def tecla(s, k):
        if s.ayuda:
            s.ayuda = False
            return
        if s.conf:
            if isinstance(k, str) and k.lower() == "s":
                accion, s.conf = s.conf[1], None
                threading.Thread(target=accion, daemon=True).start()
            elif k in ("n", "N", "\x1b", "\n", "\r"):
                s.conf = None
                s.aviso("Cancelado", GRIS)
            return
        if not s.modo_cmd:
            if k == ":":
                s.modo_cmd, s.buf = True, ""
            elif s.vista == "precarga":   # moverse por la lista de artistas
                paso = {curses.KEY_UP: -1, curses.KEY_DOWN: 1, curses.KEY_PPAGE: -15, curses.KEY_NPAGE: 15}.get(k, 0)
                s.desde = max(0, s.desde + paso)
            return
        if k == "\x1b":
            s.modo_cmd = False
        elif k in ("\n", "\r", curses.KEY_ENTER):
            s.modo_cmd = False
            linea, s.buf = s.buf, ""
            s.ejecutar(linea)
        elif k in (curses.KEY_BACKSPACE, "\x7f", "\b"):
            if s.buf:
                s.buf = s.buf[:-1]
            else:
                s.modo_cmd = False
        elif isinstance(k, str) and k.isprintable():
            s.buf += k


def main(scr):
    curses.curs_set(0)
    curses.use_default_colors()
    for i, c in enumerate([curses.COLOR_GREEN, curses.COLOR_YELLOW, curses.COLOR_RED, curses.COLOR_CYAN], start=1):
        curses.init_pair(i, c, -1)
    curses.init_pair(GRIS, 8 if curses.COLORS > 8 else curses.COLOR_WHITE, -1)
    curses.set_escdelay(25)
    scr.timeout(1000)   # se redibuja cada segundo: las solicitudes nuevas aparecen solas
    ui = UI(scr)
    while not ui.salir:
        ui.dibujar()
        scr.refresh()
        try:
            k = scr.get_wch()
        except curses.error:
            continue
        if k == curses.KEY_RESIZE:
            curses.update_lines_cols()
            continue
        ui.tecla(k)


if __name__ == "__main__":
    locale.setlocale(locale.LC_ALL, "")
    os.environ.setdefault("ESCDELAY", "25")
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    print("Panel cerrado. La API sigue funcionando igual.")
