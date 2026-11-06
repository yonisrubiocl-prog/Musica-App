"""Escuchar en varios dispositivos (como Spotify Connect): cada cuenta tiene una reproducción, la que suena en un
dispositivo (la web del PC, la app del celular…), y los demás la ven y la manejan.

- El que suena cuenta lo que pasa (POST /conectar/estado): canción, segundo, cola, aleatorio, repetir, pausa. Si
  otro dispositivo de la cuenta está sonando, se le dice 409 (salvo que diga `tomar`: entonces pasa a ser él).
- Todos esperan cambios (GET /conectar, espera larga de hasta ESPERA s, como la pestaña DC): lo que suena, dónde y
  la lista de dispositivos; al que suena, además, las órdenes que le mandaron los otros.
- Desde otro dispositivo (POST /conectar/orden): pausa, siguiente, anterior, ir a un segundo, poner una cola nueva
  ("cola", con la canción que toca) o "transferir" a otro dispositivo (el de antes se pausa, el nuevo sigue en el
  mismo segundo).
Un dispositivo está "vivo" si preguntó hace menos de VIVO s. Todo en memoria (y en FILE cada poco, para seguir donde
se dejó tras reiniciar). Sin peticiones a YouTube. Ver README.md, "Escuchar en varios dispositivos".
"""
import asyncio
import json
import logging
import os
import time

log = logging.getLogger("musicapp.conectar")

FILE = "/data/conectar.json"
ESPERA = 25                             # la espera larga de GET /conectar
VIVO = 45                               # un dispositivo que no pregunta en este rato ya no está
GUARDA = 20                             # cada cuánto se guarda en FILE si cambió algo
MAX_COLA = 1000                         # canciones de una cola como mucho
TIPOS = {"pausa", "siguiente", "anterior", "ir", "cola", "transferir", "desconectar"}


