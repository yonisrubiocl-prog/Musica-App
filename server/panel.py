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
from datetime import datetime

D = os.path.dirname(os.path.abspath(__file__))
USERS = os.path.join(D, "data", "users.json")
USERDATA = os.path.join(D, "data", "userdata.json")   # historial de cada uno (última canción que pidió)
PRECARGA = os.path.join(D, "data", "precarga.json")   # cómo va la precarga de álbumes (precarga.py)
OPINIONES = "/var/lib/musicapp/recomendar/opiniones.jsonl"   # "¿qué te parecieron las recomendaciones?"
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
    (":H", "Esta ayuda."),
    (":Q", "Salir del panel (la API sigue igual)."),
    ("Para pedir acceso", ""),
    ("", "https://musica.yoneapolis.com/acceso  (entran con Google y quedan pendientes)"),
    ("Colores", ""),
    ("", "amarillo = pendiente · verde = aprobado · rojo = bloqueado"),
    ("Precarga", ""),
    ("", "Arriba: qué artista y álbum está bajando la precarga, cuándo baja la siguiente y cuántas lleva."),
    ("Abajo", ""),
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
        s.put(0, 0, " MusicApp · usuarios".ljust(W - 9) + time.strftime("%H:%M:%S"), 0, True)
        s.scr.chgat(0, 0, W, curses.A_REVERSE | curses.A_BOLD)
        s.put(1, 1, f"{n['pendiente']} pendientes", AMARILLO, True)
        s.put(1, 17, f"{n['aprobado']} aprobados", VERDE)
        s.put(1, 31, f"{n['bloqueado']} bloqueados", ROJO)
        texto, color = precarga()
        s.put(1, 46, "│ " + texto, color)

        texto, color = opiniones()
        s.put(H - 2, 2, texto, color)
        s.caja(2, 0, H - 4, W, "USUARIOS")
        s.put(3, 2, f"{'#':>3}  {'estado':<10} {'email':<34} {'nombre':<22} {'pidió':<12} {'último login':<13} "
                    f"{'última canción':<14} {'24 h'}", GRIS, True)
        if not s.lista:
            s.put(5, 4, "Nadie ha pedido acceso todavía. Enlace: https://musica.yoneapolis.com/acceso", GRIS)
        for i, (sub, u) in enumerate(s.lista[: max(0, H - 8)], start=1):
            s.put(3 + i, 2, f"{i:>3}  ", 0, True)
            s.put(3 + i, 7, f"{u['status']:<10} ", COLOR.get(u["status"], 0), u["status"] == "pendiente")
            s.put(3 + i, 18, f"{u['email'][:33]:<34} {(u.get('name') or '')[:21]:<22} "
                             f"{fecha(u.get('since')):<12} {fecha(u.get('seen')):<13} ")
            t, dia = act.get(sub, (0, 0))
            reciente = t and time.time() - t < 3600
            s.put(3 + i, 104, f"{hace(t):<14} ", VERDE if reciente else (GRIS if not t or time.time() - t > 86400 else 0),
                  bool(reciente))
            s.put(3 + i, 119, f"{dia or '—'}", GRIS if not dia else 0)
        if len(s.lista) > H - 8:
            s.put(H - 4, 4, f"… y {len(s.lista) - (H - 8)} más (agranda la ventana)", GRIS)
        if s.ayuda:
            s.dibujar_ayuda(H, W)
        s.linea_cmd(H, W)

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
            s.put(H - 1, 0, ":1 aprobar el 1  ·  :1 3 4 varios  ·  :B 2 bloquear  ·  :H ayuda  ·  :Q salir", GRIS)
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
