"""Panel de la música en la terminal (Textual): Resumen, Usuarios, Actividad, Biblioteca, Precarga y Sistema.

Se manda como siempre: ':' abre la línea de comandos (:1 aprueba al 1, :B 2 bloquea, :H ayuda, :Q sale). Las teclas
sueltas solo mueven (1–6 cambian de pestaña, flechas, ratón): nada se aprueba ni se bloquea por accidente.
"""
import json
import os
import time

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import (Button, DataTable, Digits, Input, ProgressBar, Sparkline, Static, TabbedContent,
                             TabPane)

from . import datos as d

# Paletas (:T las cambia; se recuerda en ~/.config/panel-musica.json). "suave" es la de siempre; "app", los colores
# vivos de la app; "sobria", casi sin color.
PALETAS = {
    "suave": dict(violeta="#B4A2EE", rosa="#E3A6C6", azul="#8EAAEA", verde="#9DCB9F", amarillo="#E2C07E",
                  rojo="#E3909B", gris="#6F7488", texto="#C9CDDA", fondo="#0F1117", tarjeta="#151821", panel="#1B1F2A"),
    "app": dict(violeta="#9B5CFF", rosa="#F04DBB", azul="#5268FF", verde="#3DDC97", amarillo="#FFB547",
                rojo="#FF5C7A", gris="#7C7F93", texto="#FFFFFF", fondo="#080A12", tarjeta="#151725", panel="#1D2033"),
    "sobria": dict(violeta="#A3ADB9", rosa="#BCAEA0", azul="#93AABB", verde="#97B5A1", amarillo="#CDB98E",
                   rojo="#C99191", gris="#656B74", texto="#C6CACF", fondo="#111315", tarjeta="#171A1D", panel="#1D2023"),
}
PREFERENCIAS = os.path.expanduser("~/.config/panel-musica.json")


def aplicar_paleta(nombre):
    """Pone los colores de la paleta 'nombre' (los que usa el texto de las tablas) y devuelve su tema de Textual."""
    global VIOLETA, ROSA, AZUL, VERDE, AMARILLO, ROJO, GRIS, COLOR_ESTADO, COLOR_PRECARGA, ICONO, COLOR_TIPO
    p = PALETAS[nombre]
    VIOLETA, ROSA, AZUL = p["violeta"], p["rosa"], p["azul"]
    VERDE, AMARILLO, ROJO, GRIS = p["verde"], p["amarillo"], p["rojo"], p["gris"]
    COLOR_ESTADO = {"pendiente": AMARILLO, "aprobado": VERDE, "bloqueado": ROJO}
    COLOR_PRECARGA = {"bajando": AZUL, "adelantado": AMARILLO, "hecho": VERDE, "quitado": ROJO, "pendiente": ""}
    ICONO = {"app": ("📱", VIOLETA), "discord": ("🎧", AZUL), "api": ("⚙", GRIS)}
    COLOR_TIPO = {"suena": "", "opina": AMARILLO, "bajada": GRIS, "acceso": AMARILLO, "aviso": ROJO, "bot": GRIS}
    return Theme(name=f"musica-{nombre}", primary=VIOLETA, secondary=ROSA, accent=AZUL, foreground=p["texto"],
                 background=p["fondo"], surface=p["tarjeta"], panel=p["panel"], success=VERDE, warning=AMARILLO,
                 error=ROJO, dark=True)


def paleta_guardada():
    try:
        with open(PREFERENCIAS) as f:
            n = json.load(f).get("paleta")
        return n if n in PALETAS else "suave"
    except (OSError, ValueError):
        return "suave"


def guardar_paleta(nombre):
    try:
        os.makedirs(os.path.dirname(PREFERENCIAS), exist_ok=True)
        with open(PREFERENCIAS, "w") as f:
            json.dump({"paleta": nombre}, f)
    except OSError:
        pass


aplicar_paleta("suave")
PESTANAS = ["resumen", "usuarios", "actividad", "biblioteca", "precarga", "sistema"]
EQ = "▁▂▃▄▅▆▇█▇▆▅▄▃▂"
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
ESTADOS = {"running": "encendido", "exited": "apagado", "restarting": "reiniciando", "paused": "en pausa",
           "created": "creado", "dead": "muerto", "no existe": "no existe"}
SALUD = {"healthy": "sano", "unhealthy": "enfermo", "starting": "arrancando"}

AYUDA = [
    ("Cómo se usa", None),
    ("", "':' abre la línea de comandos; Enter la manda y Esc la cierra. Mientras escribes, los números no se mueven."),
    ("", "Las teclas sueltas solo mueven: 1–6 cambian de pestaña, flechas y ratón recorren las tablas."),
    ("", "Con el ratón: clic en un usuario o artista y usa sus botones. Todos piden confirmar antes de hacer nada."),
    ("En la pestaña Usuarios (2)", None),
    (":<n>", "Aprobar al número n.   Ej:  :1    Varios:  :1 3 4"),
    (":B <n>", "Bloquear al número n (pide confirmar). Cierra sus sesiones al momento."),
    (":ADM <n>", "Hacerle administrador (sin límite de dispositivos) o quitárselo."),
    ("En la pestaña Precarga (5)", None),
    (":A <n>", "Adelantar al artista n: el siguiente en bajarse (el último adelantado va primero)."),
    (":X <n>", "Quitar al artista n de la precarga (pide confirmar). Otra vez :X lo devuelve."),
    ("En la pestaña Sistema (6)", None),
    (":R API", "Reiniciar la API (pide confirmar). La música se corta unos segundos para todos."),
    (":R BOT", "Reiniciar el bot de Discord (pide confirmar). Corta lo que suene; luego pregunta «¿Seguimos?»."),
    ("En cualquier pestaña", None),
    (":T", "Cambiar de paleta de colores (suave, app, sobria). Se recuerda para la próxima vez."),
    (":H", "Esta ayuda.          :Q  Salir (la API sigue igual)."),
    ("Pestañas", None),
    ("1 Resumen", "Servicios, quién escucha ahora, biblioteca, YouTube, precarga y reproducciones de las últimas 24 h."),
    ("2 Usuarios", "Todos, con dispositivos, última canción y canciones en 24 h. A la derecha, el elegido en detalle."),
    ("3 Actividad", "Lo que pasa: canciones en la app, la web y Discord, bajadas, solicitudes de acceso."),
    ("4 Biblioteca", "Lo más puesto, los artistas que más suenan y los géneros."),
    ("5 Precarga", "Los artistas cuyos álbumes se bajan solos, en el orden en que irán."),
    ("6 Sistema", "Contenedores (CPU, RAM, desde cuándo), disco, bloqueos de YouTube y avisos del registro de la API."),
    ("Colores", None),
    ("", "amarillo = pendiente · verde = aprobado · rojo = bloqueado · violeta = app/web · azul = Discord"),
    ("Para pedir acceso", None),
    ("", "https://musica.yoneapolis.com/acceso  (entran con Google y quedan pendientes)"),
]