class Conectar:
    def __init__(self):
        self.cuentas = {}                     # sub -> {v, activo, disp: {id: {nombre, visto}}, sonando, ordenes, n}
        self.eventos = {}                     # sub -> asyncio.Event (se cambia por uno nuevo en cada cambio)
        self.sucio = False
        try:
            with open(FILE) as f:
                self.cuentas = json.load(f)
        except (OSError, ValueError):
            pass

    def _cuenta(self, sub):
        c = self.cuentas.setdefault(sub, {"v": 1, "activo": None, "disp": {}, "sonando": None, "ordenes": [], "n": 0})
        return c

    def _cambio(self, sub):
        c = self._cuenta(sub)
        c["v"] += 1
        self.sucio = True
        ev = self.eventos.pop(sub, None)
        if ev:
            ev.set()

    def _vivo(self, c, d):
        x = c["disp"].get(d)
        return bool(x) and time.time() - x["visto"] < VIVO

    def _visto(self, sub, disp, nombre):
        """Apunta que `disp` está abierto. Si es nuevo o vuelve tras un rato, cambia la lista para los demás."""
        c = self._cuenta(sub)
        era = self._vivo(c, disp)
        x = c["disp"].setdefault(disp, {"nombre": nombre or "Dispositivo", "visto": 0})
        x["visto"] = time.time()
        if nombre:
            x["nombre"] = nombre[:40]
        for d in [d for d, y in c["disp"].items() if time.time() - y["visto"] > 30 * 86400]:   # olvidar los viejos
            c["disp"].pop(d)
        if not era:
            self._cambio(sub)

    def salir(self, sub, disp):
        """`disp` se cierra (la TV al apagarse, por ejemplo): deja de estar abierto ya, sin esperar a VIVO. Si sonaba
        ahí, lo que sonaba queda en pausa en su segundo (los otros lo ven como cuando se cierra el que suena)."""
        c = self._cuenta(sub)
        x = c["disp"].get(disp)
        if not x:
            return
        x["visto"] = 0
        if c["activo"] == disp and c["sonando"]:
            c["sonando"] = {**c["sonando"], "pos": self._pos(c["sonando"]), "pausa": True, "at": time.time()}
        log.info("conectar: %s cierra %s", sub[:6], x["nombre"])
        self._cambio(sub)

    def _pos(self, s):
        """El segundo por el que va ahora (el que suena lo dijo hace un rato)."""
        if not s:
            return 0
        p = s.get("pos") or 0
        if not s.get("pausa"):
            p += time.time() - (s.get("at") or time.time())
        return round(min(p, s.get("duracion") or p), 1)

    def vista(self, sub, disp):
        """Lo que ve `disp`: dónde suena, lo que suena (con el segundo de ahora) y, si es él el que suena, sus órdenes."""
        c = self._cuenta(sub)
        activo = c["activo"]
        vivo = bool(activo) and self._vivo(c, activo)
        s = c["sonando"]
        return {"v": c["v"], "activo": activo, "activo_vivo": vivo, "este": disp,
                "dispositivos": [{"id": d, "nombre": x["nombre"], "vivo": self._vivo(c, d)}
                                 for d, x in sorted(c["disp"].items(), key=lambda i: -i[1]["visto"])
                                 if self._vivo(c, d) or d == activo],
                "sonando": {**s, "pos": self._pos(s)} if s else None,
                "ordenes": [o for o in c["ordenes"]] if disp == activo else [],
                "desconectar": self._desconectar(c, disp)}

    def _desconectar(self, c, disp):
        """¿Le han pedido a esta TV que se cierre? (una vez: al decírselo se olvida; las que ya no están, también)"""
        lista = [d for d in c.get("desconectar", []) if self._vivo(c, d)]
        c["desconectar"] = [d for d in lista if d != disp]
        return disp in lista

    async def esperar(self, sub, disp, nombre, desde):
        self._visto(sub, disp, nombre)
        c = self._cuenta(sub)
        if desde == c["v"]:
            ev = self.eventos.setdefault(sub, asyncio.Event())
            try:
                await asyncio.wait_for(ev.wait(), ESPERA)
            except asyncio.TimeoutError:
                pass
            if c["disp"].get(disp, {}).get("visto"):   # si se despidió mientras esperaba (salir), no revivirlo
                self._visto(sub, disp, nombre)
        return self.vista(sub, disp)

    def estado(self, sub, disp, nombre, datos, tomar=False, hecho=None):
        """El dispositivo `disp` cuenta lo que suena. False si suena otro (vivo) y no lo quiere tomar."""
        self._visto(sub, disp, nombre)
        c = self._cuenta(sub)
        if c["activo"] != disp and c["activo"] and self._vivo(c, c["activo"]) and not tomar:
            return False
        if c["activo"] != disp:
            log.info("conectar: %s suena ahora en %s", sub[:6], c["disp"][disp]["nombre"])
            c["activo"], c["ordenes"] = disp, []
        if hecho is not None:
            c["ordenes"] = [o for o in c["ordenes"] if o["n"] > hecho]
        s = dict(c["sonando"] or {})
        for k in ("cancion", "pos", "pausa", "qi", "radio", "repetir", "aleatorio", "duracion", "artista"):
            if k in datos:
                s[k] = datos[k]
        if "cola" in datos:
            s["cola"] = (datos["cola"] or [])[:MAX_COLA]
        s["at"] = time.time()
        c["sonando"] = s
        self._cambio(sub)
        return True

    def orden(self, sub, disp, tipo, datos):
        """Una orden de `disp` para el que suena. Devuelve un error (texto) o None."""
        if tipo not in TIPOS:
            return "orden desconocida"
        self._visto(sub, disp, None)
        c = self._cuenta(sub)
        if tipo == "transferir":
            a = (datos or {}).get("a")
            if a not in c["disp"] or not self._vivo(c, a):
                return "ese dispositivo no está abierto"
            if a == c["activo"]:
                return None
            s = c["sonando"]
            if s:   # el nuevo sigue en el mismo segundo, sonando
                c["sonando"] = {**s, "pos": self._pos(s), "at": time.time(), "pausa": False}
            log.info("conectar: %s pasa la música a %s", sub[:6], c["disp"][a]["nombre"])
            c["activo"], c["ordenes"] = a, []
            self._cambio(sub)
            return None
        if tipo == "desconectar":   # cerrar la pantalla de una TV ({a}): desde la web o la app, la conectara quien la conectara
            a = (datos or {}).get("a")
            if not (isinstance(a, str) and a.startswith("tv") and a in c["disp"]):
                return "esa TV no está"
            c.setdefault("desconectar", [])
            if a not in c["desconectar"]:
                c["desconectar"].append(a)
            if c["activo"] == a and c["sonando"]:   # lo que sonaba allí queda en el que la cierra, en pausa
                c["sonando"] = {**c["sonando"], "pos": self._pos(c["sonando"]), "pausa": True, "at": time.time()}
                c["activo"], c["ordenes"] = disp, []
            log.info("conectar: %s desconecta la TV %s", sub[:6], a)
            self._cambio(sub)
            return None
        if not c["activo"] or not self._vivo(c, c["activo"]):
            return "no está sonando en ningún dispositivo"
        c["n"] += 1
        c["ordenes"] = (c["ordenes"] + [{"n": c["n"], "tipo": tipo, "datos": datos or {}, "de": disp}])[-50:]
        s = c["sonando"]
        if tipo == "cola" and s:   # lo ven ya los demás, sin esperar a que el que suena lo cuente
            cola, qi = (datos.get("cola") or [])[:MAX_COLA], datos.get("qi", 0)
            s = {**s, "cola": cola, "qi": qi}
            if datos.get("nueva") and 0 <= qi < len(cola):   # otra canción: ya la nueva, desde el 0
                s.update(cancion=cola[qi], pos=0, at=time.time())
            c["sonando"] = s
        elif tipo in ("siguiente", "anterior") and s and s.get("cola"):
            # La canción nueva, ya: si no, los mandos seguían con la de antes hasta que el que suena la cargara y la
            # contara (unos segundos en la TV) y la página "se quedaba pegada". El que suena la confirma después.
            cola, qi, pos = s["cola"], s.get("qi", 0) or 0, self._pos(s)
            if tipo == "siguiente" and qi + 1 < len(cola):
                c["sonando"] = {**s, "cancion": cola[qi + 1], "qi": qi + 1, "pos": 0, "at": time.time()}
            elif tipo == "anterior":
                j = qi - 1 if pos <= 3 and qi > 0 else qi
                c["sonando"] = {**s, "cancion": cola[j], "qi": j, "pos": 0, "at": time.time()}
        self._cambio(sub)
        return None

    async def guardar(self):
        while True:
            await asyncio.sleep(GUARDA)
            if not self.sucio:
                continue
            self.sucio = False
            try:
                tmp = FILE + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(self.cuentas, f, ensure_ascii=False)
                os.replace(tmp, FILE)
            except OSError as e:
                log.warning("conectar: no pude guardar: %s", e)