def t(texto, color="", bold=False, dim=False):
    return Text(str(texto), style=" ".join(x for x in (color, "bold" if bold else "", "dim" if dim else "") if x))


def corta(texto, n):
    texto = texto or ""
    return texto if len(texto) <= n else texto[: n - 1] + "…"


def punto(bien, aviso=False):
    return t("●", VERDE if bien else (AMARILLO if aviso else ROJO))


def tabla_igual(tabla, filas):
    """¿La tabla ya enseña estas filas? (para no repintarla y que no salte el cursor)."""
    firma = hash(tuple(tuple(str(c) for c in f[1]) for f in filas))
    if getattr(tabla, "_firma", None) == firma:
        return True
    tabla._firma = firma
    return False


def rellenar(tabla, filas):
    """filas = [(clave, celdas)]; mantiene la fila elegida si sigue estando."""
    if tabla_igual(tabla, filas):
        return
    fila = tabla.cursor_row
    tabla.clear()
    for clave, celdas in filas:
        tabla.add_row(*celdas, key=clave)
    if filas:
        tabla.move_cursor(row=min(fila, len(filas) - 1), animate=False, scroll=False)


# ---------- ventanas ----------

class Confirmar(ModalScreen[bool]):
    BINDINGS = [Binding("s,y", "si", "Sí"), Binding("n,escape", "no", "No")]

    def __init__(self, pregunta, detalle=""):
        super().__init__()
        self.pregunta, self.detalle = pregunta, detalle

    def compose(self) -> ComposeResult:
        with Vertical(id="caja-confirmar"):
            yield Static(self.pregunta, id="pregunta")
            if self.detalle:
                yield Static(self.detalle, classes="sub")
            with Horizontal(id="botones"):
                yield Button("No (n)", id="no")
                yield Button("Sí (s)", id="si", variant="warning")

    def on_button_pressed(self, ev: Button.Pressed):
        self.dismiss(ev.button.id == "si")

    def action_si(self):
        self.dismiss(True)

    def action_no(self):
        self.dismiss(False)


class Ayuda(ModalScreen):
    BINDINGS = [Binding("escape,q,h,enter,space", "cerrar", "Cerrar")]

    def compose(self) -> ComposeResult:
        texto = Text()
        for a, b in AYUDA:
            if b is None:
                texto.append(f"\n{a}\n", style=f"bold {VIOLETA}")
            else:
                texto.append(f"  {a:<12}", style=f"bold {AMARILLO}")
                texto.append(f"{b}\n")
        with VerticalScroll(id="caja-ayuda") as caja:
            caja.border_title = "Ayuda · Esc para cerrar"
            yield Static(texto)

    def action_cerrar(self):
        self.dismiss()

    def on_click(self):
        self.dismiss()


# ---------- el panel ----------

class Panel(App):
    CSS_PATH = "panel.tcss"
    TITLE = "Música · panel"
    AUTO_FOCUS = None   # nada enfocado al empezar: así 1–6 cambian de pestaña
    BINDINGS = [
        Binding("colon", "comando", "Comando", show=False),
        Binding("escape", "cerrar_comando", show=False),
        *[Binding(str(i + 1), f"pestana('{p}')", show=False) for i, p in enumerate(PESTANAS)],
    ]

    def __init__(self):
        super().__init__()
        self.usuarios, self.congelados = [], None   # congelados: la lista que valía al abrir ':' (los números no se mueven)
        self.arts, self.arts_congelados = [], None
        self.api_log = {"bajadas": [], "avisos": []}
        self.conts, self.salud = {}, (None, 0)
        self.aviso_hasta, self.paso = 0, 0
        self.escuchan = []
        self.confirmando = False

    # -- construcción
    def compose(self) -> ComposeResult:
        with Horizontal(id="barra"):
            yield Static("♪ MÚSICA · panel", id="marca")
            yield Static("", id="servicios")
            yield Static("", id="reloj")
        with TabbedContent(id="tabs", initial="resumen"):
            with TabPane("1 Resumen", id="resumen"):
                with VerticalScroll():
                    with Grid(id="g-resumen"):
                        with Vertical(classes="tarjeta", id="c-usuarios"):
                            yield Digits("0", id="d-aprobados")
                            yield Static("", id="u-sub", classes="sub")
                        with Vertical(classes="tarjeta", id="c-biblioteca"):
                            yield Digits("0", id="d-canciones")
                            yield ProgressBar(total=100, show_eta=False, id="p-espacio")
                            yield Static("", id="b-sub", classes="sub")
                        with Vertical(classes="tarjeta", id="c-youtube"):
                            yield Static("", id="yt-estado")
                            yield ProgressBar(total=300, show_eta=False, id="p-youtube")
                            yield Static("", id="yt-sub", classes="sub")
                        with Vertical(classes="tarjeta", id="c-servicios"):
                            yield Static("", id="srv-lista")
                        with Vertical(classes="tarjeta ancho2", id="c-escuchando"):
                            yield Static("", id="escuchando")
                        with Vertical(classes="tarjeta ancho2", id="c-precarga"):
                            yield Static("", id="pre-linea")
                            yield ProgressBar(total=100, show_eta=False, id="p-precarga")
                            yield Static("", id="pre-sub", classes="sub")
                        with Vertical(classes="tarjeta ancho4", id="c-horas"):
                            yield Static("", id="h-app", classes="eje")
                            yield Sparkline([0] * 24, id="sp-app")
                            yield Static("", id="h-dc", classes="eje")
                            yield Sparkline([0] * 24, id="sp-dc")
                            yield Static("", id="h-eje", classes="eje")
                        with Vertical(classes="tarjeta ancho4", id="c-ultimo"):
                            yield Static("", id="ultimo")
            with TabPane("2 Usuarios", id="usuarios"):
                with Horizontal(id="p-usuarios"):
                    yield DataTable(id="t-usuarios", cursor_type="row", zebra_stripes=True)
                    with VerticalScroll(classes="tarjeta", id="detalle"):
                        with Horizontal(id="u-botones", classes="botones"):
                            yield Button("✓ Aprobar", id="b-aprobar", variant="success", compact=True)
                            yield Button("⊘ Bloquear", id="b-bloquear", variant="error", compact=True)
                            yield Button("★ Administrador", id="b-admin", variant="primary", compact=True)
                        yield Static("", id="detalle-texto")
            with TabPane("3 Actividad", id="actividad"):
                yield DataTable(id="t-actividad", cursor_type="row", zebra_stripes=True)
            with TabPane("4 Biblioteca", id="biblioteca"):
                with Horizontal(id="b-cifras"):
                    with Vertical(classes="tarjeta", id="bc-1"):
                        yield Static("", id="bc-canciones")
                    with Vertical(classes="tarjeta", id="bc-2"):
                        yield Static("", id="bc-espacio")
                        yield ProgressBar(total=100, show_eta=False, id="p-espacio2")
                    with Vertical(classes="tarjeta", id="bc-3"):
                        yield Static("", id="bc-disco")
                        yield ProgressBar(total=100, show_eta=False, id="p-disco")
                with Horizontal(id="b-tablas"):
                    yield DataTable(id="t-top", cursor_type="row", zebra_stripes=True)
                    yield DataTable(id="t-artistas", cursor_type="row", zebra_stripes=True)
                    yield DataTable(id="t-generos", cursor_type="row", zebra_stripes=True)
            with TabPane("5 Precarga", id="precarga"):
                yield Static("", id="pre-resumen")
                with Horizontal(id="pre-botones", classes="botones"):
                    yield Static("", id="pre-elegido")
                    yield Button("⏫ Adelantar", id="b-adelantar", variant="primary", compact=True)
                    yield Button("✕ Quitar", id="b-quitar", variant="error", compact=True)
                yield DataTable(id="t-precarga", cursor_type="row", zebra_stripes=True)
            with TabPane("6 Sistema", id="sistema"):
                with Horizontal(id="s-arriba"):
                    yield DataTable(id="t-contenedores", cursor_type="row", show_cursor=False)
                    with Vertical(classes="tarjeta", id="s-servidor"):
                        yield Static("", id="s-texto")
                        yield ProgressBar(total=100, show_eta=False, id="p-ram")
                        yield Static("", id="s-texto2")
                        yield ProgressBar(total=100, show_eta=False, id="p-raiz")
                        with Horizontal(id="s-botones", classes="botones"):
                            yield Button("↻ Reiniciar API", id="b-r-api", variant="warning", compact=True)
                            yield Button("↻ Reiniciar bot", id="b-r-bot", variant="warning", compact=True)
                with Horizontal(id="s-abajo"):
                    yield DataTable(id="t-avisos", cursor_type="row", zebra_stripes=True)
                    yield DataTable(id="t-bloqueos", cursor_type="row", zebra_stripes=True)
        yield Static("", id="mensaje")
        cmd = Input(id="cmd", placeholder="comando (Enter para mandarlo, Esc para cancelar)")
        cmd.can_focus = False   # escondida no recibe teclas: solo al abrirla con ':'
        yield cmd

    def on_mount(self):
        for n in PALETAS:
            self.register_theme(aplicar_paleta(n))
        self.paleta = paleta_guardada()
        aplicar_paleta(self.paleta)
        self.theme = f"musica-{self.paleta}"
        titulos = {"c-usuarios": "Usuarios", "c-biblioteca": "Biblioteca", "c-youtube": "YouTube",
                   "c-servicios": "Servicios", "c-escuchando": "Escuchando ahora", "c-precarga": "Precarga de álbumes",
                   "c-horas": "Reproducciones · últimas 24 h", "c-ultimo": "Lo último", "detalle": "Detalle",
                   "bc-1": "Canciones", "bc-2": "Espacio de la música", "bc-3": "Disco /var",
                   "s-servidor": "Servidor", "t-contenedores": "Contenedores", "t-avisos": "Avisos y errores de la API (48 h)",
                   "t-bloqueos": "Bloqueos de YouTube", "t-top": "Lo más puesto", "t-artistas": "Artistas que más suenan",
                   "t-generos": "Géneros"}
        for i, titulo in titulos.items():
            self.query_one(f"#{i}").border_title = titulo
        cols = {
            "t-usuarios": ["#", "Estado", "Nombre", "Disp.", "Escuchó", "24 h", "♥", "Listas", "Última canción", "Email"],
            "t-actividad": ["Hora", "", "Quién", "Qué"],
            "t-top": ["#", "Canción", "Artista", "Veces"],
            "t-artistas": ["#", "Artista", "Veces", "Canciones"],
            "t-generos": ["Género", "Canciones", ""],
            "t-precarga": ["#", "Estado", "Artista", "Canciones", "Álbumes"],
            "t-contenedores": ["Servicio", "Estado", "Desde", "Reinicios", "CPU", "RAM", "Imagen"],
            "t-avisos": ["Hora", "Nivel", "Mensaje"],
            "t-bloqueos": ["Cuándo", "Hasta", "Peticiones/h", "Por"],
        }
        for i, c in cols.items():
            self.query_one(f"#{i}", DataTable).add_columns(*c)
        for b in self.query(".botones Button"):   # responden al clic sin quedarse el foco: así 1–6 siguen cambiando de pestaña
            b.can_focus = False
        self.on_resize()
        self.set_interval(1, self.reloj)
        self.set_interval(0.2, self.animar)
        self.set_interval(2, self.leer_rapido)
        self.set_interval(10, self.leer_lento)
        self.leer_rapido()
        self.leer_lento()
        self.pista()

    def on_resize(self, _=None):
        self.screen.set_class(self.size.width < 120, "estrecho")

    # -- lectura en segundo plano
    @work(thread=True, exclusive=True, group="rapido")
    def leer_rapido(self):
        try:
            r = {"usuarios": d.usuarios(), "biblioteca": d.biblioteca(), "horas": d.por_hora(),
                 "escuchan": d.escuchando(), "precarga": d.precarga(), "arts": d.artistas_precarga(),
                 "youtube": d.youtube(), "opiniones": d.opiniones(), "salud": d.salud_api(), "sistema": d.sistema(),
                 "actividad": d.actividad(self.api_log)}
        except Exception as e:   # un archivo raro no tumba el panel: se avisa y se sigue
            self.call_from_thread(self.avisar, f"No pude leer los datos: {e}", "mal")
            return
        self.call_from_thread(self.pintar, r)

    @work(thread=True, exclusive=True, group="lento")
    def leer_lento(self):
        conts, log = d.contenedores(), d.registro_api()
        self.call_from_thread(self.pintar_lento, conts, log)

    # -- pintar
    def pintar(self, r):
        self.salud = r["salud"]
        self.escuchan = r["escuchan"]
        if self.congelados is None:
            self.usuarios = r["usuarios"]
        if self.arts_congelados is None:
            self.arts = r["arts"]
        self.pintar_resumen(r)
        self.pintar_usuarios()
        self.pintar_actividad(r["actividad"])
        self.pintar_biblioteca(r["biblioteca"])
        self.pintar_precarga(r["precarga"])
        self.pintar_sistema(r["sistema"], r["youtube"])
        self.pintar_servicios()

    def pintar_servicios(self):
        api_ok, ms = self.salud
        partes = Text()
        partes.append_text(punto(api_ok))
        partes.append(f" API {int(ms)} ms   " if api_ok else " API caída   ")
        for n, nombre in (("musicbot", "Bot"), ("musicapp-cloudflared", "Túnel"), ("musicapp-tailscale", "Funnel")):
            c = self.conts.get(n)
            if c:
                partes.append_text(punto(c.get("estado") == "running"))
                partes.append(f" {nombre}   ")
        n = len(self.escuchan)
        if n:
            partes.append(f"♪ {n} escuchando", style=f"bold {ROSA}")
        self.query_one("#servicios", Static).update(partes)
        lista = Text()
        lista.append_text(punto(api_ok))
        lista.append(" API de música", style="bold")
        lista.append(f"  {int(ms)} ms\n" if api_ok else "  no responde\n", style=GRIS if api_ok else ROJO)
        for n, nombre in d.CONTENEDORES.items():
            if n == d.API_CONT:
                continue
            c = self.conts.get(n)
            if not c:
                lista.append("● ", style=GRIS)
                lista.append(f"{nombre}\n", style=GRIS)
                continue
            vivo = c.get("estado") == "running"
            lista.append_text(punto(vivo))
            lista.append(f" {nombre}", style="bold")
            lista.append(f"  {d.hace(c.get('desde')).replace('hace ', '')}\n" if vivo else f"  {c.get('estado')}\n",
                         style=GRIS if vivo else ROJO)
        self.query_one("#srv-lista", Static).update(lista)
        caidos = (not api_ok) or any(c.get("estado") != "running" for c in self.conts.values())
        self.query_one("#c-servicios").set_class(bool(self.conts) and caidos, "mal")

    def pintar_resumen(self, r):
        us = r["usuarios"]
        cuenta = {e: sum(u["estado"] == e for u in us) for e in d.ORDEN}
        hoy = sum(1 for u in us if u["dia"])
        self.query_one("#d-aprobados", Digits).update(str(cuenta["aprobado"]))
        sub = Text()
        if cuenta["pendiente"]:
            sub.append(f"⚠ {cuenta['pendiente']} pendiente(s): pestaña 2\n", style=f"bold {AMARILLO}")
        sub.append(f"usuarios · {hoy} escucharon hoy")
        if cuenta["bloqueado"]:
            sub.append(f" · {cuenta['bloqueado']} bloqueado(s)", style=ROJO)
        self.query_one("#u-sub", Static).update(sub)
        self.query_one("#c-usuarios").set_class(bool(cuenta["pendiente"]), "alerta")

        b = r["biblioteca"]
        self.query_one("#d-canciones", Digits).update(str(b["canciones"]))
        pct = 100 * b["usado"] / b["tope"] if b["tope"] else 0
        self.query_one("#p-espacio", ProgressBar).update(total=100, progress=pct)
        nuevas = sum(1 for x in self.api_log.get("bajadas", []) if time.time() - x[0] < 86400)
        self.query_one("#b-sub", Static).update(Text.assemble(
            f"{d.tamano(b['usado'])} de {d.tamano(b['tope'])}",
            (f" · +{nuevas} hoy" if nuevas else "", f"bold {VERDE}")))

        yt = r["youtube"]
        bloqueado = yt["bloqueado_hasta"] > time.time()
        if yt["sin_datos"]:
            estado = t("● sin datos (¿API apagada?)", AMARILLO, True)
        elif bloqueado:
            estado = t(f"● BLOQUEADO hasta las {d.fecha(yt['bloqueado_hasta'], '%H:%M')}", ROJO, True)
        else:
            estado = t("● normal", VERDE, True)
        self.query_one("#yt-estado", Static).update(estado)
        self.query_one("#p-youtube", ProgressBar).update(total=yt["tope"] or 300, progress=yt["peticiones"])
        ult = yt["ultimo"]
        self.query_one("#yt-sub", Static).update(
            f"{yt['peticiones']} de {yt['tope']} peticiones/h\n"
            + (f"último bloqueo {d.hace(ult.get('cuando'))}" if ult else "nunca nos ha bloqueado"))
        self.query_one("#c-youtube").set_class(bloqueado, "mal")

        texto, tipo, c = r["precarga"]
        color = {"parada": ROJO, "esperando": GRIS, "bajando": AZUL}.get(tipo, GRIS)
        self.query_one("#pre-linea", Static).update(t(texto, color, tipo != "esperando"))
        if c:
            self.query_one("#p-precarga", ProgressBar).update(total=max(1, c["artistas"]), progress=c["artistas_hechos"])
            self.query_one("#pre-sub", Static).update(
                f"artistas {c['artistas_hechos']} de {c['artistas']} · {c['bajadas']} canciones bajadas · "
                f"{c['cola']} en cola" + (f" · {c['fallidas']} fallidas" if c["fallidas"] else ""))
        self.query_one("#c-precarga").set_class(tipo == "parada", "mal")

        app, dc = r["horas"]
        sa, sd = sum(app), sum(dc)
        self.query_one("#sp-app", Sparkline).data = app
        self.query_one("#sp-dc", Sparkline).data = dc
        self.query_one("#h-app", Static).update(Text.assemble(("📱 app y web ", f"bold {VIOLETA}"),
                                                              (f"{sa} canciones · máx {max(app)}/h", GRIS)))
        self.query_one("#h-dc", Static).update(Text.assemble(("🎧 Discord ", f"bold {AZUL}"),
                                                             (f"{sd} canciones · máx {max(dc)}/h", GRIS)))
        ancho = max(10, self.query_one("#sp-app").size.width)
        self.query_one("#h-eje", Static).update("hace 24 h".ljust(ancho - 5) + "ahora")

        ult = Text()
        for x in r["actividad"][:12]:
            self.linea_actividad(ult, x)
        self.query_one("#ultimo", Static).update(ult or t("Nada en las últimas 48 h.", GRIS))

    def linea_actividad(self, texto, x):
        cuando, donde, quien, que, tipo = x
        icono, color = ICONO.get(donde, ("·", GRIS))
        texto.append(f"{d.fecha(cuando, '%H:%M')} ", style=GRIS)
        texto.append(f"{icono} ")
        if quien:
            texto.append(f"{quien} ", style=color)
        texto.append(f"{que}\n", style=COLOR_TIPO.get(tipo, ""))

    def animar(self):
        self.paso += 1
        caja = self.query_one("#escuchando", Static)
        if not self.escuchan:
            caja.update(t("Nadie está escuchando ahora mismo.", GRIS))
            return
        out = Text()
        for i, (quien, donde, cancion, cuando) in enumerate(self.escuchan[:6]):
            icono, color = ICONO[donde]
            barras = "".join(EQ[(self.paso + i * 3 + k * 5) % len(EQ)] for k in range(4))
            out.append(f"{barras} ", style=ROSA)
            out.append(f"{icono} {corta(quien, 14)}", style=f"bold {color}")
            out.append(f" {cancion}", style="")
            out.append(f"  {d.hace(cuando)}\n", style=GRIS)
        caja.update(out)

    def pintar_usuarios(self):
        filas = []
        for i, u in enumerate(self.usuarios, start=1):
            reciente = u["ultima"] and time.time() - u["ultima"] < 3600
            filas.append((u["sub"], [
                t(i, bold=True), t(u["estado"], COLOR_ESTADO.get(u["estado"], ""), u["estado"] == "pendiente"),
                t(corta(u["nombre"], 24) + (" ★" if u["admin"] else "")),
                t(f"{u['dispositivos']}" + (f"+{u['web']}w" if u["web"] else "")),
                t(d.hace(u["ultima"]), VERDE if reciente else GRIS, bool(reciente)),
                t(u["dia"] or "—", "" if u["dia"] else GRIS), t(u["favoritas"] or "—", ROSA if u["favoritas"] else GRIS),
                t(u["playlists"] or "—", "" if u["playlists"] else GRIS),
                t(corta(u["ultima_cancion"], 42) or "—", "" if u["ultima_cancion"] else GRIS), t(u["email"], GRIS)]))
        tabla = self.query_one("#t-usuarios", DataTable)
        rellenar(tabla, filas)
        self.pintar_detalle()

    def pintar_detalle(self):
        tabla = self.query_one("#t-usuarios", DataTable)
        if not self.usuarios:
            self.query_one("#detalle-texto", Static).update(
                t("Nadie ha pedido acceso todavía.\nEnlace: https://musica.yoneapolis.com/acceso", GRIS))
            return
        u = self.usuarios[min(tabla.cursor_row, len(self.usuarios) - 1)]
        self.query_one("#b-aprobar").display = u["estado"] != "aprobado"
        self.query_one("#b-aprobar", Button).label = "✓ Desbloquear" if u["estado"] == "bloqueado" else "✓ Aprobar"
        self.query_one("#b-bloquear").display = u["estado"] != "bloqueado"
        self.query_one("#b-admin").display = u["estado"] == "aprobado"
        self.query_one("#b-admin", Button).label = "☆ Quitar administrador" if u["admin"] else "★ Hacer administrador"
        x = Text()
        x.append(f"{u['nombre'] or u['email']}\n", style=f"bold {VIOLETA}")
        x.append(f"{u['email']}\n", style=GRIS)
        x.append(f"{u['estado']}", style=f"bold {COLOR_ESTADO.get(u['estado'], '')}")
        x.append("  ·  administrador (sin límite)\n" if u["admin"] else "\n", style=AMARILLO)
        filas = [("Pidió acceso", d.fecha(u["pidio"])), ("Último login", d.fecha(u["visto"])),
                 ("Dispositivos", f"{u['dispositivos']} de la app" + (f" + {u['web']} web" if u["web"] else "")
                  + ("" if u["admin"] else " (máx. 3)")),
                 ("Discord", u["discord"] or "sin vincular"),
                 ("Favoritas", str(u["favoritas"])), ("Playlists", str(u["playlists"])),
                 ("Canciones 24 h", str(u["dia"]))]
        for a, b in filas:
            x.append(f"{a:<15}", style=GRIS)
            x.append(f"{b}\n")
        if u["historial"]:
            x.append("\nÚltimas canciones\n", style=f"bold {ROSA}")
            ancho = max(20, self.query_one("#detalle").size.width - 18)
            for vid, cuando in u["historial"][:15]:
                x.append(f"{d.hace(cuando).replace('hace ', ''):>7}  ", style=GRIS)
                x.append(f"{corta(d.cancion(vid), ancho)}\n")
        self.query_one("#detalle-texto", Static).update(x)
        self.query_one("#detalle").border_title = f"#{self.usuarios.index(u) + 1} · {u['nombre'].split()[0] if u['nombre'] else 'detalle'}"

    def on_data_table_row_highlighted(self, ev: DataTable.RowHighlighted):
        if ev.data_table.id == "t-usuarios":
            self.pintar_detalle()
        elif ev.data_table.id == "t-precarga":
            self.pintar_elegido_precarga()

    def usuario_elegido(self):
        if not self.usuarios:
            return None
        return self.usuarios[min(self.query_one("#t-usuarios", DataTable).cursor_row, len(self.usuarios) - 1)]

    def artista_elegido(self):
        if not self.arts:
            return None, None
        k = min(self.query_one("#t-precarga", DataTable).cursor_row, len(self.arts) - 1)
        return k + 1, self.arts[k]

    def pintar_elegido_precarga(self):
        k, a = self.artista_elegido()
        if not a:
            self.query_one("#pre-botones").display = False
            return
        self.query_one("#pre-botones").display = True
        name, _, estado, _ = a
        self.query_one("#pre-elegido", Static).update(Text.assemble(("Elegido: ", GRIS), (f"#{k} {name}", f"bold {VIOLETA}"),
                                                                    (f"  ({estado})", COLOR_PRECARGA[estado] or GRIS)))
        self.query_one("#b-adelantar").display = estado not in ("quitado", "hecho", "bajando")
        self.query_one("#b-quitar", Button).label = "↩ Devolver" if estado == "quitado" else "✕ Quitar"
        self.query_one("#b-quitar").display = estado != "hecho"

    # -- botones: lo mismo que los comandos, siempre con confirmación
    def on_button_pressed(self, ev: Button.Pressed):
        b = ev.button.id
        if b in ("b-aprobar", "b-bloquear", "b-admin"):
            u = self.usuario_elegido()
            if not u:
                return
            if b == "b-aprobar":
                verbo = "Desbloquear y aprobar" if u["estado"] == "bloqueado" else "Aprobar"
                self.confirmar(f"¿{verbo} a {u['email']}?", "Podrá entrar y escuchar música con su cuenta de Google.",
                               lambda: self.cambiar("aprobar", [u]))
            elif b == "b-bloquear":
                self.confirmar(f"¿Bloquear a {u['email']}?", "Se le cierran todas las sesiones al momento.",
                               lambda: self.cambiar("bloquear", [u]))
            else:
                accion = "noadmin" if u["admin"] else "admin"
                pregunta = (f"¿Quitarle el administrador a {u['email']}?" if u["admin"] else
                            f"¿Hacer administrador a {u['email']}?")
                self.confirmar(pregunta, "Los administradores no tienen límite de dispositivos.",
                               lambda: self.cambiar(accion, [u]))
        elif b in ("b-adelantar", "b-quitar"):
            k, a = self.artista_elegido()
            if not a:
                return
            name, estado = a[0], a[2]
            if b == "b-adelantar":
                self.confirmar(f"¿Adelantar a {name}?", "Será el siguiente en bajarse, cuando acabe el álbum que esté bajando.",
                               lambda: (d.adelantar(name), self.avisar(f"{name}: el siguiente en la precarga", "ok"),
                                        self.leer_rapido()))
            elif estado == "quitado":
                self.confirmar(f"¿Devolver a {name} a la precarga?", "",
                               lambda: (d.quitar(name, fuera=False), self.avisar(f"{name} vuelve a la precarga", "ok"),
                                        self.leer_rapido()))
            else:
                self.confirmar(f"¿Quitar a {name} de la precarga?", "Lo que ya se bajó se queda.",
                               lambda: (d.quitar(name), self.avisar(f"{name} fuera de la precarga", "mal"), self.leer_rapido()))
        elif b in ("b-r-api", "b-r-bot"):
            self.ejecutar("R API" if b == "b-r-api" else "R BOT", self.usuarios, self.arts)

    def pintar_actividad(self, act):
        filas = []
        for i, (cuando, donde, quien, que, tipo) in enumerate(act):
            icono, color = ICONO.get(donde, ("·", GRIS))
            filas.append((f"a{i}", [t(d.fecha(cuando), GRIS), icono, t(quien, color),
                                    t(que, COLOR_TIPO.get(tipo, ""))]))
        rellenar(self.query_one("#t-actividad", DataTable), filas)

    def pintar_biblioteca(self, b):
        horas = b["duracion"] / 3600
        self.query_one("#bc-canciones", Static).update(Text.assemble(
            (f"{b['canciones']}", f"bold {AZUL}"), " canciones · ", (f"{b['artistas']}", f"bold {VIOLETA}"),
            " artistas\n", (f"{horas:,.0f} horas de música".replace(",", "."), GRIS)))
        pct = 100 * b["usado"] / b["tope"] if b["tope"] else 0
        self.query_one("#bc-espacio", Static).update(f"{d.tamano(b['usado'])} de {d.tamano(b['tope'])} (al pasarse, "
                                                     "borra lo que hace más que no suena)")
        self.query_one("#p-espacio2", ProgressBar).update(total=100, progress=pct)
        usado = b["disco_total"] - b["disco_libre"]
        self.query_one("#bc-disco", Static).update(f"{d.tamano(b['disco_libre'])} libres de {d.tamano(b['disco_total'])}")
        self.query_one("#p-disco", ProgressBar).update(total=100, progress=100 * usado / max(1, b["disco_total"]))
        rellenar(self.query_one("#t-top", DataTable), [
            (f"c{i}", [t(i, GRIS), t(corta(titulo, 44), bold=i <= 3), t(corta(artista, 22), GRIS), t(veces, ROSA, True)])
            for i, (titulo, artista, veces) in enumerate(b["top"], start=1)])
        rellenar(self.query_one("#t-artistas", DataTable), [
            (f"a{i}", [t(i, GRIS), t(corta(a, 28), bold=i <= 3), t(p, ROSA, True), t(n, GRIS)])
            for i, (a, p, n) in enumerate(b["top_artistas"], start=1)])
        maximo = max([n for _, n in b["generos"]] or [1])
        rellenar(self.query_one("#t-generos", DataTable), [
            (f"g{i}", [t(g, GRIS if g == "sin género" else ""), t(n), t("█" * max(1, round(12 * n / maximo)), VIOLETA)])
            for i, (g, n) in enumerate(b["generos"])])

    def pintar_precarga(self, pre):
        texto, tipo, c = pre
        x = Text()
        x.append("Ahora: ", style=GRIS)
        x.append(texto, style=f"bold {({'parada': ROJO, 'bajando': AZUL}).get(tipo, GRIS)}")
        if c:
            x.append(f"   ·   {c['bajadas']} bajadas · {c['cola']} en cola · artistas {c['artistas_hechos']}/{c['artistas']}",
                     style=GRIS)
        x.append("\nDe los 3 primeros pendientes se elige uno al azar. Clic en un artista y sus botones, o :A <n> / :X <n>.",
                 style=GRIS)
        self.query_one("#pre-resumen", Static).update(x)
        filas = []
        for i, (name, songs, estado, albumes) in enumerate(self.arts, start=1):
            apagado = estado in ("hecho", "quitado")
            filas.append((f"p{i}", [t(i, bold=True), t(estado, COLOR_PRECARGA[estado], estado in ("bajando", "adelantado")),
                                    t(name, GRIS if apagado else ""), t(songs, GRIS), t(albumes, GRIS)]))
        rellenar(self.query_one("#t-precarga", DataTable), filas)
        self.pintar_elegido_precarga()

    def pintar_sistema(self, s, yt):
        c1, c5, c15 = s["carga"]
        ram_usada = s["ram_total"] - s["ram_libre"]
        self.query_one("#s-texto", Static).update(Text.assemble(
            ("Carga ", GRIS), (f"{c1:.2f}", f"bold {VERDE if c1 < s['cpus'] else ROJO}"),
            (f" {c5:.2f} {c15:.2f}  ({s['cpus']} núcleos)\n", GRIS),
            ("RAM ", GRIS), f"{d.tamano(ram_usada)} de {d.tamano(s['ram_total'])}"))
        self.query_one("#p-ram", ProgressBar).update(total=100, progress=100 * ram_usada / max(1, s["ram_total"]))
        usado = s["raiz_total"] - s["raiz_libre"]
        self.query_one("#s-texto2", Static).update(Text.assemble(
            ("Disco / ", GRIS), f"{d.tamano(s['raiz_libre'])} libres de {d.tamano(s['raiz_total'])}"))
        self.query_one("#p-raiz", ProgressBar).update(total=100, progress=100 * usado / max(1, s["raiz_total"]))
        rellenar(self.query_one("#t-bloqueos", DataTable), [
            (f"y{i}", [t(d.fecha(b.get("cuando"))), t(d.fecha(b.get("hasta"), "%H:%M"), ROJO),
                       t(b.get("peticiones_hora", "?")), t(b.get("donde") or b.get("por") or "", GRIS)])
            for i, b in enumerate(yt["bloqueos"])] or [("y-", [t("—", GRIS), t("nunca bloqueado", VERDE), "", ""])])

    def pintar_lento(self, conts, log):
        self.conts, self.api_log = conts, log
        filas = []
        for n, nombre in d.CONTENEDORES.items():
            c = conts.get(n, {})
            vivo = c.get("estado") == "running"
            salud = c.get("salud")
            estado = ESTADOS.get(c.get("estado"), c.get("estado", "?")) + (f" ({SALUD.get(salud, salud)})" if salud else "")
            filas.append((n, [t(nombre, bold=True), t(estado, VERDE if vivo else ROJO, not vivo),
                              t(d.hace(c.get("desde")) if vivo else "—", GRIS),
                              t(c.get("reinicios", 0), ROJO if c.get("reinicios") else GRIS),
                              t(f"{c.get('cpu', '—')} %" if c.get("cpu") else "—"), t(c.get("ram", "—")),
                              t(c.get("imagen", ""), GRIS)]))
        rellenar(self.query_one("#t-contenedores", DataTable), filas)
        avisos = list(reversed(log.get("avisos", [])))[:200]
        rellenar(self.query_one("#t-avisos", DataTable), [
            (f"w{i}", [t(d.fecha(cuando), GRIS), t(nivel, ROJO if nivel != "WARNING" else AMARILLO, True), t(msg[:200])])
            for i, (cuando, nivel, _, msg) in enumerate(avisos)] or [("w-", [t("—", GRIS), t("bien", VERDE), t("sin avisos", GRIS)])])
        self.pintar_servicios()

    def reloj(self):
        ahora = time.localtime()
        self.query_one("#reloj", Static).update(f"{DIAS[ahora.tm_wday]} {time.strftime('%d/%m  %H:%M:%S', ahora)}")
        if self.aviso_hasta and time.time() > self.aviso_hasta:
            self.aviso_hasta = 0
            self.pista()

    # -- línea de abajo
    def pista(self):
        tab = self.query_one(TabbedContent).active
        propios = {
            "resumen": "1–6 cambia de pestaña (2 para aprobar o bloquear)",
            "usuarios": "clic en alguien y usa sus botones  ·  o :1 aprobar  ·  :B 2 bloquear  ·  :ADM 2 admin",
            "actividad": "flechas o ratón para recorrer las últimas 48 h",
            "biblioteca": "Tab cambia de tabla  ·  flechas o ratón para recorrerla",
            "precarga": "clic en un artista y usa los botones  ·  o :A 3 adelantar  ·  :X 3 quitar o devolver",
            "sistema": "botones de la tarjeta Servidor  ·  o :R API  ·  :R BOT",
        }
        m = self.query_one("#mensaje", Static)
        m.set_classes("")
        m.update(f"{propios.get(tab, '')}  ·  :T colores  ·  :H ayuda  ·  :Q salir")

    def avisar(self, texto, clase="info", segundos=8):
        m = self.query_one("#mensaje", Static)
        m.set_classes(clase)
        m.update(texto)
        self.aviso_hasta = time.time() + segundos

    def on_tabbed_content_tab_activated(self, _):
        if not self.aviso_hasta:
            self.pista()

    def action_pestana(self, p):
        # sin foco antes de cambiar: si se queda en algo de la pestaña vieja, Textual la vuelve a abrir
        self.set_focus(None)
        self.query_one(TabbedContent).active = p

    # -- comandos
    def action_comando(self):
        cmd = self.query_one("#cmd", Input)
        self.congelados, self.arts_congelados = list(self.usuarios), list(self.arts)
        cmd.value = ""
        cmd.can_focus = True
        cmd.add_class("abierto")
        self.query_one("#mensaje").display = False
        cmd.focus()

    def action_cerrar_comando(self):
        cmd = self.query_one("#cmd", Input)
        if cmd.has_class("abierto"):
            self.cerrar_comando()

    def cerrar_comando(self, descongelar=True):
        cmd = self.query_one("#cmd", Input)
        cmd.remove_class("abierto")
        cmd.can_focus = False
        self.query_one("#mensaje").display = True
        if descongelar:
            self.congelados = self.arts_congelados = None
        self.set_focus(None)

    def on_input_submitted(self, ev: Input.Submitted):
        linea = ev.value.strip().lstrip(":").strip()
        lista, arts = self.congelados or self.usuarios, self.arts_congelados or self.arts
        self.cerrar_comando(descongelar=False)
        self.ejecutar(linea, lista, arts)
        if not self.confirmando:   # si pide confirmar, la lista sigue quieta hasta contestar
            self.congelados = self.arts_congelados = None

    def ejecutar(self, linea, lista, arts):
        cmd = linea.upper()
        tab = self.query_one(TabbedContent).active
        if not linea:
            return
        if cmd == "Q":
            return self.exit()
        if cmd == "H":
            return self.push_screen(Ayuda())
        if cmd == "T" or cmd.startswith("T "):
            return self.cambiar_paleta(linea[1:].strip().lower())
        # cada pestaña tiene sus comandos; en otra, se dice adónde ir
        if cmd.startswith("R ") or cmd == "R":
            if tab != "sistema":
                return self.avisar("Reiniciar está en la pestaña Sistema (6):  :R API  ·  :R BOT", "mal")
            if cmd not in ("R API", "R BOT"):
                return self.avisar("Uso:  :R API  o  :R BOT", "mal")
            cont = d.API_CONT if cmd == "R API" else d.BOT_CONT
            nombre = d.CONTENEDORES[cont]
            detalle = ("La música se corta unos segundos para todos (app, web y Discord)." if cont == d.API_CONT else
                       "Corta lo que suene en Discord; al volver pregunta «¿Seguimos?».")
            return self.confirmar(f"¿Reiniciar {nombre}?", detalle, lambda: self.reiniciar(cont, nombre))
        if tab == "precarga":
            return self.ejecutar_precarga(cmd, linea, arts)
        es_usuarios = linea[:1].isdigit() or cmd.startswith("ADM") or cmd == "B" or cmd.startswith("B ")
        if es_usuarios and tab != "usuarios":
            return self.avisar("Aprobar, bloquear y administrador están en la pestaña Usuarios (2)", "mal")
        if cmd[:1] in ("A", "X") and cmd[1:].strip().isdigit():
            return self.avisar("Adelantar y quitar artistas están en la pestaña Precarga (5)", "mal")
        if cmd.startswith("ADM"):
            elegidos = self.elegir(linea[3:], lista)
            if not elegidos:
                return self.avisar("Uso: :ADM <número de la lista>", "mal")
            u = elegidos[0]
            accion = "noadmin" if u["admin"] else "admin"
            pregunta = (f"¿Quitarle el administrador a {u['email']}?" if u["admin"] else
                        f"¿Hacer administrador a {u['email']}?")
            return self.confirmar(pregunta, "Los administradores no tienen límite de dispositivos.",
                                  lambda: self.cambiar(accion, [u]))
        if cmd.startswith("B ") or cmd == "B":
            elegidos = self.elegir(linea[1:], lista)
            if not elegidos:
                return self.avisar("Uso: :B <número de la lista>", "mal")
            emails = ", ".join(u["email"] for u in elegidos)
            return self.confirmar(f"¿Bloquear a {emails}?", "Se le cierran todas las sesiones al momento.",
                                  lambda: self.cambiar("bloquear", elegidos))
        if linea[:1].isdigit():
            elegidos = self.elegir(linea, lista)
            if not elegidos:
                return self.avisar(f"No hay número «{linea}» en la lista de usuarios", "mal")
            bloqueados = [u["email"] for u in elegidos if u["estado"] == "bloqueado"]
            if bloqueados:   # desbloquear es raro: que no pase por un número mal puesto
                return self.confirmar(f"{', '.join(bloqueados)} está bloqueado. ¿Aprobar igual?", "",
                                      lambda: self.cambiar("aprobar", elegidos))
            ya = [u for u in elegidos if u["estado"] == "aprobado"]
            if len(ya) == len(elegidos):
                return self.avisar(f"{', '.join(u['email'] for u in ya)} ya estaba aprobado", "info")
            self.avisar("Aprobando…", "info")
            return self.cambiar("aprobar", elegidos)
        self.avisar(f"Comando desconocido: :{linea}   (:H ayuda)", "mal")

    def ejecutar_precarga(self, cmd, linea, arts):
        try:
            k = int(linea[1:].strip())
            assert k >= 1 and cmd[:1] in ("A", "X")
            name, _, estado, _ = arts[k - 1]
        except (ValueError, IndexError, AssertionError):
            return self.avisar("En Precarga:  :A <n> adelantar  ·  :X <n> quitar o devolver  (aprobar y bloquear, en Usuarios: 2)",
                               "mal")
        if cmd[0] == "A":
            if estado == "quitado":
                return self.avisar(f"{name} está quitado: :X {k} para devolverlo antes", "mal")
            d.adelantar(name)
            self.avisar(f"{name}: el siguiente en la precarga (cuando acabe el álbum que esté bajando)", "ok")
        elif estado == "quitado":
            d.quitar(name, fuera=False)
            self.avisar(f"{name} vuelve a la precarga", "ok")
        else:
            self.confirmar(f"¿Quitar a {name} de la precarga?", "Lo que ya se bajó se queda.",
                           lambda: (d.quitar(name), self.avisar(f"{name} fuera de la precarga", "mal")))
        self.leer_rapido()

    def cambiar_paleta(self, nombre):
        nombres = list(PALETAS)
        if not nombre:
            nombre = nombres[(nombres.index(self.paleta) + 1) % len(nombres)]
        if nombre not in PALETAS:
            return self.avisar(f"Paletas: {', '.join(nombres)}   (:T cambia a la siguiente)", "mal")
        self.paleta = nombre
        aplicar_paleta(nombre)
        self.theme = f"musica-{nombre}"
        guardar_paleta(nombre)
        for tabla in self.query(DataTable):   # repintar todo con los colores nuevos
            tabla._firma = None
        self.leer_rapido()
        self.leer_lento()
        self.avisar(f"Paleta «{nombre}»  ·  :T para la siguiente ({', '.join(nombres)})", "ok")

    def elegir(self, texto, lista):
        """'1 3 4' -> los usuarios con esos números en la lista que se veía; None si alguno no existe."""
        try:
            nums = [int(x) for x in texto.split()]
        except ValueError:
            return None
        if not nums or any(not 1 <= k <= len(lista) for k in nums):
            return None
        return [lista[k - 1] for k in nums]

    def confirmar(self, pregunta, detalle, accion):
        def hecho(si):
            self.confirmando = False
            self.congelados = self.arts_congelados = None
            if si:
                accion()
            else:
                self.avisar("Cancelado", "info")
        self.confirmando = True
        self.push_screen(Confirmar(pregunta, detalle), hecho)

    @work(thread=True)
    def cambiar(self, accion, elegidos):
        hechos, fallos = [], []
        for u in elegidos:
            ok, salida = d.users_py(accion, u["sub"])
            (hechos if ok else fallos).append(u["email"] if ok else f"{u['email']} ({salida})")
        palabra = {"aprobar": "Aprobado", "bloquear": "Bloqueado", "admin": "Ahora es administrador",
                   "noadmin": "Ya no es administrador"}[accion]
        if fallos:
            self.call_from_thread(self.avisar, f"Falló: {', '.join(fallos)}", "mal", 15)
        else:
            self.call_from_thread(self.avisar, f"{palabra}: {', '.join(hechos)}", "mal" if accion == "bloquear" else "ok")
        self.call_from_thread(self.leer_rapido)

    @work(thread=True)
    def reiniciar(self, cont, nombre):
        self.call_from_thread(self.avisar, f"Reiniciando {nombre}…", "info", 60)
        ok, salida = d.reiniciar(cont)
        self.call_from_thread(self.avisar, f"{nombre} reiniciado" if ok else f"No se pudo reiniciar {nombre}: {salida}",
                              "ok" if ok else "mal")
        self.call_from_thread(self.leer_lento)


def main():
    Panel().run()
    print("Panel cerrado. La API sigue funcionando igual.")
